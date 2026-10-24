"""Chat Analysis — the lexicons and the aggregate endpoint, all offline.

The page is deterministic by design (lexicon + counting, no model calls), so every
number it shows can be pinned exactly: seed known messages, assert the counts.
"""
from datetime import datetime, timedelta

from app import models
from app.services.chat_insights import (build_vocab, chat_insights, extract_terms,
                                        sentiment_of)


# --------------------------------------------------------------------------
# sentiment lexicon
# --------------------------------------------------------------------------
def test_positive_negative_and_neutral_messages_score_as_expected():
    assert sentiment_of("ทำแล้วชอบมากค่ะ ขอบคุณนะคะ") > 0
    assert sentiment_of("แพงจัง แล้วก็เจ็บมากเลยค่ะ") < 0
    assert sentiment_of("ขอเลื่อนนัดเป็นวันศุกร์ค่ะ") == 0


def test_negation_flips_polarity_both_ways():
    assert sentiment_of("ไม่แพงเลยค่ะ") > 0, "ไม่ + แพง = คำชม"
    assert sentiment_of("ทำมาแล้วไม่ชอบเลย") < 0, "ไม่ + ชอบ = คำติ"


def test_emoji_carry_sentiment():
    assert sentiment_of("เริ่ดมาก 😍") > 0
    assert sentiment_of("รอคิวนานมาก 😡") < 0


def test_a_bare_url_or_number_is_neutral():
    assert sentiment_of("https://pay.example.com/xyz") == 0
    assert sentiment_of("0812345678") == 0


# --------------------------------------------------------------------------
# word extraction
# --------------------------------------------------------------------------
def _vocab(db, clinic):
    svc = models.Service(clinic_id=clinic.id, name="Botox Jaw Slimming",
                         category="injectable", base_price=8900, active=True)
    db.add(svc)
    db.commit()
    return build_vocab(db, clinic.id)


def test_catalog_name_is_matched_once_not_also_as_generic_latin(db, clinic):
    vocab_re, canonical, treatments = _vocab(db, clinic)
    terms = extract_terms("สนใจ Botox Jaw Slimming ค่ะ ราคาเท่าไหร่คะ",
                          vocab_re, canonical)
    assert terms.count("Botox Jaw Slimming") == 1
    assert "botox" not in terms, "the span is claimed by the catalog name"
    assert "ราคาเท่าไหร่" in terms
    assert "Botox Jaw Slimming" in treatments


def test_longest_thai_term_wins_over_its_prefix(db, clinic):
    vocab_re, canonical, _ = _vocab(db, clinic)
    terms = extract_terms("แพ็กเกจโบท็อกซ์มีไหมคะ", vocab_re, canonical)
    assert "โบท็อกซ์" in terms and "แพ็กเกจ" in terms


def test_latin_stopwords_and_urls_never_reach_the_cloud(db, clinic):
    vocab_re, canonical, _ = _vocab(db, clinic)
    terms = extract_terms("hello can you send https://line.me/xyz please", vocab_re, canonical)
    assert terms == []


# --------------------------------------------------------------------------
# the aggregate — seeded conversation, pinned numbers
# --------------------------------------------------------------------------
def _seed(db, clinic, *, branch=None, channel="web", at=None, texts=()):
    cust = models.Customer(clinic_id=clinic.id, name="มะลิ", channel=channel,
                           channel_user_id=f"u-{id(texts)}")
    db.add(cust)
    db.flush()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id,
                               channel=channel, branch_id=branch)
    db.add(conv)
    db.flush()
    t0 = at or datetime.utcnow()
    for i, (sender, text) in enumerate(texts):
        db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id,
                              sender=sender, text=text,
                              created_at=t0 + timedelta(minutes=i)))
    db.commit()
    return cust, conv


def test_insights_count_only_customer_messages_and_split_sentiment(db, clinic):
    _seed(db, clinic, texts=[
        ("customer", "สนใจโบท็อกซ์ค่ะ ราคาเท่าไหร่คะ"),
        ("ai", "ราคาเริ่มต้น 8,900 บาทค่ะ โบท็อกซ์ โบท็อกซ์ โบท็อกซ์"),
        ("customer", "ชอบมากเลยค่ะ ขอบคุณค่ะ"),
        ("customer", "แต่แพงจังเลย"),
    ])
    d = chat_insights(db, clinic.id, datetime.utcnow() - timedelta(days=1))
    assert d["totals"]["customer_msgs"] == 3
    assert d["totals"]["ai_msgs"] == 1
    assert d["sentiment"]["positive"] == 1
    assert d["sentiment"]["negative"] == 1
    assert d["sentiment"]["neutral"] == 1
    counts = {w["text"]: w["count"] for w in d["words"]}
    assert counts.get("โบท็อกซ์") == 1, "the AI's own words never enter the cloud"


def test_hour_heatmap_buckets_in_bangkok_time(db, clinic):
    # 18:30 UTC on a Monday = 01:30 Tuesday in Bangkok
    monday_utc = datetime(2026, 8, 24, 18, 30)
    _seed(db, clinic, at=monday_utc, texts=[("customer", "สวัสดีค่ะ")])
    d = chat_insights(db, clinic.id, monday_utc - timedelta(days=1))
    assert d["hours"][1][1] == 1, "Tuesday 01:xx Bangkok, not Monday 18:xx UTC"
    assert sum(sum(r) for r in d["hours"]) == 1


def test_period_cutoff_excludes_old_messages(db, clinic):
    _seed(db, clinic, at=datetime.utcnow() - timedelta(days=40),
          texts=[("customer", "ข้อความเก่า")])
    _seed(db, clinic, texts=[("customer", "ข้อความใหม่")])
    d = chat_insights(db, clinic.id, datetime.utcnow() - timedelta(days=30))
    assert d["totals"]["customer_msgs"] == 1


def test_branch_filter_and_clinic_isolation(db, clinic, make_clinic):
    other = make_clinic("Clinic B", slug="chat-b")
    b1 = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    _seed(db, clinic, branch=b1.id, texts=[("customer", "สาขาหนึ่งค่ะ")])
    _seed(db, clinic, branch=None, texts=[("customer", "ไม่ระบุสาขา")])
    _seed(db, other, texts=[("customer", "คลินิกอื่น")])
    all_d = chat_insights(db, clinic.id, datetime.utcnow() - timedelta(days=1))
    assert all_d["totals"]["customer_msgs"] == 2, "the other clinic never leaks in"
    b_d = chat_insights(db, clinic.id, datetime.utcnow() - timedelta(days=1),
                        branch_id=b1.id)
    assert b_d["totals"]["customer_msgs"] == 1


def test_median_reply_time_and_takeover_count(db, clinic):
    t0 = datetime.utcnow() - timedelta(hours=1)
    cust, conv = _seed(db, clinic, texts=[])
    for sender, text, offset in [
        ("customer", "สวัสดีค่ะ", 0),
        ("ai", "สวัสดีค่ะ ยินดีต้อนรับ", 30),          # reply after 30 s
        ("customer", "ขอราคาหน่อยค่ะ", 60),
        ("system", "Kwan took over the conversation. AI replies are paused.", 70),
        ("admin", "ราคา 8,900 ค่ะ", 150),               # reply after 90 s
    ]:
        db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id,
                              sender=sender, text=text,
                              created_at=t0 + timedelta(seconds=offset)))
    db.commit()
    d = chat_insights(db, clinic.id, t0 - timedelta(minutes=5))
    assert d["totals"]["median_reply_seconds"] == 60      # median of 30 and 90
    assert d["totals"]["takeovers"] == 1


def test_attention_list_carries_the_negative_message_and_its_conversation(db, clinic):
    cust, conv = _seed(db, clinic, texts=[("customer", "บวมมาก แสบมากเลยค่ะ 😭")])
    d = chat_insights(db, clinic.id, datetime.utcnow() - timedelta(days=1))
    assert len(d["attention"]) == 1
    a = d["attention"][0]
    assert a["conversation_id"] == conv.id
    assert a["customer"] == "มะลิ"
    assert "บวมมาก" in a["text"]


def test_topics_list_only_catalog_treatments(db, clinic):
    svc = models.Service(clinic_id=clinic.id, name="HIFU Lifting", category="lifting",
                         base_price=25000, active=True)
    db.add(svc)
    db.commit()
    _seed(db, clinic, texts=[("customer", "สนใจ HIFU Lifting กับเรื่องราคาค่ะ")])
    d = chat_insights(db, clinic.id, datetime.utcnow() - timedelta(days=1))
    assert d["topics"] == [{"name": "HIFU Lifting", "count": 1}]
    kinds = {w["text"]: w["kind"] for w in d["words"]}
    assert kinds["HIFU Lifting"] == "treatment"
    assert kinds["ราคา"] == "general"


# --------------------------------------------------------------------------
# the endpoint
# --------------------------------------------------------------------------
def test_endpoint_scopes_to_the_active_clinic_and_accepts_period(db, clinic, auth_client):
    _seed(db, clinic, texts=[("customer", "สวัสดีค่ะ สนใจทรีตเมนต์ค่ะ")])
    r = auth_client.get("/api/chat-analysis?period=7d")
    assert r.status_code == 200
    d = r.json()
    assert d["period"] == "7d"
    assert d["totals"]["customer_msgs"] == 1
    assert d["sentiment"]["mode"] == "day"
    r = auth_client.get("/api/chat-analysis?period=all")
    assert r.json()["sentiment"]["mode"] == "month"
