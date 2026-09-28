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

Matching a question to a topic, and the endpoint, are T046's.
"""

import re
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

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
