"""Two live bookings: the payment link must know WHICH one, and a branch move must be said.

A real chat: the customer booked HIFU Lifting at South Aurora and paid the ฿4,800
deposit. They then asked about Signature Facial, which South does not offer, so the
assistant moved the conversation to Central Aurora and booked it there — paid in full.
When they came back to settle the HIFU balance, ``create_payment_link`` looked at the
NEWEST booking (the Signature they had just settled), found nothing outstanding, and
reported "already paid" — so they were told a ฿19,200 balance was cleared.

Meanwhile the HIFU booking stayed at South while every price on screen was Central's,
where the same treatment costs more; nobody mentioned it, and the assistant offered the
same time slot at the other branch as though a person could attend both.
"""
from datetime import timedelta

from app import models
from app.ai.chat import _booking_hint
from app.ai.tools import execute_tool
from app.services import booking as bk


def _branches(db, clinic):
    south = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    south.name = "South Aurora"
    central = models.Branch(clinic_id=clinic.id, name="Central Aurora",
                            open_hour=10, close_hour=20)
    db.add(central)
    db.commit()
    return south, central


def _service(db, clinic, name, price, branch_ids=()):
    s = models.Service(clinic_id=clinic.id, name=name, category="facial",
                       base_price=price, duration_min=60, active=True)
    db.add(s)
    db.flush()
    for bid in branch_ids:
        db.add(models.ServiceBranch(clinic_id=clinic.id, service_id=s.id, branch_id=bid))
    db.commit()
    return s


def _customer(db, clinic, branch):
    c = models.Customer(clinic_id=clinic.id, name="ช็อคชิพ", phone="0944444444",
                        channel="web", branch_id=branch.id)
    db.add(c)
    db.commit()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=c.id, channel="web",
                               branch_id=branch.id)
    db.add(conv)
    db.commit()
    return c, conv


def _booking(db, clinic, cust, svc, branch, price, deposit, paid=0.0, hours=24):
    b = models.Booking(clinic_id=clinic.id, customer_id=cust.id, service_id=svc.id,
                       branch_id=branch.id, slot_at=bk._now_local() + timedelta(hours=hours),
                       status="confirmed", price=price, deposit_required=deposit)
    db.add(b)
    db.flush()
    if paid:
        db.add(models.Payment(clinic_id=clinic.id, customer_id=cust.id, booking_id=b.id,
                              amount=paid, status="paid", type="deposit"))
    db.commit()
    return b


def _charged(db, booking) -> float:
    """The amount of the newest UNPAID payment raised against this booking. Stripe is
    off in tests, so no URL is minted — the Payment row is what proves which booking
    the tool acted on and for how much."""
    p = (db.query(models.Payment)
         .filter(models.Payment.booking_id == booking.id,
                 models.Payment.status != "paid")
         .order_by(models.Payment.id.desc()).first())
    return float(p.amount) if p else 0.0


def _two_bookings(db, clinic):
    """The reported situation: HIFU part-paid at South, Signature settled at Central."""
    south, central = _branches(db, clinic)
    hifu = _service(db, clinic, "HIFU Lifting", 24000)
    facial = _service(db, clinic, "Signature Facial", 2800, branch_ids=[central.id])
    db.add(models.ServicePrice(clinic_id=clinic.id, service_id=hifu.id,
                               branch_id=central.id, price=26000))
    db.commit()
    cust, conv = _customer(db, clinic, south)
    part_paid = _booking(db, clinic, cust, hifu, south, 24000, 4800, paid=4800)
    settled = _booking(db, clinic, cust, facial, central, 2200, 600, paid=2200, hours=25)
    return south, central, hifu, facial, cust, conv, part_paid, settled


# --------------------------------------------------------------------------
# create_payment_link — which booking?
# --------------------------------------------------------------------------
def test_it_refuses_to_guess_between_two_bookings(db, clinic):
    _s, _c, _hifu, _facial, cust, conv, _pp, _st = _two_bookings(db, clinic)

    res = execute_tool(db, conv, cust, "create_payment_link", {"type": "full"})
    assert "need_which_booking" in res
    assert len(res["need_which_booking"]) == 2
    assert "already_paid" not in res and "payment_link" not in res
    assert "Do NOT guess" in res["note"]


def test_the_named_treatment_decides_which_balance_is_collected(db, clinic):
    _s, _c, _hifu, _facial, cust, conv, part_paid, _st = _two_bookings(db, clinic)

    res = execute_tool(db, conv, cust, "create_payment_link",
                       {"type": "full", "treatment": "HIFU Lifting"})
    assert "already_paid" not in res, "the OTHER booking is the settled one"
    assert _charged(db, part_paid) == 19200.0, "24,000 less the 4,800 already paid"


def test_the_customers_own_last_message_can_decide_it(db, clinic):
    """They wrote "ขอจ่าย HIFU Lifting ที่เหลือค่ะ" — the model need not relay it."""
    _s, _c, _hifu, _facial, cust, conv, _pp, _st = _two_bookings(db, clinic)
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="customer",
                          text="ขอจ่าย HIFU Lifting ส่วนที่เหลือค่ะ"))
    db.commit()

    execute_tool(db, conv, cust, "create_payment_link", {"type": "full"})
    assert _charged(db, _pp) == 19200.0, "the treatment they named, not the newest booking"


def test_already_paid_names_the_treatment_it_is_about(db, clinic):
    """"already paid" against the wrong booking is how a ฿19,200 balance vanished."""
    _s, _c, _hifu, _facial, cust, conv, _pp, _st = _two_bookings(db, clinic)

    res = execute_tool(db, conv, cust, "create_payment_link",
                       {"type": "full", "treatment": "Signature Facial"})
    assert res.get("already_paid") is True
    assert "Signature Facial" in res["booking"]
    assert res["paid_total"] == "฿2,200"


def test_a_single_booking_still_needs_no_naming(db, clinic):
    south, _central = _branches(db, clinic)
    svc = _service(db, clinic, "HIFU Lifting", 24000)
    cust, conv = _customer(db, clinic, south)
    only = _booking(db, clinic, cust, svc, south, 24000, 4800, paid=4800)

    execute_tool(db, conv, cust, "create_payment_link", {"type": "full"})
    assert _charged(db, only) == 19200.0


def test_a_full_payment_raised_before_the_deposit_is_resized_after(db, clinic):
    """Found while replaying the chat: the customer was asked for a stale ฿24,000.

    A "full" payment raised while nothing was paid is for the WHOLE price; once the
    deposit goes through the amount owed is smaller. The same row must be reused (a
    booking never carries two payable rows) with its amount brought down to the balance.
    """
    from app.services import billing as sp

    south, _central = _branches(db, clinic)
    svc = _service(db, clinic, "HIFU Lifting", 24000)
    cust, _conv = _customer(db, clinic, south)
    bk_row = _booking(db, clinic, cust, svc, south, 24000, 4800)      # nothing paid yet

    first = sp.create_payment(db, booking=bk_row, ptype="full")
    assert first.amount == 24000.0

    deposit = sp.create_payment(db, booking=bk_row, ptype="deposit")
    sp.mark_paid(db, deposit)

    again = sp.create_payment(db, booking=bk_row, ptype="full")
    assert again.id == first.id, "one payable row per booking and type"
    assert again.amount == 19200.0, "24,000 less the 4,800 now paid"


# --------------------------------------------------------------------------
# the branch the paid booking stays at
# --------------------------------------------------------------------------
def test_the_checklist_reports_a_booking_left_at_another_branch(db, clinic):
    south, central, _hifu, _facial, cust, conv, _pp, _st = _two_bookings(db, clinic)
    conv.branch_id = central.id          # the chat moved; the booking did not
    db.commit()

    hint = _booking_hint(db, conv, cust)
    assert "BOOKINGS AT ANOTHER BRANCH" in hint
    assert f"HIFU Lifting at {south.name}" in hint
    assert "paid so far ฿4,800" in hint
    assert "฿26,000" in hint and "฿24,000" in hint, "the price gap is spelled out"
    assert "cannot be at two branches at once" in hint


def test_the_move_itself_carries_the_warning(db, clinic):
    """On the turn the branch changes — before anything is quoted or booked against it."""
    south, central, _hifu, facial, cust, conv, _pp, _st = _two_bookings(db, clinic)
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="customer",
                          text=f"{central.name} ค่ะ"))
    db.commit()

    res = execute_tool(db, conv, cust, "list_treatments",
                       {"branch": central.name, "branch_said": central.name})
    assert conv.branch_id == central.id, "the customer named it, so it sticks"
    assert "existing_booking_elsewhere" in res
    said = res["branch_move_say_it_like"]
    assert south.name in said and "24,000" in said
    assert "26,000" in said, "the price at the branch they are moving to"
    assert "ไม่ได้ย้ายคิว" in said
    assert facial.name


def test_no_warning_when_the_branch_did_not_change(db, clinic):
    south, _central, _hifu, _facial, cust, conv, _pp, _st = _two_bookings(db, clinic)

    res = execute_tool(db, conv, cust, "list_treatments",
                       {"branch": south.name, "branch_said": south.name})
    assert "existing_booking_elsewhere" not in res


def test_no_such_warning_when_everything_is_at_this_branch(db, clinic):
    south, _central = _branches(db, clinic)
    svc = _service(db, clinic, "HIFU Lifting", 24000)
    cust, conv = _customer(db, clinic, south)
    _booking(db, clinic, cust, svc, south, 24000, 4800, paid=4800)

    assert "BOOKINGS AT ANOTHER BRANCH" not in _booking_hint(db, conv, cust)


def test_no_price_gap_line_when_the_price_is_the_same(db, clinic):
    """Only a price that actually MOVED is worth interrupting the customer for."""
    south, central = _branches(db, clinic)
    svc = _service(db, clinic, "HIFU Lifting", 24000)
    cust, conv = _customer(db, clinic, south)
    _booking(db, clinic, cust, svc, south, 24000, 4800, paid=4800)
    conv.branch_id = central.id
    db.commit()

    hint = _booking_hint(db, conv, cust)
    assert "BOOKINGS AT ANOTHER BRANCH" in hint
    assert "NOT the" not in hint
