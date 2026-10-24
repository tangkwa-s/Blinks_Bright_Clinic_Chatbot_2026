"""Chat analysis — what customers actually write, aggregated for the dashboard.

Everything here is DETERMINISTIC (lexicons + counting, no model calls): the page must
load in milliseconds, cost nothing per view, and be testable offline — the same reasons
the reply-text strips in chat.py are deterministic rather than prompt rules. The
trade-off is honest: a lexicon reads "แพงจัง" as negative but cannot read sarcasm; for
a clinic dashboard that trade is right.

Thai has no spaces, so the word cloud is built by LONGEST-MATCH against a known
vocabulary (the clinic's own catalog + a curated aesthetic-clinic lexicon) instead of a
tokenizer dependency: substring matching is exact in Thai, and matching longest-first
stops "โบท็อกซ์" from also counting as "โบ". Latin words are tokenized normally, minus
stopwords, and skipping spans already claimed by a catalog name so "Botox Jaw Slimming"
does not also count "botox".

Times: created_at is stored UTC; every bucket (hour heatmap, daily trend) converts to
Bangkok first — a 18:00Z message is a 01:00 chat, tomorrow, to the clinic.
"""
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from app import models
from app.scope import scoped

_BKK = timedelta(hours=7)

_URL_RE = re.compile(r"https?://\S+|\S+@\S+")
_LATIN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")

# Latin words that appear in Thai chats without being "content" — channel words,
# romanised particles, generic chat filler. Kept small on purpose.
_LATIN_STOP = {
    "the", "and", "for", "you", "your", "are", "was", "were", "can", "could",
    "with", "have", "has", "had", "this", "that", "these", "there", "here",
    "what", "when", "where", "which", "who", "why", "how", "much", "many",
    "not", "but", "get", "got", "want", "need", "would", "will", "like",
    "just", "also", "about", "from", "into", "then", "than", "them", "they",
    "she", "him", "her", "his", "our", "out", "one", "two", "see", "say",
    "said", "send", "yes", "okay", "know", "let", "come", "please", "hello",
    "thanks", "thank", "krub", "krab", "kha", "kaa", "nka", "khap", "naka",
    "https", "http", "com",
}

# --- word-cloud vocabulary: what customers talk about at an aesthetic clinic -------
# Curated, not exhaustive: terms must be unambiguous enough that a substring hit means
# the topic really came up. Single very short words ("โบ", "ตา") are excluded — they
# match inside unrelated words.
CHAT_TERMS = (
    # money / booking mechanics
    "ราคา", "กี่บาท", "โปรโมชั่น", "โปรโมชัน", "ส่วนลด", "ลดราคา", "แพ็กเกจ", "แพคเกจ",
    "คอร์ส", "จองคิว", "จองเลย", "เลื่อนนัด", "ยกเลิกนัด", "มัดจำ", "ชำระเงิน", "โอนเงิน",
    "เต็มจำนวน", "ผ่อน", "บัตรเครดิต", "พร้อมเพย์", "ใบเสร็จ", "ราคาเท่าไหร่", "เท่าไหร่", "เท่าไร",
    # logistics
    "สาขา", "เดินทาง", "ที่จอดรถ", "เปิดกี่โมง", "ปิดกี่โมง", "เวลาเปิด", "เสาร์", "อาทิตย์",
    "วันหยุด", "คิวว่าง", "วันนี้", "พรุ่งนี้",
    # people
    "คุณหมอ", "หมอ", "แพทย์", "พยาบาล", "ผู้เชี่ยวชาญ", "ปรึกษา",
    # treatments & concerns (generic — the clinic's own catalog is added on top)
    "โบท็อกซ์", "โบทอกซ์", "ฟิลเลอร์", "เลเซอร์", "ทรีตเมนต์", "ทรีทเม้นท์", "ไฮฟู", "ไฮฟู่",
    "มาเดอร์มา", "มีโซ", "เมโส", "สลายไขมัน", "ดูดไขมัน", "ร้อยไหม", "ฉีดผิว", "ผลักวิตามิน",
    "วิตามินผิว", "ดริปวิตามิน", "สิว", "รอยสิว", "หลุมสิว", "ฝ้า", "รอยดำ", "รอยแดง",
    "รูขุมขน", "ริ้วรอย", "หน้าเรียว", "กราม", "เหนียง", "โหนกแก้ม", "ร่องแก้ม", "ใต้ตา",
    "ถุงใต้ตา", "คาง", "ปีกจมูก", "หน้าผาก", "ยกกระชับ", "หน้าใส", "ผิวใส", "ผิวขาว",
    "ผิวแห้ง", "ผิวมัน", "ผิวแพ้ง่าย", "หมองคล้ำ", "หมอง", "ลดอายุ", "ฟื้นฟูผิว", "มาส์กหน้า",
    "นวดหน้า", "ขัดผิว", "ทำความสะอาดผิว", "รักแร้", "ขนหน้า", "กำจัดขน",
    # safety / experience
    "เจ็บไหม", "เจ็บมั้ย", "ยาชา", "พักฟื้น", "บวม", "ช้ำ", "แดง", "แพ้", "ผลข้างเคียง",
    "อยู่ได้นาน", "กี่เดือน", "กี่ครั้ง", "เห็นผล", "ผลลัพธ์", "รีวิว", "ก่อนหลัง", "ปลอดภัย",
    "มาตรฐาน",
    # NOT here, learned from live data: "อย" / "กระ" — two-or-three character terms that
    # are prefixes of everyday words (อยาก/อยู่, กระจ่าง/กระชับ) substring-match half the
    # chat and dominate the cloud with noise. "หมอง" is listed so "หมองคล้ำ/ผิวหมอง"
    # doesn't get claimed by the shorter "หมอ" (doctor) inside it.
)

# --- sentiment lexicon --------------------------------------------------------------
# Polarity words a clinic customer actually types. Terms already carrying "ไม่" are NOT
# listed — negation is handled by the flip below, so "ไม่พอใจ" = พอใจ flipped, and the
# two never double-count. Ambiguous words ("นาน", "แนะนำ", "โอเค") are left out.
POS_TERMS = (
    "ดีมาก", "ดีจัง", "ดีเลย", "สวยมาก", "สวยขึ้น", "สวยจัง", "ชอบมาก", "ชอบเลย", "ชอบ",
    "รักเลย", "ประทับใจ", "พอใจ", "ถูกใจ", "คุ้มค่า", "คุ้มมาก", "คุ้ม", "ปังมาก", "ปัง",
    "ว้าว", "เยี่ยม", "สุดยอด", "เลิศ", "ฟินมาก", "ฟิน", "ขอบคุณ", "ขอบคุน", "บริการดี",
    "เป็นกันเอง", "สะดวก", "รวดเร็ว", "ทันใจ", "สบายใจ", "มั่นใจ", "อุ่นใจ", "ดีขึ้น",
    "หายแล้ว", "เห็นผลจริง", "ได้ผลดี", "ได้ผล", "เนียนขึ้น", "ใสขึ้น", "กระจ่างใส",
    "เด้งมาก", "ธรรมชาติมาก", "ไม่เจ็บ", "หน้าใสขึ้น", "ราคาดี", "ถูกมาก",
    "good", "great", "love", "nice", "amazing", "perfect", "awesome", "best",
    "happy", "excellent", "wonderful",
    "😊", "😍", "🥰", "❤️", "👍", "✨", "🙏", "😁", "😄", "🤩", "💕",
)
NEG_TERMS = (
    "แพงมาก", "แพงจัง", "แพงไป", "แพงเกิน", "แพง", "เจ็บมาก", "เจ็บจัง", "เจ็บ", "ปวดมาก",
    "ปวด", "บวมมาก", "บวมไม่ยุบ", "ช้ำมาก", "แสบ", "คัน", "แพ้", "อักเสบ", "เป็นหนอง",
    "แย่มาก", "แย่", "ห่วย", "ผิดหวัง", "เสียใจ", "เสียดาย", "เสียเวลา", "โกรธ",
    "หงุดหงิด", "รำคาญ", "รอนานมาก", "รอนาน", "ช้ามาก", "ช้าจัง", "กังวล", "กลัว",
    "เครียด", "ปัญหา", "ร้องเรียน", "เฟล", "พัง", "หลอก", "โกง", "อันตราย",
    "ผลข้างเคียง", "แสบมาก", "แดงมาก", "เจ็บอยู่", "แสบอยู่",
    "bad", "expensive", "pain", "painful", "slow", "terrible", "worst", "angry",
    "disappointed", "swollen", "allergic", "scam",
    "😭", "😢", "😡", "👎", "😠", "💢", "😞", "😖", "🤬",
)
# Negators flip the polarity of the term that follows them ("ไม่แพง" = positive,
# "ไม่สวย" = negative). Checked in the 8 characters before a match.
NEGATORS = ("ไม่ค่อย", "ไม่ได้", "ไม่", "อย่า", "not", "n't", "never", "no")


def _lexicon_re(terms) -> re.Pattern:
    """One alternation, longest-first, so 'แพงมาก' wins over 'แพง' at the same spot."""
    ordered = sorted(set(terms), key=len, reverse=True)
    return re.compile("|".join(re.escape(t) for t in ordered), re.IGNORECASE)


_POS_RE = _lexicon_re(POS_TERMS)
_NEG_RE = _lexicon_re(NEG_TERMS)


def _negated(text: str, start: int) -> bool:
    window = text[max(0, start - 8):start].rstrip()
    return any(window.endswith(n) for n in NEGATORS)


def sentiment_of(text: str) -> int:
    """Signed lexicon score for one message: >0 positive, <0 negative, 0 neutral."""
    clean = _URL_RE.sub(" ", text or "")
    score = 0
    for m in _POS_RE.finditer(clean):
        score += -1 if _negated(clean, m.start()) else 1
    for m in _NEG_RE.finditer(clean):
        score += 1 if _negated(clean, m.start()) else -1
    return score


def build_vocab(db, clinic_id: int):
    """(regex, canonical map, treatment-name set) for this clinic's word cloud.

    Canonical map folds case/spelling variants of a catalog name onto the catalog's own
    spelling, so 'botox jaw slimming' and 'Botox Jaw Slimming' are one word.
    """
    canonical: dict[str, str] = {}
    treatments: set[str] = set()
    for s in scoped(db, models.Service, clinic_id).filter_by(active=True).all():
        name = (s.name or "").strip()
        if len(name) >= 3:
            canonical[name.lower()] = name
            treatments.add(name)
    for b in scoped(db, models.Branch, clinic_id).all():
        name = (b.name or "").strip()
        if len(name) >= 3:
            canonical.setdefault(name.lower(), name)
    for term in CHAT_TERMS:
        canonical.setdefault(term.lower(), term)
    return _lexicon_re(canonical.keys()), canonical, treatments


def extract_terms(text: str, vocab_re: re.Pattern, canonical: dict) -> list[str]:
    """Canonical vocabulary terms in one message (longest-match), plus generic Latin
    words outside the matched spans."""
    clean = _URL_RE.sub(" ", text or "")
    found, spans = [], []
    for m in vocab_re.finditer(clean):
        found.append(canonical.get(m.group(0).lower(), m.group(0)))
        spans.append((m.start(), m.end()))
    for m in _LATIN_RE.finditer(clean):
        if any(a <= m.start() < b for a, b in spans):
            continue
        w = m.group(0).lower()
        if w not in _LATIN_STOP:
            found.append(w)
    return found


def _median_reply_seconds(rows) -> int | None:
    """Median seconds from a customer message to the FIRST ai/admin message after it,
    per conversation. rows must be (Message, Conversation) in chronological order."""
    pending: dict[int, datetime] = {}
    deltas = []
    for msg, conv in rows:
        if msg.sender == "customer":
            pending.setdefault(conv.id, msg.created_at)   # first unanswered in a burst
        elif msg.sender in ("ai", "admin") and conv.id in pending:
            dt = (msg.created_at - pending.pop(conv.id)).total_seconds()
            if 0 <= dt < 86400:
                deltas.append(dt)
    return round(statistics.median(deltas)) if deltas else None


def chat_insights(db, clinic_id: int, since: datetime, branch_id=None,
                  trend_by: str = "day") -> dict:
    """The whole chat-analysis payload in one chronological pass over the messages."""
    q = (db.query(models.Message, models.Conversation)
         .join(models.Conversation,
               models.Message.conversation_id == models.Conversation.id)
         .filter(models.Message.clinic_id == clinic_id,
                 models.Message.created_at >= since))
    if branch_id:
        q = q.filter(models.Conversation.branch_id == branch_id)
    rows = q.order_by(models.Message.conversation_id, models.Message.created_at,
                      models.Message.id).all()

    vocab_re, canonical, treatments = build_vocab(db, clinic_id)
    words: Counter = Counter()
    topic_counts: Counter = Counter()
    channels: Counter = Counter()
    hours = [[0] * 24 for _ in range(7)]           # [Mon..Sun][0..23], Bangkok time
    senti = {"positive": 0, "neutral": 0, "negative": 0}
    trend: dict[str, dict] = defaultdict(lambda: {"positive": 0, "negative": 0, "neutral": 0})
    customer_ids: set[int] = set()
    conversation_ids: set[int] = set()
    ai_msgs = admin_msgs = takeovers = customer_msgs = 0
    negatives = []                                  # (created_at, conv_id, customer_id, text)

    for msg, conv in rows:
        if msg.sender == "ai":
            ai_msgs += 1
            continue
        if msg.sender == "admin":
            admin_msgs += 1
            continue
        if msg.sender == "system":
            if "took over" in (msg.text or ""):
                takeovers += 1
            continue
        # --- customer message ---
        customer_msgs += 1
        customer_ids.add(conv.customer_id)
        conversation_ids.add(conv.id)
        channels[conv.channel or "web"] += 1
        local = msg.created_at + _BKK
        hours[local.weekday()][local.hour] += 1
        for term in extract_terms(msg.text or "", vocab_re, canonical):
            words[term] += 1
            if term in treatments:
                topic_counts[term] += 1
        score = sentiment_of(msg.text or "")
        label = "positive" if score > 0 else "negative" if score < 0 else "neutral"
        senti[label] += 1
        key = local.strftime("%Y-%m-%d" if trend_by == "day" else "%Y-%m")
        trend[key][label] += 1
        if score < 0:
            negatives.append((msg.created_at, conv.id, conv.customer_id, msg.text or ""))

    # merged customers are redirect stubs — never count them as extra people
    real_customers = 0
    if customer_ids:
        real_customers = (scoped(db, models.Customer, clinic_id)
                          .filter(models.Customer.id.in_(customer_ids),
                                  models.Customer.merged_into_id.is_(None)).count())

    negatives.sort(key=lambda x: x[0], reverse=True)
    name_by_id = {}
    if negatives:
        ids = {c for _, _, c, _ in negatives[:8]}
        name_by_id = {c.id: c.name for c in
                      scoped(db, models.Customer, clinic_id)
                      .filter(models.Customer.id.in_(ids)).all()}
    attention = [{
        "conversation_id": conv_id,
        "customer": name_by_id.get(cust_id, "ลูกค้า"),
        "text": text[:160],
        "at": (created + _BKK).isoformat(timespec="minutes"),
    } for created, conv_id, cust_id, text in negatives[:8]]

    return {
        "totals": {
            "customer_msgs": customer_msgs,
            "customers": real_customers,
            "conversations": len(conversation_ids),
            "ai_msgs": ai_msgs,
            "admin_msgs": admin_msgs,
            "takeovers": takeovers,
            "median_reply_seconds": _median_reply_seconds(rows),
        },
        "sentiment": {**senti, "mode": trend_by,
                      "trend": [{"label": k, **v} for k, v in sorted(trend.items())]},
        "words": [{"text": w, "count": n,
                   "kind": "treatment" if w in treatments else "general"}
                  for w, n in words.most_common(60)],
        "topics": [{"name": n, "count": c} for n, c in topic_counts.most_common(8)],
        "channels": [{"channel": ch, "count": n} for ch, n in channels.most_common()],
        "hours": hours,
        "attention": attention,
    }
