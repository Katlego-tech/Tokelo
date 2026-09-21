"""The curated legal sources (REQ-006; docs/design/ocr.md, navigator.md).

This set is the ceiling on everything Tokelo says about the law: a rule may cite only what is in
here, and so may an answer. So the tests are about the set itself — that every section says which
Act it is from and where the text was taken, that no two share an ID, and that nothing is empty —
rather than about any one section's words."""

import pytest

from tokelo.core import sources

ACTS = {
    "Rental Housing Act 50 of 1999",
    "Consumer Protection Act 68 of 2008",
    "Prevention of Illegal Eviction from and Unlawful Occupation of Land Act 19 of 1998",
    "Unfair Practices Regulations, 2001 (Gauteng)",
}


# Until the consolidated texts are in hand (docs/legal/README.md), the set is empty and this is
# the shape of what is missing. strict=True: the day curation lands, this test passes, the suite
# goes red for an unexpected pass, and the marker comes off. It cannot be forgotten.
@pytest.mark.xfail(strict=True, reason="T022: the curated sections aren't in yet")
@pytest.mark.req("REQ-006")
def test_the_set_covers_the_law_the_specification_names():
    """SPEC.md promises checks against three Acts, and the flags cite the Gauteng regulations
    that put detail on them. Until each is curated, the product can't say what it promises."""
    assert {section.act for section in sources.all_sections()} == ACTS


@pytest.mark.req("REQ-006")
def test_every_section_says_what_it_is_and_where_it_came_from():
    for section in sources.all_sections():
        where = f"{section.id}"
        assert section.act in ACTS, f"{where}: {section.act} isn't one of the curated Acts"
        assert section.number, f"{where}: no section number"
        assert section.title, f"{where}: no title"
        assert len(section.text) > 80, f"{where}: the text is too short to be a section"
        # Where it was taken from, so any line can be read against the page it came from.
        assert section.source.url.startswith("https://"), f"{where}: no source URL"
        assert section.source.publisher, f"{where}: no publisher"
        assert section.source.retrieved, f"{where}: no retrieval date"


@pytest.mark.req("REQ-006")
def test_an_id_names_one_section_and_only_one():
    ids = [section.id for section in sources.all_sections()]
    assert len(ids) == len(set(ids)), "two sections share an ID"
    assert sources.ids() == frozenset(ids)


@pytest.mark.req("REQ-006")
def test_a_section_can_be_fetched_by_its_id():
    for wanted in sources.ids():
        section = sources.section(wanted)
        assert section.id == wanted
        assert section.text.strip() == section.text


@pytest.mark.req("REQ-006")
def test_asking_for_a_section_that_was_never_curated_is_an_error_not_an_empty_answer():
    """A rule or a topic that cites something outside the set must fail loudly where it is
    loaded, not quietly show a tenant an explanation with no law behind it."""
    with pytest.raises(sources.NotCurated) as refused:
        sources.section("RHA-999")
    assert "RHA-999" in str(refused.value)


@pytest.mark.req("REQ-006")
def test_the_law_a_tenant_is_shown_is_the_law_that_is_in_force():
    """Every section records the day its text was checked against the source, and an Act that has
    been amended says which amendments its text includes. A citation with no date is a citation
    nobody can check later."""
    for section in sources.all_sections():
        assert section.source.as_at, f"{section.id}: no 'as at' date"
        assert section.source.amendments, f"{section.id}: say which amendments this text includes"
