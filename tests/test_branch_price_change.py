"""list_treatments must announce a branch price that moved.

The prompt already told the AI to flag it and the model kept skipping the rule: asked
for a branch it simply stated the new number, leaving the customer to notice on their
own that 9,500 had become 10,000. When the branch is the DEARER one that is the
customer finding out at the counter. The tool now hands over the finished sentence,
which is a thing a test can hold — a prompt rule is not.
"""
from app import models
from app.ai import tools as T

STANDARD = 9500


# Booking on the website is members-only (tools.booking_requires_signup), and these
# tests are about the booking itself, so their web customers hold a portal account.
MEMBER = "portal-member"


def _setup(db, clinic, branch_price):
    """One clinic, two branches, and a service (a NAME the starter catalog does
    not already carry) priced differently at the second."""
    home = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    home.name = "Central Aurora"
    other = models.Branch(clinic_id=clinic.id, name="North Aurora",
                          open_hour=10, close_hour=20)
    db.add(other)
    db.flush()
    svc = models.Service(clinic_id=clinic.id, name="Aqua Glow Booster", category="ผิว",
                         base_price=STANDARD, duration_min=40, active=True)
    db.add(svc)
    db.flush()
    db.add(models.ServicePrice(clinic_id=clinic.id, service_id=svc.id,
                               branch_id=other.id, price=branch_price))
    cust = models.Customer(password_hash=MEMBER, clinic_id=clinic.id, name="คุณเทส", channel="web")
    db.add(cust)
    db.flush()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web",
                               branch_id=other.id)
    db.add(conv)
    db.commit()
    return conv, cust, svc, other


def _quote(db, conv, text):
    """The AI's earlier message to this customer — where the first figure came from."""
    db.add(models.Message(clinic_id=conv.clinic_id, conversation_id=conv.id,
                          sender="ai", text=text))
    db.commit()


def _aqua(res):
    return next(t for t in res["treatments"] if t["name"] == "Aqua Glow Booster")


def test_dearer_branch_is_announced_with_a_ready_sentence(db, clinic):
    """The damaging direction: the customer was quoted 9,500 and this branch is 10,000."""
    conv, cust, _svc, _br = _setup(db, clinic, 10000)
    _quote(db, conv, "สกินบู๊ทเริ่มต้นที่ 9,500 บาท ใช้เวลาประมาณ 40 นาทีค่ะ")

    res = T.execute_tool(db, conv, cust, "list_treatments", {})
    item = _aqua(res)

    assert item["price_from"] == "฿10,000"
    assert item["standard_price"] == "฿9,500"
    assert item["price_moved"] == "higher"
    assert "สูงกว่า" in item["say_it_like"]
    assert "฿500" in item["say_it_like"]                 # the gap, spelled out
    assert "North Aurora" in item["say_it_like"]
    assert "price_change_note" in res
    assert "confirm the new price BEFORE" in res["price_change_note"]


def test_cheaper_branch_is_announced_too(db, clinic):
    conv, cust, _svc, _br = _setup(db, clinic, 9000)
    _quote(db, conv, "สกินบู๊ทเริ่มต้นที่ 9,500 บาทค่ะ")

    item = _aqua(T.execute_tool(db, conv, cust, "list_treatments", {}))
    assert item["price_moved"] == "lower"
    assert "ต่ำกว่า" in item["say_it_like"]


def test_silent_when_the_customer_was_never_quoted_the_standard_price(db, clinic):
    """Branch named before any price was given — there is nothing to reconcile, so the
    note would only be noise."""
    conv, cust, _svc, _br = _setup(db, clinic, 10000)
    _quote(db, conv, "สะดวกสาขาไหนคะ ตอนนี้เรามีสาขา Central Aurora และ North Aurora ค่ะ")

    res = T.execute_tool(db, conv, cust, "list_treatments", {})
    assert "standard_price" not in _aqua(res)
    assert "price_change_note" not in res


def test_silent_when_the_branch_price_matches_the_standard(db, clinic):
    conv, cust, _svc, _br = _setup(db, clinic, STANDARD)
    _quote(db, conv, "สกินบู๊ทเริ่มต้นที่ 9,500 บาทค่ะ")

    res = T.execute_tool(db, conv, cust, "list_treatments", {})
    assert "standard_price" not in _aqua(res)
    assert "price_change_note" not in res


def test_the_customers_own_figure_does_not_count_as_a_quote(db, clinic):
    """Only what the CLINIC side stated counts — a number the customer typed
    ("งบ 9500 ได้ไหมคะ") is not a price the clinic gave them."""
    conv, cust, _svc, _br = _setup(db, clinic, 10000)
    db.add(models.Message(clinic_id=conv.clinic_id, conversation_id=conv.id,
                          sender="customer", text="งบประมาณ 9500 ได้ไหมคะ"))
    db.commit()

    res = T.execute_tool(db, conv, cust, "list_treatments", {})
    assert "standard_price" not in _aqua(res)


def test_a_human_teammates_quote_counts(db, clinic):
    """A teammate's number is authoritative context, so contradicting it needs the
    same announcement."""
    conv, cust, _svc, _br = _setup(db, clinic, 10000)
    db.add(models.Message(clinic_id=conv.clinic_id, conversation_id=conv.id,
                          sender="admin", text="สกินบู๊ท 9,500 บาทค่ะ"))
    db.commit()

    assert _aqua(T.execute_tool(db, conv, cust, "list_treatments", {})
                         )["price_moved"] == "higher"


def test_another_treatments_price_does_not_silence_the_announcement(db, clinic):
    """The reported failure. The opening menu lists several treatments and several
    prices; this branch then charges ฿5,000 for Aqua Glow — the same figure the menu
    had just quoted for a DIFFERENT treatment. Read as one flat pile of numbers, 5,000
    looked "already said" and the announcement never fired, so the customer went from
    the ฿9,500 they had been quoted to ฿5,000 without a word.
    """
    conv, cust, _svc, _br = _setup(db, clinic, 5000)
    other = models.Service(clinic_id=clinic.id, name="Acne Clear Program", category="ผิว",
                           base_price=5000, duration_min=45, active=True)
    db.add(other)
    db.commit()
    _quote(db, conv, "ขอแนะนำทรีตเมนต์ยอดนิยมค่ะ\n"
                     "1. Acne Clear Program, ช่วยดูแลปัญหาสิว, ราคาเริ่มต้น 5,000 บาท\n"
                     "2. Aqua Glow Booster, ทรีตเมนต์ผิว, ราคาเริ่มต้น 9,500 บาท")

    res = T.execute_tool(db, conv, cust, "list_treatments", {})
    item = _aqua(res)
    assert item["price_from"] == "฿5,000"
    assert item["price_moved"] == "lower", "5,000 belongs to the OTHER treatment's line"
    assert "9,500" in item["say_it_like"]
    assert "price_change_note" in res


def test_the_note_retires_once_the_branch_price_has_been_said(db, clinic):
    """Every later list_treatments call used to re-arm the note, and the model dutifully
    repeated the whole price paragraph — even in answer to a bare "ครับ"."""
    conv, cust, _svc, _br = _setup(db, clinic, 10000)
    _quote(db, conv, "สกินบู๊ทเริ่มต้นที่ 9,500 บาทค่ะ")
    assert "price_change_note" in T.execute_tool(db, conv, cust, "list_treatments", {})

    # the AI has now told them; a second call must not ask for it again
    _quote(db, conv, "ที่สาขา North Aurora ราคาอยู่ที่ 10,000 บาทค่ะ สูงกว่าที่แจ้งไว้ 500 บาท")
    again = T.execute_tool(db, conv, cust, "list_treatments", {})
    assert "price_change_note" not in again
    assert "standard_price" not in _aqua(again)


# --------------------------------------------------------------------------
# A promotion that applies itself at booking time must be spoken out loud
# --------------------------------------------------------------------------
def _bookable(db, clinic, branch_price=None, promo_price=None):
    """Customer ready to book, having already answered the deposit-or-full question."""
    from datetime import timedelta
    from app.services import booking as bk

    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = models.Service(clinic_id=clinic.id, name="Aqua Glow Booster", category="ผิว",
                         base_price=STANDARD, duration_min=40, active=True)
    db.add(svc)
    db.flush()
    if branch_price:
        db.add(models.ServicePrice(clinic_id=clinic.id, service_id=svc.id,
                                   branch_id=branch.id, price=branch_price))
    if promo_price:
        now = bk._now_local()
        db.add(models.Promotion(clinic_id=clinic.id, service_id=svc.id,
                                title="First Aqua Glow ฿7,900", promo_price=promo_price,
                                active=True, valid_from=now - timedelta(days=1),
                                valid_to=now + timedelta(days=30)))
    cust = models.Customer(password_hash=MEMBER, clinic_id=clinic.id, name="คุณเทส", phone="0812345678",
                           channel="web", branch_id=branch.id)
    db.add(cust)
    db.flush()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web",
                               branch_id=branch.id)
    db.add(conv)
    db.commit()
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="ai",
                          text="ราคา 9,000 บาท มัดจำ 1,800 บาท ชำระมัดจำหรือเต็มจำนวนคะ"))
    db.commit()
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id,
                          sender="customer", text="มัดจำค่ะ"))
    db.commit()

    slot = bk.available_slots(db, branch.id, bk._now_local() + timedelta(days=3))[0]
    return conv, cust, {"treatment": svc.name, "date": slot.strftime("%Y-%m-%d"),
                        "time": slot.strftime("%H:%M"), "payment_type": "deposit",
                        "payment_said": "มัดจำค่ะ"}


def test_an_auto_applied_promotion_is_announced(db, clinic):
    """list_treatments quotes 9,000 (promotions are only offered when asked) but
    create_booking applies the promo, so the booking lands at 7,900. The customer
    agreed to one number and must be told it moved, even downwards."""
    conv, cust, args = _bookable(db, clinic, branch_price=9000, promo_price=7900)

    res = T.execute_tool(db, conv, cust, "book_appointment", args)

    assert res["booked"] is True
    assert res["price"] == "฿7,900"
    assert res["price_before_promo"] == "฿9,000"
    assert res["promo_applied"] == "First Aqua Glow ฿7,900"
    assert "฿9,000" in res["promo_say_it_like"] and "฿7,900" in res["promo_say_it_like"]
    assert "never let an agreed number change" in res["promo_note"]


def test_no_promo_no_announcement(db, clinic):
    """Nothing to explain when the booked price is the price they agreed to."""
    conv, cust, args = _bookable(db, clinic, branch_price=9000)

    res = T.execute_tool(db, conv, cust, "book_appointment", args)
    assert res["booked"] is True and res["price"] == "฿9,000"
    assert "promo_applied" not in res and "promo_note" not in res
