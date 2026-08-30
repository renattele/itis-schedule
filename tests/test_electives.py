"""Elective distribution parsing and matching (no live network)."""

from src.electives import (
    StudentChoice,
    collect_elective_pool,
    find_elective_match,
    merge_student_lists,
    parse_choices_csv,
    personal_lessons,
)
from src.parser import Lesson


def _lesson(**kwargs) -> Lesson:
    defaults = dict(
        day=2,
        time_start="17:30",
        time_end="19:00",
        subject="Функциональное программирование (Blockchain)",
        instructor="Хайруллин А.Ф.",
        room="1304",
        notes="Дисциплины по выбору",
        link="",
        type="Прак",
    )
    defaults.update(kwargs)
    return Lesson(**defaults)


MAIN_CSV = """ФИО,Группа,"Блок 1
(7 семестр)","Блок 2
(7 семестр)","Блок 3
(8 семестр)"
Иванов Иван Иванович,11-303,Блокчейн-технологии,Введение в облачные технологии,Основы контент-маркетинга для ИТ-специалистов
Петров Пётр Петрович,11-301,Frontend для начинающих,Анализ данных в нефтегазовой сфере,Robotics
"""

HUM_CSV = """ФИО,Группа,Форма обучения,Гуманитарный блок №1 (осенний семестр),Гуманитарный блок №2 (осенний семестр)
Иванов Иван Иванович,11-303,Бюджет,Психология управления,Психология личной эффективности
Петров Пётр Петрович,11-301,Бюджет,Психология,Культурология
"""


def test_parse_skips_spring_semester_and_identity_columns():
    students = {s.name: s for s in parse_choices_csv(MAIN_CSV)}
    ivan = students["Иванов Иван Иванович"]
    assert ivan.group == "11-303"
    assert ivan.electives == [
        "Блокчейн-технологии",
        "Введение в облачные технологии",
    ]
    assert all("контент-маркетинг" not in e.casefold() for e in ivan.electives)


def test_parse_humanitarian_columns():
    students = parse_choices_csv(HUM_CSV)
    assert students[0].electives == [
        "Психология управления",
        "Психология личной эффективности",
    ]


def test_merge_unions_electives_from_both_tabs():
    merged = merge_student_lists(
        [parse_choices_csv(MAIN_CSV), parse_choices_csv(HUM_CSV)]
    )
    by_name = {s.name: s for s in merged}
    assert by_name["Иванов Иван Иванович"].electives == [
        "Блокчейн-технологии",
        "Введение в облачные технологии",
        "Психология управления",
        "Психология личной эффективности",
    ]


def test_merge_folds_yo_typos_and_short_fio():
    main = [
        StudentChoice("Сикачёв Артём Николаевич", "11-301", ["Erlang"]),
        StudentChoice("Хафизов Булат", "11-303", ["Блокчейн-технологии"]),
        StudentChoice("Валиуллин Ильнар Ильгизович", "11-307", ["Скриптинг, визуализация"]),
    ]
    hum = [
        StudentChoice("Сикачев Артем Николаевич", "11-301", ["Психология"]),
        StudentChoice("Хафизов Булат Наилевич", "11-303", ["Психология управления"]),
        StudentChoice("Валиуллин Ильнар Ильгизовчи", "11-307", ["Культурология"]),
    ]
    merged = {s.name: s for s in merge_student_lists([main, hum])}
    assert set(merged) == {
        "Сикачёв Артём Николаевич",
        "Хафизов Булат Наилевич",
        "Валиуллин Ильнар Ильгизович",
    }
    assert merged["Сикачёв Артём Николаевич"].electives == ["Erlang", "Психология"]
    assert merged["Хафизов Булат Наилевич"].electives == [
        "Блокчейн-технологии",
        "Психология управления",
    ]


def test_merge_keeps_fuller_group_when_fio_duplicated():
    main = [
        StudentChoice("Смирнов Иван Иванович", "11-301", ["Frontend для начинающих"]),
        StudentChoice("Смирнов Иван Иванович", "11-302", ["Erlang"]),
    ]
    hum = [
        StudentChoice("Смирнов Иван Иванович", "11-302", ["Психология"]),
    ]
    merged = merge_student_lists([main, hum])
    assert len(merged) == 1
    student = merged[0]
    assert student.group == "11-302"
    assert student.electives == ["Erlang", "Психология"]


def test_blockchain_matches_parenthetical_alias():
    pool = [
        _lesson(),
        _lesson(
            subject="Функциональное программирование (Erlang)",
            instructor="Фролов Д.Д.",
            room="1509",
        ),
    ]
    matched = find_elective_match("Блокчейн-технологии", pool)
    assert [m.instructor for m in matched] == ["Хайруллин А.Ф."]


def test_cloud_does_not_match_parenthetical_sibling_course():
    cloud = _lesson(
        subject="Введение в облачные технологии",
        instructor="Валиуллин Р.М.",
        room="1311",
        day=5,
        time_start="12:10",
    )
    oil = _lesson(
        subject="Введение в облачные технологии (Анализ данных в нефтегазовой сфере)",
        instructor="Шевченко Д.В.",
        room="1305",
        day=1,
    )
    matched = find_elective_match("Введение в облачные технологии", [cloud, oil])
    assert [m.instructor for m in matched] == ["Валиуллин Р.М."]
    oil_matched = find_elective_match("Анализ данных в нефтегазовой сфере", [cloud, oil])
    assert [m.instructor for m in oil_matched] == ["Шевченко Д.В."]


def test_psychology_courses_stay_distinct():
    management = _lesson(
        subject="Психология управления (1-9 нед.)",
        instructor="Пучкова И.М.",
        room="",
        day=3,
        time_start="10:10",
    )
    personal = _lesson(
        subject="Психология личной эффективности, лек.9 нед., группа №1 прак. с 10 нед.",
        instructor="Добротворская С.Г.",
        room="1405",
        day=4,
        time_start="10:10",
    )
    plain = _lesson(
        subject="Психология лек.9 нед.",
        instructor="Устин П.Н.",
        room="1408",
        day=4,
        time_start="10:10",
    )
    pool = [management, personal, plain]
    assert find_elective_match("Психология управления", pool) == [management]
    assert find_elective_match("Психология личной эффективности", pool) == [personal]
    assert find_elective_match("Психология", pool) == [plain]


def test_frontend_and_scripting_stay_distinct():
    frontend = _lesson(
        subject="Скриптинг, визуализация (Frontend)",
        instructor="Зайцева Д.А.",
        room="",
    )
    scripting = _lesson(
        subject="Скриптинг, визуализация",
        instructor="Костюк Д.И.",
        room="1305",
        day=4,
    )
    assert [m.instructor for m in find_elective_match("Frontend для начинающих", [frontend, scripting])] == [
        "Зайцева Д.А."
    ]
    assert [m.instructor for m in find_elective_match("Скриптинг, визуализация", [frontend, scripting])] == [
        "Костюк Д.И."
    ]


def test_robotics_parenthetical_vs_practicum():
    robotics = _lesson(
        subject="Проектный практикум по робототехнике. Часть 1 (Robotics)",
        instructor="Загиров А.И.",
        room="1308",
    )
    practicum = _lesson(
        subject="Проектный практикум по робототехнике. Ч1.",
        instructor="Апурин А.А.",
        room="",
    )
    assert [m.instructor for m in find_elective_match("Robotics", [robotics, practicum])] == [
        "Загиров А.И."
    ]
    assert [m.instructor for m in find_elective_match("Проектный практикум по робототехнике", [robotics, practicum])] == [
        "Апурин А.А."
    ]


def test_nested_unclosed_sre_parenthetical():
    sre = _lesson(
        subject=(
            "Функциональное программирование (Промышленная разработка, "
            "эксплуатация и надежность программных систем SRE "
            "(Функциональное программирование)"
        ),
        instructor="Фахрутдинов С.Р.",
        room="",
        day=1,
    )
    matched = find_elective_match(
        "Промышленная разработка, эксплуатация и надежность программных систем SRE",
        [sre],
    )
    assert matched == [sre]


def test_truncated_parenthetical_still_matches_sre():
    sre = _lesson(
        subject="Функциональное программирование (Промышленная разработка, эксплуатация и надежность програ",
        instructor="Фахрутдинов С.Р.",
        room="",
        day=1,
    )
    matched = find_elective_match(
        "Промышленная разработка, эксплуатация и надежность программных систем SRE",
        [sre],
    )
    assert matched == [sre]


def test_personal_lessons_keeps_core_and_chosen_electives():
    core = _lesson(
        subject="Технологии искусственного интеллекта",
        instructor="Агафонов А.А.",
        room="1307",
        notes="",
        day=0,
        time_start="12:10",
    )
    chosen = _lesson()
    other = _lesson(
        subject="Культурология",
        instructor="Сыченкова Л.А.",
        room="",
        day=2,
        time_start="08:30",
    )
    result = personal_lessons([core, chosen, other], [chosen, other], ["Блокчейн-технологии"])
    assert core in result
    assert chosen in result
    assert other not in result


def test_collect_elective_pool_skips_other_years():
    schedule = {
        "11-303": [_lesson()],
        "11-311": [_lesson(subject="Психология", instructor="", room="")],
        "11-401": [_lesson(subject="Культурология", instructor="Сыченкова Л.А.")],
    }
    pool = collect_elective_pool(schedule)
    assert {l.subject for l in pool} == {"Функциональное программирование (Blockchain)"}
