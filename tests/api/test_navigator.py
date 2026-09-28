"""Asking the rights navigator (REQ-014, REQ-006; docs/design/navigator.md §4, §9; api.md §6).

Two promises are held here:
- **every example question finds its own topic.** They are the catalogue's tests. So are a few
  phrasings no topic lists, so the matching isn't only memorising its examples.
- **a question no topic covers is told so,** and pointed to the Rental Housing Tribunal. It is
  never answered with the nearest topic: a confident wrong answer is the worst outcome here.

The threshold and the margin are set so that both hold, and this file is the record of why.
"""

import json
import time

import pytest

from tokelo.api import navigator
from tokelo.api.handler import handler
from tokelo.api.views import NOTICE
from tokelo.core import sources

TENANT = "11111111-1111-4111-8111-111111111111"

# navigator.md §9's fixed set, and SPEC.md US4's own example.
OUTSIDE = [
    "Can I sublet on Airbnb?",
    "Can I sublet my flat on Airbnb?",
    "Am I allowed to keep a dog in my flat?",
    "My neighbours play loud music every night",
    "Who pays the municipal rates on the property?",
    "Can I run my hair salon business from the house?",
    "How do I apply for a housing subsidy?",
    "What is the weather in Johannesburg?",
]

# Phrasings no topic lists, each with the topic a tenant asking it needs.
UNSEEN = [
    ("Is my landlord allowed to keep my deposit?", "deposits"),
    ("The landlord cut off the electricity yesterday", "services-and-lockouts"),
    ("Can the owner come in without telling me first?", "landlord-entry"),
    ("I received an eviction notice", "eviction"),
    ("My lease has a R500 late fee, is that unfair?", "unfair-terms"),
]


def ask(question: object, tenant: str | None = TENANT) -> dict:
    event: dict = {
        "version": "2.0",
        "routeKey": "ANY /api/{proxy+}",
        "rawPath": "/api/navigator",
        "requestContext": {"http": {"method": "POST", "path": "/api/navigator"}},
        "body": json.dumps({"question": question}),
    }
    if tenant is not None:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": tenant}}}
    return event


def answer_to(question: str) -> dict:
    response = handler(ask(question))
    assert response["statusCode"] == 200, response
    return json.loads(response["body"])


EXAMPLES = [(t.id, q) for t in navigator.catalogue() for q in t.questions]


@pytest.mark.req("REQ-014")
@pytest.mark.parametrize(("topic_id", "question"), EXAMPLES)
def test_every_example_question_finds_its_own_topic(topic_id, question):
    assert navigator.match(question) == topic_id


@pytest.mark.req("REQ-014")
@pytest.mark.parametrize(("question", "topic_id"), UNSEEN)
def test_a_phrasing_no_topic_lists_still_finds_its_topic(question, topic_id):
    assert navigator.match(question) == topic_id


@pytest.mark.req("REQ-014")
@pytest.mark.parametrize("question", OUTSIDE)
def test_a_question_no_topic_covers_is_told_so_and_pointed_to_the_tribunal(question):
    reply = answer_to(question)

    assert reply["outside"] is True
    assert reply["refer_to"] == "the Rental Housing Tribunal"
    assert "Rental Housing Tribunal" in reply["message"]
    assert set(reply) == {"outside", "message", "refer_to"}


@pytest.mark.req("REQ-014", "REQ-006")
def test_the_spec_example_is_answered_from_the_rental_housing_act_and_the_pie_act():
    """SPEC.md US4: "Can my landlord cut the water because I'm late?" cites the Rental Housing
    Act and the PIE Act, and says it is legal information."""
    reply = answer_to("Can my landlord cut the water because I'm late?")

    assert reply["topic"] == "Services and lock-outs"
    acts = {ref["act"] for ref in reply["sections"]}
    assert any(a.startswith("Rental Housing Act") for a in acts)
    assert any(a.startswith("Prevention of Illegal Eviction") for a in acts)
    assert reply["notice"] == NOTICE
    assert set(reply) == {"topic", "answer", "sections", "notice"}


@pytest.mark.req("REQ-006")
def test_every_answer_cites_only_curated_sections_and_no_case_law():
    for topic in navigator.catalogue():
        reply = answer_to(topic.questions[0])
        assert {ref["id"] for ref in reply["sections"]} <= sources.ids()
        assert not navigator.CASE_LAW.search(reply["answer"])


@pytest.mark.req("REQ-014")
@pytest.mark.parametrize("question", ["", "  ", "hi", "x" * 501, None, 42])
def test_a_question_that_is_empty_too_long_or_not_text_is_refused(question):
    response = handler(ask(question))

    assert response["statusCode"] == 422
    assert json.loads(response["body"])["error"]["code"] == "refused"


def test_the_threshold_and_margin_sit_between_what_they_separate():
    """The record of why the two numbers are what they are: each keeps a quarter point of room
    on both sides, so a topic added later that crowds them fails here, not on a tenant."""

    def top_two(question: str) -> tuple[float, float]:
        ranked = sorted((navigator.score(t, question) for t in navigator.catalogue()), reverse=True)
        return ranked[0], ranked[0] - ranked[1]

    inside = [top_two(q) for _, q in EXAMPLES] + [top_two(q) for q, _ in UNSEEN]
    outside = [top_two(q) for q in OUTSIDE]
    room = 0.25
    assert min(best for best, _ in inside) >= navigator.THRESHOLD + room
    assert min(margin for _, margin in inside) >= navigator.MARGIN + room
    assert max(best for best, _ in outside) <= navigator.THRESHOLD - room


def test_a_near_tie_is_outside_rather_than_a_guess():
    """navigator.md §4: a question that two topics score almost alike is referred on."""
    tied = "deposit and eviction"
    scores = sorted((navigator.score(t, tied) for t in navigator.catalogue()), reverse=True)

    assert scores[0] - scores[1] < navigator.MARGIN
    assert navigator.match(tied) is None


def test_a_crafted_question_can_t_make_the_patterns_run_long():
    """At most 500 characters, and no nested repetition in any pattern (§Threats)."""
    crafted = ("a" * 30 + "!") * 16

    started = time.monotonic()
    handler(ask(crafted[:500]))
    assert time.monotonic() - started < 1.0


@pytest.mark.req("REQ-001")
def test_an_unauthenticated_question_is_refused():
    assert handler(ask("Does my deposit earn interest?", tenant=None))["statusCode"] == 401
