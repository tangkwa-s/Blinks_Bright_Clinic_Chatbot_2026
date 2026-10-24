"""Hybrid knowledge context for the AI assistant.

For a clinic the whole knowledge base is only a few thousand tokens, so the AI is
given the COMPLETE structured catalog every reply (branches, treatments,
promotions, doctors) read live from the DB, instead of similarity-RAG which can
silently drop items (the missing-branch / missing-treatment bug). KB articles are
included in full while small, and fall back to embedding-RAG only when a clinic's
article set grows past a token budget. Tools (check_availability, book_appointment,
create_payment_link) still handle live actions and branch-precise pricing.
"""
import json

from app import models
from app.ai import rag
from app.ai.rag import fmt_hours
from app.scope import scoped
from app.services.booking import _now_local
from app.services.promotions import (exhausted_promo_ids, promo_branch_ids,
                                     promo_date_ok, promo_runs_at)

# Articles are included verbatim while their total stays under this budget (rough
# tokens). Past it, fall back to embedding-RAG so a huge article set can't bloat
# every reply. ~chars/3 errs large for Thai, which is the safe direction.
ARTICLE_TOKEN_BUDGET = 8000



def _est_tokens(s: str) -> int:
    return len(s or "") // 3



def build_context(db, clinic_id: int, branch_id, query: str, k: int = 5,
                  asked_names: list[str] | None = None,
                  allowed_branch_ids: set[int] | None = None):
    """Return (context_text, source_labels) for one reply.

    source_labels is the coarse list of sections used (for the inbox source chips).

    ``asked_names`` / ``allowed_branch_ids`` describe the treatments the CUSTOMER has
    named and the branches that offer all of them (``chat.respond`` computes them via
    tools.treatments_named_by_customer / branches_offering). They are optional so the
    older callers keep working, but without them this block is branch-blind — and it is
    injected on EVERY turn, so it out-argued the tool result and the booking checklist
    the moment the model answered without calling a tool: it listed treatments a branch
    does not have, and its "name EVERY one" line produced a which-branch question over
    branches that could not serve what the customer had just asked for.
    """
    blocks: list[str] = []
    sources: list[str] = []

    # --- branches (every one) ---
    branches = scoped(db, models.Branch, clinic_id).order_by(models.Branch.id).all()
    if branches:
        lines = [f"- {b.name}" + (f", {b.address}" if b.address else "")
                 + (f", โทร {b.phone}" if b.phone else "")
                 + f", open {fmt_hours(b)}" for b in branches]
        header = (f"BRANCHES ({len(branches)} total — the 'open' times are each branch's opening "
                  "hours. Name every one when the customer asks where you are or wants to change "
                  "branch, EXCEPT when they have asked about a treatment that only some branches "
                  "offer: then name only the branches listed for it in TREATMENTS")
        if len(branches) > 1:
            header += (". IMPORTANT: this clinic has multiple branches, so BEFORE checking "
                       "availability, quoting a branch-specific price, or booking, you MUST ask the "
                       "customer which branch they want — availability, prices and promotions "
                       "differ by branch")
        # The treatment they actually asked for narrows the question to a real answer.
        eligible = [b for b in branches if allowed_branch_ids and b.id in allowed_branch_ids]
        if asked_names and eligible and len(eligible) < len(branches):
            header += (f". The customer has asked about {', '.join(asked_names)}, offered ONLY at "
                       f"{', '.join(b.name for b in eligible)} — when you ask or confirm a branch "
                       "for it, name ONLY those and no others")
        blocks.append(header + "):\n" + "\n".join(lines))
        sources.append("Branches")

    # --- treatments: the complete active menu ---
    svcs = (scoped(db, models.Service, clinic_id)
            .filter_by(active=True).order_by(models.Service.id).all())
    if svcs:
        # Branch-specific price overrides the catalog base price when the conversation's
        # branch is already known — mirrors list_treatments/resolved_price so this
        # always-injected context can't hand the model a stale/wrong base price for a
        # customer whose branch we already know (previously this ignored branch_id
        # entirely, so a plain price question never needed a tool call and always got
        # the base price).
        price_by_service = {}
        if branch_id:
            for sp in (scoped(db, models.ServicePrice, clinic_id)
                       .filter_by(branch_id=branch_id).all()):
                if sp.price:   # a falsy row is no override — mirror resolved_price
                    price_by_service[sp.service_id] = sp.price
        cur_branch = next((b for b in branches if b.id == branch_id), None) if branch_id else None
        # Which branches each treatment is restricted to (no entry = every branch).
        # Same reader as the tools and catalog.py::_branch_ids_by_service.
        branch_names = {b.id: b.name for b in branches}
        restricted_to: dict[int, set[int]] = {}
        for row in scoped(db, models.ServiceBranch, clinic_id).all():
            restricted_to.setdefault(row.service_id, set()).add(row.branch_id)
        # All-branch treatments FIRST. "Prefer the ones every branch has" is the clinic's
        # rule, and the model picks the first two or three off the list — so ordering
        # enforces it, where a sentence in the header only asks for it.
        if not branch_id:
            svcs = sorted(svcs, key=lambda x: (1 if restricted_to.get(x.id) else 0, x.id))
        lines, scoped_any, example = [], False, ""
        for s in svcs:
            only_at = restricted_to.get(s.id)
            # A known branch means the prices below are quoted "exactly as-is", so a
            # treatment that branch does not offer must not be in the list at all.
            if only_at and branch_id and branch_id not in only_at:
                continue
            price = price_by_service.get(s.id, s.base_price)
            # Same deposit rule as create_booking: per-service override (capped at the
            # price) else the automatic 20% rounded to ฿100. Spelling it out here keeps
            # the deposit figure GROUNDED when the model reuses it in a later turn's
            # booking summary (the grounding guard only sees THIS turn's tool results,
            # so a deposit learned from an earlier list_treatments call used to flag).
            p = float(price or 0)
            deposit = (min(float(s.deposit), p) if getattr(s, "deposit", 0) and s.deposit > 0
                       else round(p * 0.2 / 100) * 100)
            note = " ".join(filter(None, [
                f"prep: {s.prep_notes}." if s.prep_notes else "",
                f"aftercare: {s.aftercare_notes}." if s.aftercare_notes else "",
                f"not suitable if: {s.contraindications}." if s.contraindications else "",
            ]))
            # The branch scope travels ON the treatment's own line: a rule stated once in
            # a header is read as advice, a fact printed beside the price is read as data.
            where = ""
            if only_at and not branch_id:
                names = [branch_names[b] for b in sorted(only_at) if b in branch_names]
                if names:
                    where = f" (only at: {', '.join(names)})"
                    scoped_any = True
                    if not example:   # a finished line, built from this clinic's own names
                        example = (f"'{s.name} (มีเฉพาะสาขา {', '.join(names)})' / "
                                   f"'{s.name} (only at {', '.join(names)})'")
            lines.append(
                f"- {s.name}" + (f" [{s.category}]" if s.category else "") + where
                + f": from ฿{int(price or 0):,}, {s.duration_min} min"
                + (f", deposit ฿{int(deposit):,}" if p > 0 else "")
                + (f", repeat every {s.recommended_interval_days} days"
                   if s.recommended_interval_days else "")
                + (f" — {note}" if note else ""))
        if cur_branch:
            header = ("TREATMENTS (this branch's menu — only recommend treatments from this list. "
                      f"Prices shown are ALREADY for the customer's branch, {cur_branch.name} — "
                      "quote them exactly as-is, no need to check further. Treatments this branch "
                      "does not offer are NOT listed: if the customer asks for one by name, say "
                      "plainly that this branch does not have it, never substitute another)")
        elif len(branches) > 1:
            header = ("TREATMENTS (the full menu — only recommend treatments from this list. "
                      "These are STANDARD prices; this clinic has multiple branches and the "
                      "customer's branch isn't known yet, so ask which branch first, then call "
                      "list_treatments with that branch for the exact price before quoting one")
            if scoped_any:
                # "Which of these do you fancy?" must not lead with something half the
                # clinic cannot do — but a clinic whose whole menu is branch-specific
                # still has to be able to sell it.
                header += (". A treatment marked '(only at: ...)' exists at THOSE branches ONLY: "
                           "never offer it at another branch, and never name a branch outside its "
                           "list when asking which branch they want. When YOU choose what to "
                           "present, prefer treatments with no '(only at)' mark — they are listed "
                           "first and every branch has them; use a marked one when there are not "
                           "enough unmarked ones to suggest, or when the customer named it "
                           "themselves. Whenever a marked treatment appears in your reply its "
                           "branches MUST appear beside it, written out like this: " + example)
            header += ")"
        else:
            header = ("TREATMENTS (the full menu — only recommend treatments from this list; "
                      "quote the price shown)")
        # Write the catalog spelling, not the customer's. A customer types "ไฮฟู" for a
        # treatment filed as "Hifu", and when the assistant mirrors their spelling back
        # the clinic's own checks — which match on the catalog name — no longer recognise
        # which treatment is being discussed, so the branch rules above stop applying.
        header += (" ALWAYS write a treatment's name EXACTLY as spelled in this list, even "
                   "when the customer spelt it differently or in another script: never a "
                   "transliteration, translation or shortened form.")
        blocks.append(header + ":\n" + "\n".join(lines))
        sources.append("Treatments")

    # --- promotions: active, in-date, quota-available, branch-applicable,
    #     linked service still active ---
    now = _now_local()
    promos = (scoped(db, models.Promotion, clinic_id)
              .filter(models.Promotion.active.is_(True)).all())
    dead = exhausted_promo_ids(db, clinic_id) if promos else set()
    promo_bmap = promo_branch_ids(db, clinic_id) if promos else {}
    active = []
    for p in promos:
        # With no branch chosen yet, a branch-specific promo still shows here (the
        # catalog block is clinic-wide context); once one is known it must apply there.
        if branch_id and not promo_runs_at(promo_bmap.get(p.id), branch_id):
            continue
        if not promo_date_ok(p, now):
            continue
        if p.id in dead:
            continue
        if p.service_id:
            svc = db.get(models.Service, p.service_id)
            if svc and not svc.active:
                continue
        active.append(p)
    if active:
        lines = [f"- {p.title}: {p.detail}"
                 + (f" ({p.discount_label})" if p.discount_label else "")
                 + (f" promo price ฿{int(p.promo_price):,}" if p.promo_price else "")
                 for p in active]
        blocks.append("PROMOTIONS (mention ONLY if the customer explicitly asks about deals / "
                      "promotions / discounts):\n" + "\n".join(lines))
        sources.append("Promotions")

    # --- doctors ---
    docs = (scoped(db, models.StaffMember, clinic_id)
            .filter(models.StaffMember.role == "doctor",
                    models.StaffMember.active.is_(True)).all())
    if docs:
        lines = []
        for d in docs:
            br = db.get(models.Branch, d.branch_id) if d.branch_id else None
            lines.append(f"- {d.name}" + (f" ({br.name})" if br else "")
                         + (f": {d.bio}" if d.bio else ""))
        blocks.append("DOCTORS:\n" + "\n".join(lines))
        sources.append("Doctors")

    # --- KB articles: all of them while small, else embedding-RAG (the scale valve) ---
    arts = [a for a in scoped(db, models.KBArticle, clinic_id).filter_by(active=True).all()
            if not a.branch_id or not branch_id or a.branch_id == branch_id]
    total = sum(_est_tokens(a.content) for a in arts)
    if arts and total <= ARTICLE_TOKEN_BUDGET:
        blocks.append("KNOWLEDGE BASE:\n"
                      + "\n\n".join(f"[{a.title}]\n{a.content}" for a in arts))
        sources.append("Knowledge Base")
    elif query:  # large article set — retrieve only the most relevant chunks
        chunks = rag.retrieve(db, query, clinic_id, branch_id=branch_id, k=k)
        if chunks:
            blocks.append("KNOWLEDGE BASE (most relevant):\n"
                          + "\n\n".join(f"[{c['title']}]\n{c['text']}" for c in chunks))
            sources.append("Knowledge Base")

    return "\n\n".join(blocks), sources
