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
    args = parser.parse_args(argv)

    semester_start = datetime.strptime(args.semester_start, "%Y-%m-%d")
    semester_end = datetime.strptime(args.semester_end, "%Y-%m-%d")

    # 1. Fetch
    print(f"📥 Fetching schedule (sheet {args.spreadsheet_id}, gid={args.gid})…")
    xlsx_bytes = fetch_schedule(args.spreadsheet_id, args.gid)
    print(f"   Downloaded {len(xlsx_bytes)} bytes")

    # 2. Parse
    print("🔍 Parsing schedule…")
    schedule = parse_schedule(xlsx_bytes)
    total_lessons = sum(len(v) for v in schedule.values())
    print(f"   Found {len(schedule)} groups, {total_lessons} total lessons")

    # 3. Generate group calendars
    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Store generated group calendars mapping: group_name -> list[Lesson]
    # We already have `schedule`.

    print("📅 Generating group calendars…")
    semester_start = date.fromisoformat(args.semester_start)
    semester_end = date.fromisoformat(args.semester_end)

    for group, lessons in schedule.items():
        ical_bytes = generate_ical(group, lessons, semester_start, semester_end)
        
        output_path = output_dir / f"{group}.ics"
        with open(output_path, "wb") as f:
            f.write(ical_bytes)
        print(f"   ✅ {output_path}  ({len(lessons) * 17} events approx)") # 17 weeks

    # 4. Generate student calendars (if choices spreadsheet ID is provided or hardcoded)
    # The user provided the ID in the prompt: 1bsaeOl8JQepHnEQggIo9fNzaCNyvFRtTlhqrYGP5YK4
    # We should probably make this an argument, but for now we can hardcode it or add arg.
    # Let's add arg support in a separate step or just hardcode for this task.
    # User asked to "generate schedule for each one", implying we should just do it.
    
    CHOICES_SHEET_ID = "1bsaeOl8JQepHnEQggIo9fNzaCNyvFRtTlhqrYGP5YK4"
    print(f"🔍 Fetching student choices from {CHOICES_SHEET_ID}…")
    try:
        from src.electives import fetch_choices, find_elective_match
        
        choices = fetch_choices(CHOICES_SHEET_ID)
        print(f"   Found {len(choices)} student choices")
        
        # Build a pool of ALL unique 3rd year electives to search against
        # We only put marked "electives" in the pool to avoid accidental matches with mandatory classes
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
        
        # Deduplicate pool
        elective_pool = list(set(elective_pool_all))
        
        generated_students = 0
        students_dir = output_dir / "students"
        students_dir.mkdir(exist_ok=True)

        for student in choices:
            # 1. Base schedule from their group - separate mandatory from elective slots
            all_base = schedule.get(student.group, [])
            if not all_base:
                print(f"   ⚠️  Group {student.group} not found for student {student.name}")
                continue
            
            # Filter out generic elective placeholders
            personal_lessons_set = set()
            for l in all_base:
                if not is_elective_lesson(l):
                    personal_lessons_set.add(l)
            
            # 2. Match their electives from the across-group pool
            # Tech block
            found_tech = find_elective_match(student.tech_block, elective_pool)
            for m in found_tech:
                personal_lessons_set.add(m)
            
            # Sci block
            found_sci = find_elective_match(student.sci_block, elective_pool)
            for m in found_sci:
                personal_lessons_set.add(m)
                
            # Convert back to list for iCal generator
            personal_lessons = list(personal_lessons_set)
            
            # Generate
            # Sanitize filename
            safe_name = "".join(c for c in student.name if c.isalnum() or c in (" ", "-", "_")).strip()
            ical_bytes = generate_ical(f"Schedule for {student.name}", personal_lessons, semester_start, semester_end)
            
            st_path = students_dir / f"{student.group}_{safe_name}.ics"
            with open(st_path, "wb") as f:
                f.write(ical_bytes)
            generated_students += 1
            
        print(f"   🎉 Generated {generated_students} student calendars in {students_dir}")

    except Exception as e:
        print(f"   ❌ Failed to process student choices: {e}")


if __name__ == "__main__":
    main()
