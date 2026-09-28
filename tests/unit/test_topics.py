"""The navigator's curated topics (REQ-014, REQ-006; docs/design/navigator.md §6, §9).

A topic is an answer a tenant may act on, so the catalogue refuses to load one that could say
anything the curated law doesn't. These tests hold the real topics to that, and check that each
of the loader's rules really refuses a topic that breaks it.
"""

from pathlib import Path

import pytest

from tokelo.api import navigator
from tokelo.core import sources

# navigator.md §6 ("What the topics cover") and T045's Done.
COVERED = {
    "repairs",
    "landlord-entry",
    "deposits",
    "services-and-lockouts",
    "eviction",
    "ending-a-fixed-term-lease",
    "unfair-terms",
    "joint-inspections",
}

GOOD = """+++
id = "{id}"
title = "A topic"
questions = ["one?", "two?", "three?"]
any_of = ['\\bdeposit']
section_ids = ["RHA-5"]
+++
{answer}
"""


def write(folder: Path, name: str, text: str) -> None:
    (folder / f"{name}.md").write_text(text, encoding="utf-8")


def a_topic(**changes: str) -> str:
    fields = {
        "id": "a-topic",
        "answer": "Under the Rental Housing Act, the landlord must refund it (section 5(3)(i)).",
    }
    return GOOD.format(**(fields | changes))


# ----------------------------------------------------------- the real topics ---
@pytest.mark.req("REQ-014", "REQ-006")
def test_the_catalogue_loads_and_covers_the_topics_the_design_names():
    topics = navigator.load(navigator.root())

    assert {t.id for t in topics} == COVERED


@pytest.mark.req("REQ-006")
def test_every_topic_cites_only_curated_sections():
    curated = sources.ids()
    for topic in navigator.load(navigator.root()):
        assert topic.section_ids, topic.id
        assert set(topic.section_ids) <= curated, topic.id
        assert all(ref["id"] in curated for ref in topic.sections())


@pytest.mark.req("REQ-014")
def test_every_topic_has_its_example_questions_and_a_short_answer():
    for topic in navigator.load(navigator.root()):
        assert len(topic.questions) >= navigator.MIN_QUESTIONS, topic.id
        assert 0 < len(topic.answer) <= navigator.ANSWER_LIMIT, topic.id


@pytest.mark.req("REQ-006")
def test_no_answer_gives_advice_or_calls_anything_lawful():
    """Tokelo says what the curated law says; it doesn't tell anyone what to do about it, and the
    notice that says so travels with every answer (api.md §6)."""
    for topic in navigator.load(navigator.root()):
        words = topic.answer.lower()
        for advice in ("you should", "we advise", "our advice", "is lawful", "is legal", "illegal"):
            assert advice not in words, (topic.id, advice)


# ---------------------------------------------------------------- the rules ---
@pytest.mark.req("REQ-006")
def test_a_section_that_isnt_curated_is_refused(tmp_path):
    write(tmp_path, "a", a_topic().replace('["RHA-5"]', '["RHA-99"]'))

    with pytest.raises(navigator.BadTopic, match="not a curated section"):
        navigator.load(tmp_path)


@pytest.mark.req("REQ-006")
def test_a_topic_that_cites_nothing_is_refused(tmp_path):
    write(tmp_path, "a", a_topic().replace('["RHA-5"]', "[]"))

    with pytest.raises(navigator.BadTopic, match="cites no section"):
        navigator.load(tmp_path)


def test_fewer_than_three_questions_is_refused(tmp_path):
    write(tmp_path, "a", a_topic().replace('"one?", "two?", "three?"', '"one?", "two?"'))

    with pytest.raises(navigator.BadTopic, match="at least 3"):
        navigator.load(tmp_path)


def test_a_duplicate_id_is_refused(tmp_path):
    write(tmp_path, "a", a_topic())
    write(tmp_path, "b", a_topic())

    with pytest.raises(navigator.BadTopic, match="already a topic"):
        navigator.load(tmp_path)


def test_an_answer_over_2000_characters_is_refused(tmp_path):
    write(tmp_path, "a", a_topic(answer="The deposit (section 5). " + "x" * 2000))

    with pytest.raises(navigator.BadTopic, match="over 2000"):
        navigator.load(tmp_path)


@pytest.mark.req("REQ-006")
@pytest.mark.parametrize(
    "citation",
    [
        "Maphango v Aengus Lifestyle Properties",
        "[2012] ZACC 2",
        "2012 (5) SA 531 (CC)",
        "a ruling of the ZASCA",
    ],
)
def test_any_mention_of_case_law_is_refused(tmp_path, citation):
    write(tmp_path, "a", a_topic(answer=f"As held in {citation}, the deposit (section 5)."))

    with pytest.raises(navigator.BadTopic, match="case law"):
        navigator.load(tmp_path)


@pytest.mark.req("REQ-006")
@pytest.mark.parametrize(
    "answer",
    [
        "The Rental Housing Act says the Tribunal hears it (section 13(1)).",
        "The Rental Housing Act says so: see sections 5 and 8.",
        "Gauteng's regulations say so (regulation 9(3)).",
        # The number is cited, but for another Act: RHA-5 is cited, the PIE Act's section 5 isn't.
        "The Rental Housing Act has its rule (section 5), and the PIE Act another (section 5).",
    ],
)
def test_an_answer_naming_a_section_it_doesnt_cite_is_refused(tmp_path, answer):
    """The answer can't quote a number its citations don't back: 13 isn't RHA-5, 8 isn't cited,
    and no Gauteng regulation is."""
    write(tmp_path, "a", a_topic(answer=answer))

    with pytest.raises(navigator.BadTopic, match="doesn't cite"):
        navigator.load(tmp_path)


@pytest.mark.req("REQ-006")
def test_a_section_named_before_its_act_is_refused(tmp_path):
    """A bare "section 5" says nothing about which Act it is in, so a reader can't check it."""
    write(tmp_path, "a", a_topic(answer="The landlord must refund it (section 5(3)(i))."))

    with pytest.raises(navigator.BadTopic, match="before naming its Act"):
        navigator.load(tmp_path)


def test_a_pattern_with_nested_repetition_is_refused(tmp_path):
    write(tmp_path, "a", a_topic().replace("'\\bdeposit'", "'(a+)+b'"))

    with pytest.raises(navigator.BadTopic, match="nests a repetition"):
        navigator.load(tmp_path)


def test_a_pattern_that_doesnt_compile_is_refused(tmp_path):
    write(tmp_path, "a", a_topic().replace("'\\bdeposit'", "'(unclosed'"))

    with pytest.raises(navigator.BadTopic, match="unclosed|missing"):
        navigator.load(tmp_path)


def test_a_good_topic_loads(tmp_path):
    write(tmp_path, "a", a_topic())

    (topic,) = navigator.load(tmp_path)
    assert topic.id == "a-topic"
    assert topic.any_of[0].search("my Deposit")
