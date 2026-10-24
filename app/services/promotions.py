"""Shared promotion-eligibility helpers.

ONE implementation of "is this promotion usable right now?" consumed by every
surface that shows or applies a promo — ``booking.resolved_price_detail``, the
``list_promotions`` AI tool, ``context.build_context`` and the RAG query-time
filter — so the price a customer is quoted, the deals the AI lists, and the
price actually booked can never drift apart.

Two dimensions of eligibility:
  - **effective period** — ``promo_date_ok`` mirrors resolved_price's SQL
    comparison exactly (``valid_from <= now <= valid_to``, NULL = open-ended,
    ``now`` in Bangkok wall-clock — pass ``booking._now_local()``).
  - **quota** — ``Promotion.quota`` (0 = unlimited). A promo is *used* once per
    booking stamped with its ``promo_id`` that has at least one PAID payment
    (deposit or full). Refunds free the slot automatically because the payment
    status leaves 'paid'. Quota is enforced at quote/booking time, not payment
    time, so N concurrent unpaid bookings can all take the last slot and later
    all pay — an accepted oversell for this single-process SQLite design.
"""
from sqlalchemy import func

from app import models
from app.scope import scoped


def promo_date_ok(promo, now) -> bool:
    """True when ``promo`` is inside its effective period at ``now``
    (clinic-local wall clock, i.e. ``booking._now_local()``). NULL bounds are
    open-ended. Same comparison direction as resolved_price's SQL filter."""
    return ((not promo.valid_from or promo.valid_from <= now)
            and (not promo.valid_to or promo.valid_to >= now))


def promo_used_counts(db, clinic_id, promo_ids=None) -> dict[int, int]:
    """{promo_id: redemptions} for one clinic in a single grouped query.

    A redemption = a distinct booking stamped with the promo that has >= 1
    paid payment. Optionally restricted to ``promo_ids``.
    """
    if promo_ids is not None and not promo_ids:
        return {}
    q = (db.query(models.Booking.promo_id,
                  func.count(func.distinct(models.Booking.id)))
         .join(models.Payment, models.Payment.booking_id == models.Booking.id)
         .filter(models.Booking.clinic_id == clinic_id,
                 models.Booking.promo_id.isnot(None),
                 models.Payment.status == "paid")
         .group_by(models.Booking.promo_id))
    if promo_ids is not None:
        q = q.filter(models.Booking.promo_id.in_(list(promo_ids)))
    return {pid: int(n) for pid, n in q.all()}


def exhausted_promo_ids(db, clinic_id) -> set[int]:
    """Ids of this clinic's promotions whose quota is fully redeemed.

    Constant two queries regardless of promo count: one for quota-limited
    promos, one grouped usage count over just those ids.
    """
    quotas = {pid: qty for pid, qty in
              scoped(db, models.Promotion, clinic_id)
              .filter(models.Promotion.quota > 0)
              .with_entities(models.Promotion.id, models.Promotion.quota).all()}
    if not quotas:
        return set()
    used = promo_used_counts(db, clinic_id, promo_ids=list(quotas))
    return {pid for pid, qty in quotas.items() if used.get(pid, 0) >= qty}


def promo_branch_ids(db, clinic_id: int) -> dict[int, set[int]]:
    """Every promotion's branch set for one clinic, keyed by promotion id.

    An empty set (or no entry) means "runs at every branch" — the same convention
    ServiceBranch uses. The legacy single ``Promotion.branch_id`` is folded in here
    too, so a row written before the join table existed still reads correctly even
    if the startup backfill has not run yet: ONE reader, so the price a customer is
    quoted and the deals the AI lists cannot disagree about where a promo applies.
    """
    out: dict[int, set[int]] = {}
    for row in scoped(db, models.PromotionBranch, clinic_id).all():
        out.setdefault(row.promotion_id, set()).add(row.branch_id)
    for p in scoped(db, models.Promotion, clinic_id).all():
        if p.branch_id and p.id not in out:
            out[p.id] = {p.branch_id}
    return out


def promo_runs_at(branch_ids: set[int] | None, branch_id) -> bool:
    """Does a promotion with this branch set apply at ``branch_id``?

    No restriction = everywhere. With a restriction and an UNKNOWN branch the answer
    is False: a branch-specific deal must never be quoted before the customer has
    said which branch they want.
    """
    if not branch_ids:
        return True
    return bool(branch_id) and branch_id in branch_ids
