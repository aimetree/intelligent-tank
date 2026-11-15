#!/usr/bin/env python3
"""登记与机器核对这几个脚本的测试。直接跑：python3 tools/tests/test_step1.py；也可以用 pytest。

和 test_validate.py 一个做法：tools/tests/example/ 的示例数据（全部虚构）照现在的写法应当原样通过；
再逐处把它改错，每改一处，对应的检查必须报出来。来源文本在 tools/tests/example_texts/，也是虚构的。
要联网的检查（check_identifiers.py）这里用假的网络应答来测，不发真的请求。
"""
import contextlib
import copy
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

import check_identifiers as C  # noqa: E402
import compare_extractions as X  # noqa: E402
import ids as I  # noqa: E402
import machine_check as M  # noqa: E402
import store  # noqa: E402
import textmatch as T  # noqa: E402
import validate as V  # noqa: E402

SCHEMA = V.load_schema()
EXAMPLE = os.path.join(HERE, "example")
TEXTS = os.path.join(HERE, "example_texts")
DAY = "2026-11-11"
LATER = "2026-11-20"


def fresh():
    return V.load_dataset(EXAMPLE)


@contextlib.contextmanager
def example_copy():
    """示例数据的一份临时拷贝，写回文件的测试用。"""
    with tempfile.TemporaryDirectory() as tmp:
        data = os.path.join(tmp, "data")
        shutil.copytree(EXAMPLE, data)
        yield data


def ev(ds, i):
    return ds["evidence"][i]


def src(ds, sid):
    return ds["sources"][sid]


def quiet(fn, *args):
    """跑一个命令行入口，不让它的输出混进测试结果。返回 (退出码, 输出)。"""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = fn(*args)
    return code, out.getvalue()


# ---------------------------------------------------------------- 编号

def test_next_ids():
    ds = fresh()
    assert I.next_ids(ds, "SRC") == ["SRC-000012"]
    assert I.next_ids(ds, "EV", source_id="SRC-000001") == ["EV-000001-005"]
    assert I.next_ids(ds, "EV", 3, "SRC-000012") == ["EV-000012-001", "EV-000012-002", "EV-000012-003"]
    assert I.next_ids(ds, "CMP", 2) == ["CMP-000004", "CMP-000005"]
    assert I.next_ids(ds, "RVW") == ["RVW-000005"]
    assert I.next_ids(ds, "TOP") == ["TOP-000002"]
    for kind, key in (("LOG", "worklog"), ("CHG", "changes")):
        used = {r["id"] for r in ds[key]}
        (new,) = I.next_ids(ds, kind)
        assert new not in used and int(new[4:]) == max(int(x[4:]) for x in used) + 1


def test_next_ids_counts_files_that_do_not_load():
    """读不了的来源文件也占着号，不能把它的号再分出去。"""
    with example_copy() as data:
        with open(os.path.join(data, "public", "sources", "SRC-000020.json"), "w", encoding="utf-8") as f:
            f.write("{ 这不是合法的 JSON")
        assert I.next_ids(V.load_dataset(data), "SRC") == ["SRC-000021"]


def test_ids_bad_usage():
    ds = fresh()
    for args in (("EV",), ("EV", 1, "SRC-12"), ("XYZ",), ("SRC", 0)):
        try:
            I.next_ids(ds, *args)
        except ValueError:
            continue
        raise AssertionError(f"应当拒绝 {args}")
    assert quiet(I.main, ["EV", "--data", EXAMPLE])[0] == 2
    assert quiet(I.main, ["SRC", "--data", EXAMPLE]) == (0, "SRC-000012\n")


# ---------------------------------------------------------------- 原文比对

def test_norm():
    assert T.norm("mA cm⁻²\tat\n80 %") == "mA cm-2 at 80 %"
    assert T.norm("８５．６") == "85.6"                       # 全角数字
    assert T.norm("eﬃciency “high”") == 'efficiency "high"'    # 连字、弯引号
    assert T.norm("co­polymer − 5") == "copolymer - 5"              # 软连字符、减号


SNIPPET_CASES = [
    ("逐字", "X-1 98.1 87.3 85.6", "Table 2\nX-1\t98.1\t87.3\t85.6\nP-212", True),
    ("表格的一行被拆成几行", "Z-1 97.0 83.0 80.5", "Z-1\n97.0\n83.0\n80.5", True),
    ("原文少了空格", "Area resistance 0.45 Ω cm²", "Area resistance0.45 Ω cm²", True),
    ("原文行尾断词", "fluoropolymers are within scope", "fluoro-\npolymers are within scope", True),
    ("上标和减号的写法不同", "at 80 mA cm-2", "at 80 mA cm⁻² in", True),
    ("中文和全角括号", "示例摘要（虚构）", "项目摘要：示例摘要(虚构)", True),
    ("数字不一样", "X-1 98.1 87.3 85.7", "X-1 98.1 87.3 85.6", False),
    ("大小写不放宽", "area resistance 0.45", "Area resistance 0.45", False),
    ("片段太短", "85.6", "X-1 98.1 87.3 85.6", False),
    ("原文里没有", "an energy efficiency of 90%", "an energy efficiency of 84.0%", False),
]


def test_find_snippet():
    wrong = [name for name, snippet, text, want in SNIPPET_CASES if T.find_snippet(snippet, text)[0] != want]
    assert not wrong, wrong


VALUE_CASES = [
    ("表格里的一格", "85.6", "X-1 98.1 87.3 85.6", True),
    ("后面跟着百分号", "84", "above 84% at 80 mA cm-2", True),
    ("句末", "85.6", "the efficiency was 85.6.", True),
    ("科学记数", "1.2×10-7", "D = 1.2 × 10⁻⁷ cm² min⁻¹", True),
    ("x 当乘号", "3.4×10-9", "3.4 x 10-9 cm2/min", True),
    ("负数", "-0.5", "a shift of −0.5 V", True),
    ("更长的数的后半截", "85.6", "185.6 mS/cm", False),
    ("更长的数的前半截", "85.6", "85.65 %", False),
    ("少了乘 10 的幂", "1.2", "1.2 × 10−7 cm2/min", False),
    ("片段里是负数", "0.5", "a shift of -0.5 V", False),
    ("样品名里的数字", "1", "X-1 membrane", False),
    ("型号里的数字", "212", "N212 was used", False),
    ("抄错了数位", "86.5", "X-1 98.1 87.3 85.6", False),
]


def test_find_value():
    wrong = [name for name, value, snippet, want in VALUE_CASES if bool(T.find_value(value, snippet)) != want]
    assert not wrong, wrong


def test_unit_key():
    same = [("mA/cm2", "mA cm-2", "mA·cm⁻²", "mA cm−2"), ("mS/cm", "mS cm-1"), ("ohm*cm2", "Ω cm²", "Ω·cm2"),
            ("mohm*cm2", "mΩ cm2"), ("S*min/cm3", "S min cm-3"), ("cm2/min", "cm² min⁻¹"), ("mol/L", "M", "mol L-1", "mol dm-3"),
            ("degC", "°C"), ("um", "μm", "µm"), ("%/cycle", "% per cycle"), ("h", "hours", "hr"), ("%/d", "% per day")]
    for group in same:
        assert len({T.unit_key(u) for u in group}) == 1, group
    keys = [T.unit_key(g[0]) for g in same] + [T.unit_key("S/cm"), T.unit_key("%")]
    assert len(set(keys)) == len(keys), "不同的单位不能得到同一个键"
    assert T.unit_key("1") == "" and T.unit_key("") == ""


UNIT_CASES = [
    ("单位一致", "0.45", "ohm*cm2", ["ohm*cm2", "mohm*cm2"], "Area resistance 0.45 Ω cm²", "pass"),
    ("片段里没有单位", "85.6", "%", ["%", "1"], "X-1 98.1 87.3 85.6", "pass"),
    ("百分号紧跟着数值", "84", "%", ["%", "1"], "an energy efficiency above 84% at 80 mA cm-2", "pass"),
    ("每圈的衰减", "0.05", "%/cycle", ["%", "%/cycle"], "a decay of 0.05% per cycle over 500 cycles", "pass"),
    ("认不出的单位不算不一致", "250", "EUR/m2", ["EUR/m2", "USD/m2"], "a membrane price of 250 € m-2", "pass"),
    ("差了一千倍的单位", "0.085", "mS/cm", ["mS/cm", "S/cm", "S/m"], "a conductivity of 0.085 S cm-1 at 25 °C", "fail"),
    ("币种不对", "250", "USD/m2", ["EUR/m2", "USD/m2"], "a price of 250 EUR/m2 was assumed", "fail"),
    ("片段里没有这个数值", "86.5", "%", ["%"], "X-1 98.1 87.3 85.6", "fail"),
]


def test_check_value_unit():
    wrong = [name for name, value, unit, units, snippet, want in UNIT_CASES
             if T.check_value_unit(value, unit, units, snippet)[0] != want]
    assert not wrong, wrong


# ---------------------------------------------------------------- 机器核对

def test_machine_check_reproduces_example():
    """示例数据里已经写好的机器核对结果、状态和风险档，脚本照着示例的来源文本重算，得到的是同样的；
    待核的两条查过之后成了机器已核；人工已核及以上的不动；写回之后校验照样通过。"""
    with example_copy() as data:
        ds = V.load_dataset(data)
        before = copy.deepcopy(ds["evidence"])
        rows, touched = M.run(ds, TEXTS, DAY)
        assert rows and all(r.outcome == "pass" for r in rows), [r for r in rows if r.outcome != "pass"]
        for i, old in before.items():
            new = ev(ds, i)
            if old["verification_status"] not in M.OPEN:
                assert new == old, f"{i} 已经核过，不应当改动"
                continue
            if "machine_check" in old:
                assert new["machine_check"] == old["machine_check"], i
                assert new["verification_status"] == old["verification_status"], i
            if "risk" in old:
                assert new["risk"] == old["risk"], i
        for i in ("EV-000006-001", "EV-000011-001"):
            assert before[i]["verification_status"] == "pending" and ev(ds, i)["verification_status"] == "machine_checked"
        assert ev(ds, "EV-000006-001")["machine_check"] == {"identifier": "pass", "snippet": "pass", "value_unit": "na", "at": DAY}
        assert ev(ds, "EV-000011-001")["risk"]["reasons"] == ["qualified_value"]
        assert V.validate(ds, SCHEMA) == []
        store.save_sources(ds, touched)
        again = V.load_dataset(data)
        assert V.validate(again, SCHEMA) == []
        assert M.run(again, TEXTS, LATER)[1] == set(), "结果没变，重跑不应当再改文件（日期也不动）"


def _unverify(ds, i):
    e = ev(ds, i)
    for k in ("verified_by", "verified_at", "expert_reviewed_by", "expert_reviewed_at"):
        e.pop(k, None)
    e["verification_status"] = "pending"


# (说明, 怎么改错, 证据, 应当得到的 machine_check 字段, 应当得到的状态)
MACHINE_CASES = [
    ("片段和原文差一个数字", lambda d: ev(d, "EV-000001-004").__setitem__("snippet", "X-0 97.5 85.2 83.2"),
     "EV-000001-004", {"snippet": "fail"}, "pending"),
    ("数值抄错了数位，片段没错", lambda d: ev(d, "EV-000001-004").__setitem__("value_reported", "81.3"),
     "EV-000001-004", {"snippet": "pass", "value_unit": "fail"}, "pending"),
    ("数值是更长的数的一截", lambda d: ev(d, "EV-000001-004").__setitem__("value_reported", "3.1"),
     "EV-000001-004", {"value_unit": "fail"}, "pending"),
    ("单位和片段里的不一致", lambda d: ev(d, "EV-000002-001").__setitem__("unit_reported", "mohm*cm2"),
     "EV-000002-001", {"snippet": "pass", "value_unit": "fail"}, "pending"),
    ("来源的标识没通过解析", lambda d: src(d, "SRC-000007")["id_check"].__setitem__("result", "fail"),
     "EV-000007-001", {"identifier": "fail", "snippet": "pass"}, "pending"),
    ("来源还没有查过标识", lambda d: src(d, "SRC-000007").pop("id_check"),
     "EV-000007-002", {"identifier": "fail"}, "pending"),
    ("条件的片段原文里没有", lambda d: ev(d, "EV-000004-002").__setitem__("conditions_snippet", "at 120 mA/cm2 and 40 degC"),
     "EV-000004-002", {"snippet": "fail", "value_unit": "pass"}, "pending"),
    ("没有原文片段", lambda d: ev(d, "EV-000004-002").pop("snippet"),
     "EV-000004-002", {"snippet": "fail"}, "pending"),
    ("陈述型的片段原文里没有", lambda d: ev(d, "EV-000006-001").__setitem__("snippet", "另一段摘要（虚构）"),
     "EV-000006-001", {"snippet": "fail", "value_unit": "na"}, "pending"),
]


def test_machine_check_reports_each_broken_case():
    missed = []
    for name, mutate, i, want, status in MACHINE_CASES:
        ds = fresh()
        mutate(ds)
        rows, _ = M.run(ds, TEXTS, DAY)
        row = next(r for r in rows if r.id == i)
        mc = ev(ds, i)["machine_check"]
        if row.outcome != "fail" or any(mc[k] != v for k, v in want.items()) or ev(ds, i)["verification_status"] != status:
            missed.append(f"{name}：{mc}，状态 {ev(ds, i)['verification_status']}")
        elif not row.notes:
            missed.append(f"{name}：没有说明哪里不对")
    assert not missed, missed


def test_machine_check_failure_is_high_risk_and_clears_when_fixed():
    ds = fresh()
    e = ev(ds, "EV-000001-004")
    good = e["snippet"]
    e["snippet"] = "X-0 97.5 85.2 83.2"
    M.run(ds, TEXTS, DAY)
    assert e["verification_status"] == "pending" and e["risk"]["tier"] == "high"
    assert "machine_check_failed" in e["risk"]["reasons"]
    assert "V-27" not in {x.rule for x in V.validate(ds, SCHEMA)}, "退回待核之后，状态和机器核对的结果是一致的"
    e["snippet"] = good
    M.run(ds, TEXTS, LATER)
    assert e["verification_status"] == "machine_checked" and e["machine_check"]["at"] == LATER
    assert e["risk"] == {"tier": "medium", "reasons": ["multiple_samples_or_tables"], "set_by": "script", "set_at": LATER}
    assert V.validate(ds, SCHEMA) == []


def test_machine_check_without_source_text():
    """没有来源文本，片段没法查：待核的不写结果、留在待核；已经是机器已核的不动。"""
    with tempfile.TemporaryDirectory() as empty:
        ds = fresh()
        before = copy.deepcopy(ds["evidence"])
        rows, _ = M.run(ds, empty, DAY, sources={"SRC-000006", "SRC-000007"})
        assert {r.id: r.outcome for r in rows} == {"EV-000006-001": "no_text", "EV-000007-001": "no_text", "EV-000007-002": "no_text"}
        assert "machine_check" not in ev(ds, "EV-000006-001") and ev(ds, "EV-000006-001")["verification_status"] == "pending"
        assert ev(ds, "EV-000007-001")["machine_check"] == before["EV-000007-001"]["machine_check"]
        assert ev(ds, "EV-000007-001")["verification_status"] == "machine_checked"
        assert quiet(M.main, ["--texts", empty, "--data", EXAMPLE, "--source", "SRC-000006"])[0] == 1


def test_machine_check_figure_read():
    """图上读数没有片段可比：只看标识，snippet、value_unit 写不适用，风险档是高。"""
    ds = fresh()
    _unverify(ds, "EV-000001-003")
    M.run(ds, TEXTS, DAY)
    e = ev(ds, "EV-000001-003")
    assert e["machine_check"] == {"identifier": "pass", "snippet": "na", "value_unit": "na", "at": DAY}
    assert e["verification_status"] == "machine_checked" and e["risk"]["tier"] == "high"


def test_machine_check_leaves_verified_evidence_alone():
    ds = fresh()
    e = ev(ds, "EV-000003-001")           # 人工已核
    e["snippet"] = "这个片段原文里没有（示例）"
    snapshot = copy.deepcopy(e)
    rows, touched = M.run(ds, TEXTS, DAY)
    assert e == snapshot and "EV-000003-001" not in {r.id for r in rows} and "SRC-000003" not in touched


def test_risk_prefill_keeps_manual_reasons():
    ds = fresh()
    a, b = ev(ds, "EV-000001-004"), ev(ds, "EV-000002-001")
    a["risk"] = {"tier": "high", "reasons": ["outlier"], "set_by": "claude", "set_at": DAY}
    b["risk"] = {"tier": "high", "reasons": ["other"], "note": "规格书的版本号对不上（示例）", "set_by": "claude", "set_at": DAY}
    M.run(ds, TEXTS, LATER)
    assert a["risk"]["tier"] == "high" and a["risk"]["reasons"] == ["outlier", "multiple_samples_or_tables"]
    assert b["risk"] == {"tier": "high", "reasons": ["other"], "note": "规格书的版本号对不上（示例）", "set_by": "claude", "set_at": DAY}
    assert V.validate(ds, SCHEMA) == []


def test_machine_check_cli_writes_back():
    with example_copy() as data:
        code, out = quiet(M.main, ["--texts", TEXTS, "--data", data, "--date", DAY])
        assert code == 0 and "没有写回" in out
        assert V.load_dataset(data)["evidence"]["EV-000006-001"]["verification_status"] == "pending"
        code, out = quiet(M.main, ["--texts", TEXTS, "--data", data, "--date", DAY, "--write"])
        assert code == 0 and "写回了 3 个来源文件" in out, out
        ds = V.load_dataset(data)
        assert ds["evidence"]["EV-000006-001"]["verification_status"] == "machine_checked"
        assert V.validate(ds, SCHEMA) == []
        for sid in ("SRC-000001", "SRC-000007"):   # 没改的文件一个字节都不变
            name = os.path.join("public", "sources", sid + ".json")
            assert open(os.path.join(data, name), "rb").read() == open(os.path.join(EXAMPLE, name), "rb").read()


# ---------------------------------------------------------------- 两遍抽取的比对

REGISTRATION_ONLY = ("id", "record_version", "created_by", "created_at", "verification_status", "double_extraction",
                     "machine_check", "risk", "verified_by", "verified_at", "expert_reviewed_by", "expert_reviewed_at",
                     "baseline_ref", "control_ref", "value_std", "series_label")


def a_pass(sid="SRC-000001"):
    """把示例数据里一个来源的证据当成一遍抽取的结果：去掉登记时才有的字段。"""
    ds = fresh()
    return [{k: v for k, v in e.items() if k not in REGISTRATION_ONLY}
            for i, e in sorted(ds["evidence"].items()) if e["source_id"] == sid]


def test_compare_identical_passes():
    p1 = a_pass()
    report = X.compare(p1, copy.deepcopy(p1))
    s = report["summary"]
    assert (s["agree"], s["figure_read"], s["mismatch"], s["only_pass1"], s["only_pass2"]) == (3, 1, 0, 0, 0)
    assert s["mismatch_rate"] == 0.0
    assert all(r["double_extraction"] == "agree" for r in report["agree"])
    assert report["figure_read"][0]["record"]["double_extraction"] == "na"


def _by_sample(rows, label, at=None):
    return next(r for r in rows if r.get("sample_label") == label and r.get("obtained_from") != "figure_read"
                and (at is None or r["conditions"]["current_density"]["value"] == at))


# (说明, 怎么改第二遍, 应当落在哪一组, 应当报出的字段)
COMPARE_CASES = [
    ("数值不一样", lambda p: _by_sample(p, "X-1").__setitem__("value_reported", "86.5"), "mismatch", "value_reported"),
    ("数值的写法不一样", lambda p: _by_sample(p, "X-1").__setitem__("value_reported", "85.60"), "mismatch", "value_reported"),
    ("单位不一样", lambda p: _by_sample(p, "X-1").__setitem__("unit_reported", "1"), "mismatch", "unit_reported"),
    ("条件不一样", lambda p: _by_sample(p, "X-0")["conditions"].__setitem__("temperature", {"reported": "30 °C", "value": 30, "unit": "degC"}),
     "mismatch", "conditions.temperature"),
    ("一遍写了未报告", lambda p: _by_sample(p, "X-0")["conditions"].__setitem__("temperature", "not_reported"),
     "mismatch", "conditions.temperature"),
    ("一遍解析出了条件的值，另一遍只照抄了原文", lambda p: _by_sample(p, "X-0")["conditions"].__setitem__("temperature", {"reported": "25 °C"}),
     "mismatch", "conditions.temperature"),
    ("文字条件一遍写了，另一遍写未报告", lambda p: _by_sample(p, "X-0")["conditions"].__setitem__("electrode", {"reported": "carbon felt"}),
     "mismatch", "conditions.electrode"),
    ("限定符不一样", lambda p: _by_sample(p, "P-212").__setitem__("value_qualifier", "approx"), "mismatch", "value_qualifier"),
    ("出处不在同一张表", lambda p: _by_sample(p, "P-212")["locator"].__setitem__("table", "3"), "mismatch", "locator.table"),
    ("数值挂到了另一个样品上", lambda p: _by_sample(p, "X-1").update(sample_label="X-9"), "mismatch", "sample_label"),
    ("第二遍漏了一条", lambda p: p.remove(_by_sample(p, "X-0")), "only_pass1", None),
    ("第二遍多了一条", lambda p: p.append(dict(copy.deepcopy(_by_sample(p, "X-1")), indicator="coulombic_efficiency", value_reported="98.1")),
     "only_pass2", None),
]


def test_compare_reports_each_difference():
    missed = []
    for name, mutate, group, field in COMPARE_CASES:
        p1, p2 = a_pass(), a_pass()
        mutate(p2)
        report = X.compare(p1, p2)
        hit = report[group]
        fields = {d["field"] for m in report["mismatch"] for d in m["differences"]}
        if len(hit) != 1 or (field and field not in fields) or report["summary"]["mismatch_rate"] <= 0:
            missed.append(f"{name}：{report['summary']}，报出的字段 {sorted(fields)}")
    assert not missed, missed


def test_compare_ignores_wording_of_text_conditions():
    """文字条件两遍各自照抄的那一小段不一样长，不算不一致；写成规范一句的（有 value）照样逐字比。"""
    p1, p2 = a_pass(), a_pass()
    for p, words in ((p1, "carbon felt (XF-30A)"), (p2, "two pieces of carbon felt electrodes")):
        for r in p:
            if r.get("conditions"):
                r["conditions"]["electrode"] = {"reported": words}
    s = X.compare(p1, p2)["summary"]
    assert (s["mismatch"], s["only_pass1"], s["only_pass2"], s["mismatch_rate"]) == (0, 0, 0, 0.0), s
    for p, value in ((p1, "H2SO4 3 mol/L"), (p2, "H2SO4 2 mol/L")):
        _by_sample(p, "X-1")["conditions"]["acid"] = {"reported": "in sulfuric acid", "value": value}
    report = X.compare(p1, p2)
    assert report["summary"]["mismatch"] == 1, report["summary"]
    assert {d["field"] for d in report["mismatch"][0]["differences"]} == {"conditions.acid"}


def test_compare_figure_readings_and_statements():
    """图上读数两遍读得不一样不算不一致，并排列出来；陈述型只比有没有、在不在同一处，不比转述的措辞。"""
    p1, p2 = a_pass(), a_pass()
    next(r for r in p2 if r["obtained_from"] == "figure_read")["value_reported"] = "80.7"
    report = X.compare(p1, p2)
    assert report["summary"]["mismatch"] == 0 and report["figure_read"][0]["readings"] == ["81.2", "80.7"]
    s1, s2 = a_pass("SRC-000005"), a_pass("SRC-000005")
    s2[0]["summary"] = "换一种说法的转述（示例）"
    assert X.compare(s1, s2)["summary"]["agree"] == 1


def test_compare_cli():
    with tempfile.TemporaryDirectory() as tmp:
        p1, p2 = a_pass(), a_pass()
        _by_sample(p2, "X-1")["value_reported"] = "86.5"
        f1, f2, out = (os.path.join(tmp, n) for n in ("pass1.json", "pass2.json", "report.json"))
        store.write_json(f1, {"source_id": "SRC-000001", "evidence": p1})
        store.write_json(f2, p2)                                  # 直接给列表也可以
        code, text = quiet(X.main, [f1, f2, "--out", out])
        assert code == 0 and "不一致 1" in text and "value_reported" in text, text
        report = json.load(open(out, encoding="utf-8"))
        assert report["source_id"] == "SRC-000001" and report["summary"]["agree"] == 2
        store.write_json(f2, {"source_id": "SRC-000002", "evidence": p2})
        assert quiet(X.main, [f1, f2])[0] == 2                    # 不是同一个来源


# ---------------------------------------------------------------- 标识解析（假的网络应答）

FOUND = (200, b'{"responseCode": 1, "handle": "x", "values": []}')
NOT_FOUND = (404, b'{"responseCode": 100, "handle": "x"}')
HANDLE = "https://doi.org/api/handles/"


def fake_web(overrides=None):
    """假的网络：DOI 注册处都查得到，网站没有 robots.txt，网址都打得开；overrides 里的另算。"""
    calls = []

    def get(url):
        calls.append(url)
        answer = (overrides or {}).get(url)
        if isinstance(answer, Exception):
            raise answer
        if answer is not None:
            return answer
        if url.startswith(HANDLE):
            return FOUND
        if url.endswith("/robots.txt"):
            return 404, b""
        return 200, b"<html></html>"
    get.calls = calls
    return get


def no_sleep(_seconds):
    pass


def test_identifier_plan():
    def plan(**fields):
        return C.plan(dict({"terms": {"no_scraping": False}, "fetched_by": "ai_tool", "url": "https://example.org/x"}, **fields))[0]
    assert plan(identifiers={"doi": "10.0000/x"}) == "doi_registry"
    assert plan(identifiers={"doi": "10.0000/x"}, fetched_by="member_download", terms={"no_scraping": True}) == "doi_registry"
    assert plan(fetched_by="member_lookup") == "member"
    assert plan(fetched_by="member_download", terms={"no_scraping": True}) == "member"
    assert plan(identifiers={"patent_number": "US0000000B2"}) == "http"
    assert plan(terms={"no_scraping": True}) is None
    assert plan(url="ftp://example.org/x") is None


def test_identifiers_reproduce_example():
    """把示例数据里的 id_check 去掉重查：得到的结果和查法与示例里写的一样；
    成员取来的来源不发请求；有 DOI 的只问注册处，不碰来源自己的网站；写回之后校验通过。"""
    with example_copy() as data:
        ds = V.load_dataset(data)
        stored = {sid: (s["id_check"]["result"], s["id_check"]["method"]) for sid, s in ds["sources"].items()}
        for s in ds["sources"].values():
            del s["id_check"]
        web = fake_web()
        rows, touched = C.run(ds, web, at=DAY, sleep=no_sleep)
        assert {sid: (s["id_check"]["result"], s["id_check"]["method"]) for sid, s in ds["sources"].items()} == stored
        assert touched == set(ds["sources"]) and all(r["result"] == "pass" for r in rows)
        assert "https://example.org/grant" not in web.calls           # SRC-000006：成员代查的
        assert not [u for u in web.calls if "example.org/pre1" in u]   # SRC-000007：条款禁止自动访问，只问 DOI 注册处
        assert web.calls.count("https://example.org/robots.txt") == 1  # 一个网站的 robots.txt 只取一次
        assert HANDLE + "10.0000/example.0001" in web.calls
        store.save_sources(ds, touched)
        assert V.validate(V.load_dataset(data), SCHEMA) == []


def _lacking(ds, *sids):
    for sid in sids:
        ds["sources"][sid].pop("id_check")
    return ds


# (说明, 要重查的来源, 假的网络应答, 应当得到的结果, 应当写进数据的 id_check 的结果；None 是不写)
IDENTIFIER_CASES = [
    ("DOI 注册处查无此号", "SRC-000001", {HANDLE + "10.0000/example.0001": NOT_FOUND}, "fail", "fail"),
    ("注册处出错", "SRC-000001", {HANDLE + "10.0000/example.0001": (500, b"{}")}, "unknown", None),
    ("注册处没连上", "SRC-000001", {HANDLE + "10.0000/example.0001": OSError("timed out")}, "unknown", None),
    ("网址 404", "SRC-000002", {"https://example.org/p-212.pdf": (404, b"")}, "fail", "fail"),
    ("网址 410", "SRC-000005", {"https://example.org/policy": (410, b"")}, "fail", "fail"),
    ("网站拒绝访问", "SRC-000002", {"https://example.org/p-212.pdf": (403, b"")}, "unknown", None),
    ("网址没连上", "SRC-000002", {"https://example.org/p-212.pdf": OSError("connection reset")}, "unknown", None),
    ("robots.txt 不让自动访问", "SRC-000002", {"https://example.org/robots.txt": (200, b"User-agent: *\nDisallow: /\n")}, "unknown", None),
    ("robots.txt 要登录才能看", "SRC-000002", {"https://example.org/robots.txt": (403, b"")}, "unknown", None),
    ("robots.txt 没读成", "SRC-000002", {"https://example.org/robots.txt": (503, b"")}, "unknown", None),
]


def test_identifier_check_reports_each_broken_case():
    missed = []
    for name, sid, overrides, want, written in IDENTIFIER_CASES:
        ds = _lacking(fresh(), sid)
        web = fake_web(overrides)
        rows, touched = C.run(ds, web, at=DAY, sleep=no_sleep)
        (row,) = rows
        got = (ds["sources"][sid].get("id_check") or {}).get("result")
        if row["result"] != want or got != written or (written is None) != (sid not in touched):
            missed.append(f"{name}：结果 {row['result']}，写进数据的 {got}")
        elif want != "pass" and not row["note"]:
            missed.append(f"{name}：没有说明")
        elif "robots" in name and "https://example.org/p-212.pdf" in web.calls:
            missed.append(f"{name}：robots.txt 不让或没读成，还是去打开了网址")
    assert not missed, missed


def test_identifier_check_skips_what_it_must_not_fetch():
    ds = _lacking(fresh(), "SRC-000002")
    src(ds, "SRC-000002")["terms"]["no_scraping"] = True      # 条款禁止自动访问，又不是成员取来的
    web = fake_web()
    (row,), touched = C.run(ds, web, at=DAY, sleep=no_sleep)
    assert row["result"] == "skipped" and row["note"] and not web.calls and not touched


def test_identifier_check_which_sources():
    ds = fresh()
    web = fake_web()
    assert C.run(ds, web, at=LATER, sleep=no_sleep) == ([], set()) and not web.calls   # 都通过了，默认不重查
    rows, touched = C.run(ds, web, at=LATER, sources={"SRC-000001"}, sleep=no_sleep)   # 点名的重查，日期更新
    assert [r["id"] for r in rows] == ["SRC-000001"] and touched == {"SRC-000001"}
    assert src(ds, "SRC-000001")["id_check"] == {"result": "pass", "at": LATER, "method": "doi_registry"}
    pauses = []
    rows, touched = C.run(fresh(), fake_web(), at=LATER, recheck=True, sleep=pauses.append)
    assert len(rows) == 11 and len(touched) == 11
    assert len(pauses) == 9, "十个要发请求的来源之间停九次；成员取来的那个不发请求"


def test_doi_is_cleaned_and_encoded():
    web = fake_web()
    assert C.check_doi("https://doi.org/10.1000/a b#c", web) == ("pass", "")
    assert web.calls == [HANDLE + "10.1000/a%20b%23c"]


def test_identifier_selftest():
    """自检用一个存在的号和一个不存在的号；注册处对哪个号都说查得到（或都查不到），自检要不过。"""
    missing = HANDLE + C.SELFTEST_MISSING
    assert all(ok for _, ok, _ in C.selftest(fake_web({missing: NOT_FOUND})))
    assert not all(ok for _, ok, _ in C.selftest(fake_web()))                      # 不存在的号也“查到了”
    assert not all(ok for _, ok, _ in C.selftest(fake_web({HANDLE + C.SELFTEST_FOUND: NOT_FOUND, missing: NOT_FOUND})))
    assert not all(ok for _, ok, _ in C.selftest(fake_web({missing: OSError("blocked")})))   # 没连上不算查不到
    real, C.http_get = C.http_get, fake_web({missing: NOT_FOUND})
    try:
        assert quiet(C.main, ["--selftest"])[0] == 0
        C.http_get = fake_web()
        assert quiet(C.main, ["--selftest"])[0] == 1
    finally:
        C.http_get = real


def test_identifier_cli_and_summary():
    with example_copy() as data, tempfile.TemporaryDirectory() as tmp:
        real, C.http_get = C.http_get, fake_web()      # 命令行入口用的是模块里的 http_get，换成假的
        try:
            report, summary = os.path.join(tmp, "report.json"), os.path.join(tmp, "summary.md")
            code, out = quiet(C.main, ["--data", data, "--all", "--write", "--date", LATER, "--report", report, "--summary", summary])
        finally:
            C.http_get = real
        assert code == 0 and "通过 11" in out and "写回了 11 个来源文件" in out, out
        assert len(json.load(open(report, encoding="utf-8"))["results"]) == 11
        assert open(summary, encoding="utf-8").read().count("| SRC-") == 11
        assert V.validate(V.load_dataset(data), SCHEMA) == []


# ---------------------------------------------------------------- 校验规则里跟着改的两处

def test_statement_evidence_can_be_machine_checked_with_na():
    """分类型、陈述型没有数值可核：value_unit 写不适用，照样可以到机器已核及以上（V-27）。"""
    ds = fresh()
    assert ev(ds, "EV-000005-001")["machine_check"]["value_unit"] == "na"
    assert ev(ds, "EV-000005-001")["verification_status"] == "human_verified"
    assert V.validate(ds, SCHEMA) == []


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
    cases = len(SNIPPET_CASES) + len(VALUE_CASES) + len(UNIT_CASES) + len(MACHINE_CASES) + len(COMPARE_CASES) + len(IDENTIFIER_CASES)
    print(f"{cases} 处对错的用例" + ("，结果都和预期的一样" if not failed else ""), "｜失败", failed)
    sys.exit(1 if failed else 0)
