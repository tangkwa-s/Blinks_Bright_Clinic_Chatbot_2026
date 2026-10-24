"""Automation messages leave a truthful, visible trace in the chat thread.

Every automation / campaign send attempt persists a Message in the customer's
conversation with the delivery outcome stamped in ``meta`` (``automation`` +
``delivery``), so failures show up in the inbox as a 'not delivered' chip
instead of vanishing silently. Also locks in the run_automations sent/failed
counts and the scheduled-campaign empty-message guard.
"""
from datetime import datetime, timedelta

from app import models
from app.services.automations import process_due
from app.services.booking import _now_local
from app.services.inbox import broadcast_to_customer, msg_dict


def _make_customer(db, clinic, name="Fah", channel="web", uid="trace-u1"):
    c = models.Customer(clinic_id=clinic.id, name=name, channel=channel,
                        channel_user_id=uid, pipeline_stage="new_lead",
                        temperature="warm", lead_score=20)
    db.add(c)
    db.commit()
    return c


def _make_due_reminder(db, clinic, cust, rtype="winback"):
    r = models.Reminder(
        clinic_id=clinic.id, customer_id=cust.id, type=rtype,
        channel=cust.channel or "web", title="We miss you",
        body="คิดถึงนะคะ กลับมาดูแลผิวกันไหมคะ",
        due_at=_now_local() - timedelta(minutes=5), status="scheduled")
    db.add(r)
    db.commit()
    return r


def _messages_for(db, clinic, cust):
    conv_ids = [c.id for c in db.query(models.Conversation)
                .filter_by(clinic_id=clinic.id, customer_id=cust.id).all()]
    return (db.query(models.Message)
            .filter(models.Message.conversation_id.in_(conv_ids)).all()) if conv_ids else []


def test_web_customer_reminder_delivers_and_traces_sent(db, clinic):
    cust = _make_customer(db, clinic, channel="web")
    r = _make_due_reminder(db, clinic, cust)

    out = process_due(db, clinic)
    assert out == {"sent": 1, "failed": 0}

    db.refresh(r)
    assert r.status == "sent"

    msgs = _messages_for(db, clinic, cust)
    assert len(msgs) == 1
    assert msgs[0].meta.get("automation") is True
    assert msgs[0].meta.get("delivery") == "sent"
    assert "reason" not in msgs[0].meta


def test_blank_text_still_persists_nothing(db, clinic):
    cust = _make_customer(db, clinic, channel="web")
    assert broadcast_to_customer(db, cust, "   ") is False
    assert _messages_for(db, clinic, cust) == []


def test_msg_dict_exposes_automation_flags_only_for_automation(db, clinic):
    cust = _make_customer(db, clinic, channel="web")
    _make_due_reminder(db, clinic, cust)
    process_due(db, clinic)
    sent = _messages_for(db, clinic, cust)[0]

    d = msg_dict(sent)
    assert d["automation"] is True
    assert "delivery_failed" not in d
    assert d["sender_name"] == "Automation"

    # a plain human admin reply carries neither flag
    conv = db.get(models.Conversation, sent.conversation_id)
    human = models.Message(clinic_id=clinic.id, conversation_id=conv.id,
                           sender="admin", sender_name="Bank", text="สวัสดีค่ะ")
    db.add(human)
    db.commit()
    d2 = msg_dict(human)
    assert "automation" not in d2
    assert "delivery_failed" not in d2


def test_msg_dict_surfaces_guardrail_flags_the_filters_could_not_strip(db, clinic):
    """offer_flags/discount_flags/payment_unverified are computed every turn by
    app/ai/guardrails.py but were never read by msg_dict — a flagged reply reached no
    one but the meta JSON column. Any one of the three should surface as a reason a
    human can see on the bubble."""
    cust = _make_customer(db, clinic, channel="web", uid="w-flag-1")
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web")
    db.add(conv)
    db.commit()

    offer_msg = models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="ai",
                               text="...", meta={"grounded": True, "offer_flags": ["ฟรี"]})
    discount_msg = models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="ai",
                                  text="...", meta={"grounded": True, "discount_flags": [500]})
    unverified_msg = models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="ai",
                                    text="...", meta={"grounded": True, "payment_unverified": True})
    clean_msg = models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="ai",
                               text="...", meta={"grounded": True})
    db.add_all([offer_msg, discount_msg, unverified_msg, clean_msg])
    db.commit()

    assert msg_dict(offer_msg)["flag_reasons"] == ["offer"]
    assert msg_dict(discount_msg)["flag_reasons"] == ["discount"]
    assert msg_dict(unverified_msg)["flag_reasons"] == ["payment"]
    assert "flag_reasons" not in msg_dict(clean_msg)


def test_msg_dict_surfaces_the_grounding_trail_for_staff(db, clinic):
    """meta.grounding (app/ai/chat.py::respond's raw KB/catalog/tool-result trail) must
    reach msg_dict verbatim so staff can debug a hallucinated claim, and must be absent
    entirely when the reply carries none (older rows, or the canned fallback reply)."""
    cust = _make_customer(db, clinic, channel="web", uid="w-ground-1")
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web")
    db.add(conv)
    db.commit()

    grounded_msg = models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="ai",
                                  text="...", meta={"grounded": True, "grounding": "KB: HIFU 25000 baht"})
    clean_msg = models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="ai",
                               text="...", meta={"grounded": True})
    db.add_all([grounded_msg, clean_msg])
    db.commit()

    assert msg_dict(grounded_msg)["grounding"] == "KB: HIFU 25000 baht"
    assert "grounding" not in msg_dict(clean_msg)


def test_campaign_delivery_stamps_automation_meta(db, clinic):
    from app.routers.broadcast import deliver_campaign

    reachable = _make_customer(db, clinic, name="Nok", channel="web", uid="w-1")
    camp = models.Campaign(clinic_id=clinic.id, name="Summer Promo", audience={},
                           channel="all", message="โปรหน้าร้อนค่ะ", status="draft",
                           audience_count=1)
    db.add(camp)
    db.commit()

    out = deliver_campaign(db, camp, clinic.id)
    assert out["sent"] == 1
    assert out["failed"] == 0

    ok_msgs = _messages_for(db, clinic, reachable)
    assert len(ok_msgs) == 1
    assert ok_msgs[0].sender_name == "Summer Promo"
    assert ok_msgs[0].meta.get("delivery") == "sent"

    # the per-recipient campaign log records the delivery
    acts = (db.query(models.Activity)
            .filter_by(type="campaign", ref_type="campaign", ref_id=camp.id).all())
    statuses = {a.customer_id: a.summary.split(" · ")[-1] for a in acts}
    assert statuses[reachable.id] == "delivered"


def test_scheduling_campaign_with_empty_message_is_rejected(auth_client):
    future = (datetime.now() + timedelta(days=1)).isoformat(timespec="minutes")
    r = auth_client.post("/api/campaigns", json={
        "name": "Empty scheduled", "audience": {}, "channel": "all",
        "message": "   ", "scheduled_at": future})
    assert r.status_code == 400
    assert "message" in r.json()["detail"].lower()

    # a draft (unscheduled) empty campaign is still allowed — manual send has its own guard
    r2 = auth_client.post("/api/campaigns", json={
        "name": "Empty draft", "audience": {}, "channel": "all", "message": ""})
    assert r2.status_code == 200
    assert r2.json()["status"] == "draft"
