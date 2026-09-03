"""sitegen: manifest + README/snapshot regeneration (no network)."""

import pathlib

from src.sitegen import (
    build_manifest,
    course_of,
    group_url,
    raw_url,
    render_groups_markdown,
    replace_between,
    update_index,
    update_readme,
)


def _files() -> list[str]:
    return [
        "groups/unified/11-501.ics",
        "groups/lectures/11-501.ics",
        "groups/practices/11-501.ics",
        "groups/unified/11.1-521.ics",
        "groups/practices/11.1-521.ics",
        "groups/unified/11-314а.ics",
        "students/unified/11-501_Иванов_Иван_Иванович.ics",
        "students/unified/11-501_Петров_Пётр_Петрович.ics",
    ]


def test_course_of():
    assert course_of("11-301") == "1 курс"
    assert course_of("11-412") == "2 курс"
    assert course_of("11-522") == "3 курс"
    assert course_of("11-608") == "4 курс"
    assert course_of("11.1-521") == "Магистратура"
    assert course_of("zzz") == "Прочее"


def test_raw_url_encodes_cyrillic():
    url = raw_url("groups/unified/11-314а.ics")
    assert "11-314%D0%B0.ics" in url
    assert url.startswith("https://cdn.jsdelivr.net/gh/")


def test_build_manifest_flags_and_students():
    m = build_manifest(_files())
    assert m["students_total"] == 2
    by_name = {g["name"]: g for g in m["groups"]}
    assert set(by_name) == {"11-501", "11.1-521", "11-314а"}
    assert by_name["11-501"]["lectures"] and by_name["11-501"]["practices"]
    assert by_name["11-501"]["students"] == 2
    assert not by_name["11.1-521"]["lectures"] and by_name["11.1-521"]["practices"]
    assert group_url("11-501").endswith("/groups/unified/11-501.ics")


def test_build_manifest_students_list():
    m = build_manifest(_files())
    assert {"g": "11-501", "n": "Иванов Иван Иванович", "f": "11-501_Иванов_Иван_Иванович"} in m["students"]
    assert {"g": "11-501", "n": "Петров Пётр Петрович", "f": "11-501_Петров_Пётр_Петрович"} in m["students"]


def test_build_manifest_student_group_with_underscore():
    m = build_manifest([
        "groups/unified/11-631_англ.ics",
        "students/unified/11-631_англ_Петрова_Анна_Сергеевна.ics",
    ])
    assert m["students"] == [
        {"g": "11-631_англ", "n": "Петрова Анна Сергеевна", "f": "11-631_англ_Петрова_Анна_Сергеевна"}
    ]
    assert m["groups"][0]["students"] == 1


def test_render_groups_markdown_has_copyable_links():
    m = build_manifest(_files())
    md = render_groups_markdown(m)
    assert "### 3 курс" in md
    assert "`https://cdn.jsdelivr.net/gh/" in md
    assert "| 11-501 |" in md


def test_update_readme_replaces_marked_regions(tmp_path: pathlib.Path):
    readme = tmp_path / "README.md"
    readme.write_text(
        "# T\n<!-- UPDATED-START -->\nold\n<!-- UPDATED-END -->\n"
        "<!-- GROUPS-START -->\nold\n<!-- GROUPS-END -->\n",
        encoding="utf-8",
    )
    assert update_readme(readme, build_manifest(_files()), "now") is True
    text = readme.read_text(encoding="utf-8")
    assert "11-501" in text and "old" not in text
    assert update_readme(readme, build_manifest(_files()), "now") is False


def test_update_index_replaces_snapshot(tmp_path: pathlib.Path):
    index = tmp_path / "index.html"
    index.write_text(
        "<script>\n/* SNAPSHOT-START */\nconst SNAPSHOT = null;\n/* SNAPSHOT-END */\n</script>\n",
        encoding="utf-8",
    )
    assert update_index(index, build_manifest(_files()), "now") is True
    text = index.read_text(encoding="utf-8")
    assert '"n":"11-501"' in text
    # Timestamp alone must not rewrite the file (no empty CI commits).
    assert update_index(index, build_manifest(_files()), "later") is False
    assert replace_between("a[START]b[END]c", "[START]", "[END]", "X") == "a[START]\nX\n[END]c"
