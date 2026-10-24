"""Only offer the branches that actually have the treatment the customer asked for.

A treatment restricted to 2 of 3 branches used to be invisible until a branch was
known, so the assistant asked "which branch?" over ALL THREE, the customer picked the
one that does not have it, and the reply came back listing that branch's OTHER
treatments plus "if you're interested in <the one they asked for>, let me know and
I'll check with the team" — which is both wrong (nothing needs checking) and a dead
end (the branch will never have it).

Both halves are decided from the DB + the transcript, never from the model:
which treatment the customer named, and which branches run it.
"""
from app import models
from app.ai.chat import _booking_hint, _correct_branch_list
from app.ai.context import build_context
from app.ai.tools import (branches_offering, execute_tool,
                          treatments_named_by_customer)


def _line_for(ctx, name):
    """That treatment's own line in the catalog block ('' when it isn't listed)."""
    return next((ln for ln in ctx.splitlines() if ln.startswith(f"- {name}:")
                 or ln.startswith(f"- {name} ")), "")


def _context(db, clinic, conv):
    """The catalog block exactly as ``chat.respond`` builds it for this conversation."""
    asked = treatments_named_by_customer(db, conv)
    return build_context(db, clinic.id, conv.branch_id, "",
                         asked_names=[s.name for s in asked],
                         allowed_branch_ids=branches_offering(db, clinic.id, asked))[0]


def _branch(db, clinic, name):
    b = models.Branch(clinic_id=clinic.id, name=name, open_hour=9, close_hour=21)
    db.add(b)
    db.commit()
    return b


def _service(db, clinic, name, branch_ids=(), price=1000.0):
    s = models.Service(clinic_id=clinic.id, name=name, category="facial",
                       base_price=price, duration_min=45, active=True)
    db.add(s)
    db.flush()
    for bid in branch_ids:
        db.add(models.ServiceBranch(clinic_id=clinic.id, service_id=s.id, branch_id=bid))
    db.commit()
    return s


def _chat(db, clinic, *customer_lines, branch=None):
    cust = models.Customer(clinic_id=clinic.id, name="Web Visitor", channel="web")
    db.add(cust)
    db.commit()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web",
                               branch_id=branch.id if branch else None)
    db.add(conv)
    db.commit()
    for line in customer_lines:
        db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id,
                              sender="customer", text=line))
    db.commit()
    return conv, cust


def _clear_catalog(db, clinic):
    """Retire the fixture's seeded treatments — they are unrestricted, so they show at
    every branch and nothing would ever come back empty."""
    for s in db.query(models.Service).filter_by(clinic_id=clinic.id).all():
        s.active = False
    db.commit()


def _three(db, clinic):
    """The reported setup: 3 branches, the asked-for treatment at only 2 of them."""
    first = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    first.name = "วัดพระศรี"
    db.commit()
    b2 = _branch(db, clinic, "วัดเสมียนนารี")
    b3 = _branch(db, clinic, "สยามพารากอน")
    svc = _service(db, clinic, "Acne Clear Program test2", branch_ids=[b2.id, b3.id])
    return first, b2, b3, svc


# --------------------------------------------------------------------------
# reading what the customer asked for
# --------------------------------------------------------------------------
def test_the_longest_matching_name_wins(db, clinic):
    """"Acne Clear Program test" is a prefix of "Acne Clear Program test2" — matching
    the short one first would answer about a different treatment entirely."""
    _first, b2, _b3, long_svc = _three(db, clinic)
    short_svc = _service(db, clinic, "Acne Clear Program test", branch_ids=[b2.id])

    conv, _c = _chat(db, clinic, "สนใจ Acne Clear Program test2")
    named = treatments_named_by_customer(db, conv)
    assert [s.id for s in named] == [long_svc.id]
    assert short_svc.id not in {s.id for s in named}


def test_only_the_customers_own_words_count(db, clinic):
    """The assistant naming a treatment must not narrow the branch question."""
    _first, _b2, _b3, svc = _three(db, clinic)
    conv, _c = _chat(db, clinic, "สวัสดีค่ะ")
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="ai",
                          text=f"แนะนำ {svc.name} ค่ะ"))
    db.commit()
    assert treatments_named_by_customer(db, conv) == []


def test_branches_offering_intersects_and_falls_back(db, clinic):
    first, b2, b3, svc = _three(db, clinic)
    everywhere = _service(db, clinic, "Global Facial")
    only_first = _service(db, clinic, "First Only", branch_ids=[first.id])

    assert branches_offering(db, clinic.id, [svc]) == {b2.id, b3.id}
    assert branches_offering(db, clinic.id, []) is None
    assert branches_offering(db, clinic.id, [everywhere]) is None, "unrestricted narrows nothing"
    assert branches_offering(db, clinic.id, [svc, everywhere]) == {b2.id, b3.id}
    assert branches_offering(db, clinic.id, [svc, only_first]) is None, \
        "no branch has both — narrowing would be a lie"


# --------------------------------------------------------------------------
# the branch question the customer is actually asked
# --------------------------------------------------------------------------
def test_the_checklist_offers_only_branches_that_have_it(db, clinic):
    first, b2, b3, svc = _three(db, clinic)
    conv, cust = _chat(db, clinic, f"สนใจ {svc.name}")

    hint = _booking_hint(db, conv, cust)
    assert b2.name in hint and b3.name in hint
    assert first.name not in hint, "the branch without it must not be offered"


def test_the_checklist_still_names_every_branch_when_nothing_narrows_it(db, clinic):
    first, b2, b3, _svc = _three(db, clinic)
    conv, cust = _chat(db, clinic, "สวัสดีค่ะ มีบริการอะไรบ้าง")

    hint = _booking_hint(db, conv, cust)
    for b in (first, b2, b3):
        assert b.name in hint


def test_the_checklist_says_so_when_the_chosen_branch_does_not_have_it(db, clinic):
    """The customer picked it off a list they should never have been shown — the reply
    has to say why, not quietly answer with something else."""
    first, b2, b3, svc = _three(db, clinic)
    conv, cust = _chat(db, clinic, f"สนใจ {svc.name}", first.name, branch=first)

    hint = _booking_hint(db, conv, cust)
    assert "is NOT offered at" in hint and first.name in hint
    assert b2.name in hint and b3.name in hint


# --------------------------------------------------------------------------
# the last check: the model's OWN draft
# --------------------------------------------------------------------------
def test_a_wrong_branch_list_is_corrected_when_the_customer_spelt_it_differently(db, clinic):
    """The customer answered "ไฮฟู"; the catalog says "Hifu".

    Nothing that reads the CUSTOMER's words could match those, so no earlier layer
    narrowed anything and all three branches were offered for a treatment that exists at
    two. The draft itself opened "สนใจ Hifu ใช่ไหมคะ" — the model resolves the spelling,
    so the draft is where the treatment is always named canonically.
    """
    first, b2, b3, _t2 = _three(db, clinic)
    hifu = _service(db, clinic, "Hifu", branch_ids=[b2.id, b3.id])
    conv, _cust = _chat(db, clinic, "ไฮฟู")

    draft = (f"สนใจ {hifu.name} ใช่ไหมคะ\n\nสะดวกสาขาไหนคะ ตอนนี้มีสาขา {first.name}, "
             f"{b2.name} และ {b3.name} ค่ะ")
    out = _correct_branch_list(db, conv, draft)
    assert first.name not in out
    assert f"{b2.name} และ {b3.name}" in out
    assert f"สนใจ {hifu.name} ใช่ไหมคะ" in out, "only the branch list is touched"


def test_a_stray_thai_mark_in_the_name_still_matches(db, clinic):
    """The real catalog row is "็Hifu" — a mai taikhu typed before the H, invisible in
    the admin form. The assistant writes "Hifu", so an exact match found nothing and the
    treatment was treated as if it had never been mentioned."""
    first, b2, b3, _t2 = _three(db, clinic)
    typo = _service(db, clinic, "็Hifu", branch_ids=[b2.id, b3.id])
    conv, _cust = _chat(db, clinic, "ไฮฟู")

    draft = f"สนใจ Hifu ใช่ไหมคะ สะดวกสาขาไหนคะ มีสาขา {first.name}, {b2.name} และ {b3.name} ค่ะ"
    out = _correct_branch_list(db, conv, draft)
    assert first.name not in out
    assert typo.name  # the row keeps its name; only the MATCH ignores the stray mark


def test_a_branch_list_joined_by_nothing_but_a_space_is_still_corrected(db, clinic):
    """Thai drops the conjunction freely: "ตอนนี้เรามีสาขาสีลม สาขาทองหล่อค่ะ" is a list.
    Requiring a comma or "และ" let exactly that shape through untouched."""
    first, b2, b3, _t2 = _three(db, clinic)
    hifu = _service(db, clinic, "Hifu", branch_ids=[b2.id, b3.id])
    conv, _cust = _chat(db, clinic, "ไฮฟู")

    draft = f"สนใจ {hifu.name} ใช่ไหมคะ ตอนนี้เรามีสาขา{first.name} สาขา{b2.name}ค่ะ"
    out = _correct_branch_list(db, conv, draft)
    assert first.name not in out
    assert b2.name in out and b3.name in out


def test_a_menu_keeps_each_lines_own_branches(db, clinic):
    """The correction must not make a correct reply wrong.

    An opening menu names every treatment at once. Judging the whole reply against ONE
    allowed set meant intersecting all their branch sets — Test (พระศรี+เสมียนนารี) with
    Hifu (เสมียนนารี+พารากอน) leaves เสมียนนารี alone — so both lines, each correct as
    written, were rewritten to that single branch and the customer was told neither
    treatment ran anywhere else.
    """
    first, b2, b3, _t2 = _three(db, clinic)
    a = _service(db, clinic, "Test Lift", branch_ids=[first.id, b2.id])
    b = _service(db, clinic, "Hifu", branch_ids=[b2.id, b3.id])
    conv, _cust = _chat(db, clinic, "ดีครับ")

    draft = ("ขอแนะนำทรีตเมนต์ยอดนิยมค่ะ\n"
             f"- {a.name} มีที่สาขา {first.name} และ {b2.name} ค่ะ ราคาเริ่มต้น 5,000 บาท\n"
             f"- {b.name} มีที่สาขา {b2.name} และ {b3.name} ค่ะ ราคาเริ่มต้น 10,000 บาท")
    assert _correct_branch_list(db, conv, draft) == draft


def test_a_menu_line_with_the_wrong_branch_is_still_fixed(db, clinic):
    """Per line means per line — a line that IS wrong still gets corrected, against the
    treatment named on that line and not against the rest of the menu."""
    first, b2, b3, _t2 = _three(db, clinic)
    a = _service(db, clinic, "Test Lift", branch_ids=[first.id, b2.id])
    b = _service(db, clinic, "Hifu", branch_ids=[b2.id, b3.id])
    conv, _cust = _chat(db, clinic, "ดีครับ")

    draft = (f"- {a.name} มีที่สาขา {first.name} และ {b2.name} ค่ะ\n"
             f"- {b.name} มีที่สาขา {first.name} และ {b2.name} ค่ะ")   # Hifu is not at `first`
    out = _correct_branch_list(db, conv, draft).splitlines()
    assert out[0] == f"- {a.name} มีที่สาขา {first.name} และ {b2.name} ค่ะ", "untouched"
    assert out[1] == f"- {b.name} มีที่สาขา {b2.name} และ {b3.name} ค่ะ"


def test_a_line_naming_several_treatments_is_left_alone(db, clinic):
    """No single branch list answers for two treatments at once."""
    first, b2, b3, _t2 = _three(db, clinic)
    a = _service(db, clinic, "Test Lift", branch_ids=[first.id, b2.id])
    b = _service(db, clinic, "Hifu", branch_ids=[b2.id, b3.id])
    conv, _cust = _chat(db, clinic, "ดีครับ")

    draft = f"{a.name} กับ {b.name} มีที่สาขา {first.name}, {b2.name} และ {b3.name} ค่ะ"
    assert _correct_branch_list(db, conv, draft) == draft


def test_a_single_branch_mention_is_never_rewritten(db, clinic):
    """"This treatment is not available at X" names one branch on purpose — editing it
    would invert the sentence."""
    first, b2, b3, _t2 = _three(db, clinic)
    hifu = _service(db, clinic, "Hifu", branch_ids=[b2.id, b3.id])
    conv, _cust = _chat(db, clinic, "ไฮฟู")

    draft = (f"{hifu.name} ยังไม่เปิดให้บริการที่สาขา {first.name} ค่ะ "
             f"ตอนนี้มีที่สาขา {b2.name} และ {b3.name} ค่ะ")
    assert _correct_branch_list(db, conv, draft) == draft


def test_a_correct_branch_list_is_left_alone(db, clinic):
    _first, b2, b3, _t2 = _three(db, clinic)
    hifu = _service(db, clinic, "Hifu", branch_ids=[b2.id, b3.id])
    conv, _cust = _chat(db, clinic, "ไฮฟู")

    draft = f"{hifu.name} สะดวกสาขาไหนคะ มีที่ {b2.name} และ {b3.name} ค่ะ"
    assert _correct_branch_list(db, conv, draft) == draft


def test_an_unrestricted_treatment_keeps_every_branch(db, clinic):
    """The correction must never fire on a treatment every branch offers."""
    first, b2, b3, _t2 = _three(db, clinic)
    everywhere = _service(db, clinic, "Global Facial")
    conv, _cust = _chat(db, clinic, "สนใจ Global Facial")

    draft = (f"{everywhere.name} สะดวกสาขาไหนคะ ตอนนี้มีสาขา {first.name}, "
             f"{b2.name} และ {b3.name} ค่ะ")
    assert _correct_branch_list(db, conv, draft) == draft


def test_the_correction_speaks_the_replys_language(db, clinic):
    first, b2, b3, _t2 = _three(db, clinic)
    hifu = _service(db, clinic, "Hifu", branch_ids=[b2.id, b3.id])
    conv, _cust = _chat(db, clinic, "hifu please")

    draft = f"{hifu.name} - which branch suits you? We have {first.name}, {b2.name} and {b3.name}."
    out = _correct_branch_list(db, conv, draft)
    assert f"{b2.name} and {b3.name}" in out
    assert first.name not in out


# --------------------------------------------------------------------------
# the catalog block injected on EVERY turn — the one that used to outvote the rest
# --------------------------------------------------------------------------
def test_the_catalog_block_names_only_the_branches_that_have_it(db, clinic):
    """The reported failure: the model answered without calling a tool, so the only
    thing it read was this block — which listed every branch and told it to name them."""
    first, b2, b3, svc = _three(db, clinic)
    conv, _cust = _chat(db, clinic, "ดีคะ", svc.name)

    ctx = _context(db, clinic, conv)
    assert f"ONLY at {b2.name}, {b3.name}" in ctx
    assert "name ONLY those and no others" in ctx
    assert "name EVERY one" not in ctx, "the unconditional order is what overrode everything"


def test_the_catalog_block_labels_a_restricted_treatment(db, clinic):
    _first, b2, b3, svc = _three(db, clinic)
    conv, _cust = _chat(db, clinic, "สวัสดีค่ะ")

    ctx = _context(db, clinic, conv)
    assert f"(only at: {b2.name}, {b3.name})" in _line_for(ctx, svc.name)
    assert "prefer treatments with no '(only at)' mark" in ctx, \
        "an all-branch treatment leads the pitch"
    # A finished line beats a rule: the model dropped the branches when it was only
    # told to mention them, so it is handed the sentence in both languages.
    assert f"'{svc.name} (มีเฉพาะสาขา {b2.name}, {b3.name})'" in ctx


def test_all_branch_treatments_are_listed_first(db, clinic):
    """The clinic's rule is "the ones every branch has win". The model takes the first
    two or three off the list, so the ORDER enforces it — a header sentence only asks."""
    _clear_catalog(db, clinic)
    _first, _b2, _b3, restricted = _three(db, clinic)
    everywhere = _service(db, clinic, "Global Facial")
    conv, _cust = _chat(db, clinic, "มีอะไรแนะนำบ้างคะ")

    listed = [ln for ln in _context(db, clinic, conv).splitlines() if ln.startswith("- ")]
    names = [ln for ln in listed if everywhere.name in ln or restricted.name in ln]
    assert everywhere.name in names[0]
    assert restricted.name in names[-1]


def test_the_catalog_block_drops_what_this_branch_does_not_have(db, clinic):
    """With a branch known the block says "quote them exactly as-is", so a treatment the
    branch does not offer must not be in the list at all."""
    first, _b2, _b3, svc = _three(db, clinic)
    keep = _service(db, clinic, "Everywhere Facial")
    conv, _cust = _chat(db, clinic, "สวัสดีค่ะ", first.name, branch=first)

    ctx = _context(db, clinic, conv)
    assert keep.name in ctx
    assert svc.name not in ctx


def test_a_clinic_whose_whole_menu_is_branch_specific_still_gets_listed(db, clinic):
    """The "prefer all-branch treatments" rule must not empty the menu of a clinic that
    has only one or two, each at its own branch."""
    _clear_catalog(db, clinic)
    first, b2, _b3, svc = _three(db, clinic)
    solo = _service(db, clinic, "First Only Facial", branch_ids=[first.id])
    conv, _cust = _chat(db, clinic, "มีบริการอะไรบ้างคะ")

    ctx = _context(db, clinic, conv)
    assert "(only at:" in _line_for(ctx, svc.name)
    assert f"(only at: {first.name})" in _line_for(ctx, solo.name)
    assert b2.name in ctx


# --------------------------------------------------------------------------
# the tool result
# --------------------------------------------------------------------------
def test_list_treatments_carries_the_branches_instead_of_hiding(db, clinic):
    """A branch-restricted treatment is listed WITH its branches, never hidden.

    Hiding it until a branch was known is what left the assistant asking about branches
    that do not have it; hiding it also cost a clinic whose whole menu is branch-specific
    its entire pitch. So it is shown and labelled — the same shape the always-injected
    catalog block uses, so the two can never say different things.
    """
    first, b2, b3, svc = _three(db, clinic)
    other = _service(db, clinic, "Unasked Exclusive", branch_ids=[b3.id])
    conv, cust = _chat(db, clinic, f"สนใจ {svc.name}")

    res = execute_tool(db, conv, cust, "list_treatments", {})
    listed = {t["name"]: t for t in res["treatments"]}
    assert listed[svc.name]["only_at"] == [b2.name, b3.name]
    assert listed[other.name]["only_at"] == [b3.name], "labelled, not hidden"
    assert f"ONLY at: {b2.name}, {b3.name}" in res["branch_note"]
    assert first.name not in res["branch_note"]
    assert "prefer treatments without it" in res["branch_note"], \
        "all-branch treatments lead the pitch"


def test_the_branch_fact_comes_ready_made_with_the_catalog_name(db, clinic):
    """The customer typed "ไฮฟู่ว" and the reply came back "ไฮฟู่วมีที่สาขา..." — their own
    spelling. That leaves them unsure which menu item they are getting (this clinic has
    "…test" and "…test2"), and it switches OFF chat._correct_branch_list, which matches
    on the catalog name. A rule to use the catalog spelling loses to the pull of echoing
    the customer, so the sentence is handed over instead.

    A STATEMENT, not a question: ending it with "สะดวกสาขาไหนคะ" got it pasted into an
    opening menu, giving three treatments three which-branch questions and pushing the
    prices off their lines. The question belongs to the model, which writes it in the
    ครับ/ค่ะ of that conversation instead of the template's.
    """
    _first, b2, b3, svc = _three(db, clinic)
    conv, cust = _chat(db, clinic, "ไฮฟู่ว")

    item = next(t for t in execute_tool(db, conv, cust, "list_treatments", {})["treatments"]
                if t["name"] == svc.name)
    assert item["say_it_like"] == f"{svc.name} มีที่สาขา {b2.name} และ {b3.name} ค่ะ"
    assert "สะดวกสาขาไหนคะ" not in item["say_it_like"]
    assert svc.name in item["say_it_like_en"]
    assert "?" not in item["say_it_like_en"]


def test_an_unrestricted_treatment_carries_no_branch_caveat(db, clinic):
    _first, _b2, _b3, _svc = _three(db, clinic)
    everywhere = _service(db, clinic, "Global Facial")
    conv, cust = _chat(db, clinic, "มีอะไรแนะนำบ้างคะ")

    res = execute_tool(db, conv, cust, "list_treatments", {})
    listed = {t["name"]: t for t in res["treatments"]}
    assert "only_at" not in listed[everywhere.name]


def test_list_treatments_says_this_branch_does_not_have_it(db, clinic):
    first, b2, b3, svc = _three(db, clinic)
    _service(db, clinic, "Something Else")
    conv, cust = _chat(db, clinic, f"สนใจ {svc.name}", first.name, branch=first)

    res = execute_tool(db, conv, cust, "list_treatments", {})
    assert svc.name not in {t["name"] for t in res["treatments"]}
    missing = res["not_at_this_branch"]
    assert [m["name"] for m in missing] == [svc.name]
    assert missing[0]["available_at"] == [b2.name, b3.name]
    assert first.name in missing[0]["say_it_like"]
    assert b2.name in missing[0]["say_it_like"] and b3.name in missing[0]["say_it_like"]


def test_a_brand_new_branch_with_an_empty_menu_says_why(db, clinic):
    """A branch opened after the catalog was written has nothing on it yet.

    The empty list used to come back bare, and the model filled the gap with the two
    treatments it had named one turn earlier — both belonging to the OTHER branch:
    "สาขาเปิดใหม่มีทรีตเมนต์ผิวหน้าให้เลือก 2 ตัวค่ะ". Same rule as an empty availability
    day: the reason travels with the emptiness.
    """
    _clear_catalog(db, clinic)
    first = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    first.name = "สาขาเดิม"
    db.commit()
    fresh = _branch(db, clinic, "สาขาเปิดใหม่")
    _service(db, clinic, "Aqua Peel", branch_ids=[first.id])
    _service(db, clinic, "Gold Lifting", branch_ids=[first.id])

    conv, cust = _chat(db, clinic, "สนใจทำหน้าใสค่ะ", fresh.name, branch=fresh)
    res = execute_tool(db, conv, cust, "list_treatments", {})

    assert res["treatments"] == []
    assert res["empty_reason"] == "no_treatments_at_this_branch"
    assert res["available_at"] == [first.name]
    assert fresh.name in res["say_it_like"] and first.name in res["say_it_like"]
    assert "Do NOT name any treatment" in res["empty_note"]


def test_an_empty_catalog_is_not_reported_as_a_branch_problem(db, clinic):
    _clear_catalog(db, clinic)
    fresh = _branch(db, clinic, "สาขาเปิดใหม่")
    conv, cust = _chat(db, clinic, "มีอะไรบ้างคะ", fresh.name, branch=fresh)

    res = execute_tool(db, conv, cust, "list_treatments", {})
    assert res["treatments"] == []
    assert res["empty_reason"] == "catalog_empty"
    assert "available_at" not in res


def test_a_branch_that_has_it_reports_nothing_missing(db, clinic):
    _first, b2, _b3, svc = _three(db, clinic)
    conv, cust = _chat(db, clinic, f"สนใจ {svc.name}", b2.name, branch=b2)

    res = execute_tool(db, conv, cust, "list_treatments", {})
    listed = {t["name"]: t for t in res["treatments"]}
    assert svc.name in listed
    assert "not_at_this_branch" not in res
    assert "only_at" not in listed[svc.name], "no branch caveat once they are at a branch that has it"
