"""A human takeover (manual, or the automatic 'serious' escalation in sales.py) pauses
the AI so a person can handle the conversation — but nothing ever reverted that on its
own if the person then went quiet. A customer whose message sat unanswered could wait
forever with no reply from anyone.

sweep_stale_takeovers (app/services/inbox.py) closes that gap: once the customer's
latest message has sat unanswered longer than settings.takeover_timeout_minutes
(default 15, .env TAKEOVER_TIMEOUT_MINUTES), the conversation automatically hands back
to the AI — mirroring the manual 'Return to AI' button exactly (same shared helper,
auto_return_to_ai), so there is only one version of "what happens on return".
"""
from datetime import datetime, timedelta

from app import models
from app.services import inbox


def _conversation(db, clinic, *, ai_enabled=False, last_message_at=None):
    cust = models.Customer(clinic_id=clinic.id, name="A", channel="web",
                           channel_user_id="w1")
    db.add(cust)
    db.flush()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web",
                               ai_enabled=ai_enabled,
                               last_message_at=last_message_at or datetime.utcnow())
    db.add(conv)
    db.commit()
    return conv, cust


def _msg(db, conv, sender, text="hi"):
    db.add(models.Message(clinic_id=conv.clinic_id, conversation_id=conv.id,
                          sender=sender, text=text))
    db.commit()


def test_stale_unanswered_takeover_reverts_to_ai(db, clinic, monkeypatch):
    now = datetime(2026, 8, 1, 12, 0)
    stale_at = now - timedelta(minutes=20)
    conv, _ = _conversation(db, clinic, ai_enabled=False, last_message_at=stale_at)
    _msg(db, conv, "customer", "ยังอยู่ไหมคะ")

    called = []
    monkeypatch.setattr(inbox, "generate_ai_reply", lambda cid: called.append(cid))

    n = inbox.sweep_stale_takeovers(db, clinic.id, now=now)

    assert n == 1
    db.expire_all()
    assert conv.ai_enabled is True
    assert conv.escalation_reason == ""
    assert called == [conv.id]
    system_texts = [m.text for m in db.query(models.Message)
                    .filter_by(conversation_id=conv.id, sender="system").all()]
    assert any("15" in t and "automatically handed back" in t for t in system_texts)


def test_actively_engaged_takeover_not_reverted(db, clinic, monkeypatch):
    now = datetime(2026, 8, 1, 12, 0)
    recent = now - timedelta(minutes=5)   # well inside the 15-minute timeout
    conv, _ = _conversation(db, clinic, ai_enabled=False, last_message_at=recent)
    _msg(db, conv, "customer", "สนใจค่ะ")

    called = []
    monkeypatch.setattr(inbox, "generate_ai_reply", lambda cid: called.append(cid))

    n = inbox.sweep_stale_takeovers(db, clinic.id, now=now)

    assert n == 0
    assert called == []
    db.expire_all()
    assert conv.ai_enabled is False


def test_admin_already_replied_not_reverted(db, clinic, monkeypatch):
    """The takeover itself is old, but a human DID answer — just waiting on the
    customer's next message. There is nothing to hand back."""
    now = datetime(2026, 8, 1, 12, 0)
    stale_at = now - timedelta(minutes=30)
    conv, _ = _conversation(db, clinic, ai_enabled=False, last_message_at=stale_at)
    _msg(db, conv, "customer", "ราคาเท่าไหร่คะ")
    _msg(db, conv, "admin", "2500 บาทค่ะ")

    called = []
    monkeypatch.setattr(inbox, "generate_ai_reply", lambda cid: called.append(cid))

    n = inbox.sweep_stale_takeovers(db, clinic.id, now=now)

    assert n == 0
    assert called == []
    db.expire_all()
    assert conv.ai_enabled is False


def test_ai_enabled_conversation_is_never_touched(db, clinic, monkeypatch):
    now = datetime(2026, 8, 1, 12, 0)
    stale_at = now - timedelta(minutes=60)
    conv, _ = _conversation(db, clinic, ai_enabled=True, last_message_at=stale_at)
    _msg(db, conv, "customer", "hello")

    monkeypatch.setattr(inbox, "generate_ai_reply", lambda cid: (_ for _ in ()).throw(
        AssertionError("must not fire for an AI-owned conversation")))

    n = inbox.sweep_stale_takeovers(db, clinic.id, now=now)

    assert n == 0
    db.expire_all()
    assert conv.ai_enabled is True


def test_auto_escalation_from_analyze_is_also_covered(db, clinic, monkeypatch):
    """sales.py::analyze sets ai_enabled=False for a 'serious' escalation the same way
    a manual takeover does — the sweep must not special-case it away."""
    now = datetime(2026, 8, 1, 12, 0)
    stale_at = now - timedelta(minutes=16)
    conv, _ = _conversation(db, clinic, ai_enabled=False, last_message_at=stale_at)
    conv.escalation_reason = "Customer sentiment turned negative."
    db.commit()
    _msg(db, conv, "customer", "ทำไมไม่มีใครตอบเลย")

    called = []
    monkeypatch.setattr(inbox, "generate_ai_reply", lambda cid: called.append(cid))

    n = inbox.sweep_stale_takeovers(db, clinic.id, now=now)

    assert n == 1
    db.expire_all()
    assert conv.ai_enabled is True
    assert conv.escalation_reason == ""


def test_sweep_all_stale_takeovers_covers_every_active_clinic(db, make_clinic, monkeypatch):
    from app.services.automations import sweep_all_stale_takeovers

    now = datetime(2026, 8, 1, 12, 0)
    stale_at = now - timedelta(minutes=20)
    clinic_a = make_clinic("Clinic A", slug="clinic-a-t")
    clinic_b = make_clinic("Clinic B", slug="clinic-b-t")
    conv_a, _ = _conversation(db, clinic_a, ai_enabled=False, last_message_at=stale_at)
    _msg(db, conv_a, "customer", "hi")
    conv_b, _ = _conversation(db, clinic_b, ai_enabled=False, last_message_at=stale_at)
    _msg(db, conv_b, "customer", "hi")

    monkeypatch.setattr(inbox, "generate_ai_reply", lambda cid: None)

    total = sweep_all_stale_takeovers(now=now)

    assert total == 2
    db.expire_all()
    assert conv_a.ai_enabled is True
    assert conv_b.ai_enabled is True


def test_manual_return_to_ai_route_still_flips_and_notes_correctly(db, clinic, auth_client):
    conv, _ = _conversation(db, clinic, ai_enabled=False)
    _msg(db, conv, "customer", "จองได้ไหมคะ")

    r = auth_client.post(f"/api/conversations/{conv.id}/return-to-ai")
    assert r.status_code == 200, r.text
    assert r.json()["ai_replying"] is True

    db.expire_all()
    assert conv.ai_enabled is True
    system_texts = [m.text for m in db.query(models.Message)
                    .filter_by(conversation_id=conv.id, sender="system").all()]
    assert "Conversation handed back to the AI assistant." in system_texts
