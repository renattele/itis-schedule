"""generate_ical output must be Google/Apple/Outlook-friendly (no network)."""

from datetime import date

from src.generator import _uid, generate_ical
from src.parser import Lesson


def _lesson(**kwargs) -> Lesson:
    defaults = dict(
        day=2,
        time_start="08:30",
        time_end="10:00",
        subject="Тест",
        instructor="Иванов И.И.",
        room="1304",
        notes="",
        link="",
        type="Прак",
    )
    defaults.update(kwargs)
    return Lesson(**defaults)


def _ical_text(**kwargs) -> str:
    return generate_ical(
        "11-501", [_lesson(**kwargs)], date(2026, 9, 1), date(2026, 12, 31)
    ).decode()


def test_required_fields_present():
    text = _ical_text()
    assert "CALSCALE:GREGORIAN" in text
    assert "METHOD:PUBLISH" in text
    assert text.count("UID:") == text.count("DTSTAMP:")
    assert "DTSTAMP:" in text
    # Holiday (2026-11-04, Wed) must be excluded via EXDATE with TZID.
    assert "EXDATE;TZID=Europe/Moscow:20261104T083000" in text


def test_until_is_utc():
    text = _ical_text()
    (line,) = [ln for ln in text.splitlines() if ln.startswith("RRULE:")]
    assert line.endswith("Z"), line
    # Same instant as the old floating 23:59 Moscow time (UTC+3).
    assert "UNTIL=20261230T205959Z" in line


def test_uid_stable_without_dtstamp():
    a = _uid("11-501", _lesson())
    b = _uid("11-501", _lesson())
    assert a == b and a.endswith("@itis-schedule")


def test_calname_override_keeps_uids():
    from src.generator import generate_ical as gen

    plain = gen("ITIS 11-501", [_lesson()], date(2026, 9, 1), date(2026, 12, 31)).decode()
    renamed = gen("ITIS 11-501", [_lesson()], date(2026, 9, 1), date(2026, 12, 31), calname="ITIS").decode()
    assert "X-WR-CALNAME:ITIS 11-501" in plain
    assert "X-WR-CALNAME:ITIS\r\n" in renamed
    uids = lambda t: sorted(ln for ln in t.splitlines() if ln.startswith("UID:"))
    assert uids(plain) == uids(renamed)


def _cell_lessons(text: str, group: str = "11-303") -> list[Lesson]:
    """Lessons *group* gets from a one-cell sheet (Monday 12:10-13:40)."""
    import io

    import openpyxl

    from src.parser import parse_schedule

    wb = openpyxl.Workbook()
    ws = wb.active
    ws["C2"] = "11-303"
    ws["D2"] = "11-304"
    ws["A3"] = "* ПОНЕДЕЛЬНИК *"
    ws["B3"] = "12.10-13.40"
    ws["C3"] = text
    ws.merge_cells("C3:D3")
    buf = io.BytesIO()
    wb.save(buf)
    return parse_schedule(buf.getvalue())[group]


def _short(lesson: Lesson) -> tuple:
    return (lesson.subject, lesson.time_start, lesson.room, lesson.skip, lesson.only)


def test_permanent_move_splits_into_before_and_after():
    before, after = _cell_lessons(
        "Технологии искусственного интеллекта, Газизов А.М. 1307\n"
        "с 9 ноября перенос на 17:30 ауд.1310"
    )
    assert (before.time_start, before.room, before.until) == ("12:10", "1307", "11-09")
    assert (after.time_start, after.time_end, after.room, after.start_from) == (
        "17:30", "19:00", "1310", "11-09",
    )
    ics = generate_ical("11-303", [before, after], date(2026, 9, 1), date(2026, 12, 31)).decode()
    assert "DTSTART;TZID=Europe/Moscow:20260907T121000" in ics
    assert "UNTIL=20261102" in ics
    assert "DTSTART;TZID=Europe/Moscow:20261109T173000" in ics


def test_one_off_changes():
    cases = {
        "БД, Зубков М.В. ауд. 109\n9 ноября не будет с переносом на 18 ноября в 17:30 онлайн": [
            ("БД", "12:10", "109", ("11-09",), ()),
            ("БД", "17:30", "онлайн", (), ("11-18",)),
        ],
        "БД, Зубков М.В. 1304\n(7.11 онлайн)": [
            ("БД", "12:10", "1304", ("11-07",), ()),
            ("БД", "12:10", "онлайн", (), ("11-07",)),
        ],
        "БД, Зубков М.В. 1304 (11.11 не будет) https://telemost.360.yandex.ru/j/1": [
            ("БД", "12:10", "1304", ("11-11",), ()),
        ],
        "БД, Зубков М.В. 1304\n21 ноября": [("БД", "12:10", "1304", (), ("11-21",))],
        "БД, Зубков М.В. (16.09, 7.10)": [
            ("БД", "12:10", "", (), ("09-16",)),
            ("БД", "12:10", "", (), ("10-07",)),
        ],
    }
    for text, expected in cases.items():
        assert sorted(_short(x) for x in _cell_lessons(text)) == sorted(expected), text


def test_group_and_glued_blocks():
    text = (
        "ОС, Максютин С.В. 1-9 нед. 1310\n"
        "11-304 ТИК, Салимов Ф.И. 12 ноября в ауд.1509\n\n"
        "Продвинутый Linux, Камалетдинов И.Р. в ауд.1302"
    )
    assert [_short(x) for x in _cell_lessons(text)] == [
        ("ОС", "12:10", "1310", (), ()),
        ("Продвинутый Linux", "12:10", "1302", (), ()),
    ]
    assert ("ТИК", "12:10", "1509", (), ("11-12",)) in [
        _short(x) for x in _cell_lessons(text, "11-304")
    ]
