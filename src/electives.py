"""
Module to handle student-specific elective choices.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Set

import requests

from .parser import Lesson

CHOICES_URL_TEMPLATE = (
    "https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"
)

COL_NAME = "ФИО"
COL_GROUP = "Группа"
COL_TECH_BLOCK_7 = "Технологический блок (7 семестр)"
COL_SCI_BLOCK_7 = "Научный блок (7 семестр)"

DEFAULT_LOCAL_CHOICES = Path(__file__).resolve().parents[1] / "student_choices.json"

_GENERIC_TOKENS = {
    "для",
    "при",
    "или",
    "дисциплина",
    "дисциплины",
    "выбору",
    "курс",
    "курсы",
    "семестр",
    "блок",
}

_TOKEN_SYNONYMS: dict[str, set[str]] = {
    "блокчейн": {"блокчейн", "blockchain"},
    "blockchain": {"блокчейн", "blockchain"},
    "эффективности": {"эффективности", "эффективность", "эффективност"},
    "эффективность": {"эффективности", "эффективность", "эффективност"},
}


@dataclass
class StudentChoice:
    name: str
    group: str
    electives: list[str] = field(default_factory=list)


def fetch_choices(spreadsheet_id: str, gid: str = "0") -> List[StudentChoice]:
    """Fetch and parse student elective choices."""
    url = CHOICES_URL_TEMPLATE.format(spreadsheet_id=spreadsheet_id, gid=gid)
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    content = response.content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))

    students = []
    for row in reader:
        if not row.get(COL_NAME) or not row.get(COL_GROUP):
            continue
        electives = []
        for col in (COL_TECH_BLOCK_7, COL_SCI_BLOCK_7):
            val = (row.get(col) or "").strip()
            if val:
                electives.append(val)
        students.append(
            StudentChoice(
                name=row[COL_NAME].strip(),
                group=row[COL_GROUP].strip(),
                electives=electives,
            )
        )
    return students


def load_local_choices(path: Path | str | None = None) -> dict:
    """Load per-student elective overrides from JSON.

    Format:
      {"ФИО": {"group": "11-303", "electives": ["...", "..."]}}
    """
    path = Path(path) if path else DEFAULT_LOCAL_CHOICES
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {}
    return data


def merge_local_choices(
    students: List[StudentChoice], overlay: dict
) -> List[StudentChoice]:
    """Replace/add electives from a local JSON overlay, keyed by student name."""
    by_name = {s.name: s for s in students}
    for name, spec in overlay.items():
        if isinstance(spec, list):
            electives = [str(x).strip() for x in spec if str(x).strip()]
            group = by_name[name].group if name in by_name else ""
        elif isinstance(spec, dict):
            electives = [str(x).strip() for x in spec.get("electives", []) if str(x).strip()]
            group = str(spec.get("group") or "").strip()
            if not group and name in by_name:
                group = by_name[name].group
        else:
            continue
        by_name[name] = StudentChoice(name=name, group=group, electives=electives)
    return list(by_name.values())


def normalize_text(text: str) -> str:
    """Normalize text for fuzzy matching (lowercase, remove punctuation)."""
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return " ".join(text.split())


def extract_keywords(choice_str: str) -> Set[str]:
    """Extract significant keywords from a choice string."""
    clean_choice = re.sub(r"[()]", " ", choice_str)
    norm = normalize_text(clean_choice)
    tokens = set(norm.split())
    ignore = {
        "технологии",
        "разработки",
        "разработка",
        "по",
        "для",
        "начинающих",
        "доп",
        "главы",
        "блок",
        "семестр",
        "прикладные",
        "задачи",
        "интеллектуального",
        "анализа",
        "данных",
        "на",
        "основы",
        "программного",
        "обеспечения",
        "систем",
        "управлению",
        "управление",
        "приложений",
        "приложения",
        "приложение",
        "часть",
        "часть1",
        "часть2",
        "мобильных",
        "архитектура",
        "проектирование",
        "занятия",
        "вебинар",
        "вебинары",
        "дисциплина",
        "дисциплины",
        "выбору",
    }
    return {t for t in tokens if t not in ignore and len(t) > 2}


def _choice_tokens(choice: str) -> list[str]:
    return [
        t
        for t in normalize_text(choice).split()
        if len(t) > 2 and t not in _GENERIC_TOKENS
    ]


def _token_hits(token: str, lesson_tokens: Set[str]) -> bool:
    variants = _TOKEN_SYNONYMS.get(token, {token})
    if variants & lesson_tokens:
        return True
    joined = " ".join(lesson_tokens)
    return any(v in joined for v in variants)


def find_elective_match(choice: str, available_lessons: List[Lesson]) -> List[Lesson]:
    """Find scheduled lessons matching the user's choice string."""
    if not choice:
        return []

    choice_norm = normalize_text(choice)
    tokens = _choice_tokens(choice)
    instructor_match = re.search(r"[–-]\s*([А-ЯЁ][а-яё]+)\s+[А-ЯЁ]\.", choice)
    instructor_surname = instructor_match.group(1).lower() if instructor_match else ""

    matches = []
    for lesson in available_lessons:
        if not lesson.instructor:
            continue
        lesson_text = normalize_text(f"{lesson.subject} {lesson.instructor}")
        lesson_tokens = set(lesson_text.split())

        if instructor_surname and instructor_surname in lesson_tokens:
            matches.append(lesson)
            continue

        if choice_norm and choice_norm in lesson_text:
            matches.append(lesson)
            continue

        if tokens and all(_token_hits(t, lesson_tokens) for t in tokens):
            matches.append(lesson)

    return matches


def is_elective_lesson(lesson: Lesson) -> bool:
    text = f"{lesson.subject} {lesson.instructor} {lesson.notes}".lower()
    return "по выбору" in text or "практика лаборато" in text


def collect_elective_pool(schedule: dict[str, list[Lesson]], prefix: str = "11-3") -> list[Lesson]:
    pool: list[Lesson] = []
    for gid, lessons in schedule.items():
        if str(gid).startswith(prefix):
            pool.extend(l for l in lessons if is_elective_lesson(l))
    return list(set(pool))


def personal_lessons(
    group_lessons: list[Lesson],
    elective_pool: list[Lesson],
    electives: list[str],
) -> list[Lesson]:
    """Core group lessons plus electives matching the student's choices."""
    chosen: set[Lesson] = set()
    for lesson in group_lessons:
        if not is_elective_lesson(lesson):
            chosen.add(lesson)
    for choice in electives:
        chosen.update(find_elective_match(choice, elective_pool))
    return list(chosen)
