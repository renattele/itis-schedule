"""Generate iCal (.ics) calendars from parsed lessons."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event

from .parser import Lesson

TZ = ZoneInfo("Europe/Moscow")


def _uid(group: str, lesson: Lesson) -> str:
    """Generate a deterministic UID for an event."""
    raw = f"{group}|{lesson.day}|{lesson.time_start}|{lesson.subject}"
    return hashlib.sha1(raw.encode()).hexdigest() + "@itis-schedule"


def _first_weekday(start: date, target_weekday: int) -> date:
    """Find the first date >= *start* that falls on *target_weekday*."""
    days_ahead = (target_weekday - start.weekday()) % 7
    return start + timedelta(days=days_ahead)


def generate_ical(
    group_id: str,
    lessons: list[Lesson],
    semester_start: date,
    semester_end: date,
    include_type: bool = True,
) -> bytes:
    """Create an iCal calendar for one group.

    Each lesson becomes a weekly-recurring VEVENT spanning the semester.

    Args:
        group_id: e.g. "11-501".
        lessons: Parsed lesson list.
        semester_start: First day of the semester.
        semester_end: Last day of the semester.
        include_type: Whether to prepend [Type] to the summary.

    Returns:
        Serialised iCal bytes (UTF-8).
    """
    cal = Calendar()
    cal.add("prodid", "-//ITIS Schedule Generator//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", group_id)
    cal.add("x-wr-timezone", "Europe/Moscow")

    for lesson in lessons:
        h_start, m_start = map(int, lesson.time_start.split(":"))
        h_end, m_end = map(int, lesson.time_end.split(":"))

        first_date = _first_weekday(semester_start, lesson.day)
        
        # Handle even/odd weeks
        interval = 1
        if lesson.weeks != "all":
            interval = 2
            # Calculate week of first_date relative to semester_start
            # Assume week of semester_start is Week 1 (Odd)
            days_diff = (first_date - semester_start).days
            # Start of week of semester_start (Monday)
            sem_monday = semester_start - timedelta(days=semester_start.weekday())
            # Start of week of first_date (Monday)
            first_monday = first_date - timedelta(days=first_date.weekday())
            week_num = ((first_monday - sem_monday).days // 7) + 1
            parity = "odd" if week_num % 2 != 0 else "even"
            
            if lesson.weeks != parity:
                # Move to next week
                first_date += timedelta(days=7)

        if first_date > semester_end:
            continue

        dt_start = datetime.combine(
            first_date, time(h_start, m_start, 0), tzinfo=TZ
        )
        dt_end = datetime.combine(
            first_date, time(h_end, m_end, 0), tzinfo=TZ
        )

        event = Event()
        event.add("uid", _uid(group_id, lesson))
        event.add("dtstart", dt_start)
        event.add("dtend", dt_end)
        summary = lesson.subject
        if include_type and lesson.type:
            summary = f"[{lesson.type}] {summary}"
        
        event.add("summary", summary)

        # Prefer notes as-is from the source calendar.
        desc_parts: list[str] = []
        if lesson.notes:
            desc_parts.append(lesson.notes)
        elif lesson.instructor:
            desc_parts.append(f"Преподаватель: {lesson.instructor}")
        if lesson.link:
            event.add("url", lesson.link)

        if desc_parts:
            event.add("description", "\n".join(desc_parts))

        if lesson.link:
            event.add("location", lesson.link)
        elif lesson.room:
            event.add("location", lesson.room)

        # Recur until semester end.
        rrule = {
            "freq": "weekly",
            "until": datetime.combine(
                semester_end, time(23, 59, 59), tzinfo=TZ
            ),
        }
        if interval > 1:
            rrule["interval"] = interval
            
        event.add("rrule", rrule)

        cal.add_component(event)

    return cal.to_ical()
