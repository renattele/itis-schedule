"""CLI entry-point: fetch → parse → generate .ics files."""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
from datetime import date, datetime

from .fetcher import fetch_schedule
from .generator import generate_ical
from .parser import parse_schedule

DEFAULT_SPREADSHEET_ID = "13CqvyFsOa5Z5LYCfMCz4IyAnuTIcjYqI0ARgt8-5MpQ"
DEFAULT_GID = "0"
DEFAULT_OUTPUT_DIR = "./calendars"
DEFAULT_SEMESTER_START = "2026-02-09"
DEFAULT_SEMESTER_END = "2026-06-06"


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
    total_lessons = sum(len(v) for v in schedule.values())
    print(f"   Found {len(schedule)} groups, {total_lessons} total lessons")

    def save_ical_safe(title: str, lessons: list, output_path: pathlib.Path, include_type: bool = True):
        if not lessons:
            return
        ical_bytes = generate_ical(title, lessons, semester_start_date, semester_end_date, include_type=include_type)
        with open(output_path, "wb") as f:
            f.write(ical_bytes)

    def process_calendar_set(name: str, lessons: list, base_dir: pathlib.Path):
        # 1. Unified
        if args.split_types:
            unified_dir = base_dir / "unified"
            unified_dir.mkdir(exist_ok=True)
            save_ical_safe(f"ITIS {name}", lessons, unified_dir / f"{name}.ics")
            
            # 2. Split
            lectures = [l for l in lessons if l.type == "Лекц"]
            practices = [l for l in lessons if l.type == "Прак"]
            
            if lectures:
                lectures_dir = base_dir / "lectures"
                lectures_dir.mkdir(exist_ok=True)
                save_ical_safe("ITIS Лекции", lectures, lectures_dir / f"{name}.ics", include_type=False)
            
            if practices:
                practices_dir = base_dir / "practices"
                practices_dir.mkdir(exist_ok=True)
                save_ical_safe("ITIS Практики", practices, practices_dir / f"{name}.ics", include_type=False)
        else:
            save_ical_safe(f"ITIS {name}", lessons, base_dir / f"{name}.ics")

    # 3. Generate group calendars
    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("📅 Generating group calendars…")
    for group, lessons in schedule.items():
        process_calendar_set(group, lessons, output_dir)
        print(f"   ✅ {group} processed")

    # 4. Generate student calendars
    CHOICES_SHEET_ID = "1bsaeOl8JQepHnEQggIo9fNzaCNyvFRtTlhqrYGP5YK4"
    print(f"🔍 Fetching student choices from {CHOICES_SHEET_ID}…")
    try:
        from src.electives import fetch_choices, find_elective_match
        
        choices = fetch_choices(CHOICES_SHEET_ID)
        print(f"   Found {len(choices)} student choices")
        
        elective_pool_all = []

        def is_elective_lesson(l):
            subj = l.subject.lower()
            instr = l.instructor.lower()
            notes = l.notes.lower()
            return "по выбору" in subj or "по выбору" in instr or "по выбору" in notes or "практика лаборато" in subj

        for gid, lessons in schedule.items():
            if gid.startswith("11-3"):
                for l in lessons:
                    if is_elective_lesson(l):
                        elective_pool_all.append(l)
        
        elective_pool = list(set(elective_pool_all))
        
        generated_students = 0
        students_dir = output_dir / "students"
        students_dir.mkdir(exist_ok=True)

        for student in choices:
            all_base = schedule.get(student.group, [])
            if not all_base:
                continue
            
            personal_lessons_set = set()
            for l in all_base:
                if not is_elective_lesson(l):
                    personal_lessons_set.add(l)
            
            found_tech = find_elective_match(student.tech_block, elective_pool)
            for m in found_tech:
                personal_lessons_set.add(m)
            
            found_sci = find_elective_match(student.sci_block, elective_pool)
            for m in found_sci:
                personal_lessons_set.add(m)
                
            personal_lessons = list(personal_lessons_set)
            
            safe_name = "".join(c for c in student.name if c.isalnum() or c in (" ", "-", "_")).strip()
            full_name = f"{student.group}_{safe_name}"
            
            process_calendar_set(full_name, personal_lessons, students_dir)
            generated_students += 1
            
        print(f"   🎉 Processed {generated_students} student calendars in {students_dir}")

    except Exception as e:
        print(f"   ❌ Failed to process student choices: {e}")


if __name__ == "__main__":
    main()
