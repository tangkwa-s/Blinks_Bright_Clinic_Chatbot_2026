"""Booking on the website is for members.

The anonymous chat widget (home page, ``/chat/<slug>``) still answers questions, but
only a customer signed in through the portal, whose chat runs on their own record,
can take a slot. The rule is read off the customer record (``password_hash``), not the
conversation, because the portal thread and the anonymous widget share channel "web".
Two layers, like every other booking rule: a prompt hint so the assistant does not
walk a visitor through the whole checklist first, and ``book_appointment`` refusing
outright so no phrasing gets past it.
"""
from datetime import timedelta

from app import models
from app.ai.chat import _shows_signup, _signup_hint
from app.ai.tools import booking_requires_signup, execute_tool
from app.services import booking
from app.services.inbox import msg_dict

PW = "secret12345"


def _customer(db, clinic, channel="web", password_hash=""):
    c = models.Customer(clinic_id=clinic.id, name="คุณทดสอบ", phone="0812345678",
                        channel=channel, password_hash=password_hash)
    db.add(c)
    db.commit()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=c.id, channel=channel)
    db.add(conv)
    db.commit()
    return c, conv


def _book_args(db, clinic):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = db.query(models.Service).filter_by(clinic_id=clinic.id, active=True).first()
    slot = booking.available_slots(db, branch.id, booking._now_local() + timedelta(days=3))[0]
    return branch, {"treatment": svc.name, "branch": branch.name, "branch_said": branch.name,
                    "date": slot.strftime("%Y-%m-%d"), "time": slot.strftime("%H:%M"),
                    "payment_type": "deposit", "payment_said": "มัดจำค่ะ"}


def test_anonymous_web_visitor_cannot_book(db, clinic):
    cust, conv = _customer(db, clinic)
    _branch, args = _book_args(db, clinic)
    res = execute_tool(db, conv, cust, "book_appointment", args)
    assert res["need_signup"] is True and res["booked"] is False
    assert res["signup_path"].startswith("/portal")
    assert db.query(models.Booking).filter_by(customer_id=cust.id).count() == 0
    # refused before anything else ran, so not even the branch was written
    db.refresh(conv)
    assert conv.branch_id is None


def test_portal_member_is_not_asked_to_sign_up(db, clinic):
    cust, conv = _customer(db, clinic, password_hash="portal-member")
    _branch, args = _book_args(db, clinic)
    res = execute_tool(db, conv, cust, "book_appointment", args)
    assert not res.get("need_signup")


def test_questions_still_work_for_a_visitor(db, clinic):
    cust, conv = _customer(db, clinic)
    res = execute_tool(db, conv, cust, "list_treatments", {})
    assert not res.get("need_signup")


def test_prompt_hint_only_for_visitors(db, clinic):
    anon, anon_conv = _customer(db, clinic)
    assert "MEMBERS-ONLY BOOKING" in _signup_hint(anon_conv, anon)
    member, member_conv = _customer(db, clinic, password_hash="portal-member")
    assert _signup_hint(member_conv, member) == ""


def test_signup_button_follows_the_reply(db, clinic):
    anon, conv = _customer(db, clinic)
    assert _shows_signup(conv, anon, "ราคา 2,500 บาทค่ะ", refused=True)
    assert _shows_signup(conv, anon, "รบกวนสมัครสมาชิกก่อนนะคะ", refused=False)
    assert _shows_signup(conv, anon, "Please sign up first.", refused=False)
    assert not _shows_signup(conv, anon, "ราคา 2,500 บาทค่ะ", refused=False)
    member, mconv = _customer(db, clinic, password_hash="portal-member")
    assert not _shows_signup(mconv, member, "เข้าสู่ระบบแล้วค่ะ", refused=False)


def test_msg_dict_carries_the_signup_flag(db, clinic):
    _c, conv = _customer(db, clinic)
    m = models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="ai",
                       text="สมัครสมาชิกก่อนนะคะ", meta={"signup": True})
    db.add(m)
    db.commit()
    assert msg_dict(m)["signup"] is True


def test_widget_is_told_whether_the_thread_is_a_members(client, db, clinic):
    r = client.post("/api/channels/web/start", json={"clinic": clinic.slug})
    assert r.status_code == 200 and r.json()["member"] is False
    anon = client.get("/api/channels/web/messages", params={"token": r.json()["token"]})
    assert anon.json()["member"] is False

    reg = client.post("/api/portal/register", json={"name": "คุณทดสอบ", "phone": "0812345678",
                                                    "password": PW, "clinic": clinic.slug})
    assert reg.status_code == 200, reg.text
    tok = client.post("/api/portal/chat", json={}).json()["token"]
    mine = client.get("/api/channels/web/messages", params={"token": tok})
    assert mine.json()["member"] is True
