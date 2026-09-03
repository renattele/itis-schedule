"""Generate the dynamic bits: README group tables + site snapshot.

Reads the real state of the ``calendars`` branch (via ``git ls-tree`` or a
local directory) and refreshes:

1. ``README.md`` — group tables between
   ``<!-- GROUPS-START -->`` / ``<!-- GROUPS-END -->`` markers.
2. ``docs/index.html`` — embedded fallback snapshot between
   ``/* SNAPSHOT-START */`` / ``/* SNAPSHOT-END */`` markers.

Stdlib only. Run: ``python -m src.sitegen`` from the repo root.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import subprocess
import urllib.parse

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

OWNER = "renattele"
REPO = "itis-schedule"
BRANCH = "calendars"

RAW_BASE = f"https://cdn.jsdelivr.net/gh/{OWNER}/{REPO}@{BRANCH}"

GROUPS_MARK_START = "<!-- GROUPS-START -->"
GROUPS_MARK_END = "<!-- GROUPS-END -->"
UPDATED_MARK_START = "<!-- UPDATED-START -->"
UPDATED_MARK_END = "<!-- UPDATED-END -->"
SNAPSHOT_MARK_START = "/* SNAPSHOT-START */"
SNAPSHOT_MARK_END = "/* SNAPSHOT-END */"

COURSES = ["1 курс", "2 курс", "3 курс", "4 курс", "Магистратура", "Прочее"]
COURSE_SHORT = {
    "11-3": "1 курс",
    "11-4": "2 курс",
    "11-5": "3 курс",
    "11-6": "4 курс",
}


def course_of(group: str) -> str:
    """Map a group label to its course section."""
    if group.startswith("11.1-"):
        return "Магистратура"
    return COURSE_SHORT.get(group[:4], "Прочее")


def raw_url(rel_path: str) -> str:
    """Public raw URL for a file on the calendars branch (percent-encoded)."""
    return f"{RAW_BASE}/{urllib.parse.quote(rel_path, safe='/:')}"


def list_branch_files(ref: str = "origin/calendars") -> list[str]:
    """List file paths on a git ref (null-separated, unicode-safe)."""
    out = subprocess.check_output(
        ["git", "ls-tree", "-r", "-z", "--name-only", ref],
        cwd=REPO_ROOT,
    )
    return [p for p in out.decode("utf-8").split("\x00") if p]


def list_local_files(cal_dir: pathlib.Path) -> list[str]:
    """List .ics paths under a local calendars dir (same shape as branch)."""
    return sorted(
        str(p.relative_to(cal_dir)).replace("\\", "/")
        for p in cal_dir.rglob("*.ics")
        if p.is_file()
    )


def build_manifest(files: list[str]) -> dict:
    """Build a JSON-serialisable manifest from a file list."""
    unified = {
        p.removeprefix("groups/unified/").removesuffix(".ics")
        for p in files
        if p.startswith("groups/unified/") and p.endswith(".ics")
    }
    lectures = {
        p.removeprefix("groups/lectures/").removesuffix(".ics")
        for p in files
        if p.startswith("groups/lectures/") and p.endswith(".ics")
    }
    practices = {
        p.removeprefix("groups/practices/").removesuffix(".ics")
        for p in files
        if p.startswith("groups/practices/") and p.endswith(".ics")
    }
    # Filenames are percent-decoded group labels (git gives us raw unicode).
    groups = sorted(unified, key=lambda g: (course_of(g) != "Магистратура", g))
    order = {c: i for i, c in enumerate(COURSES)}
    groups.sort(key=lambda g: (order.get(course_of(g), 99), g))

    student_files = [
        p for p in files if p.startswith("students/unified/") and p.endswith(".ics")
    ]
    students_by_group: dict[str, int] = {}
    students: list[dict] = []
    for p in sorted(student_files):
        stem = p.removeprefix("students/unified/").removesuffix(".ics")
        # Group itself may contain "_" (e.g. 11-631_англ): longest match wins.
        group = next(
            (g for g in sorted(unified, key=len, reverse=True) if stem.startswith(g + "_")),
            stem.split("_", 1)[0] if "_" in stem else stem,
        )
        students_by_group[group] = students_by_group.get(group, 0) + 1
        name = stem[len(group) + 1 :] if stem.startswith(group + "_") else stem
        students.append({"g": group, "n": name.replace("_", " "), "f": stem})
    students.sort(key=lambda s: (s["n"], s["g"]))

    return {
        "groups": [
            {
                "name": g,
                "course": course_of(g),
                "lectures": g in lectures,
                "practices": g in practices,
                "students": students_by_group.get(g, 0),
            }
            for g in groups
        ],
        "students_total": len(student_files),
        "students": students,
    }


def group_url(group: str, kind: str = "unified") -> str:
    """Raw URL for a group calendar (kind: unified|lectures|practices)."""
    return raw_url(f"groups/{kind}/{group}.ics")


def render_groups_markdown(manifest: dict) -> str:
    """Markdown tables per course, one copy-pasteable link per row."""
    lines: list[str] = []
    by_course: dict[str, list] = {c: [] for c in COURSES}
    for g in manifest["groups"]:
        by_course.setdefault(g["course"], by_course["Прочее"]).append(g)
    for course in COURSES:
        items = by_course.get(course, [])
        if not items:
            continue
        lines.append(f"### {course}")
        lines.append("")
        lines.append("| Группа | Ссылка для подписки (копируй) | Студентов |")
        lines.append("|--------|-------------------------------|-----------|")
        for g in items:
            url = group_url(g["name"])
            lines.append(
                f"| {g['name']} | [`{url}`]({url}) | {g['students'] or '—'} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def replace_between(text: str, start: str, end: str, replacement: str) -> str:
    """Replace the region between two markers (markers kept)."""
    before, sep1, rest = text.partition(start)
    if not sep1:
        raise ValueError(f"start marker not found: {start}")
    _, sep2, after = rest.partition(end)
    if not sep2:
        raise ValueError(f"end marker not found: {end}")
    return f"{before}{start}\n{replacement.rstrip()}\n{sep2}{after}"


def update_readme(readme_path: pathlib.Path, manifest: dict, when: str) -> bool:
    """Refresh README generated regions. Returns True if changed.

    The timestamp only moves when the group tables actually change, so
    scheduled CI runs don't produce empty commits.
    """
    text = readme_path.read_text(encoding="utf-8")
    groups_md = render_groups_markdown(manifest)
    before, sep1, rest = text.partition(GROUPS_MARK_START)
    if not sep1:
        raise ValueError(f"start marker not found: {GROUPS_MARK_START}")
    _, sep2, _ = rest.partition(GROUPS_MARK_END)
    if not sep2:
        raise ValueError(f"end marker not found: {GROUPS_MARK_END}")
    current_groups = rest.partition(GROUPS_MARK_END)[0].strip()
    if current_groups == groups_md.strip():
        return False
    updated = replace_between(text, GROUPS_MARK_START, GROUPS_MARK_END, groups_md)
    stamp = (
        f"Календари обновляются каждые 5 часов. "
        f"Таблицы ниже сгенерированы {when} из ветки `calendars` "
        f"({len(manifest['groups'])} групп, {manifest['students_total']} персональных календарей)."
    )
    updated = replace_between(updated, UPDATED_MARK_START, UPDATED_MARK_END, stamp)
    if updated != text:
        readme_path.write_text(updated, encoding="utf-8")
        return True
    return False


def _slim_manifest(manifest: dict) -> dict:
    return {
        "base": RAW_BASE,
        "studentsTotal": manifest["students_total"],
        "groups": [
            {
                "n": g["name"],
                "c": g["course"],
                "l": 1 if g["lectures"] else 0,
                "p": 1 if g["practices"] else 0,
                "s": g["students"],
            }
            for g in manifest["groups"]
        ],
        "students": [
            {"g": s["g"], "n": s["n"], "f": s["f"]} for s in manifest["students"]
        ],
    }


def snapshot_js(manifest: dict, when: str) -> str:
    """Compact JS snapshot for embedding into docs/index.html."""
    slim = {"updated": when, **_slim_manifest(manifest)}
    return "const SNAPSHOT = " + json.dumps(slim, ensure_ascii=False, separators=(",", ":")) + ";"


def update_index(index_path: pathlib.Path, manifest: dict, when: str) -> bool:
    """Refresh the embedded snapshot in docs/index.html.

    Only touches the file when the manifest content actually changed
    (the timestamp alone must not cause rewrites / empty CI commits).
    """
    import re

    text = index_path.read_text(encoding="utf-8")
    m = re.search(
        re.escape(SNAPSHOT_MARK_START) + r"\s*const SNAPSHOT = (\{.*?\});",
        text,
        re.DOTALL,
    )
    if m:
        try:
            current = json.loads(m.group(1))
            current.pop("updated", None)
            if current == _slim_manifest(manifest):
                return False
        except (json.JSONDecodeError, AttributeError):
            pass
    updated = replace_between(
        text, SNAPSHOT_MARK_START, SNAPSHOT_MARK_END, snapshot_js(manifest, when)
    )
    if updated != text:
        index_path.write_text(updated, encoding="utf-8")
        return True
    return False


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Regenerate README tables + site snapshot.")
    parser.add_argument("--ref", default="origin/calendars", help="git ref to scan")
    parser.add_argument("--calendars-dir", type=pathlib.Path, default=None,
                        help="scan a local dir instead of git (for CI ./calendars)")
    parser.add_argument("--readme", type=pathlib.Path, default=REPO_ROOT / "README.md")
    parser.add_argument("--index", type=pathlib.Path, default=REPO_ROOT / "docs" / "index.html")
    args = parser.parse_args(argv)

    if args.calendars_dir is not None:
        files = list_local_files(args.calendars_dir)
        source = str(args.calendars_dir)
    else:
        files = list_branch_files(args.ref)
        source = args.ref
    manifest = build_manifest(files)
    when = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    changed_readme = update_readme(args.readme, manifest, when) if args.readme.exists() else False
    changed_index = update_index(args.index, manifest, when) if args.index.exists() else False
    print(f"source: {source} ({len(files)} files)")
    print(f"groups: {len(manifest['groups'])}, student calendars: {manifest['students_total']}")
    print(f"README updated: {changed_readme}, index snapshot updated: {changed_index}")


if __name__ == "__main__":
    main()
