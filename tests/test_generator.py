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
