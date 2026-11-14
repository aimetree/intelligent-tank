#!/usr/bin/env python3
"""校验脚本的测试。直接跑：python3 tools/tests/test_validate.py；也可以用 pytest。

做法：tools/tests/example/ 是一组虚构的示例数据，应当全部通过；
然后逐处把它改错，每改一处，对应的规则必须报出来。另有几条“写对了应当通过”的测试，
和一条总的检查：校验脚本里出现的每一条规则，都至少有一处改错的测试。
"""
import copy
import json
import os
import re
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
DAY = "2026-11-11"


def fresh():
    return V.load_dataset(EXAMPLE)


def rules_hit(ds, external=()):
    return {i.rule for i in V.validate(ds, SCHEMA, external)}


def issued_report(**cited):
    return {"id": "RPT-000001", "topic_id": T, "title": "示例报告", "language": "zh", "version": "1", "status": "issued",
            "issued_at": DAY, "data_version": "abc1234", "evidence_file": "reports/RPT-000001/evidence.json", **cited}


def ev(ds, i):
    return ds["evidence"][i]


def src(ds, sid):
    return ds["sources"][sid]


def smp(ds, sid, label):
    return next(x for x in ds["samples"][sid] if x["label"] == label)


def report(ds, **cited):
    ds["reports"]["RPT-000001"] = issued_report(**cited)


# (说明, 应当报出的规则, 怎么改错, 假设要对外的可比组)
CASES = [
    # ---- 结构
    ("拼错了字段名", "V-00", lambda d: ev(d, "EV-000001-001").__setitem__("sampel_label", "X"), ()),
    ("字段填了空值 null", "V-00", lambda d: ev(d, "EV-000001-001").__setitem__("scope_note", None), ()),
    ("原文数值写成了数字而不是字符串", "V-00", lambda d: ev(d, "EV-000001-001").__setitem__("value_reported", 85.6), ()),
    ("条件的写法不对", "V-00", lambda d: ev(d, "EV-000001-001")["conditions"].__setitem__("temperature", "25 °C"), ()),
    ("证据编号的写法不对", "V-01", lambda d: ev(d, "EV-000001-001").__setitem__("baseline_ref", "EV-1-2"), ()),
    ("枚举值不在表里", "V-03", lambda d: ev(d, "EV-000001-001").__setitem__("evidence_type", "measured"), ()),
    ("来源缺必填字段", "V-10", lambda d: src(d, "SRC-000001").pop("handling"), ()),
    ("来源没写由谁取来", "V-10", lambda d: src(d, "SRC-000001").pop("fetched_by"), ()),
    ("证据缺必填字段", "V-20", lambda d: ev(d, "EV-000001-001").pop("locator"), ()),
    # ---- 引用与分区
    ("引用了不存在的实体", "V-02", lambda d: ev(d, "EV-000001-001").__setitem__("subject_id", "ENT-000999"), ()),
    ("公共区里出现客户专属记录", "V-05", lambda d: ev(d, "EV-000001-001").__setitem__("visibility", "client"), ()),
    # ---- 实体、题目卡、字典
    ("机构没填机构类别", "V-06", lambda d: d["entities"]["ENT-000004"].pop("org_kind"), ()),
    ("AI 确认了实体身份", "V-06", lambda d: d["entities"]["ENT-000001"].__setitem__("confirmed_by", "claude"), ()),
    ("进行中的题目没有确认人", "V-07", lambda d: d["topics"][T].__setitem__("status", "active"), ()),
    ("指标用到了没定义的条件", "V-07", lambda d: d["dictionaries"][T]["indicators"][0]["required_conditions"].append("flow_rate"), ()),
    ("器件层指标漏了统一必填的条件", "V-07", lambda d: d["dictionaries"][T]["indicators"][0]["required_conditions"].remove("temperature"), ()),
    ("事实项和指标用了同一个键", "V-07", lambda d: d["dictionaries"][T]["facts"][0].__setitem__("key", "energy_efficiency"), ()),
    ("事实项对应的问题不在题目卡里", "V-07", lambda d: d["dictionaries"][T]["facts"][0].__setitem__("question", "Q9"), ()),
    ("可比规则的关键条件没定义", "V-07", lambda d: d["dictionaries"][T]["rules"][2]["key_conditions"].append("flow_rate"), ()),
    ("分类维度的 only_when 用了没定义的维度", "V-07", lambda d: d["topics"][T]["facets"][2]["only_when"].__setitem__("fluorine_kind", ["x"]), ()),
    ("有要换算的单位却没写标准单位", "V-07", lambda d: d["dictionaries"][T]["facts"][2].pop("unit_std"), ()),
    ("标准单位没有列在允许的单位里", "V-07", lambda d: d["dictionaries"][T]["indicators"][2]["units_accepted"].clear(), ()),
    ("可比规则写的层级和适用的指标不一致", "V-07", lambda d: d["dictionaries"][T]["rules"][0].__setitem__("level", "material"), ()),
    # ---- 分类维度
    ("实体用了没定义的分类维度", "V-08", lambda d: d["entities"]["ENT-000001"]["facets"].__setitem__("colour", "red"), ()),
    ("分类取值不在允许的取值里", "V-08", lambda d: smp(d, "SRC-000001", "X-1")["facets"].__setitem__("conduction_type", "magic"), ()),
    ("实验室样品缺传导类型", "V-08", lambda d: smp(d, "SRC-000001", "X-1")["facets"].pop("conduction_type"), ()),
    ("部分含氟没写子类", "V-08", lambda d: smp(d, "SRC-000007", "Z-1")["facets"].pop("partial_fluorine_kind"), ()),
    ("非氟却写了部分含氟的子类", "V-08", lambda d: smp(d, "SRC-000001", "X-1")["facets"].__setitem__("partial_fluorine_kind", "pfsa_blend"), ()),
    ("材料族记在了样品上", "V-08", lambda d: smp(d, "SRC-000001", "X-1")["facets"].__setitem__("material_family", "pbi"), ()),
    ("商业膜在样品登记里写了分类", "V-08", lambda d: smp(d, "SRC-000001", "P-212").__setitem__("facets", {"fluorine_class": "perfluorinated"}), ()),
    ("产品缺含氟类别", "V-08", lambda d: d["entities"]["ENT-000003"]["facets"].pop("fluorine_class"), ()),
    ("材料族实体缺材料族", "V-08", lambda d: d["entities"]["ENT-000007"].pop("facets"), ()),
    ("只登记的论文没写膜的类别", "V-08", lambda d: src(d, "SRC-000009")["topics"][0].pop("facets"), ()),
    # ---- 来源
    ("自动读取的文件放进了 Project 文件区", "V-10", lambda d: src(d, "SRC-000001").__setitem__("copy_kept", "project_files"), ()),
    ("来源的标识没通过解析却作证据", "V-11", lambda d: src(d, "SRC-000001")["id_check"].__setitem__("result", "fail"), ()),
    ("条款禁止 AI 却由读取工具直接读", "V-12", lambda d: src(d, "SRC-000002")["terms"].__setitem__("no_ai", True), ()),
    ("条款禁止自动抓取却由读取工具直接读", "V-12", lambda d: src(d, "SRC-000007").__setitem__("fetched_by", "ai_tool"), ()),
    ("只有摘要却标全文", "V-13", lambda d: src(d, "SRC-000003").__setitem__("access_scope", "full"), ()),
    ("没买的付费来源标了全文", "V-13", lambda d: src(d, "SRC-000011").update(access_route="public_web", access_scope="full"), ()),
    ("没买的付费来源没写评估单在哪", "V-13", lambda d: src(d, "SRC-000011")["paid"].pop("assessment"), ()),
    ("只到题录的来源出了证据", "V-13", lambda d: src(d, "SRC-000001").update(access_route="metadata", access_scope="metadata_only"), ()),
    ("新闻当证据来源", "V-14", lambda d: src(d, "SRC-000002").__setitem__("source_type", "news"), ()),
    ("政策法规没写法域", "V-15", lambda d: src(d, "SRC-000005").pop("jurisdiction"), ()),
    ("纳入的专利没记法律状态", "V-15", lambda d: src(d, "SRC-000004")["doc"].pop("status"), ()),
    ("专利的法律状态填了进程", "V-15", lambda d: src(d, "SRC-000004")["doc"]["status"].__setitem__("stage", "in_force"), ()),
    ("政策法规的状态没写进程", "V-15", lambda d: src(d, "SRC-000005")["doc"]["status"].pop("stage"), ()),
    ("资助记录没写项目号", "V-15", lambda d: src(d, "SRC-000006")["doc"].pop("project_number"), ()),
    ("写了金额没写币种", "V-15", lambda d: src(d, "SRC-000006")["doc"].pop("currency"), ()),
    ("学位论文没写取用的部分", "V-15", lambda d: src(d, "SRC-000001").__setitem__("source_type", "thesis"), ()),
    ("预印本和正式版没有互相指向", "V-16", lambda d: src(d, "SRC-000008").pop("version_of"), ()),
    ("被更正的来源没标已更正", "V-16", lambda d: src(d, "SRC-000003").__setitem__("status", "active"), ()),
    ("标了已更正却没有更正声明", "V-16", lambda d: src(d, "SRC-000010").pop("corrects"), ()),
    ("读了全文的论文没写核心指标找过的结果", "V-17", lambda d: src(d, "SRC-000007")["topics"][0].pop("core_check"), ()),
    ("核心指标漏了一项", "V-17", lambda d: src(d, "SRC-000001")["topics"][0]["core_check"].pop("area_resistance"), ()),
    ("写了找到却没有证据", "V-17", lambda d: src(d, "SRC-000001")["topics"][0]["core_check"].__setitem__("area_resistance", "found"), ()),
    ("有证据却写原文没报告", "V-17", lambda d: src(d, "SRC-000001")["topics"][0]["core_check"].__setitem__("energy_efficiency", "not_reported"), ()),
    # ---- 样品登记
    ("样品名不在登记里", "V-19", lambda d: ev(d, "EV-000001-001").__setitem__("sample_label", "X-9"), ()),
    ("证据的对象和登记的不一致", "V-19", lambda d: ev(d, "EV-000001-001").__setitem__("subject_id", "ENT-000007"), ()),
    ("实验室样品没有登记", "V-19", lambda d: d["samples"]["SRC-000003"].clear(), ()),
    ("同文基准没写形态", "V-19", lambda d: smp(d, "SRC-000001", "P-212").pop("baseline_form"), ()),
    ("重铸的基准膜指向了产品", "V-19", lambda d: smp(d, "SRC-000001", "P-212").__setitem__("baseline_form", "recast"), ()),
    ("样品登记缺对象", "V-19", lambda d: smp(d, "SRC-000001", "X-1").pop("subject_id"), ()),
    # ---- 证据
    ("层级与指标不一致", "V-21", lambda d: ev(d, "EV-000001-001").__setitem__("level", "material"), ()),
    ("给不录入的指标建了证据", "V-21", lambda d: ev(d, "EV-000001-001").__setitem__("indicator", "max_current_density"), ()),
    ("数值型没有指标也没有事实项", "V-21", lambda d: ev(d, "EV-000011-001").pop("fact"), ()),
    ("事实项的层级不对", "V-21", lambda d: ev(d, "EV-000011-001").__setitem__("level", "system"), ()),
    ("漏填必填条件", "V-22", lambda d: ev(d, "EV-000001-001")["conditions"].pop("temperature"), ()),
    ("事实项的必填条件漏了", "V-22", lambda d: ev(d, "EV-000011-001")["conditions"].pop("year"), ()),
    ("单位不在允许范围", "V-23", lambda d: ev(d, "EV-000002-001").__setitem__("unit_reported", "ohm"), ()),
    ("事实项的单位不在允许范围", "V-23", lambda d: ev(d, "EV-000011-001").__setitem__("unit_reported", "GW"), ()),
    ("换算值不一致", "V-23", lambda d: ev(d, "EV-000001-001").__setitem__("value_std", 8.56), ()),
    ("不换算的单位填了 value_std", "V-23", lambda d: (d["dictionaries"][T]["facts"][2]["units_accepted"].append({"unit": "GW"}),
                                                   ev(d, "EV-000011-001").__setitem__("unit_reported", "GW")), ()),
    ("缺原文片段", "V-24", lambda d: ev(d, "EV-000001-002").pop("snippet"), ()),
    ("全文来源却标仅摘要", "V-25", lambda d: ev(d, "EV-000001-001").__setitem__("obtained_from", "abstract_only"), ()),
    ("出处只写到来源", "V-26", lambda d: ev(d, "EV-000001-001").__setitem__("locator", {"text": "见论文"}), ()),
    ("AI 标成人工已核", "V-27", lambda d: ev(d, "EV-000003-001").__setitem__("verified_by", "claude"), ()),
    ("机器核对没过却标已核", "V-27", lambda d: ev(d, "EV-000002-001")["machine_check"].__setitem__("snippet", "fail"), ()),
    ("存疑没写说明", "V-27", lambda d: ev(d, "EV-000003-001").__setitem__("verification_status", "disputed"), ()),
    ("来源撤稿后证据没处理", "V-28", lambda d: src(d, "SRC-000003").__setitem__("status", "retracted"), ()),
    ("基准指到了别的来源", "V-29", lambda d: ev(d, "EV-000001-001").__setitem__("baseline_ref", "EV-000003-001"), ()),
    ("基准指到了同文对照", "V-29", lambda d: ev(d, "EV-000001-001").__setitem__("baseline_ref", "EV-000001-004"), ()),
    ("同文对照指到了基准膜", "V-29", lambda d: ev(d, "EV-000001-001").__setitem__("control_ref", "EV-000001-002"), ()),
    ("人工已核的证据没标风险档", "V-31", lambda d: ev(d, "EV-000003-001").pop("risk"), ()),
    ("图上读数标成低风险", "V-31", lambda d: ev(d, "EV-000001-003")["risk"].__setitem__("tier", "low"), ()),
    ("风险理由漏了推得出的", "V-31", lambda d: ev(d, "EV-000003-001")["risk"].__setitem__("reasons", []), ()),
    ("厂商规格书的数标成实验数据", "V-32", lambda d: ev(d, "EV-000002-001").__setitem__("evidence_type", "experimental"), ()),
    ("政策法规的证据没写对应的问题", "V-33", lambda d: ev(d, "EV-000005-001").pop("questions"), ()),
    ("问题编号不在题目卡里", "V-33", lambda d: ev(d, "EV-000005-001").__setitem__("questions", ["Q9"]), ()),
    ("事实项对应的问题没写进 questions", "V-33", lambda d: ev(d, "EV-000005-001").__setitem__("questions", ["Q4"]), ()),
    # ---- 关系
    ("推断的关系标成已核", "V-30", lambda d: d["relations"]["REL-000003"].update(verification_status="human_verified", verified_by="kai", verified_at=DAY), ()),
    ("有出处的关系没写转述", "V-30", lambda d: d["relations"]["REL-000001"].pop("summary"), ()),
    # ---- 可比组
    ("跨层级放进一组", "V-40", lambda d: d["comparisons"]["CMP-000001"]["members"].append({"evidence_id": "EV-000002-001", "role": "member"}), ()),
    ("可比组建在合规层", "V-40", lambda d: d["comparisons"]["CMP-000003"].__setitem__("level", "compliance"), ()),
    ("可比组拿约束性的规则作依据", "V-40", lambda d: d["dictionaries"][T]["rules"][0].pop("tier_if_met"), ()),
    ("可比组的指标不在规则适用的指标里", "V-40", lambda d: d["dictionaries"][T]["rules"][0].__setitem__("applies_to", ["max_current_density"]), ()),
    ("陈述放进了可比组", "V-40", lambda d: d["comparisons"]["CMP-000003"]["members"].append({"evidence_id": "EV-000004-001", "role": "member"}), ()),
    ("仅摘要进直接可比", "V-41", lambda d: d["comparisons"]["CMP-000001"]["members"].append({"evidence_id": "EV-000003-001", "role": "member"}), ()),
    ("条件未报告进直接可比，组上没写", "V-41", lambda d: ev(d, "EV-000001-002")["conditions"].__setitem__("temperature", "not_reported"), ()),
    ("写了缺的条件却没写同一套条件的依据", "V-41", lambda d: (ev(d, "EV-000001-002")["conditions"].__setitem__("temperature", "not_reported"),
                                               d["comparisons"]["CMP-000001"].__setitem__("missing_conditions", ["temperature"])), ()),
    ("归一化的组定为直接可比", "V-42", lambda d: d["comparisons"]["CMP-000002"].__setitem__("tier", "direct"), ()),
    ("AI 定档", "V-43", lambda d: d["comparisons"]["CMP-000001"].__setitem__("decided_by", "claude"), ()),
    ("作废的证据留在组里", "V-44", lambda d: ev(d, "EV-000001-002").update(verification_status="void", void_reason="示例"), ()),
    ("直接可比的组里混进了别的来源", "V-45", lambda d: d["comparisons"]["CMP-000001"]["members"].append({"evidence_id": "EV-000007-001", "role": "member"}), ()),
    ("直接可比的组里不是同一批测试", "V-45", lambda d: ev(d, "EV-000001-002").__setitem__("series_label", "S2"), ()),
    ("与基准之比的组没写基准膜", "V-46", lambda d: d["comparisons"]["CMP-000002"].pop("baseline_subject_id"), ()),
    ("不同型号的基准膜放进了一组", "V-46", lambda d: d["comparisons"]["CMP-000002"].__setitem__("baseline_subject_id", "ENT-000002"), ()),
    ("重铸的和商业的放进了一组", "V-46", lambda d: d["comparisons"]["CMP-000002"].__setitem__("baseline_class", "recast"), ()),
    ("关键条件不相同", "V-47", lambda d: ev(d, "EV-000004-002")["conditions"].__setitem__("current_density", {"reported": "100 mA cm-2", "value": 100, "unit": "mA/cm2"}), ()),
    ("关键条件没报告却进条件化比较", "V-47", lambda d: ev(d, "EV-000004-002")["conditions"].__setitem__("current_density", "not_reported"), ()),
    # ---- 复核单
    ("专业已复核的可比组没有复核单", "V-48", lambda d: d["reviews"].clear(), ()),
    ("已复核的复核单里有未定的条目", "V-48", lambda d: d["reviews"]["RVW-000001"]["items"][0].__setitem__("decision", "pending"), ()),
    ("改了却没写变化记录", "V-48", lambda d: d["reviews"]["RVW-000001"]["items"][1].__setitem__("decision", "modify"), ()),
    ("复核单没覆盖全部成员", "V-48", lambda d: d["reviews"]["RVW-000001"].pop("batch"), ()),
    ("证据上的复核人与复核单不一致", "V-48", lambda d: ev(d, "EV-000001-001").__setitem__("expert_reviewed_by", "expert-01"), ()),
    ("AI 当了复核人", "V-48", lambda d: d["reviews"]["RVW-000001"].__setitem__("reviewer", "claude"), ()),
    # ---- 判断与描述
    ("判断没写成立条件", "V-50", lambda d: d["assessments"]["ASM-000001"].__setitem__("layer", "judgment"), ()),
    ("现阶段用了判断这一层", "V-51", lambda d: d["assessments"]["ASM-000001"].update(layer="judgment", conditions="示例", unknowns="示例"), ()),
    # ---- 对外
    ("机器已核的证据进了已发出的报告", "V-60", lambda d: report(d, evidence_ids=["EV-000002-001"]), ()),
    ("已发出的报告没附证据数据文件", "V-60", lambda d: (report(d, evidence_ids=["EV-000005-001"]), d["reports"]["RPT-000001"].pop("evidence_file")), ()),
    ("报告用到的政策，登记内容没人核对", "V-60", lambda d: (src(d, "SRC-000005").pop("record_verified_by"), report(d, evidence_ids=["EV-000005-001"])), ()),
    ("出报告时题目卡没写截至日期", "V-60", lambda d: (d["topics"][T].pop("cutoff_date"), report(d, evidence_ids=["EV-000005-001"])), ()),
    ("草稿状态的可比组拿去对外", "V-61", lambda d: None, ("CMP-000002",)),
    ("图上读数没复读就对外", "V-62", lambda d: (ev(d, "EV-000001-003")["figure_read"].pop("reread_by"), report(d, evidence_ids=["EV-000001-003"])), ()),
    ("只给链接的来源被报告引用", "V-63", lambda d: (src(d, "SRC-000001").__setitem__("external_use", "link_only"), report(d, evidence_ids=["EV-000001-001"])), ()),
    ("没核过的关系进了已发出的报告", "V-65", lambda d: report(d, rel_ids=["REL-000002"]), ()),
    ("出报告前没再查政策的状态", "V-66", lambda d: (src(d, "SRC-000005")["doc"]["status"].__setitem__("checked_at", "2026-10-01"), report(d, evidence_ids=["EV-000005-001"])), ()),
    # ---- 日志
    ("更正没写错误类型", "V-70", lambda d: d["changes"][0].pop("error_type"), ()),
    ("人工工时没记", "V-71", lambda d: d["worklog"][1].pop("minutes"), ()),
    ("来源获取的工时没记", "V-71", lambda d: d["worklog"][2].pop("minutes"), ()),
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


def test_every_rule_has_a_broken_case():
    """校验脚本里出现的每一条规则，都至少有一处改错的测试（V-64 是导出，V-72 要看 git，各有单独的测试）。"""
    code = open(os.path.join(TOOLS, "validate.py"), encoding="utf-8").read()
    in_code = set(re.findall(r'"(V-\d\d)"', code))
    covered = {rule for _, rule, _, _ in CASES} | {"V-64", "V-72"}
    assert in_code <= covered, sorted(in_code - covered)


def test_issued_report_passes():
    ds = fresh()
    report(ds, evidence_ids=["EV-000005-001", "EV-000004-001"], cmp_ids=["CMP-000001"])
    assert V.validate(ds, SCHEMA) == []


def test_same_paper_exception_passes():
    """D-64 第三条：同文同批的对照，原文漏写了某项条件，组上写明缺哪项、写明同一套条件的依据，可以定为直接可比。"""
    ds = fresh()
    ev(ds, "EV-000001-002")["conditions"]["temperature"] = "not_reported"
    ds["comparisons"]["CMP-000001"].update(missing_conditions=["temperature"],
                                           same_setup_note="第 5 页写明两种膜在同一套电池里先后测试（示例）")
    assert V.validate(ds, SCHEMA, ["CMP-000001"]) == []


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
            f.write('{"id": "LOG-000005"}\n')
        assert V.check_append_only(data) == []          # 末尾追加：可以
        lines = open(log, encoding="utf-8").read().splitlines()
        open(log, "w", encoding="utf-8").write("\n".join(lines[1:]) + "\n")
        assert [i.rule for i in V.check_append_only(data)] == ["V-72"]   # 删了已提交的行：不行


def test_export_drops_internal_fields():
    row = V.strip_internal(ev(fresh(), "EV-000001-003"))
    assert not (set(row) & V.INTERNAL_ONLY)
    assert "risk" not in row
    assert set(row["figure_read"]) <= {"reading_error", "source_data_checked"}
    assert row["locator"] and row["conditions"]


def test_display_flags():
    ds = fresh()

    def flags(i):
        e = ev(ds, i)
        return V.display_flags(e, ds["sources"][e["source_id"]])
    assert flags("EV-000007-001") == ["preprint"]
    assert flags("EV-000004-002") == ["patent_example"]
    assert flags("EV-000004-001") == []
    assert flags("EV-000002-001") == ["company_claim"]
    assert flags("EV-000001-003") == ["figure_read"]
    assert flags("EV-000011-001") == ["abstract_only", "not_purchased"]
    labels = json.load(open(os.path.join(REPO, "data", "labels.json"), encoding="utf-8"))["flags"]
    assert {"preprint", "thesis", "patent_example", "company_claim", "figure_read", "abstract_only", "not_purchased"} <= set(labels)


def test_labels_cover_every_enum_value():
    labels = json.load(open(os.path.join(REPO, "data", "labels.json"), encoding="utf-8"))["enums"]
    for name, node in SCHEMA["$defs"].items():
        if name.startswith("enum_"):
            got = labels.get(name[5:], {})
            assert set(got) == set(node["enum"]), name
            assert all(v.get("zh") and "en" in v for v in got.values()), name


def test_unconverted_unit_passes():
    """照原文记、不换算的单位（如装机的 GW、价格的币种）：不填 value_std，也不算“换算过单位”的风险理由。"""
    ds = fresh()
    ds["dictionaries"][T]["facts"][2]["units_accepted"].append({"unit": "GW"})
    e = ev(ds, "EV-000011-001")
    e["unit_reported"] = "GW"
    del e["value_std"]
    # 示例里这条是约数，本来就有 qualified_value；只看会不会多要一条 unit_converted
    e["risk"] = {"tier": "medium", "reasons": ["qualified_value"], "set_by": "claude", "set_at": DAY}
    assert V.validate(ds, SCHEMA) == []


def test_labels_cover_repo_topics():
    """仓库里题目卡和指标字典用到的取值、单位，labels.json 里都有显示名（看板和中英两版报告从这里取）。"""
    labels = json.load(open(os.path.join(REPO, "data", "labels.json"), encoding="utf-8"))
    values, units = labels["values"], labels["units"]
    ds = V.load_dataset(os.path.join(REPO, "data"))
    missing = []

    def named(group, code):
        v = values.get(group, {}).get(code)
        if not (v and v.get("zh") and v.get("en")):
            missing.append(f"{group}.{code}")

    def unit_named(u):
        v = units.get(u)
        if not (isinstance(v, str) or (isinstance(v, dict) and v.get("zh") and v.get("en"))):
            missing.append(f"单位 {u}")

    for t in ds["topics"].values():
        for f in t.get("facets") or []:
            for code in f.get("values") or []:
                named(f["key"], code)
    for d in ds["dictionaries"].values():
        for x in d.get("conditions", []) + d.get("indicators", []) + d.get("facts", []):
            for code in x.get("allowed_values") or []:
                named(x["key"], code)
            for u in [x.get("unit_std")] + [y["unit"] for y in x.get("units_accepted", [])]:
                if u:
                    unit_named(u)
    assert not missing, missing


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
    rules = sorted({r for _, r, _, _ in CASES})
    print(f"{len(CASES)} 处改错，涉及 {len(rules)} 条规则" + ("，全部被对应的规则报出" if not failed else ""), "｜失败", failed)
    sys.exit(1 if failed else 0)
