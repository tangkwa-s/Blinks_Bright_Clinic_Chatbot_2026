"""Regression tests for app/services/booking.py::deposit_for.

A per-service deposit override is a FLAT ฿ amount, deliberately the SAME at every
branch — the clinic sets one deposit for the treatment regardless of how much its
price differs from branch to branch. It's capped at the quoted price so a cheaper
branch is never asked for more than its own price. No override -> auto 20%.
"""
from app import models
from app.ai.tools import execute_tool
from app.services.booking import deposit_for, resolved_price_detail


def _service(base_price=2800.0, deposit=0.0):
    return models.Service(name="Signature Facial", category="Facial",
                          base_price=base_price, deposit=deposit, active=True)


def test_no_override_is_20_percent_of_whatever_price_is_quoted():
    svc = _service(base_price=2800.0, deposit=0.0)
    assert deposit_for(svc, 2800.0) == 600.0    # 20% of base, rounded to nearest 100
    assert deposit_for(svc, 2300.0) == 500.0    # 20% of a cheaper branch price
    assert deposit_for(svc, 2700.0) == 500.0    # 20% of another branch price


def test_override_is_the_same_flat_amount_at_every_branch():
    """A ฿500 override set against a ฿3,500 base must be charged as that SAME
    ฿500 at every branch, regardless of how much cheaper or pricier that
    branch's own price is — the clinic picked one deposit for the treatment."""
    svc = _service(base_price=3500.0, deposit=500.0)
    assert deposit_for(svc, 3500.0) == 500.0    # at the base price
    assert deposit_for(svc, 3000.0) == 500.0    # a cheaper branch: still ฿500
    assert deposit_for(svc, 2500.0) == 500.0    # an even cheaper branch: still ฿500


def test_override_never_exceeds_the_quoted_price():
    """catalog.py clamps the override to <= base_price on save, but a branch can
    still be priced BELOW the override — deposit_for must still cap it at that
    branch's own price so the deposit never exceeds what's actually owed."""
    svc = _service(base_price=2000.0, deposit=2000.0)   # 100% override at base
    assert deposit_for(svc, 2000.0) == 2000.0
    assert deposit_for(svc, 1000.0) == 1000.0           # capped at the lower price


def test_deposit_for_matches_resolved_branch_price(db, clinic):
    """End-to-end: a booking priced via resolved_price_detail at a branch's own
    ServicePrice still gets the SAME flat override deposit (not scaled)."""
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    other_branch = models.Branch(clinic_id=clinic.id, name="Second Branch")
    db.add(other_branch)
    db.commit()

    svc = models.Service(clinic_id=clinic.id, name="Signature Facial", category="Facial",
                        base_price=2800.0, deposit=1000.0, active=True)
    db.add(svc)
    db.commit()
    db.add(models.ServicePrice(clinic_id=clinic.id, service_id=svc.id,
                               branch_id=other_branch.id, price=2300.0))
    db.commit()

    price_base, _ = resolved_price_detail(db, clinic.id, svc, branch.id)
    price_other, _ = resolved_price_detail(db, clinic.id, svc, other_branch.id)
    assert price_base == 2800.0
    assert price_other == 2300.0
    assert deposit_for(svc, price_base) == 1000.0
    assert deposit_for(svc, price_other) == 1000.0


def test_list_treatments_tool_quotes_same_deposit_per_branch(db, make_clinic):
    """End-to-end through the AI's actual list_treatments tool call (branch name
    resolution + price_branch lookup + deposit_for) — this is the exact code path
    that quotes price/deposit to the customer. Reproduces a 3-branch clinic (a
    ฿1,000 override on a ฿2,800 base) and checks every branch gets the SAME ฿1,000
    deposit even though their prices differ."""
    clinic = make_clinic("Aurora Test Clinic", slug="aurora-test-clinic", starter=False)
    central = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    central.name = "Central Aurora"
    north = models.Branch(clinic_id=clinic.id, name="North Aurora")
    south = models.Branch(clinic_id=clinic.id, name="South Aurora")
    db.add_all([north, south])
    db.commit()

    svc = models.Service(clinic_id=clinic.id, name="Signature Facial", category="Facial",
                        base_price=2800.0, deposit=1000.0, active=True)
    db.add(svc)
    db.commit()
    db.add_all([
        models.ServicePrice(clinic_id=clinic.id, service_id=svc.id, branch_id=north.id, price=2700.0),
        models.ServicePrice(clinic_id=clinic.id, service_id=svc.id, branch_id=south.id, price=2300.0),
    ])
    db.commit()

    customer = models.Customer(clinic_id=clinic.id, name="ฟ้าใส")
    db.add(customer)
    db.commit()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=customer.id, channel="web")
    db.add(conv)
    db.commit()

    expected = {"Central Aurora": ("฿2,800", "฿1,000"),
                "North Aurora": ("฿2,700", "฿1,000"),
                "South Aurora": ("฿2,300", "฿1,000")}
    for branch_name, (price_from, deposit_from) in expected.items():
        conv.branch_id = None
        customer.branch_id = None
        # The tool only adopts a branch the CUSTOMER named, so give it the message a
        # real conversation would have (see tools.py::_branch_said_by_customer).
        db.query(models.Message).filter_by(conversation_id=conv.id).delete()
        db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id,
                              sender="customer", text=f"สนใจสาขา {branch_name} ค่ะ"))
        db.commit()
        res = execute_tool(db, conv, customer, "list_treatments", {"branch": branch_name})
        sig = next(t for t in res["treatments"] if t["name"] == "Signature Facial")
        assert sig["price_from"] == price_from
        assert sig["deposit_from"] == deposit_from
