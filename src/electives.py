"""Student elective choices from the KFU ITIS distribution spreadsheet."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Set

import requests

from .fetcher import fetch_csv
from .parser import Lesson

DEFAULT_CHOICES_SPREADSHEET_ID = "1ylZLNeuGEpb_7lVqtRlOfs6ngj_c977Zgt5XKZf_aSc"
# СРПО — основной блок, СРПО — гуманитарный блок (fall 2026/27).
DEFAULT_CHOICES_GIDS = ("1133833296", "872448650")

CHOICES_URL_TEMPLATE = (
    "https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"
)

COL_NAME = "ФИО"
COL_GROUP = "Группа"

_IDENTITY_HEADERS = {
    "фио",
    "группа",
    "форма обучения",
    "форма",
    "email",
    "почта",
    "комментарий",
    "примечание",
}
_SKIP_VALUES = {"", "-", "—", "нет", "не выбрано", "n/a", "na"}

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
    "технологии",
    "разработки",
    "разработка",
    "основы",
    "начинающих",
    "часть",
    "часть1",
    "часть2",
    "программного",
    "обеспечения",
    "систем",
    "приложений",
    "приложения",
    "приложение",
    "занятия",
    "вебинар",
    "вебинары",
    "доп",
    "главы",
    "на",
    "по",
    "в",
    "и",
    "из",
    "к",
    "от",
    "до",
    "со",
    "управление",
    "управлению",
    "задач",
    "задачи",
    "сфера",
    "сфере",
    "лек",
    "лекц",
    "лекция",
    "лекции",
    "прак",
    "практика",
    "группа",
    "нед",
    "недели",
}

_TOKEN_SYNONYMS: dict[str, set[str]] = {
    "блокчейн": {"блокчейн", "blockchain"},
    "blockchain": {"блокчейн", "blockchain"},
    "эффективности": {"эффективности", "эффективность", "эффективност"},
    "эффективность": {"эффективности", "эффективность", "эффективност"},
}

_NOISE_RE = re.compile(
    r"""
    \d+\s*-\s*\d+\s*нед\.?
    | с\s+\d+\s*(?:по\s+\d+\s*)?нед\.?
    | \d+\s*нед\.?
    | \bлек(?:ция|ции|ц)?\.?\b
    | \bпрак(?:тика)?\.?\b
    | \bгруппа\s*№?\s*\d+\b
    | \bгр\.?\s*№?\s*\d+\b
    | \bвебинары?\b
    | \bчасть\s*\d+\b
    | \bч\.?\s*\d+\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_YEAR_GROUP_RE = re.compile(r"^11-30[1-8]$")


@dataclass
class StudentChoice:
    name: str
    group: str
    electives: list[str] = field(default_factory=list)


def _norm_header(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").replace("\ufeff", "")).strip()


def _is_identity_header(name: str) -> bool:
    return _norm_header(name).casefold() in _IDENTITY_HEADERS


def _is_spring_header(name: str) -> bool:
    lowered = _norm_header(name).casefold()
    return "8 семестр" in lowered or "весенн" in lowered


def _is_elective_header(name: str) -> bool:
    header = _norm_header(name)
    return bool(header) and not _is_identity_header(header) and not _is_spring_header(header)


def _clean_value(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\r", " ").replace("\n", " ")).strip()


def parse_choices_csv(content: str) -> List[StudentChoice]:
    """Parse one distribution-sheet CSV into student choices (autumn columns only)."""
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return []

    name_col = next(
        (c for c in reader.fieldnames if _norm_header(c).casefold() == "фио"), None
    )
    group_col = next(
        (c for c in reader.fieldnames if _norm_header(c).casefold() == "группа"), None
    )
    elective_cols = [c for c in reader.fieldnames if _is_elective_header(c)]
    if not name_col or not group_col:
        return []

    students: list[StudentChoice] = []
    for row in reader:
        name = _clean_value(row.get(name_col) or "")
        group = _clean_value(row.get(group_col) or "")
        if not name or not group:
            continue
        electives: list[str] = []
        for col in elective_cols:
            val = _clean_value(row.get(col) or "")
            if val.casefold() in _SKIP_VALUES:
                continue
            if val not in electives:
                electives.append(val)
        students.append(StudentChoice(name=name, group=group, electives=electives))
    return students


def _norm_person_name(name: str) -> str:
    text = (name or "").replace("ё", "е").replace("Ё", "е")
    return re.sub(r"\s+", " ", text).casefold().strip()


def _surname(name: str) -> str:
    parts = _norm_person_name(name).split()
    return parts[0] if parts else ""


def _preferred_name(names: Iterable[str]) -> str:
    return max(names, key=lambda n: (len(n.split()), len(n)))


def _combine_students(
    students: list[StudentChoice], group: str | None = None
) -> StudentChoice:
    electives: list[str] = []
    for student in students:
        for item in student.electives:
            if item not in electives:
                electives.append(item)
    if group is None:
        groups = [s.group for s in students if s.group]
        group = max(set(groups), key=groups.count) if groups else ""
    return StudentChoice(
        name=_preferred_name(s.name for s in students),
        group=group or "",
        electives=electives,
    )


def merge_student_lists(batches: Iterable[List[StudentChoice]]) -> List[StudentChoice]:
    """Union electives for the same student across several sheet tabs.

    Names are matched with ё/е folded, and rows that share a surname + group
    (short FIO vs full FIO, typos) are treated as one person. A duplicate
    listing in another group keeps the fuller record instead of mixing courses.
    """
    rows = [student for batch in batches for student in batch]
    by_surname_group: dict[tuple[str, str], list[StudentChoice]] = {}
    for student in rows:
        key = (_surname(student.name), student.group)
        by_surname_group.setdefault(key, []).append(student)
    clustered = [
        _combine_students(items, group=group)
        for (_sn, group), items in by_surname_group.items()
    ]

    by_full: dict[str, list[StudentChoice]] = {}
    for student in clustered:
        by_full.setdefault(_norm_person_name(student.name), []).append(student)

    merged: list[StudentChoice] = []
    for items in by_full.values():
        if len(items) == 1:
            merged.append(items[0])
            continue
        # Same FIO listed under two groups: keep the row with more autumn
        # choices (the one that actually merged with the other tab).
        merged.append(max(items, key=lambda s: (len(s.electives), s.group)))
    return merged


def list_choice_gids(spreadsheet_id: str) -> list[str]:
    """Read tab gids from the public HTML view; fall back to known autumn tabs."""
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/htmlview"
    try:
        html = requests.get(url, timeout=30).text
        found = list(dict.fromkeys(re.findall(r'\bgid: "(\d+)"', html)))
        if found:
            return found
    except requests.RequestException:
        pass
    return list(DEFAULT_CHOICES_GIDS)


def fetch_choices(
    spreadsheet_id: str = DEFAULT_CHOICES_SPREADSHEET_ID,
    gid: str | None = None,
    gids: Iterable[str] | None = None,
) -> List[StudentChoice]:
    """Fetch and merge student elective choices from one or more sheet tabs."""
    if gids is not None:
        tab_ids = [str(g) for g in gids]
    elif gid is not None:
        tab_ids = [str(gid)]
    else:
        tab_ids = list_choice_gids(spreadsheet_id)

    batches = []
    for tab_id in tab_ids:
        content = fetch_csv(spreadsheet_id, tab_id)
        batches.append(parse_choices_csv(content))
    return merge_student_lists(batches)


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
            electives = [
                str(x).strip() for x in spec.get("electives", []) if str(x).strip()
            ]
            group = str(spec.get("group") or "").strip()
            if not group and name in by_name:
                group = by_name[name].group
        else:
            continue
        by_name[name] = StudentChoice(name=name, group=group, electives=electives)
    return list(by_name.values())


def normalize_text(text: str) -> str:
    """Normalize text for fuzzy matching (lowercase, remove punctuation)."""
    text = (text or "").replace("ё", "е").replace("Ё", "е")
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


def _expand_tokens(tokens: Iterable[str]) -> Set[str]:
    expanded: set[str] = set()
    for token in tokens:
        expanded |= _TOKEN_SYNONYMS.get(token, {token})
    return expanded


def _token_hits(token: str, lesson_tokens: Set[str]) -> bool:
    variants = _TOKEN_SYNONYMS.get(token, {token})
    if variants & lesson_tokens:
        return True
    joined = " ".join(lesson_tokens)
    return any(v in joined for v in variants)


def _is_metadata_phrase(text: str) -> bool:
    leftover = _NOISE_RE.sub(" ", text or "")
    return not _choice_tokens(leftover)


def _rest_is_generic(text: str) -> bool:
    return not _choice_tokens(text)


def _parentheticals(subject: str) -> list[str]:
    found = re.findall(r"\(([^)]*)\)", subject or "")
    if not found:
        dangling = re.search(r"\((.+)$", subject or "")
        found = [dangling.group(1)] if dangling else []
    cleaned = []
    for inner in found:
        inner = re.sub(r"\([^)]*\)?", " ", inner)
        inner = re.sub(r"\s+", " ", inner).strip(" ,;")
        if inner:
            cleaned.append(inner)
    return cleaned


def _primary_titles(subject: str) -> list[str]:
    """Course names a schedule cell actually represents.

    A non-metadata parenthetical is treated as the real course (or alias),
    so a shared prefix like 'Введение в облачные технологии (Анализ данных…)'
    does not steal matches from the parenthetical course.
    """
    inners = _parentheticals(subject)
    outer = re.sub(r"\([^)]*\)?", " ", subject or "")
    course_inners = [
        inner.strip()
        for inner in inners
        if inner.strip() and not _is_metadata_phrase(inner)
    ]
    if course_inners:
        return course_inners
    title = outer.strip() or (subject or "")
    return [title] if title else []


def _token_covered(needle: str, haystack: Set[str]) -> bool:
    variants = _TOKEN_SYNONYMS.get(needle, {needle})
    if variants & haystack:
        return True
    return any(
        (len(variant) >= 4 and other.startswith(variant))
        or (len(other) >= 4 and variant.startswith(other))
        for other in haystack
        for variant in variants
    )


def _hit_count(needles: list[str], haystack: Set[str]) -> int:
    return sum(1 for needle in needles if _token_covered(needle, haystack))


def _titles_match(choice: str, title: str) -> bool:
    choice_norm = normalize_text(choice)
    title_norm = normalize_text(_NOISE_RE.sub(" ", title))
    if not choice_norm or not title_norm:
        return False
    if choice_norm == title_norm:
        return True
    if title_norm.startswith(choice_norm) and _rest_is_generic(title_norm[len(choice_norm) :]):
        return True
    if choice_norm.startswith(title_norm) and _rest_is_generic(choice_norm[len(title_norm) :]):
        return True

    choice_tokens = _choice_tokens(choice_norm)
    title_tokens = _choice_tokens(title_norm)
    if not choice_tokens or not title_tokens:
        return False

    choice_hits = _hit_count(choice_tokens, _expand_tokens(title_tokens))
    title_hits = _hit_count(title_tokens, _expand_tokens(choice_tokens))
    if choice_hits == len(choice_tokens) and title_hits == len(title_tokens):
        return True
    # Truncated schedule cells (SRE, long parentheticals): every title token
    # must hit, and most of the choice still has to be present.
    needed = max(2, int(0.7 * len(choice_tokens) + 0.999))
    return title_hits == len(title_tokens) and choice_hits >= needed


def find_elective_match(choice: str, available_lessons: List[Lesson]) -> List[Lesson]:
    """Find scheduled lessons matching the user's choice string."""
    if not choice:
        return []

    instructor_match = re.search(r"[–-]\s*([А-ЯЁ][а-яё]+)\s+[А-ЯЁ]\.", choice)
    instructor_surname = instructor_match.group(1).lower() if instructor_match else ""

    matches = []
    for lesson in available_lessons:
        titles = _primary_titles(lesson.subject)
        if not titles:
            continue
        if not any(_titles_match(choice, title) for title in titles):
            continue
        if instructor_surname:
            lesson_text = normalize_text(f"{lesson.subject} {lesson.instructor}")
            if instructor_surname not in lesson_text.split():
                continue
        matches.append(lesson)
    return matches


def is_elective_lesson(lesson: Lesson) -> bool:
    text = f"{lesson.subject} {lesson.instructor} {lesson.notes}".lower()
    return "по выбору" in text or "практика лаборато" in text


def collect_elective_pool(
    schedule: dict[str, list[Lesson]],
    prefix: str = "11-3",
    group_re: re.Pattern[str] | str | None = _YEAR_GROUP_RE,
) -> list[Lesson]:
    pool: list[Lesson] = []
    matcher = re.compile(group_re) if isinstance(group_re, str) else group_re
    for gid, lessons in schedule.items():
        gid_s = str(gid)
        if matcher is not None:
            if not matcher.match(gid_s):
                continue
        elif not gid_s.startswith(prefix):
            continue
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


def unmatched_choices(
    students: List[StudentChoice], elective_pool: list[Lesson]
) -> dict[str, int]:
    """Map choice strings that hit no scheduled lesson to how often they appear."""
    counts: dict[str, int] = {}
    for student in students:
        for choice in student.electives:
            if find_elective_match(choice, elective_pool):
                continue
            counts[choice] = counts.get(choice, 0) + 1
    return counts
