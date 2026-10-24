"""Multi-tenant query scoping.

Every clinic-owned table carries ``clinic_id``. ``scoped`` returns a query
already restricted to one clinic — the single chokepoint for data isolation.
"""
from sqlalchemy.orm import Query, Session


def scoped(db: Session, model, clinic_id: int) -> Query:
    """A query for ``model`` restricted to one clinic."""
    return db.query(model).filter(model.clinic_id == clinic_id)


def customer_branch_map(db: Session, clinic_id: int) -> dict[int, int | None]:
    """The EFFECTIVE branch of every customer in one clinic.

    Web-chat leads are created by ``handle_inbound`` before any
    branch is known, so ``Customer.branch_id`` is NULL for them. Filtering a
    per-branch view on that column alone therefore showed nothing. The customer's
    branch is their own ``branch_id`` when set, else the branch they actually
    booked at, else the branch of a conversation they had.
    """
    from app import models  # local import — models imports nothing from here

    fallback: dict[int, int] = {}
    for model in (models.Booking, models.Conversation):
        rows = (db.query(model.customer_id, model.branch_id)
                .filter(model.clinic_id == clinic_id, model.branch_id.isnot(None))
                .order_by(model.id).all())
        for cust_id, branch_id in rows:
            fallback.setdefault(cust_id, branch_id)

    return {c_id: (b_id or fallback.get(c_id))
            for c_id, b_id in db.query(models.Customer.id, models.Customer.branch_id)
            .filter(models.Customer.clinic_id == clinic_id).all()}
