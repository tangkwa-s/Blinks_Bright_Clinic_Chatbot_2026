"""Retrieval-augmented generation — KB chunking, embedding, retrieval.

The knowledge base (services, promotions, articles, branches, doctors) is
chunked into ``KBChunk`` rows with OpenAI embeddings stored as JSON. Everything
is scoped to one clinic, so a clinic's AI only ever retrieves its own knowledge.
"""
import json
import math

from app import models
from app.ai.client import embed_one, embed_texts
from app.scope import scoped
from app.services.booking import _now_local, branch_days
from app.services.promotions import (exhausted_promo_ids, promo_branch_ids,
                                     promo_date_ok)


def _baht(n) -> str:
    return f"฿{int(n or 0):,}"


_DOW = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_DAY_ABBR = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu",
             "fri": "Fri", "sat": "Sat", "sun": "Sun"}


def fmt_hours(branch) -> str:
    """Compact per-branch opening hours, e.g. 'Mon-Fri 10:00-20:00, Sat-Sun 10:00-19:00'.
    Falls back to the flat open_hour/close_hour when no per-day hours are stored.

    Lives here, not in context.py, so the KB chunk and the structured catalog block are
    formatted by the SAME function. The branch chunk used to carry a hardcoded "weekdays
    10:00-20:00, weekends 10:00-19:00" that read the clinic's real hours never — and the
    assistant, handed a correct set in one block and an invented set in the other, quoted
    whichever it happened to look at.
    """
    days = branch_days(branch)     # the SAME parser availability uses
    if not days:
        return f"{branch.open_hour:02d}:00-{branch.close_hour:02d}:00 daily"
    groups = []  # group consecutive days with identical hours
    for d in _DOW:
        v = days.get(d) or {}
        lab = "closed" if v.get("closed") else f"{v.get('open', '10:00')}-{v.get('close', '20:00')}"
        if groups and groups[-1][1] == lab:
            groups[-1][0].append(d)
        else:
            groups.append(([d], lab))
    out = []
    for ds, lab in groups:
        rng = _DAY_ABBR[ds[0]] if len(ds) == 1 else f"{_DAY_ABBR[ds[0]]}-{_DAY_ABBR[ds[-1]]}"
        out.append(f"{rng} {lab}")
    return ", ".join(out)


def _service_branch_ids(db, clinic_id: int) -> dict[int, set[int]]:
    """Every service's restricted-branch set, keyed by service id (mirrors
    catalog.py::_branch_ids_by_service). No entry / an empty set = every branch."""
    out: dict[int, set[int]] = {}
    for row in scoped(db, models.ServiceBranch, clinic_id).all():
        out.setdefault(row.service_id, set()).add(row.branch_id)
    return out


def _source_items(db, clinic_id: int) -> list[tuple]:
    """Collect (source_type, source_id, title, text, branch_id) from one clinic's KB."""
    items: list[tuple] = []

    service_branches = _service_branch_ids(db, clinic_id)
    for s in scoped(db, models.Service, clinic_id).filter(models.Service.active.is_(True)).all():
        # Deliberately NO price here: a service's real price can differ per branch
        # (ServicePrice overrides), so this base_price would be wrong for any
        # branch with an override. The AI must always get price/deposit from the
        # branch-aware list_treatments tool, never from KB text (see prompts.py).
        text = (
            f"Treatment: {s.name} (category: {s.category}). {s.description} "
            f"A session takes about {s.duration_min} minutes. "
            f"Recommended interval: every {s.recommended_interval_days} days. "
            f"Preparation: {s.prep_notes} Aftercare: {s.aftercare_notes} "
            f"Contraindications: {s.contraindications}"
        )
        restricted = service_branches.get(s.id)
        if restricted:
            # The branch scope goes into the TEXT as well, not just KBChunk.branch_id.
            # The id only scopes retrieval once a branch is known; with none chosen every
            # branch's chunk comes back and the text said nothing about where the
            # treatment actually is, leaving the model free to offer it anywhere.
            names = [b.name for b in scoped(db, models.Branch, clinic_id)
                     .order_by(models.Branch.id).all() if b.id in restricted]
            if names:
                text += f" Offered only at these branches: {', '.join(names)}."
            # One chunk per branch it's offered at, so per-branch retrieval scoping
            # (KBChunk.branch_id) still works for a treatment tied to several —
            # but not all — branches (a single chunk field only holds one id).
            for bid in restricted:
                items.append(("service", s.id, s.name, text, bid))
        else:
            items.append(("service", s.id, s.name, text, None))

    now = _now_local()
    promo_bmap = promo_branch_ids(db, clinic_id)
    for p in scoped(db, models.Promotion, clinic_id).filter(models.Promotion.active.is_(True)).all():
        if not promo_date_ok(p, now):
            continue  # never index an out-of-period promo (hygiene; the query-time
            #           filter in _drop_inactive is the load-bearing guard)
        price = f" Promotional price {_baht(p.promo_price)}." if p.promo_price else ""
        text = f"Promotion: {p.title}. {p.detail} {p.discount_label}.{price}"
        # A promo can run at several branches now, and a chunk carries only one
        # branch_id — so emit one chunk per branch, exactly as a branch-restricted
        # service does above. No restriction stays a single clinic-wide chunk.
        for bid in (sorted(promo_bmap.get(p.id) or []) or [None]):
            items.append(("promotion", p.id, p.title, text, bid))

    for a in scoped(db, models.KBArticle, clinic_id).filter(models.KBArticle.active.is_(True)).all():
        items.append(("article", a.id, a.title, f"{a.title}\n{a.content}", a.branch_id))

    for b in scoped(db, models.Branch, clinic_id).all():
        items.append(("branch", b.id, b.name,
                      f"Branch: {b.name}. Address: {b.address}. Phone: {b.phone}. "
                      f"Opening hours: {fmt_hours(b)}.", b.id))

    for u in (scoped(db, models.StaffMember, clinic_id)
              .filter(models.StaffMember.role == "doctor", models.StaffMember.active.is_(True)).all()):
        branch = db.get(models.Branch, u.branch_id) if u.branch_id else None
        items.append(("doctor", u.id, u.name,
                      f"Doctor: {u.name}, {u.title or 'Aesthetic Physician'}"
                      f"{' at ' + branch.name + ' branch' if branch else ''}. {u.bio}",
                      u.branch_id))
    return items


def reindex(db, clinic_id=None) -> dict:
    """Rebuild KB chunks. With ``clinic_id`` → just that clinic; else every clinic."""
    if clinic_id is None:
        clinic_ids = [c.id for c in db.query(models.Clinic).all()]
    else:
        clinic_ids = [clinic_id]

    total_chunks = total_embedded = 0
    for cid in clinic_ids:
        items = _source_items(db, cid)
        scoped(db, models.KBChunk, cid).delete()
        db.flush()
        vectors = embed_texts([it[3] for it in items]) if items else []
        for (stype, sid, title, text, bid), vec in zip(items, vectors):
            db.add(models.KBChunk(clinic_id=cid, source_type=stype, source_id=sid,
                                  title=title, text=text, branch_id=bid, embedding=vec or []))
        total_chunks += len(items)
        total_embedded += sum(1 for v in vectors if v)
    db.commit()
    return {"chunks": total_chunks, "embedded": total_embedded}


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _keyword_score(query: str, text: str) -> float:
    words = {w for w in query.lower().split() if len(w) > 1}
    if not words:
        return 0.0
    low = text.lower()
    return sum(1 for w in words if w in low) / len(words) * 0.5


def _drop_inactive(db, clinic_id: int, chunks: list) -> list:
    """Drop chunks whose backing source has since become unusable.

    The KB index is a snapshot built at reindex time. A treatment, promotion or
    article turned off AFTER the last reindex still has its chunk in the index, so
    without this guard the AI would keep recommending a deactivated service. The
    same applies to a promotion whose effective period has since lapsed, or whose
    quota filled up (quota moves on every paid booking with no reindex at all). We
    re-check live state at query time, which is correct even if no reindex ran.
    """
    inactive_services = {sid for (sid,) in scoped(db, models.Service, clinic_id)
                         .filter(models.Service.active.is_(False))
                         .with_entities(models.Service.id).all()}
    inactive_promos = {pid for (pid,) in scoped(db, models.Promotion, clinic_id)
                       .filter(models.Promotion.active.is_(False))
                       .with_entities(models.Promotion.id).all()}
    if inactive_services:  # a promotion for a switched-off treatment is dead too
        inactive_promos |= {pid for (pid,) in scoped(db, models.Promotion, clinic_id)
                            .filter(models.Promotion.service_id.in_(inactive_services))
                            .with_entities(models.Promotion.id).all()}
    now = _now_local()     # out-of-period promos are dead (same window as resolved_price)
    inactive_promos |= {pid for (pid,) in scoped(db, models.Promotion, clinic_id)
                        .filter((models.Promotion.valid_to < now)
                                | (models.Promotion.valid_from > now))
                        .with_entities(models.Promotion.id).all()}
    inactive_promos |= exhausted_promo_ids(db, clinic_id)  # quota fully redeemed
    inactive_articles = {aid for (aid,) in scoped(db, models.KBArticle, clinic_id)
                         .filter(models.KBArticle.active.is_(False))
                         .with_entities(models.KBArticle.id).all()}
    return [c for c in chunks if not (
        (c.source_type == "service" and c.source_id in inactive_services)
        or (c.source_type == "promotion" and c.source_id in inactive_promos)
        or (c.source_type == "article" and c.source_id in inactive_articles))]


def retrieve(db, query: str, clinic_id: int, branch_id=None, k: int = 5) -> list[dict]:
    """Return the top-k KB chunks most relevant to a query, within one clinic."""
    chunks = scoped(db, models.KBChunk, clinic_id).all()
    if branch_id and branch_id not in ("all", None):
        try:
            bid = int(branch_id)
            chunks = [c for c in chunks if c.branch_id in (None, bid)]
        except (TypeError, ValueError):
            pass
    chunks = _drop_inactive(db, clinic_id, chunks)
    if not chunks:
        return []

    qvec = embed_one(query)
    use_vectors = bool(qvec) and any(c.embedding for c in chunks)
    scored = []
    for c in chunks:
        if use_vectors and c.embedding:
            score = _cosine(qvec, c.embedding)
        else:
            score = _keyword_score(query, c.text)
        scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {"id": c.id, "source_type": c.source_type, "source_id": c.source_id,
         "title": c.title, "text": c.text, "score": round(score, 3)}
        for score, c in scored[:k] if score > 0.02
    ]
