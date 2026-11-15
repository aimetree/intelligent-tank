#!/usr/bin/env python3
"""核对单（tools/verify_sheet.py）的测试。直接运行：python3 tools/tests/test_verify.py"""
import copy
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import validate as V  # noqa: E402
import verify_sheet as S  # noqa: E402

EXAMPLE = os.path.join(HERE, "example")
SCHEMA = V.load_schema()
CLEAR = ("verified_by", "verified_at", "expert_reviewed_by", "expert_reviewed_at")


def fresh():
    """示例数据的一份副本，把 SRC-000001 的证据退回到人工核对之前。返回 (目录, 数据)。"""
    d = tempfile.mkdtemp()
    shutil.copytree(EXAMPLE, d, dirs_exist_ok=True)
    path = os.path.join(d, "public", "sources", "SRC-000001.json")
    doc = json.load(open(path, encoding="utf-8"))
    for e in doc["evidence"]:
        if e["verification_status"] in ("human_verified", "expert_reviewed"):
            e["verification_status"] = "machine_checked"
            for k in CLEAR:
                e.pop(k, None)
            fr = e.get("figure_read")
            if fr:
                for k in ("reread_by", "reread_at", "reread_value", "reading_error"):
                    fr.pop(k, None)
    json.dump(doc, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return d, V.load_dataset(d)


def issues(ds):
    """校验问题。退回到核对之前以后，示例数据里的可比组、复核单会报成员还没核过，这些是底数，只看有没有多出来。"""
    return {(i.rule, i.record, i.message) for i in V.validate(ds, SCHEMA)}


def todo(ds):
    return S._todo(ds, "SRC-000001")


def answers(ds, **over):
    items = {}
    for e in todo(ds):
        a = {"decision": "ok"}
        if e.get("obtained_from") == "figure_read":
            a["reread"] = float(e["value_reported"]) + 0.2
        items[e["id"]] = a
    base = {"source_id": "SRC-000001", "verifier": "yu", "date": "2026-11-20", "minutes": 30, "items": items}
    base.update(over)
    return base


def test_setup_is_clean_and_has_a_figure_reading():
    d, ds = fresh()
    rows = todo(ds)
    assert rows and any(e.get("obtained_from") == "figure_read" for e in rows)
    pages = [int(e["locator"]["page"]) for e in rows if str(e["locator"].get("page", "")).isdigit()]
    assert pages == sorted(pages), "核对单按页码排"


def test_ok_marks_human_verified_and_records_reread():
    d, ds = fresh()
    base = issues(ds)
    said, touched, log = S.apply_answers(ds, SCHEMA, answers(ds))
    assert touched == ["SRC-000001"] and log["actor"] == "yu" and log["minutes"] == 30 and log["arm"] == "C"
    for e in ds["evidence"].values():
        if e["source_id"] != "SRC-000001" or e["verification_status"] == "void":
            continue
        assert e["verification_status"] in ("human_verified", "disputed"), e["id"]
        assert e["verified_by"] == "yu" and e["verified_at"] == "2026-11-20"
        if e.get("obtained_from") == "figure_read":
            fr = e["figure_read"]
            assert fr["reread_by"] == "yu" and abs(fr["reading_error"] - 0.2) < 1e-9, fr
    assert issues(ds) <= base
    assert log["counts"]["evidence_verified"] == len(answers(fresh()[1])["items"])


REFUSED = [
    ("核对的人是 AI", lambda a, ds: a.update(verifier="claude")),
    ("核对的人空着", lambda a, ds: a.update(verifier="")),
    ("没有分钟数也没有说明", lambda a, ds: a.pop("minutes")),
    ("没有日期", lambda a, ds: a.pop("date")),
    ("一条也没有", lambda a, ds: a.update(items={})),
    ("不认识的决定", lambda a, ds: next(iter(a["items"].values())).update(decision="yes")),
    ("别的来源的证据", lambda a, ds: a["items"].update({"EV-000002-001": {"decision": "ok"}})),
    ("图上读数没带复读的值", lambda a, ds: [v.pop("reread") for v in a["items"].values() if "reread" in v]),
    ("存疑没写原因", lambda a, ds: next(iter(a["items"].values())).update(decision="dispute")),
    ("change_ids 不是这条证据的更正", lambda a, ds: next(iter(a["items"].values())).update(decision="fix", change_ids=["CHG-999999"])),
]


def test_bad_answers_are_refused_and_nothing_changes():
    missed = []
    for name, mutate in REFUSED:
        d, ds = fresh()
        a = answers(ds)
        mutate(a, ds)
        before = copy.deepcopy(ds["evidence"])
        try:
            S.apply_answers(ds, SCHEMA, a)
            missed.append(name)
        except S.VerifyError:
            if name in ("核对的人是 AI", "核对的人空着", "没有分钟数也没有说明", "没有日期", "一条也没有") and ds["evidence"] != before:
                missed.append(name + "（数据被动过）")
    assert not missed, missed


def test_fix_without_change_and_machine_failed_are_left():
    d, ds = fresh()
    rows = [e for e in todo(ds) if e.get("obtained_from") != "figure_read"]
    a = answers(ds)
    a["items"][rows[0]["id"]] = {"decision": "fix", "note": "应为 1.0"}
    rows[1]["machine_check"]["value_unit"] = "fail"
    rows[1]["verification_status"] = "pending"
    said, touched, log = S.apply_answers(ds, SCHEMA, a)
    assert rows[0]["verification_status"] == "machine_checked" and "verified_by" not in rows[0]
    assert rows[1]["verification_status"] == "pending" and "verified_by" not in rows[1]
    assert log["counts"]["left_waiting"] == 2 and sum("没有写回" in s or "先留着" in s for s in said) == 2


def test_dispute_is_recorded():
    d, ds = fresh()
    first = todo(ds)[0]
    a = answers(ds)
    a["items"] = {first["id"]: {"decision": "dispute", "note": "和表里的数对不上"}}
    base = issues(ds)
    S.apply_answers(ds, SCHEMA, a)
    assert first["verification_status"] == "disputed" and first["dispute_note"] == "和表里的数对不上" and first["verified_by"] == "yu"
    assert issues(ds) <= base


def test_page_carries_rows_and_escapes_source_text():
    d, ds = fresh()
    first = todo(ds)[0]
    first["snippet"] = 'x</script><img src=x onerror=alert(1)>'
    page, n = S.build_page(ds, "SRC-000001", "abc1234")
    assert n == len(todo(ds)) and first["id"] in page
    assert "</script><img" not in page and page.count("</script>") == 1
    assert "http://" not in page and "https://" not in page.replace(ds["sources"]["SRC-000001"].get("url", ""), "")


def test_command_line_writes_file_and_log():
    d, ds = fresh()
    apath = os.path.join(d, "answers.json")
    json.dump(answers(ds), open(apath, "w", encoding="utf-8"))
    n_before = len(open(os.path.join(d, "worklog.jsonl"), encoding="utf-8").read().splitlines())
    assert S.main(["--data", d, "apply", "--answers", apath, "--dry-run"]) == 0
    assert len(todo(V.load_dataset(d))) == len(todo(ds)), "只看不写"
    assert S.main(["--data", d, "apply", "--answers", apath]) == 0
    after = V.load_dataset(d)
    assert not todo(after) and issues(after) <= issues(ds)
    assert len(open(os.path.join(d, "worklog.jsonl"), encoding="utf-8").read().splitlines()) == n_before + 1
    assert S.main(["--data", d, "apply", "--answers", apath]) == 1, "已经核过的不能再写一遍"


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("通过 ", name)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print("失败 ", name, repr(exc)[:400])
    print(f"核对单的测试：{len(REFUSED)} 处不合规矩的回答 ｜失败 {failed}")
    sys.exit(1 if failed else 0)
