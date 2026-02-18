"""Parse the schedule XLSX into per-group lesson lists."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

import openpyxl

# Maps Cyrillic day-of-week markers found in the spreadsheet to Python
# weekday indices (0 = Monday … 6 = Sunday).
DAY_MARKERS: dict[str, int] = {
    "ПОНЕДЕЛЬНИК": 0,
    "ВТОРНИК": 1,
    "СРЕДА": 2,
    "ЧЕТВЕРГ": 3,
    "ПЯТНИЦА": 4,
    "СУББОТА": 5,
    "ВОСКРЕСЕНЬЕ": 6,
}

# Regex that matches a day-of-week row (column A contains the day name
# surrounded by asterisks and spaces).
_DAY_RE = re.compile(
    r"\*\s*(" + "|".join(
        r"\s*".join(ch for ch in day)
        for day in DAY_MARKERS
    ) + r")\s*",
    re.IGNORECASE,
)

# Time slot pattern like "08.30-10.00" or "08:30-10:00".
_TIME_RE = re.compile(r"(\d{2})[.:](\d{2})\s*-\s*(\d{2})[.:](\d{2})")


@dataclass(frozen=True)
class Lesson:
    """A single lesson entry."""

    day: int  # 0=Monday … 6=Sunday
    time_start: str  # "HH:MM"
    time_end: str  # "HH:MM"
    subject: str
    instructor: str
    room: str
    notes: str = ""
    link: str = ""
    type: str = ""  # "Лекция", "Практика", "Лаб. работа" or empty
    weeks: str = "all"  # "all", "even", "odd"


def _normalize_day(text: str) -> str:
    """Remove extra spaces between characters in day-of-week markers."""
    return re.sub(r"\s+", "", text).upper()


def _parse_cell_text(raw: str) -> list[tuple[str, str, str, str]]:
    """Extract subject, instructor, room, and extra notes from a cell string.

    The cells typically look like:
        Математический анализ,
        Зубкова С.К.
        1306

    or multi-line electives:
        Дисциплины по выбору:
        Subject 1, Instructor 1 in 1306
        Subject 2, Instructor 2 (вебинар)
    """
    if not raw or not raw.strip():
        return []

    lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    if not lines:
        return []

    # Heuristic: If first line contains "Дисциплины по выбору", skip it and parse rest as individual items
    if "дисциплины по выбору" in lines[0].lower():
        entries = []
        for line in lines[1:]:
            # Append "(по выбору)" to help _detect_lesson_type
            split_res = _split_single_line_lesson(line)
            for s, i, r, n in split_res:
                entries.append((s, i, r, (n + " (по выбору)").strip()))
        return entries

    # Standard case: could still be one or multiple lessons
    # If the cell has commas or looks like a list, try splitting
    # for now, let's try to parse the block as one lesson first, 
    # but improve the extraction logic.
    if len(lines) == 1:
        return _split_single_line_lesson(lines[0])
    
    return [_parse_lesson_block(lines)]


def _split_single_line_lesson(line: str) -> list[tuple[str, str, str, str]]:
    """Split a single line that might contain subject, instructor, and room."""
    # Example: "Технологии разработки ПО (Android), Зарипова Д.И. (вебинары)"
    # Example: "Проектирование веб-интерфейсов, Якушенкова А.Д. в 1305"
    
    # Try to find instructor pattern: Surname I.O.
    instr_pattern = r"([А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.[А-ЯЁ]?\.?)"
    instr_m = re.search(instr_pattern, line)
    
    subject = line
    instructor = ""
    room = ""
    notes = ""
    
    if instr_m:
        instructor = instr_m.group(1).strip()
        subject = line[:instr_m.start()].strip().rstrip(",")
        remainder = line[instr_m.end():].strip().lstrip(",").strip()
        
        # Room extraction from remainder
        # Look for " в 1305" or just "1305"
        room_m = re.search(r"(?:\bв\s+)?\b(\d{3,4}(?:-\d{3,4})?)\b", remainder)
        if room_m:
            room = room_m.group(1)
            # Remove the whole match (including "в ") from notes
            notes = (remainder[:room_m.start()] + remainder[room_m.end():]).strip()
        else:
            notes = remainder
    else:
        # If no instructor, maybe just subject and room/notes
        room_m = re.search(r"(?:\bв\s+)?\b(\d{3,4}(?:-\d{3,4})?)\b", line)
        if room_m:
            room = room_m.group(1)
            subject = line[:room_m.start()].strip().rstrip(",")
            notes = line[room_m.end():].strip()
            
    return [(subject.strip(), instructor.strip(), room.strip(), notes.strip())]


def _parse_lesson_block(lines: list[str]) -> tuple[str, str, str, str]:
    """Existing logic for multi-line lesson block moved to helper."""
    subject = lines[0].rstrip(",").strip()
    instructor = ""
    room = ""
    notes_parts: list[str] = []

    for line in lines[1:]:
        clean = line.rstrip(",").strip()
        if not clean:
            continue
        # Room numbers
        if re.match(r"^\d{3,4}(-\d{3,4})?$", clean):
            room = clean
        # Instructor names
        elif re.search(r"[А-ЯЁа-яё]{2,}\s+[А-ЯЁ]\.[А-ЯЁ]?\.", clean):
            instr_match = re.match(
                r"(.*?[А-ЯЁа-яё]+\s+[А-ЯЁ]\.[А-ЯЁ]?\.?)(.*)", clean
            )
            if instr_match:
                instructor = instr_match.group(1).strip()
                remainder = instr_match.group(2).strip()
                if remainder:
                    room_m = re.search(r"\b(\d{3,4}(?:-\d{3,4})?)\b", remainder)
                    if room_m:
                        room = room_m.group(1)
                    notes_parts.append(remainder)
            else:
                instructor = clean
        elif any(k in clean.lower() for k in ["(", "нед.", "вебинар", "цор", "подгр", "онлайн", " в "]):
            room_m = re.search(r"\b(\d{3,4}(?:-\d{3,4})?)\b", clean)
            if room_m:
                room = room_m.group(1)
            notes_parts.append(clean)
        else:
            room_m = re.search(r"\b(\d{3,4}(?:-\d{3,4})?)\b", clean)
            if room_m and not instructor:
                instructor = clean
                room = room_m.group(1)
            elif room_m:
                room = room_m.group(1)
                notes_parts.append(clean)
            else:
                notes_parts.append(clean)

    notes = "; ".join(notes_parts) if notes_parts else ""
    return (subject, instructor, room, notes)


def _detect_lesson_type(subject: str, instructor: str, notes: str, is_shared: bool = True) -> str:
    """Heuristic to detect lesson type from text fields."""
    text = f"{subject} {instructor} {notes}".lower()

    if any(k in text for k in ["лекци", " лек.", " лек ", "(лек."]):
        return "Лекц"
    if any(k in text for k in ["практик", " пр.", " пр ", "(пр.", "выбору"]):
        return "Прак"

    # Fallback based on sharing:
    # Shared sessions (cross-group) are usually lectures.
    # Non-shared sessions (per-group) are usually practices.
    if is_shared:
        return "Лекц"
    else:
        return "Прак"


def _detect_lesson_weeks(subject: str, instructor: str, notes: str) -> str:
    """Heuristic to detect even/odd week parity."""
    text = f"{subject} {instructor} {notes}".lower()

    if any(k in text for k in ["нечетн", "нечет", "неч."]):
        return "odd"
    if any(k in text for k in ["четн", "чет.", "чет "]):
        return "even"

    return "all"


def parse_schedule(xlsx_bytes: bytes) -> dict[str, list[Lesson]]:
    """Parse the full schedule XLSX into a mapping of group_id → [Lesson].

    Args:
        xlsx_bytes: Raw XLSX bytes exported from Google Sheets.

    Returns:
        Dictionary mapping group identifiers (e.g. "11-501") to their
        list of Lesson objects.
    """
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    ws = wb.active

    # 1. Expand merged cells so every cell in a merge range has the value
    #    and hyperlink of the top-left cell.
    #    We build a dense in-memory grid: grid[row_idx][col_idx] = (str_value, link)
    #    using 0-based indexing for compatibility with previous logic.
    rows_data: list[list[tuple[str, str]]] = []
    # Determine max row/col
    max_row = ws.max_row
    max_col = ws.max_column

    # Pre-fill grid with empty strings
    # Note: openpyxl rows/cols are 1-based, list is 0-based.
    # ws.cell(r, c) -> grid[r-1][c-1]
    for r in range(1, max_row + 1):
        row_vals = []
        for c in range(1, max_col + 1):
            cell = ws.cell(r, c)
            val = str(cell.value) if cell.value is not None else ""
            link = ""
            if cell.hyperlink and cell.hyperlink.target:
                link = cell.hyperlink.target
            row_vals.append((val, link))
        rows_data.append(row_vals)

    # Apply merges
    for merge_range in ws.merged_cells.ranges:
        # merge_range boundaries are inclusive and 1-based
        min_col, min_row, max_col_rng, max_row_rng = (
            merge_range.min_col,
            merge_range.min_row,
            merge_range.max_col,
            merge_range.max_row,
        )
        
        # Get top-left value
        # 0-based indices
        tl_val = rows_data[min_row - 1][min_col - 1]
        
        # Fill the range
        for r in range(min_row - 1, max_row_rng):
            for c in range(min_col - 1, max_col_rng):
                rows_data[r][c] = tl_val

    # 2. Existing parsing logic using the dense grid
    if len(rows_data) < 3:
        raise ValueError("XLSX has too few rows to contain a schedule")

    # --- Extract group IDs from row index 1 (0-based) -----------------
    group_row = rows_data[1]
    groups: dict[int, str] = {}
    for col_idx in range(2, len(group_row)):
        # group_row contains (value, link) tuples now
        gid = group_row[col_idx][0].strip()
        if gid:
            groups[col_idx] = gid

    # --- Walk through data rows, tracking current day ------------------
    schedule: dict[str, list[Lesson]] = {gid: [] for gid in groups.values()}
    current_day: int | None = None

    for row in rows_data[2:]:
        if not row:
            continue

        # Check if column A contains a day-of-week marker.
        # row[0] is (val, link)
        col_a_val = row[0][0] if len(row) > 0 else ""
        day_match = _DAY_RE.search(col_a_val)
        if day_match:
            matched_text = _normalize_day(day_match.group(1))
            for day_name, day_idx in DAY_MARKERS.items():
                if matched_text == day_name:
                    current_day = day_idx
                    break

        if current_day is None:
            continue

        # Check if column B contains a time slot.
        col_b_val = row[1][0] if len(row) > 1 else ""
        time_match = _TIME_RE.search(col_b_val)
        if not time_match:
            continue

        time_start = f"{time_match.group(1)}:{time_match.group(2)}"
        time_end = f"{time_match.group(3)}:{time_match.group(4)}"

        # Parse each group column.
        for col_idx, gid in groups.items():
            if col_idx >= len(row):
                continue
            
            cell_val, cell_link = row[col_idx]
            cell_val = cell_val.strip()
            
            if not cell_val:
                continue

            # Check if this cell's content is shared with ANY other group in this row
            is_shared = False
            for other_col_idx, other_gid in groups.items():
                if other_col_idx == col_idx:
                    continue
                if other_col_idx < len(row):
                    other_val = row[other_col_idx][0].strip()
                    if other_val == cell_val:
                        is_shared = True
                        break

            results = _parse_cell_text(cell_val)
            for subject, instructor, room, notes in results:
                if not subject:
                    continue

                # Keep notes exactly as in the source calendar cell.
                raw_notes = cell_val
                lesson_type = _detect_lesson_type(subject, instructor, raw_notes, is_shared)
                weeks = _detect_lesson_weeks(subject, instructor, raw_notes)

                schedule[gid].append(
                    Lesson(
                        day=current_day,
                        time_start=time_start,
                        time_end=time_end,
                        subject=subject,
                        instructor=instructor,
                        room=room,
                        notes=raw_notes,
                        link=cell_link,
                        type=lesson_type,
                        weeks=weeks,
                    )
                )

    return schedule
