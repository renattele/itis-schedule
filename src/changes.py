"""Date-specific changes written as free text inside schedule cells.

Examples: "7 ноября онлайн", "21.10 не будет", "18.09 перенос на 6.11 в 17:30
(ауд.1311)", "с 9 ноября перенос на 17:30 ауд.1310", "(16.09, 7.10, 28.10)",
"11-603 Математический анализ, Скворцова Г.Ш. ауд.1412 (24 ноября)".

Clauses are cut out of the cell text (replaced by §N§ markers) before the
lesson is parsed, so their rooms and dates don't leak into the lesson itself.
"""

from __future__ import annotations

import re
from dataclasses import replace

MONTHS: dict[str, int] = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
_WEEKDAYS = {"понедельник": 0, "вторник": 1, "среду": 2, "четверг": 3, "пятницу": 4, "субботу": 5}

_M = "|".join(MONTHS)
_D = rf"(?:\d{{1,2}}\s+(?:{_M})|\d{{1,2}}[./](?:1[0-2]|0?[1-9])(?!\d)\.?)"
_T = r"\d{1,2}[:.]\d{2}"
_WHERE = (
    r"[ \t(]*(?:очно\s+)?(?:в\s+)?(?:онл(?:айн)?\.?(?:\s+раз\w*\.?)?|коворкинг"
    r"|(?:ауд\.?\s*)?\d{3,4}(?:-\d{3,4})?(?:\s*ауд\.?\s*физфак\w*)?)\)?"
)

_CLAUSES = [
    # 18.09 перенос на 6.11 в 17:30 (ауд.1311) / 26.10 не будет с переносом на 30.10 с 10:10-13:50
    ("move", re.compile(
        rf"(?P<d>{_D})\s*(?:не\s+будет\s+)?(?:с\s+)?перенос\w*\s+"
        rf"(?:(?P<on>в\s+онлайн)\s+|на\s*(?:\d+\s*-?\s*ую\s+неделю\s*\(\s*)?)(?P<d2>{_D})\)?"
        rf"\s*(?:в\s*(?P<t>{_T})|с\s*(?P<t1>{_T})\s*-\s*(?P<t2>{_T}))?(?P<w>{_WHERE})?",
        re.IGNORECASE,
    )),
    # (30.09 в 17.30)
    ("move", re.compile(rf"(?P<d>{_D})\s*в\s*(?P<t>{_T})(?!\d)(?P<w>{_WHERE})?", re.IGNORECASE)),
    # с 9 ноября перенос на 17:30 ауд.1310 / по нечетн.нед.перенос на субботу 12:10 ауд.1302
    ("perm", re.compile(
        rf"(?:по\s+(?P<par>(?:не)?четн)\w*\.?\s*нед\.?\s*|[сc]\s+(?P<d>{_D})\s*)?"
        rf"пер\w?нос\w*\s+на\s+(?:(?P<wd>{'|'.join(_WEEKDAYS)})\s+)?(?:в\s+)?"
        rf"(?P<t>{_T})(?!\d|\.?\s*в\s*\d)(?P<w>{_WHERE})?",
        re.IGNORECASE,
    )),
    # с 3.11 в онлайн
    ("perm", re.compile(rf"[сc]\s+(?P<d>{_D})\s*(?P<w>(?:в\s+)?онлайн)", re.IGNORECASE)),
    ("cancel", re.compile(rf"(?P<d>{_D})\s*не\s+будет(?:\s+с\s+переносом)?\s*\.?", re.IGNORECASE)),
    # (16.09, 7.10, 28.10, 25.11)
    ("only", re.compile(rf"\(\s*{_D}(?:\s*,\s*{_D})+\s*\)", re.IGNORECASE)),
    # 7 ноября онлайн / (10.11 в ауд. 1412 раз) / 1.12 перенос в ауд.1408
    ("where", re.compile(
        rf"(?P<d>{_D})\s*(?:перенос\s+)?(?P<w>{_WHERE})(?:\s*раз\w*\.?)?", re.IGNORECASE,
    )),
    # "Мусина Г.В. в 1311 в 17.30" in the 15:50 row: the lesson is at 17:30
    ("perm", re.compile(rf"(?<![\d.])в\s+(?P<t>{_T})(?![\d.]|\s*-)", re.IGNORECASE)),
    # a line holding only a date: the lesson happens on that day only
    ("only", re.compile(rf"^[ \t(]*{_D}[ \t)]*$", re.IGNORECASE | re.MULTILINE)),
]

_DATE_RE = re.compile(
    rf"(\d{{1,2}})((?:\s*(?:,|и)\s*\d{{1,2}})*)\s+({_M})|(\d{{1,2}})[./](1[0-2]|0?[1-9])(?!\d)\.?",
    re.IGNORECASE,
)
# Sub-blocks for another group or for given dates only:
# "11-603 Математический анализ, …" / "18 ноября,23 декабря Иностранный язык…",
# or a second lesson glued on after a blank line / "(…)   Продвинутый Linux …".
_BLOCK_START_RE = re.compile(
    rf"^\s*(?:(?P<g>11-\d{{3}}\w?)\s+|(?P<dates>{_D}(?:\s*(?:,|и)\s*{_D})*)\s+)(?=[А-ЯЁA-Z])"
    r"|(?:\n[ \t]*\n\s*|(?<=\))[ \t]{2,})(?=[А-ЯЁ])(?![А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.)",
    re.MULTILINE,
)
_MARK_RE = re.compile(r"§(\d+)§")


def dates_in(text: str) -> list[str]:
    """All dates in *text* as MM-DD ("3 и 17 ноября" → 11-03, 11-17)."""
    out: list[str] = []
    for m in _DATE_RE.finditer(text):
        if m.group(3):
            month = MONTHS[m.group(3).lower()]
            days = [m.group(1)] + re.findall(r"\d+", m.group(2))
        else:
            month, days = int(m.group(5)), [m.group(4)]
        out += [f"{month:02d}-{int(d):02d}" for d in days]
    return out


def strip_dates(text: str) -> str:
    return _DATE_RE.sub(" ", text)


def split_blocks(cell: str) -> tuple[str, list[tuple[str, str | None, list[str]]]]:
    """Cut sub-blocks off the cell.

    Returns the main text and [(block text, group, prefix dates)]; group is
    None for a plain second lesson that every group of the cell has.
    """
    if re.match(r"\s*Дис\w*\s+по\s+выбору", cell, re.IGNORECASE):
        return cell, []  # elective lines are parsed one by one anyway
    starts = list(_BLOCK_START_RE.finditer(cell))
    if not starts:
        return cell, []
    blocks = []
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(cell)
        dates = dates_in(m.group("dates")) if m.group("dates") else []
        group = m.group("g") or ("" if dates else None)
        blocks.append((cell[m.end():end].strip(" \n/"), group, dates))
    return cell[:starts[0].start()], blocks


def extract(text: str) -> tuple[str, list[tuple[str, re.Match]]]:
    """Replace change clauses with §N§ markers; return the text and the clauses."""
    found: list[tuple[str, re.Match]] = []

    def sub(kind: str):
        def repl(m: re.Match) -> str:
            found.append((kind, m))
            return f" §{len(found) - 1}§ "
        return repl

    for kind, regex in _CLAUSES:
        text = regex.sub(sub(kind), text)
    return text, found


def take_marks(*fields: str) -> tuple[set[int], list[str]]:
    """Marker ids found in *fields*, and the fields with markers removed."""
    ids = {int(i) for f in fields for i in _MARK_RE.findall(f)}
    cleaned = [
        re.sub(r"\(\s*[.,/]?\s*\)", "", _MARK_RE.sub("", f)).strip(" ,;/")
        for f in fields
    ]
    return ids, [re.sub(r"\s{2,}", " ", f) for f in cleaned]


def _hhmm(t: str) -> str:
    h, m = re.split(r"[:.]", t)
    return f"{int(h):02d}:{m}"


def _minutes(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def _end(lesson, start: str) -> str:
    m = _minutes(start) + _minutes(lesson.time_end) - _minutes(lesson.time_start)
    return f"{m // 60:02d}:{m % 60:02d}"


def _room(where: str | None, default: str) -> str:
    if not where:
        return default
    if "онл" in where.lower():
        return "онлайн"
    if "коворкинг" in where.lower():
        return "коворкинг"
    m = re.search(r"\d{3,4}(?:-\d{3,4})?", where)
    if not m:
        return default
    return m.group(0) + (" физфак" if "физфак" in where.lower() else "")


def _moved(lesson, m: re.Match, date: str | None = None):
    """Copy of *lesson* at the clause's new time/room (and weekday)."""
    gd = m.groupdict()
    start = _hhmm(gd.get("t") or gd.get("t1") or lesson.time_start)
    end = _hhmm(gd["t2"]) if gd.get("t2") else _end(lesson, start)
    room = "онлайн" if gd.get("on") else _room(gd.get("w"), lesson.room)
    out = replace(lesson, time_start=start, time_end=end, room=room)
    if gd.get("wd"):
        out = replace(out, day=_WEEKDAYS[gd["wd"].lower()])
    return replace(out, only=(date,)) if date else out


def apply(lesson, clauses: list[tuple[str, re.Match]]) -> list:
    """Expand *lesson* by its change clauses into the lessons that really happen."""
    parts = [lesson]
    extra = []
    for kind, m in clauses:
        gd = m.groupdict()
        if kind == "perm":
            moved = _moved(lesson, m)
            if gd.get("d"):
                d = dates_in(gd["d"])[0]
                parts = [replace(lesson, until=d), replace(moved, start_from=d)]
            elif gd.get("par"):
                odd = gd["par"].lower().startswith("не")
                parts = [
                    replace(lesson, weeks="even" if odd else "odd"),
                    replace(moved, weeks="odd" if odd else "even"),
                ]
            else:
                parts = [moved]
        elif kind == "only":
            parts = [replace(p, only=tuple(dates_in(m.group(0)))) for p in parts]

    for kind, m in clauses:
        if kind not in ("move", "cancel", "where"):
            continue
        d = dates_in(m.group("d"))[0]
        parts = [replace(p, skip=p.skip + (d,)) if d not in p.skip else p for p in parts]
        if kind == "move":
            d2 = m.groupdict().get("d2")
            extra.append(_moved(lesson, m, dates_in(d2)[0] if d2 else d))
        elif kind == "where":
            extra.append(replace(lesson, room=_room(m.group("w"), lesson.room), only=(d,)))
    return parts + extra
