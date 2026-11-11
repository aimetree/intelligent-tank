#!/usr/bin/env python3
"""校验脚本的测试。直接跑：python3 tools/tests/test_validate.py；也可以用 pytest。

做法：tools/tests/example/ 是一组虚构的示例数据，应当全部通过；
然后逐处把它改错，每改一处，对应的规则必须报出来。
"""
import copy
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
REPO = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

import make_templates  # noqa: E402
import validate as V  # noqa: E402

SCHEMA = V.load_schema()
EXAMPLE = os.path.join(HERE, "example")
T = "TOP-000001"


def fresh():
    return V.load_dataset(EXAMPLE)


def rules_hit(ds, external=()):
    return {i.rule for i in V.validate(ds, SCHEMA, external)}


def issued_report(**cited):
    return {"id": "RPT-000001", "topic_id": T, "title": "示例报告", "language": "zh", "version": "1", "status": "issued",
            "issued_at": "2026-11-11", "data_version": "abc1234", **cited}


def ev(ds, i):
    return ds["evidence"][i]


# (说明, 应当报出的规则, 怎么改错, 假设要对外的可比组)
CASES = [
    # 结构
    ("拼错了字段名", "V-00", lambda d: ev(d, "EV-000001-001").__setitem__("sampel_label", "X"), ()),
    ("字段填了空值 null", "V-00", lambda d: ev(d, "EV-000001-001").__setitem__("scope_note", None), ()),
    ("原文数值写成了数字而不是字符串", "V-00", lambda d: ev(d, "EV-000001-001").__setitem__("value_reported", 85.6), ()),
    ("条件的写法不对", "V-00", lambda d: ev(d, "EV-000001-001")["conditions"].__setitem__("temperature", "25 °C"), ()),
    ("证据编号的写法不对", "V-01", lambda d: ev(d, "EV-000001-001").__setitem__("baseline_ref", "EV-1-2"), ()),
    ("枚举值不在表里", "V-03", lambda d: ev(d, "EV-000001-001").__setitem__("evidence_type", "measured"), ()),
    ("来源缺必填字段", "V-10", lambda d: d["sources"]["SRC-000001"].pop("handling"), ()),
    ("证据缺必填字段", "V-20", lambda d: ev(d, "EV-000001-001").pop("locator"), ()),
    # 引用与分区
    ("引用了不存在的实体", "V-02", lambda d: ev(d, "EV-000001-001").__setitem__("subject_id", "ENT-000999"), ()),
    ("公共区里出现客户专属记录", "V-05", lambda d: ev(d, "EV-000001-001").__setitem__("visibility", "client"), ()),
    # 实体、题目卡、字典
    ("机构没填机构类别", "V-06", lambda d: d["entities"]["ENT-000004"].pop("org_kind"), ()),
    ("AI 确认了实体身份", "V-06", lambda d: d["entities"]["ENT-000001"].__setitem__("confirmed_by", "claude"), ()),
    ("进行中的题目没有确认人", "V-07", lambda d: d["topics"][T].__setitem__("status", "active"), ()),
    ("指标用到了没定义的条件", "V-07", lambda d: d["dictionaries"][T]["indicators"][0]["required_conditions"].append("flow_rate"), ()),
    # 来源
    ("来源的标识没通过解析却作证据", "V-11", lambda d: d["sources"]["SRC-000001"]["id_check"].__setitem__("result", "fail"), ()),
    ("条款禁止 AI 却用 AI 读", "V-12", lambda d: d["sources"]["SRC-000002"]["terms"].__setitem__("no_ai", True), ()),
    ("只有摘要却标全文", "V-13", lambda d: d["sources"]["SRC-000003"].__setitem__("access_scope", "full"), ()),
    ("新闻当证据来源", "V-14", lambda d: d["sources"]["SRC-000002"].__setitem__("source_type", "news"), ()),
    # 证据
    ("层级与指标不一致", "V-21", lambda d: ev(d, "EV-000001-001").__setitem__("level", "material"), ()),
    ("漏填必填条件", "V-22", lambda d: ev(d, "EV-000001-001")["conditions"].pop("temperature"), ()),
    ("单位不在允许范围", "V-23", lambda d: ev(d, "EV-000002-001").__setitem__("unit_reported", "ohm"), ()),
    ("换算值不一致", "V-23", lambda d: ev(d, "EV-000001-001").__setitem__("value_std", 8.56), ()),
    ("缺原文片段", "V-24", lambda d: ev(d, "EV-000001-002").pop("snippet"), ()),
    ("全文来源却标仅摘要", "V-25", lambda d: ev(d, "EV-000001-001").__setitem__("obtained_from", "abstract_only"), ()),
    ("出处只写到来源", "V-26", lambda d: ev(d, "EV-000001-001").__setitem__("locator", {"text": "见论文"}), ()),
    ("AI 标成人工已核", "V-27", lambda d: ev(d, "EV-000003-001").__setitem__("verified_by", "claude"), ()),
    ("机器核对没过却标已核", "V-27", lambda d: ev(d, "EV-000002-001")["machine_check"].__setitem__("snippet", "fail"), ()),
    ("存疑没写说明", "V-27", lambda d: ev(d, "EV-000003-001").__setitem__("verification_status", "disputed"), ()),
    ("来源撤稿后证据没处理", "V-28", lambda d: d["sources"]["SRC-000003"].__setitem__("status", "retracted"), ()),
    ("基准指到了别的来源", "V-29", lambda d: ev(d, "EV-000001-001").__setitem__("baseline_ref", "EV-000003-001"), ()),
    # 关系
    ("推断的关系标成已核", "V-30", lambda d: d["relations"]["REL-000003"].update(verification_status="human_verified", verified_by="kai", verified_at="2026-11-11"), ()),
    ("有出处的关系没写转述", "V-30", lambda d: d["relations"]["REL-000001"].pop("summary"), ()),
    # 可比组
    ("跨层级放进一组", "V-40", lambda d: d["comparisons"]["CMP-000001"]["members"].append({"evidence_id": "EV-000002-001", "role": "member"}), ()),
    ("仅摘要进直接可比", "V-41", lambda d: d["comparisons"]["CMP-000001"]["members"].append({"evidence_id": "EV-000003-001", "role": "member"}), ()),
    ("条件未报告进直接可比", "V-41", lambda d: ev(d, "EV-000001-002")["conditions"].__setitem__("temperature", "not_reported"), ()),
    ("归一化的组定为直接可比", "V-42", lambda d: d["comparisons"]["CMP-000002"].__setitem__("tier", "direct"), ()),
    ("AI 定档", "V-43", lambda d: d["comparisons"]["CMP-000001"].__setitem__("decided_by", "claude"), ()),
    ("作废的证据留在组里", "V-44", lambda d: ev(d, "EV-000001-002").update(verification_status="void", void_reason="示例"), ()),
    # 判断
    ("判断没写成立条件", "V-50", lambda d: d["assessments"]["ASM-000001"].__setitem__("layer", "judgment"), ()),
    # 对外
    ("机器已核的证据进了已发出的报告", "V-60", lambda d: d["reports"].__setitem__("RPT-000001", issued_report(evidence_ids=["EV-000002-001"])), ()),
    ("草稿状态的可比组拿去对外", "V-61", lambda d: None, ("CMP-000002",)),
    ("图上读数没复读就对外", "V-62", lambda d: (ev(d, "EV-000001-003")["figure_read"].pop("reread_by"),
                                       d["reports"].__setitem__("RPT-000001", issued_report(evidence_ids=["EV-000001-003"]))), ()),
    ("只给链接的来源被报告引用", "V-63", lambda d: (d["sources"]["SRC-000001"].__setitem__("external_use", "link_only"),
                                        d["reports"].__setitem__("RPT-000001", issued_report(evidence_ids=["EV-000001-001"]))), ()),
    ("没核过的关系进了已发出的报告", "V-65", lambda d: d["reports"].__setitem__("RPT-000001", issued_report(rel_ids=["REL-000002"])), ()),
    # 日志
    ("更正没写错误类型", "V-70", lambda d: d["changes"][0].pop("error_type"), ()),
    ("人工工时没记", "V-71", lambda d: d["worklog"][1].pop("minutes"), ()),
    ("AI 的工作没写模型", "V-71", lambda d: d["worklog"][0].pop("ai"), ()),
]


def test_example_passes():
    assert V.validate(fresh(), SCHEMA, ["CMP-000001"]) == []


def test_each_broken_case_is_reported():
    missed = []
    for name, rule, mutate, external in CASES:
        ds = copy.deepcopy(fresh())
        mutate(ds)
        if rule not in rules_hit(ds, external):
            missed.append(f"{rule} {name}")
    assert not missed, missed


def test_duplicate_id_is_reported():
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["cp", "-r", EXAMPLE, os.path.join(tmp, "d")], check=True)
        path = os.path.join(tmp, "d", "public", "entities.json")
        rows = json.load(open(path, encoding="utf-8"))
        json.dump(rows + [rows[0]], open(path, "w", encoding="utf-8"), ensure_ascii=False)
        assert "V-01" in rules_hit(V.load_dataset(os.path.join(tmp, "d")))


def test_logs_are_append_only():
    with tempfile.TemporaryDirectory() as tmp:
        data = os.path.join(tmp, "data")
        subprocess.run(["cp", "-r", EXAMPLE, data], check=True)
        git = ["git", "-C", tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        subprocess.run(["git", "-C", tmp, "init", "-q"], check=True)
        subprocess.run(git + ["add", "."], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "init"], check=True)
        log = os.path.join(data, "worklog.jsonl")
        with open(log, "a", encoding="utf-8") as f:
            f.write('{"id": "LOG-000003"}\n')
        assert V.check_append_only(data) == []          # 末尾追加：可以
        lines = open(log, encoding="utf-8").read().splitlines()
        open(log, "w", encoding="utf-8").write("\n".join(lines[1:]) + "\n")
        assert [i.rule for i in V.check_append_only(data)] == ["V-72"]   # 删了已提交的行：不行


def test_export_drops_internal_fields():
    row = V.strip_internal(ev(fresh(), "EV-000001-003"))
    assert not (set(row) & V.INTERNAL_ONLY)
    assert set(row["figure_read"]) <= {"reading_error", "source_data_checked"}
    assert row["locator"] and row["conditions"]


def test_labels_cover_every_enum_value():
    labels = json.load(open(os.path.join(REPO, "data", "labels.json"), encoding="utf-8"))["enums"]
    for name, node in SCHEMA["$defs"].items():
        if name.startswith("enum_"):
            got = labels.get(name[5:], {})
            assert set(got) == set(node["enum"]), name
            assert all(v.get("zh") and "en" in v for v in got.values()), name


def test_templates_match_schema():
    for fname, text in make_templates.build(SCHEMA).items():
        path = os.path.join(REPO, "data", "templates", fname)
        assert os.path.exists(path) and open(path, encoding="utf-8").read() == text, f"{fname} 与 schema 不一致，重跑 tools/make_templates.py"


def test_repo_data_passes():
    assert V.validate(V.load_dataset(os.path.join(REPO, "data")), SCHEMA) == []


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("通过 ", name)
            except AssertionError as exc:
                failed += 1
                print("失败 ", name, exc)
    print(f"{len(CASES)} 处改错" + ("，全部被对应的规则报出" if not failed else ""), "｜失败", failed)
    sys.exit(1 if failed else 0)
