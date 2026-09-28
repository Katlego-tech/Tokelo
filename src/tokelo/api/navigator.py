"""The rights navigator's curated topics (docs/design/navigator.md §3, §6; REQ-014, REQ-006).

A tenant asks a question, and Tokelo answers it only from a topic someone wrote, reviewed in a
PR, and grounded in the curated law: never generated (ADR-0006), never from anything else. This
module loads those topics from `docs/legal/topics/` and refuses, at load, any topic that could
put a word outside the curated law in front of a tenant:
- a section ID that isn't curated (REQ-006), or no section at all
- fewer than 3 example questions: they are the topic's own tests (T046)
- a duplicate ID
- an answer over 2,000 characters
- any mention of case law: the curated sources hold none (ADR-0006)
- a section or regulation named in the answer that the topic doesn't cite, so the answer can't
  quote a number its citations don't back
- a pattern that doesn't compile, or one with nested repetition, which could run for a long
  time on a crafted question (§Threats)

Below the loading: matching a question to a topic (§4), and the endpoint (T046).
"""

import json
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from tokelo.api import views
from tokelo.api.auth import tenant_of
from tokelo.api.responses import Response, error, json_response
from tokelo.core import sources

FRONT_MATTER = "+++"
ANSWER_LIMIT = 2000
MIN_QUESTIONS = 3

# How a judgment is cited in South Africa: "[2004] ZACC 7", "2005 (1) SA 217 (CC)", or two
# parties either side of a "v". None of it may appear: the curated sources are statutes only.
CASE_LAW = re.compile(
    r"\[\d{4}\]\s*ZA[A-Z]+"
    r"|\b\d{4}\s*\(\d+\)\s*(SA|BCLR|All SA)\b"
    r"|\bZA(CC|SCA|[A-Z]{2,5}HC)\b"
    r"|\b[A-Z][\w'-]+ v\.? [A-Z][\w'-]+"
)
# A group that repeats and is itself repeated, like (a+)+ or (\w*)*: the shape that makes a
# backtracking engine take exponential time.
NESTED_REPETITION = re.compile(r"\([^()]*[+*][^()]*\)[+*{]")
# "section 5(3)(e) and 5(7)", "sections 1 and 8", "regulation 9(3) and 9(4)", "13(1), 13(4)".
CITED = re.compile(
    r"\b(sections?|regulations?)\s+"
    r"(\d+(?:\([^)]*\))*(?:(?:,\s*|\s+and\s+|\s+to\s+)\d+(?:\([^)]*\))*)*)"
)


class BadTopic(ValueError):
    """A topic that must not be shown to anybody."""


@dataclass(frozen=True)
class Topic:
    id: str
    title: str
    questions: list[str]
    any_of: list[re.Pattern[str]]
    section_ids: list[str]
    answer: str

    def sections(self) -> list[dict[str, str]]:
        """api.md §6's SectionRefs for the sections this answer rests on."""
        return [sources.section(i).reference() for i in self.section_ids]


def root() -> Path:
    """Beside the curated sections: `legal/topics` in an image, `docs/legal/topics` here."""
    return sources.root().parent / "topics"


def parse(text: str, where: str) -> Topic:
    """One topic file, checked against every rule but the catalogue-wide one (duplicate IDs)."""
    if not text.startswith(FRONT_MATTER):
        raise BadTopic(f"{where}: a topic starts with {FRONT_MATTER}")
    _, front, body = text.split(FRONT_MATTER, 2)
    try:
        fields: dict[str, Any] = tomllib.loads(front)
    except tomllib.TOMLDecodeError as e:
        raise BadTopic(f"{where}: {e}") from e
    answer = body.strip()
    topic_id = str(fields.get("id", ""))
    if not topic_id or not fields.get("title"):
        raise BadTopic(f"{where}: a topic needs an id and a title")

    questions = [str(q) for q in fields.get("questions", [])]
    if len(questions) < MIN_QUESTIONS:
        raise BadTopic(f"{where}: {topic_id} needs at least {MIN_QUESTIONS} example questions")

    section_ids = [str(s) for s in fields.get("section_ids", [])]
    if not section_ids:
        raise BadTopic(f"{where}: {topic_id} cites no section (REQ-006)")
    curated = sources.ids()
    for cited in section_ids:
        if cited not in curated:
            raise BadTopic(
                f"{where}: {topic_id} cites {cited}, which is not a curated section "
                "(docs/legal/). An answer must rest on law this project holds."
            )

    if not answer:
        raise BadTopic(f"{where}: {topic_id} has no answer")
    if len(answer) > ANSWER_LIMIT:
        raise BadTopic(f"{where}: {topic_id}'s answer is over {ANSWER_LIMIT} characters")
    if found := CASE_LAW.search(answer):
        raise BadTopic(
            f"{where}: {topic_id} mentions case law ({found.group(0)!r}); the curated sources "
            "are statutes, and an answer may cite nothing else (ADR-0006)"
        )
    _check_numbers(answer, section_ids, f"{where}: {topic_id}")

    patterns: list[re.Pattern[str]] = []
    for pattern in fields.get("any_of", []):
        if NESTED_REPETITION.search(pattern):
            raise BadTopic(f"{where}: {topic_id}'s pattern {pattern!r} nests a repetition")
        try:
            patterns.append(re.compile(pattern, re.I))
        except re.error as e:
            raise BadTopic(f"{where}: {topic_id}'s pattern {pattern!r}: {e}") from e

    return Topic(
        id=topic_id,
        title=str(fields["title"]),
        questions=questions,
        any_of=patterns,
        section_ids=section_ids,
        answer=answer,
    )


# How an answer names each Act, and the prefix of that Act's curated IDs. A section belongs to the
# Act named most recently before it; the Gauteng regulations are numbered as regulations.
ACTS = {
    "Rental Housing Act": "RHA-",
    "Consumer Protection Act": "CPA-",
    "PIE Act": "PIE-",
}
ACT_NAMED = re.compile("|".join(re.escape(name) for name in ACTS))


def _check_numbers(answer: str, section_ids: list[str], where: str) -> None:
    """Every section or regulation number the answer names is one the topic cites, for that Act:
    a regulation among the Gauteng regulations it cites, a section among the sections it cites
    of the Act named most recently before it. "Section 4" is a different thing in the Rental
    Housing Act and the PIE Act, and a reader has to know which to look it up."""
    cited = [sources.section(i) for i in section_ids]
    named_acts = [(m.start(), ACTS[m.group(0)]) for m in ACT_NAMED.finditer(answer)]
    for found in CITED.finditer(answer):
        kind, numbers = found.group(1), found.group(2)
        named = set(re.findall(r"(?:^|,\s*|\s+and\s+|\s+to\s+)(\d+)", numbers))
        if kind.startswith("regulation"):
            prefix, act = "GT-REG-", "Gauteng's regulations"
        else:
            before = [p for at, p in named_acts if at < found.start()]
            if not before:
                raise BadTopic(f"{where} names {kind} {numbers} before naming its Act")
            prefix = before[-1]
            act = next(name for name, p in ACTS.items() if p == prefix)
        allowed = {s.number for s in cited if s.id.startswith(prefix)}
        if missing := named - allowed:
            raise BadTopic(
                f"{where} names {kind} {', '.join(sorted(missing))} of the {act}, "
                "which it doesn't cite"
            )


def load(folder: Path) -> list[Topic]:
    """Every topic in `folder`, checked, in ID order. Raises BadTopic on the first bad one."""
    topics: dict[str, Topic] = {}
    for path in sorted(folder.glob("*.md")):
        topic = parse(path.read_text(encoding="utf-8"), path.name)
        if topic.id in topics:
            raise BadTopic(f"{path.name}: {topic.id} is already a topic")
        topics[topic.id] = topic
    return [topics[k] for k in sorted(topics)]


@cache
def catalogue() -> list[Topic]:
    """The topics this image holds, loaded once per container."""
    return load(root())


# ------------------------------------------------------------------ matching ---
# navigator.md §4: patterns and word overlap, deterministic. A pattern that matches is strong
# evidence (2 each); the overlap with the topic's closest example question, a share from 0 to 1,
# breaks ties and carries phrasings no pattern names. The best topic answers only if it reaches
# THRESHOLD and beats the next by MARGIN; otherwise the question is outside. Both numbers are the
# ones tests/api/test_navigator.py needs to put every example on its topic, the held-out
# phrasings on theirs, and the out-of-scope set outside.
# Measured on the examples, the held-out phrasings and the out-of-scope set (T046): the weakest
# in-scope question scores 1.0 and wins by at least 1.0; no out-of-scope question scores above 0.
# Each number sits midway, and a test keeps it there as topics are added.
THRESHOLD = 0.5
MARGIN = 0.5
PATTERN_WEIGHT = 2.0

# Words that say nothing about which topic a question is about. "landlord", "lease", "flat" and
# the like are in nearly every tenant's question, so they are here too.
STOP_WORDS = frozenset(
    """a an the and or but if of to in on at for with from by about as into it its is are was were
    be been being do does did done have has had i me my mine we us our you your he him his she her
    they them their this that these those what which who whom when where why how can could may
    might must shall should will would not no yes so than then there here just also very too any
    all some there's i'm it's can't won't don't doesn't didn't isn't is'nt allowed legal landlord
    landlords owner tenant tenants lease flat house home place property rent renting""".split()
)


def words(text: str) -> set[str]:
    """The question's words that could tell topics apart: lower-cased, punctuation gone."""
    cleaned = re.sub(r"[^\w\s']", " ", text.lower())
    return {w.strip("'") for w in cleaned.split()} - STOP_WORDS - {""}


def score(topic: Topic, question: str) -> float:
    matched = sum(1 for p in topic.any_of if p.search(question))
    asked = words(question)
    overlap = (
        max(
            (len(asked & words(example)) / len(asked) for example in topic.questions),
            default=0.0,
        )
        if asked
        else 0.0
    )
    return PATTERN_WEIGHT * matched + overlap


def match(question: str) -> str | None:
    """The topic that answers `question`, or None when none clearly does."""
    ranked = sorted(
        ((score(t, question), t.id) for t in catalogue()), key=lambda s: s[0], reverse=True
    )
    if not ranked:
        return None
    best = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
    if best[0] >= THRESHOLD and best[0] - runner_up >= MARGIN:
        return best[1]
    return None


def topic(topic_id: str) -> Topic:
    return next(t for t in catalogue() if t.id == topic_id)


# ------------------------------------------------------------------ the endpoint ---
QUESTION_MIN, QUESTION_MAX = 3, 500  # navigator.md §4

# What a tenant is told when no topic answers them (api.md §6, `Outside`). It says what the
# Tribunal does, in the curated Act's own terms (section 13(1)), and no more: Tokelo doesn't know
# whether this particular question is one the Tribunal will hear.
REFER_TO = "the Rental Housing Tribunal"
OUTSIDE_MESSAGE = (
    "Tokelo has no written answer for this question, so it won't guess at one. The Rental "
    "Housing Tribunal hears complaints from tenants and landlords about unfair practices."
)


def ask(event: Mapping[str, Any]) -> Response:
    """POST /api/navigator {question} → Answer or Outside (api.md §6).

    The question is never stored or logged: it may be personal, and nothing here needs it once
    it has been matched (navigator.md § Threats)."""
    tenant_of(event)  # behind the authorizer like every /api/ route; this is the lock behind it
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        body = None
    question = body.get("question") if isinstance(body, dict) else None
    if not isinstance(question, str) or not (QUESTION_MIN <= len(question.strip()) <= QUESTION_MAX):
        return error(
            422,
            "refused",
            f"Ask a question of {QUESTION_MIN} to {QUESTION_MAX} characters.",
        )

    found = match(question)
    if found is None:
        return json_response(200, views.outside(OUTSIDE_MESSAGE, REFER_TO))
    chosen = topic(found)
    return json_response(200, views.answer(chosen.title, chosen.answer, chosen.sections()))
