"""CLI entry-point: fetch → parse → generate .ics files."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from datetime import date

from .electives import DEFAULT_CHOICES_SPREADSHEET_ID
from .fetcher import fetch_csv, fetch_schedule
from .generator import generate_ical
from .parser import parse_schedule

DEFAULT_SPREADSHEET_ID = "12m_Ze1NOnVvdVuSDY5bj0v4r24xLY5RhtuBxNjS26yQ"
DEFAULT_GID = "0"
DEFAULT_LINKS_GID = "333472429"
DEFAULT_OUTPUT_DIR = "./calendars"
DEFAULT_SEMESTER_START = "2026-09-01"
DEFAULT_SEMESTER_END = "2026-12-31"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Generate iCal files from KFU ITIS schedule."
    )
    parser.add_argument(
        "--spreadsheet-id",
        default=DEFAULT_SPREADSHEET_ID,
        help="Google Sheets document ID (default: %(default)s)",
    )
    parser.add_argument(
        "--gid",
        default=DEFAULT_GID,
        help="Sheet tab ID (default: %(default)s)",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for generated .ics files (default: %(default)s)",
    )
    parser.add_argument(
        "--semester-start",
        default=DEFAULT_SEMESTER_START,
        help="Semester start date YYYY-MM-DD (default: %(default)s)",
    )
    parser.add_argument(
        "--semester-end",
        default=DEFAULT_SEMESTER_END,
        help="Semester end date YYYY-MM-DD (default: %(default)s)",
    )
    parser.add_argument(
        "--split-types",
        action="store_true",
        help="Generate separate iCal files for lectures and practices.",
    )
    parser.add_argument(
        "--overrides",
        type=pathlib.Path,
        help="Path to JSON file with event overrides (keys are regexes for subject name).",
    )
    parser.add_argument(
        "--student-choices",
        type=pathlib.Path,
        default=pathlib.Path("student_choices.json"),
        help="Optional JSON overlay of per-student electives (ignored if missing).",
    )
    parser.add_argument(
        "--choices-spreadsheet-id",
        default=DEFAULT_CHOICES_SPREADSHEET_ID,
        help="Google Sheets ID with per-student elective distribution (default: %(default)s).",
    )
    parser.add_argument(
        "--choices-gid",
        action="append",
        dest="choices_gids",
        default=None,
        help="Sheet tab gid to load (repeatable). Default: discover all tabs.",
    )
    args = parser.parse_args(argv)

    semester_start_date = date.fromisoformat(args.semester_start)
    semester_end_date = date.fromisoformat(args.semester_end)

    # 1. Fetch
    print(f"📥 Fetching schedule (sheet {args.spreadsheet_id}, gid={args.gid})…")
    xlsx_bytes = fetch_schedule(args.spreadsheet_id, args.gid)
    print(f"   Downloaded {len(xlsx_bytes)} bytes")

    # 2. Parse
    print("🔍 Parsing schedule…")
    schedule = parse_schedule(xlsx_bytes)

    # 2b. Attach webinar links from the companion tab when the cell has none.
    print(f"🔗 Fetching online-class links (gid={DEFAULT_LINKS_GID})…")
    try:
        links = load_online_links(args.spreadsheet_id, DEFAULT_LINKS_GID)
        applied = apply_online_links(schedule, links)
        print(f"   Attached {applied} links from {len(links)} rows")
    except Exception as e:
        print(f"   ⚠️ Failed to apply online links: {e}")

    schedule_without_overrides = {gid: list(lessons) for gid, lessons in schedule.items()}
    
    # 3. Apply overrides
    if args.overrides:
        print(f"🛠️ Applying overrides from {args.overrides}…")
        overrides = load_overrides(args.overrides)
        apply_overrides(schedule, overrides)

    total_lessons = sum(len(v) for v in schedule.values())
    print(f"   Found {len(schedule)} groups, {total_lessons} total lessons")

    def save_ical_safe(title: str, lessons: list, output_path: pathlib.Path, include_type: bool = True):
        if not lessons:
            return
        ical_bytes = generate_ical(title, lessons, semester_start_date, semester_end_date, include_type=include_type)
        with open(output_path, "wb") as f:
            f.write(ical_bytes)

    def process_calendar_set(name: str, lessons: list, base_dir: pathlib.Path):
        unified_dir = base_dir / "unified"
        unified_dir.mkdir(parents=True, exist_ok=True)
        save_ical_safe(f"ITIS {name}", lessons, unified_dir / f"{safe_filename(name)}.ics")

        lectures_dir = base_dir / "lectures"
        practices_dir = base_dir / "practices"
        lectures_dir.mkdir(parents=True, exist_ok=True)
        practices_dir.mkdir(parents=True, exist_ok=True)

        if args.split_types:
            lectures = [l for l in lessons if l.type == "Лекц"]
            practices = [l for l in lessons if l.type == "Прак"]

            if lectures:
                save_ical_safe("ITIS Лекции", lectures, lectures_dir / f"{safe_filename(name)}.ics", include_type=False)

            if practices:
                save_ical_safe("ITIS Практики", practices, practices_dir / f"{safe_filename(name)}.ics", include_type=False)

    # 3. Generate group calendars
    output_dir = pathlib.Path(args.output_dir)
    groups_dir = output_dir / "groups"
    students_root_dir = output_dir / "students"
    groups_dir.mkdir(parents=True, exist_ok=True)
    students_root_dir.mkdir(parents=True, exist_ok=True)
    
    print("📅 Generating group calendars…")
    for group, lessons in schedule.items():
        process_calendar_set(group, lessons, groups_dir)
        print(f"   ✅ {group} processed")

    groups_without_overrides_dir = groups_dir / "without_overrides"
    print("📅 Generating group calendars (without overrides)…")
    for group, lessons in schedule_without_overrides.items():
        process_calendar_set(group, lessons, groups_without_overrides_dir)
        print(f"   ✅ {group} processed (without overrides)")

    # 4. Generate student calendars
    print(f"🔍 Fetching student choices from {args.choices_spreadsheet_id}…")
    try:
        from src.electives import (
            collect_elective_pool,
            fetch_choices,
            load_local_choices,
            merge_local_choices,
            personal_lessons,
            unmatched_choices,
        )

        choices = fetch_choices(
            args.choices_spreadsheet_id, gids=args.choices_gids
        )
        overlay = load_local_choices(args.student_choices)
        if overlay:
            choices = merge_local_choices(choices, overlay)
            print(f"   Applied local elective overrides from {args.student_choices}")
        print(f"   Found {len(choices)} student choices")

        overrides_map = load_overrides(args.overrides) if args.overrides else {}

        def generate_student_calendars(
            schedule_source: dict, out_dir: pathlib.Path, with_overrides: bool = False
        ) -> int:
            elective_pool = collect_elective_pool(schedule_source)

            generated_students = 0
            out_dir.mkdir(parents=True, exist_ok=True)
            for student in choices:
                all_base = schedule_source.get(student.group, [])
                if not all_base:
                    continue

                lessons = personal_lessons(all_base, elective_pool, student.electives)
                if with_overrides and overrides_map:
                    lessons = override_lessons(lessons, overrides_map)
                safe_name = "".join(
                    c for c in student.name if c.isalnum() or c in (" ", "-", "_")
                ).strip()
                full_name = f"{student.group}_{safe_name}"
                process_calendar_set(full_name, lessons, out_dir)
                generated_students += 1

            return generated_students

        # Match electives against original subject names, then optionally rename.
        unmatched = unmatched_choices(
            choices, collect_elective_pool(schedule_without_overrides)
        )
        if unmatched:
            print(f"   ⚠️ Unmatched elective titles ({len(unmatched)}):")
            for title, count in sorted(unmatched.items(), key=lambda kv: (-kv[1], kv[0])):
                print(f"      {count}× {title}")

        students_dir = students_root_dir
        generated_students = generate_student_calendars(
            schedule_without_overrides, students_dir, with_overrides=True
        )
        print(f"   🎉 Processed {generated_students} student calendars in {students_dir}")

        students_without_overrides_dir = students_root_dir / "without_overrides"
        generated_students_wo = generate_student_calendars(
            schedule_without_overrides, students_without_overrides_dir, with_overrides=False
        )
        print(f"   🎉 Processed {generated_students_wo} student calendars in {students_without_overrides_dir}")

    except Exception as e:
        print(f"   ❌ Failed to process student choices: {e}")


def safe_filename(name: str) -> str:
    """Turn a group/student label into a filesystem-safe .ics stem."""
    cleaned = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE).strip("._")
    return cleaned or "calendar"


_GROUP_TOKEN_RE = re.compile(r"11(?:\.\d)?-\d{3}[аa]?", re.IGNORECASE)
_SUBJECT_SKIP_TOKENS = {
    "дисциплина",
    "дисциплины",
    "выбор",
    "лекция",
    "практика",
}


def _normalize_group_spec(spec: str) -> str:
    """Fix spreadsheet typos like '11.1.-621' or '11.-1.-531'."""
    compact = spec.replace(" ", "")
    compact = re.sub(r"(11)\.-(\d)\.-(\d{3})", r"\1.\2-\3", compact)
    return compact.replace(".-", "-")


def _groups_from_spec(spec: str) -> set[str]:
    """Expand a links-tab group cell like '11-301-11-308' or '11-521, 11-522'."""
    groups: set[str] = set()
    compact = _normalize_group_spec(spec)
    for start_s, end_s in re.findall(
        rf"({_GROUP_TOKEN_RE.pattern})-({_GROUP_TOKEN_RE.pattern})",
        compact,
        flags=re.IGNORECASE,
    ):
        try:
            prefix_start, num_start = start_s.rsplit("-", 1)
            prefix_end, num_end = end_s.rsplit("-", 1)
            if prefix_start.casefold() == prefix_end.casefold():
                for n in range(int(num_start), int(num_end) + 1):
                    groups.add(f"{prefix_start}-{n}")
        except ValueError:
            pass
    for token in _GROUP_TOKEN_RE.findall(compact):
        groups.add(token)
    return groups


def _subject_tokens(text: str) -> list[str]:
    return [
        t
        for t in re.findall(r"[а-яёa-z0-9]{4,}", text.casefold())
        if t not in _SUBJECT_SKIP_TOKENS
    ]


def _row_matches_lesson(row: dict, gid: str, haystack: str) -> bool:
    """True when a links-tab row is the same course + instructor for this group."""
    restrict_groups = row.get("restrict_groups", bool(row.get("groups")))
    if restrict_groups and gid not in (row.get("groups") or set()):
        return False
    if row.get("surname") and row["surname"] not in haystack:
        return False
    tokens = _subject_tokens(row.get("subject") or "")
    if tokens:
        return all(t in haystack for t in tokens)
    return bool(row.get("surname"))


def load_online_links(spreadsheet_id: str, gid: str) -> list[dict]:
    """Parse the 'Ссылки на онлайн-занятия' tab into matchable rows."""
    import csv
    import io

    content = fetch_csv(spreadsheet_id, gid)
    rows = []
    reader = csv.reader(io.StringIO(content))
    for raw in reader:
        if len(raw) < 5:
            continue
        subject, instructor, group_spec, url = (
            raw[1].strip(),
            raw[2].strip(),
            raw[3].strip(),
            raw[4].strip(),
        )
        if not url.startswith("http") or not subject:
            continue
        surname_m = re.search(r"[А-ЯЁ][а-яё]+", instructor)
        rows.append(
            {
                "subject": subject,
                "instructor": instructor,
                "surname": surname_m.group(0).casefold() if surname_m else "",
                "groups": _groups_from_spec(group_spec),
                "restrict_groups": bool(group_spec),
                "url": url,
            }
        )
    return rows


def apply_online_links(schedule: dict, links: list[dict]) -> int:
    """Attach webinar URLs from the companion links tab by instructor + subject.

    Instructor-specific rows win over a shared cell hyperlink (elective cells
    often carry one link for a sibling webinar). Returns how many lessons
    received a URL they did not already have.
    """
    from dataclasses import replace

    applied = 0
    for gid, group_lessons in schedule.items():
        new_lessons = []
        for lesson in group_lessons:
            haystack = f"{lesson.subject} {lesson.instructor}".casefold()
            matched = None
            for row in links:
                if not _row_matches_lesson(row, gid, haystack):
                    continue
                matched = row["url"]
                break
            if matched:
                if lesson.link != matched:
                    applied += 1
                new_lessons.append(replace(lesson, link=matched))
            else:
                new_lessons.append(lesson)
        schedule[gid] = new_lessons
    return applied


def load_overrides(path: pathlib.Path) -> dict:
    """Load overrides from a JSON file."""
    if not path.exists():
        print(f"   ⚠️ Overrides file not found: {path}")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def override_lessons(lessons: list, overrides: dict) -> list:
    """Apply regex-based overrides to a lesson list."""
    compiled_overrides = []
    for pattern, values in overrides.items():
        try:
            compiled_overrides.append((re.compile(pattern, re.IGNORECASE), values))
        except re.error as e:
            print(f"   ⚠️ Invalid regex pattern '{pattern}': {e}")

    from dataclasses import replace

    new_lessons = []
    for lesson in lessons:
        matched = False
        haystack = f"{lesson.subject} {lesson.instructor}"
        for pattern, values in compiled_overrides:
            if pattern.search(haystack):
                new_lessons.append(replace(lesson, **values))
                matched = True
                break
        if not matched:
            new_lessons.append(lesson)
    return new_lessons


def apply_overrides(schedule: dict, overrides: dict) -> None:
    """Apply regex-based overrides to parsed lessons."""
    for gid, group_lessons in schedule.items():
        schedule[gid] = override_lessons(group_lessons, overrides)


if __name__ == "__main__":
    main()
