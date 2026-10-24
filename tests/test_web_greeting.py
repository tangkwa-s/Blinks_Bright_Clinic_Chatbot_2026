"""The widget's first message tells a first-time visitor what the assistant can do.

The old greeting ("สนใจบริการไหน ทักมาได้เลย") named no clinic and listed nothing, so
a visitor had to guess what to ask, and nobody learned that photos are accepted.
It now names the clinic, lists what the tools/KB really answer, mentions photos,
and says medical questions go to a doctor — in the language the widget is showing.
"""


def _greeting(client, slug, lang=None):
    body = {"clinic": slug}
    if lang:
        body["lang"] = lang
    r = client.post("/api/channels/web/start", json=body)
    assert r.status_code == 200, r.text
    msgs = r.json()["messages"]
    assert len(msgs) == 1 and msgs[0]["sender"] == "ai"
    return msgs[0]["text"]


def test_thai_greeting_names_the_clinic_and_what_it_can_do(client, clinic):
    text = _greeting(client, clinic.slug)
    assert clinic.name in text
    for item in ("ราคา", "โปรโมชัน", "จองคิว", "มัดจำ", "รูป", "สลิป", "แพทย์"):
        assert item in text, item


def test_english_widget_gets_an_english_greeting(client, clinic):
    text = _greeting(client, clinic.slug, lang="en")
    assert clinic.name in text
    assert "booking" in text and "photo" in text
    assert not any("ก" <= ch <= "๛" for ch in text)


def test_unknown_lang_falls_back_to_thai(client, clinic):
    assert "สวัสดีค่ะ" in _greeting(client, clinic.slug, lang="xx")
