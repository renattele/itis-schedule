"""Webinar URLs must not replace an in-person room in the iCal location."""

from datetime import date

from src.generator import generate_ical
from src.main import _groups_from_spec, apply_online_links
from src.parser import Lesson, _detect_lesson_weeks, _is_usable_subject, _parse_cell_text


def _lesson(**kwargs) -> Lesson:
    defaults = dict(
        day=2,
        time_start="17:30",
        time_end="19:00",
        subject="Функциональное программирование (Blockchain)",
        instructor="Хайруллин А.Ф.",
        room="1304",
        notes="",
        link="",
        type="Прак",
    )
    defaults.update(kwargs)
    return Lesson(**defaults)


def _field(ics: bytes, name: str) -> str:
    from icalendar import Calendar

    event = Calendar.from_ical(ics).walk("VEVENT")[0]
    value = event.get(name)
    return str(value) if value else ""


def test_ical_keeps_room_when_link_present():
    ics = generate_ical(
        "11-303",
        [_lesson(link="https://telemost.example/wrong")],
        date(2026, 9, 1),
        date(2026, 9, 9),
    )
    assert _field(ics, "location") == "1304"
    assert "https://telemost.example/wrong" in _field(ics, "url")


def test_ical_webinar_without_room_uses_link_as_location():
    url = "https://telemost.yandex.ru/j/17069658637666"
    ics = generate_ical(
        "11-303",
        [_lesson(subject="Психология управления", instructor="Пучкова И.М.", room="", link=url)],
        date(2026, 9, 1),
        date(2026, 9, 10),
    )
    assert url in _field(ics, "location")
    assert url in _field(ics, "url")


def test_apply_online_links_overwrites_shared_cell_hyperlink():
    lesson = _lesson(
        subject="Психология управления (1-9 нед.)",
        instructor="Пучкова И.М.",
        room="",
        link="https://telemost.360.yandex.ru/j/1996926600",
    )
    schedule = {"11-303": [lesson]}
    rows = [
        {
            "subject": "Психология управления, лек.",
            "instructor": "Пучкова И.М.",
            "surname": "пучкова",
            "groups": {"11-303"},
            "url": "https://telemost.yandex.ru/j/17069658637666",
        }
    ]
    applied = apply_online_links(schedule, rows)
    assert applied == 1
    assert schedule["11-303"][0].link == "https://telemost.yandex.ru/j/17069658637666"
    assert schedule["11-303"][0].room == ""


def test_apply_online_links_requires_all_subject_tokens():
    lesson = _lesson(
        subject="Психология личной эффективности",
        instructor="Зайнуллин А.Э.",
        room="",
        link="",
    )
    schedule = {"11-303": [lesson]}
    apply_online_links(
        schedule,
        [
            {
                "subject": "Психология управления, прак.",
                "surname": "зайнуллин",
                "groups": {"11-303"},
                "url": "https://example.com/management",
            }
        ],
    )
    assert schedule["11-303"][0].link == ""


def test_unparsed_group_spec_does_not_match_every_group():
    lesson = _lesson(
        subject="Психология управления",
        instructor="Пучкова И.М.",
        room="",
        link="",
    )
    schedule = {"11-303": [lesson]}
    apply_online_links(
        schedule,
        [
            {
                "subject": "Психология управления, лек.",
                "surname": "пучкова",
                "groups": set(),
                "restrict_groups": True,
                "url": "https://example.com/wrong-group",
            }
        ],
    )
    assert schedule["11-303"][0].link == ""


def test_empty_group_spec_still_matches_by_subject():
    lesson = _lesson(
        subject="Психология управления",
        instructor="Пучкова И.М.",
        room="",
        link="",
    )
    schedule = {"11-303": [lesson]}
    apply_online_links(
        schedule,
        [
            {
                "subject": "Психология управления, лек.",
                "surname": "пучкова",
                "groups": set(),
                "restrict_groups": False,
                "url": "https://example.com/any-group",
            }
        ],
    )
    assert schedule["11-303"][0].link == "https://example.com/any-group"


def test_group_spec_typos_and_ranges():
    assert "11.1-621" in _groups_from_spec("11.1.-621")
    assert "11.1-531" in _groups_from_spec("11.-1.-531")
    assert {"11-301", "11-302", "11-303"} <= _groups_from_spec("11-301-11-308")
    assert _groups_from_spec("not-a-group") == set()


def test_webinar_marker_line_does_not_count_as_extra_lesson():
    parsed = _parse_cell_text(
        "Дисциплина по выбору:\n"
        "Введение в облачные технологии, Валиуллин Р.М. (вебинары) в 1311\n"
        "(вебинары)"
    )
    usable = [
        item
        for item in parsed
        if _is_usable_subject(item[0].strip().rstrip(":").strip())
    ]
    assert not _is_usable_subject("(вебинары)")
    assert len(usable) == 1
    assert "облачные" in usable[0][0].lower()


def test_multi_elective_cell_stays_multi_after_junk_filter():
    parsed = _parse_cell_text(
        "Дисциплины по выбору:\n"
        "Проектный практикум по робототехнике. Ч1., Апурин А.А. (вебинары)\n"
        "Функциональное программирование (Blockchain), Хайруллин А.Ф. в 1304\n"
        "(вебинары)"
    )
    usable = [
        item
        for item in parsed
        if _is_usable_subject(item[0].strip().rstrip(":").strip())
    ]
    assert len(usable) == 2


def test_humanitarian_line_splits_shared_lecture_and_group1_practice():
    parsed = _parse_cell_text(
        "Дисциплина по выбору:\n"
        "Психология управления (1-9 нед.) Пучкова И.М. (вебинары), "
        "с 10 нед. прак. гр.№1 Зайнуллин А.Э. (вебинары)"
    )
    assert len(parsed) == 2
    assert parsed[0][1] == "Пучкова И.М."
    assert "гр.№1" not in parsed[0][0]
    assert parsed[1][1] == "Зайнуллин А.Э."
    assert "гр.№1" in parsed[1][0]
    assert _detect_lesson_weeks(parsed[0][0], parsed[0][1], parsed[0][3]) == "1-9"
    assert _detect_lesson_weeks(parsed[1][0], parsed[1][1], parsed[1][3]) == "10-18"


def test_humanitarian_line_splits_groups_2_and_3():
    parsed = _parse_cell_text(
        "Дисциплина по выбору:\n"
        "Психология управления, прак. (1-9нед.) гр.№2 Зайнуллин А.Э. , "
        "с 10 нед.прак.гр.№3  (вебинары)"
    )
    assert len(parsed) == 2
    assert "гр.№2" in parsed[0][0]
    assert "гр.№3" in parsed[1][0]
    assert parsed[0][1] == "Зайнуллин А.Э."
    assert parsed[1][1] == "Зайнуллин А.Э."
    assert _detect_lesson_weeks(parsed[0][0], parsed[0][1], parsed[0][3]) == "1-9"
    assert _detect_lesson_weeks(parsed[1][0], parsed[1][1], parsed[1][3]) == "10-18"
    assert parsed[1][0].lower().count("с 10 нед") == 1


def test_humanitarian_line_splits_groups_4_and_5():
    parsed = _parse_cell_text(
        "Дисциплины по выбору:\n"
        "Психология управления, Зайнуллин А.Э. 1-9 нед. гр.№4, с 10 нед. гр.№5 (вебинары)"
    )
    assert len(parsed) == 2
    assert "гр.№4" in parsed[0][0]
    assert "гр.№5" in parsed[1][0]
    assert parsed[0][1] == parsed[1][1] == "Зайнуллин А.Э."
    assert _detect_lesson_weeks(parsed[0][0], parsed[0][1], parsed[0][3]) == "1-9"
    assert _detect_lesson_weeks(parsed[1][0], parsed[1][1], parsed[1][3]) == "10-18"
    assert parsed[1][0].lower().count("с 10 нед") == 1


def test_psychology_splits_group2_group3_and_lecture_practice():
    parsed = _parse_cell_text(
        "Дисциплины по выбору:\n"
        "Психология гр.№2 с 1 по 9 нед.прак, гр.№3 с 10 нед.прак. Румянцева Г.Д. (вебинары)\n"
        "Психология лек.9 нед. Устин П.Н. в 1408 с 10 нед.прак. гр.№1 Румянцева Г.Д. (вебинары)"
    )
    assert any("гр.№2" in s for s, _i, _r, _n in parsed)
    assert any("гр.№3" in s for s, _i, _r, _n in parsed)
    assert any("гр.№1" in s and i == "Румянцева Г.Д." for s, i, _r, _n in parsed)
    assert any(i == "Устин П.Н." for _s, i, _r, _n in parsed)
    weeks = {_detect_lesson_weeks(s, i, n) for s, i, _r, n in parsed}
    assert "1-9" in weeks
    assert "10-18" in weeks


def test_personal_efficiency_splits_lecture_and_group1_practice():
    parsed = _parse_cell_text(
        "Дисциплины по выбору:\n"
        "Психология личной эффективности, лек.9 нед., группа №1 прак. с 10 нед."
        "Добротворская С.Г. в 1405"
    )
    assert len(parsed) == 2
    assert "группа №1" not in parsed[0][0]
    assert "группа №1" in parsed[1][0]
    assert parsed[1][1] == "Добротворская С.Г."
    assert parsed[1][2] == "1405"
    assert _detect_lesson_weeks(parsed[0][0], parsed[0][1], parsed[0][3]) == "1-9"
    assert _detect_lesson_weeks(parsed[1][0], parsed[1][1], parsed[1][3]) == "10-18"


def test_design_thinking_keeps_single_subgroup_on_one_lesson():
    parsed = _parse_cell_text(
        "Дисциплины по выбору:\n"
        "Разработка технической документации (Дизайн-мышление в ИТ-сфере), "
        "группа №1 , Лучкина Е.Ю. в 1110 (10.09 не будет)"
    )
    assert len(parsed) == 1
    subject, instructor, room, _notes = parsed[0]
    assert instructor == "Лучкина Е.Ю."
    assert room == "1110"
    assert "группа №1" in subject
    assert "Дизайн-мышление" in subject
