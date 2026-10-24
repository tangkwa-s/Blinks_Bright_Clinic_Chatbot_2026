"""Broadcast response tracking — an inbound message from a customer who
received a campaign within the response window is credited as a real reply
(replacing the simulated open rate as the engagement metric)."""
from datetime import datetime, timedelta

from app import models
from app.services.inbox import CAMPAIGN_RESPONSE_WINDOW_DAYS, handle_inbound


def _make_customer(db, clinic, name="Fah", channel="web", uid="resp-u1"):
    c = models.Customer(clinic_id=clinic.id, name=name, channel=channel,
                        channel_user_id=uid, pipeline_stage="new_lead",
                        temperature="warm", lead_score=20)
    db.add(c)
    db.commit()
    return c


def _make_campaign(db, clinic, sent=1, status="sent"):
    camp = models.Campaign(clinic_id=clinic.id, name="Promo", audience={},
                           channel="all", message="hi", status=status,
                           audience_count=sent, sent_count=sent,
                           opened_count=0)
    db.add(camp)
    db.commit()
    return camp


def _make_delivery(db, clinic, camp, cust, status="delivered", created_at=None):
    a = models.Activity(clinic_id=clinic.id, customer_id=cust.id, type="campaign",
                        summary=f"{cust.name} · {cust.channel or 'web'} · {status}",
                        ref_type="campaign", ref_id=camp.id)
    if created_at:
        a.created_at = created_at
    db.add(a)
    db.commit()
    return a


def _replies(db, camp):
    return (db.query(models.Activity)
            .filter_by(type="campaign_reply", ref_type="campaign", ref_id=camp.id)
            .all())


def test_inbound_after_delivery_creates_one_reply_and_dedupes(db, clinic):
    cust = _make_customer(db, clinic)
    camp = _make_campaign(db, clinic)
    _make_delivery(db, clinic, camp, cust)

    handle_inbound(db, clinic_id=clinic.id, channel="web",
                   channel_user_id="resp-u1", name="Fah", text="สนใจค่ะ")
    replies = _replies(db, camp)
    assert len(replies) == 1
    assert replies[0].customer_id == cust.id
    assert replies[0].clinic_id == clinic.id
    assert replies[0].summary.endswith(" · replied")

    # a second message from the same customer must NOT double-count
    handle_inbound(db, clinic_id=clinic.id, channel="web",
                   channel_user_id="resp-u1", name="Fah", text="ราคาเท่าไหร่คะ")
    assert len(_replies(db, camp)) == 1


def test_delivery_outside_window_is_not_credited(db, clinic):
    cust = _make_customer(db, clinic)
    camp = _make_campaign(db, clinic)
    stale = datetime.utcnow() - timedelta(days=CAMPAIGN_RESPONSE_WINDOW_DAYS + 1)
    _make_delivery(db, clinic, camp, cust, created_at=stale)

    handle_inbound(db, clinic_id=clinic.id, channel="web",
                   channel_user_id="resp-u1", name="Fah", text="สวัสดีค่ะ")
    assert _replies(db, camp) == []


def test_failed_delivery_is_not_credited(db, clinic):
    cust = _make_customer(db, clinic)
    camp = _make_campaign(db, clinic)
    _make_delivery(db, clinic, camp, cust, status="failed")

    handle_inbound(db, clinic_id=clinic.id, channel="web",
                   channel_user_id="resp-u1", name="Fah", text="สวัสดีค่ะ")
    assert _replies(db, camp) == []


def test_new_customer_first_message_no_reply_row(db, clinic):
    camp = _make_campaign(db, clinic)
    handle_inbound(db, clinic_id=clinic.id, channel="web",
                   channel_user_id="brand-new", name="New Visitor", text="hello")
    assert _replies(db, camp) == []


def test_most_recent_delivered_campaign_wins(db, clinic):
    cust = _make_customer(db, clinic)
    older = _make_campaign(db, clinic)
    newer = _make_campaign(db, clinic)
    _make_delivery(db, clinic, older, cust)
    _make_delivery(db, clinic, newer, cust)

    handle_inbound(db, clinic_id=clinic.id, channel="web",
                   channel_user_id="resp-u1", name="Fah", text="สนใจโปรค่ะ")
    assert _replies(db, older) == []
    assert len(_replies(db, newer)) == 1


def test_list_campaigns_reports_responded_and_rate(auth_client, db):
    clinic = auth_client.test_clinic
    cust = _make_customer(db, clinic)
    camp = _make_campaign(db, clinic, sent=4)
    _make_delivery(db, clinic, camp, cust)
    handle_inbound(db, clinic_id=clinic.id, channel="web",
                   channel_user_id="resp-u1", name="Fah", text="สนใจค่ะ")

    r = auth_client.get("/api/campaigns")
    assert r.status_code == 200, r.text
    row = next(c for c in r.json() if c["id"] == camp.id)
    assert row["responded_count"] == 1
    assert row["response_rate"] == 25  # 1 of 4 sent


def test_list_campaigns_zero_sent_no_divide_by_zero(auth_client, db):
    clinic = auth_client.test_clinic
    camp = _make_campaign(db, clinic, sent=0, status="draft")
    r = auth_client.get("/api/campaigns")
    row = next(c for c in r.json() if c["id"] == camp.id)
    assert row["responded_count"] == 0
    assert row["response_rate"] == 0


def test_campaign_log_marks_responder_and_excludes_reply_rows(auth_client, db):
    clinic = auth_client.test_clinic
    replier = _make_customer(db, clinic, name="Fah", uid="resp-u1")
    silent = _make_customer(db, clinic, name="Nok", uid="resp-u2")
    camp = _make_campaign(db, clinic, sent=2)
    _make_delivery(db, clinic, camp, replier)
    _make_delivery(db, clinic, camp, silent)
    handle_inbound(db, clinic_id=clinic.id, channel="web",
                   channel_user_id="resp-u1", name="Fah", text="สนใจค่ะ")

    r = auth_client.get(f"/api/campaigns/{camp.id}/log")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["responded"] == 1
    # only the two delivery rows appear — the campaign_reply row never leaks
    # into the parsed log
    assert body["count"] == 2
    assert all(l["status"] == "delivered" for l in body["log"])
    by_name = {l["name"]: l for l in body["log"]}
    assert by_name["Fah"]["responded"] is True
    assert by_name["Nok"]["responded"] is False
