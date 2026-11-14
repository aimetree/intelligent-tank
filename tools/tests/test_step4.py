#!/usr/bin/env python3
"""第 4 步的测试：复核单（tools/review_sheet.py）。

    python3 tools/tests/test_step4.py        也可以用 pytest 跑

查四件事：起草出来的单子和数据对得上；变成点选题之后装得进对话里的点选工具；复核人的回答写回数据之后，
单子、可比组、证据、数据概览、工作记录各是什么样；不合规矩的回答一个字也不写。示例数据全部虚构。
"""
import contextlib
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import review_sheet as R  # noqa: E402
import store  # noqa: E402
import test_dashboard as T  # noqa: E402
import validate as V  # noqa: E402

SCHEMA = V.load_schema()
REVIEWS = os.path.join("public", "topics", "TOP-000001", "reviews.json")
COMPARISONS = os.path.join("public", "topics", "TOP-000001", "comparisons.json")
ASSESSMENTS = os.path.join("public", "topics", "TOP-000001", "assessments.json")
DRAFTED = ["RVW-000002", "RVW-000003", "RVW-000004"]   # 示例数据里由脚本起草的三张


def load(data):
    ds = V.load_dataset(data)
    return ds, R.Ctx(ds, SCHEMA, R.B.load_labels(data))


def problems(data):
    return sorted({(i.rule, i.record) for i in V.validate(V.load_dataset(data), SCHEMA)})


def without_drafts(data):
    """把示例里脚本起草的三张拿掉，回到起草之前。"""
    T.edit_json(data, REVIEWS, lambda doc: doc.__setitem__(slice(None), [r for r in doc if r["id"] not in DRAFTED]))


def verify_by_hand(data, *ids):
    """把几条证据改成人工已核：专业复核之前要先人工核对。"""
    for eid in ids:
        T.edit_evidence(data, eid, lambda e: e.update(verification_status="human_verified", verified_by="yu", verified_at="2026-11-12"))


def snapshot(data):
    out = {}
    for base, _, files in os.walk(data):
        for name in files:
            with open(os.path.join(base, name), "rb") as fh:
                out[os.path.relpath(os.path.join(base, name), data)] = fh.read()
    return out


def run(*argv):
    """跑一次命令行：返回 (退出码, 屏幕上的字, 报错的字)。"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = R.main(list(argv))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def answers_file(data, answers):
    path = os.path.join(os.path.dirname(data), "answers.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(answers, fh, ensure_ascii=False)
    return path


def ready_copy():
    """示例数据的一份拷贝，CMP-000002 的成员都人工核对过，它的复核单 RVW-000003 已经交给复核人。"""
    @contextlib.contextmanager
    def made():
        with T.example_copy() as data:
            verify_by_hand(data, "EV-000007-001", "EV-000007-002")
            assert run("--data", data, "questions", "RVW-000003", "--send", "--out", os.devnull)[0] == 0
            yield data
    return made()


FULL = {"reviewer": "kai", "date": "2026-11-12", "minutes": 9,
        "items": {"CMP-000002": {"decision": "confirm"}, "EV-000003-001": {"decision": "confirm", "note": "维持只作参考"}},
        "batch": {"decision": "confirm"}}


# ---------------------------------------------------------------- 起草

def test_example_sheets_are_what_the_script_drafts():
    """示例数据里那三张起草中的单子，就是脚本对着示例数据起草出来的样子。"""
    kept = {r["id"]: r for r in json.load(open(os.path.join(T.EXAMPLE, REVIEWS), encoding="utf-8"))}
    with T.example_copy() as data:
        without_drafts(data)
        code, out, err = run("--data", data, "draft", "--date", "2026-11-11", "--write")
        assert code == 0 and "起草了 3 张，写进了 reviews.json：RVW-000002、RVW-000003、RVW-000004" in out, out + err
        made = {r["id"]: r for r in json.load(open(os.path.join(data, REVIEWS), encoding="utf-8"))}
        assert made == kept and list(made) == list(kept), "起草出来的和示例里存的一字不差，原有的一张排在前面没有动"
        assert problems(data) == [], "起草的单子通过校验"


def test_draft_lists_what_to_look_at_and_batches_the_rest():
    """期望值是对着示例数据手写的：CMP-000002 五个成员，一个只有摘要、三项条件没报告，其余四个没有要逐条看的理由。"""
    ds, ctx = load(T.EXAMPLE)
    sheet = ds["reviews"]["RVW-000003"]
    assert (sheet["comparison_id"], sheet["status"], sheet["created_by"], sheet["title"]) == ("CMP-000002", "draft", "claude", "CMP-000002 的复核单")
    assert "reviewer" not in sheet and "reviewed_at" not in sheet
    assert [(it["target_id"], it["reason"], it["decision"]) for it in sheet["items"]] == [
        ("CMP-000002", "other", "pending"), ("EV-000003-001", "missing_condition", "pending")]
    assert sheet["items"][0]["why"] == "这一组的档别是 AI 预归的，要由人来定"
    assert sheet["items"][0]["suggestion"] == "定为条件化比较。理由：各来源条件不同，用与同型号基准膜之比对齐"
    assert sheet["items"][1]["why"] == "原文没有报告：钒离子浓度、硫酸浓度、温度"
    assert sheet["items"][1]["suggestion"] == "这一条在组里已经只作参考；建议维持（仅摘要，条件不全）"
    assert sheet["batch"]["evidence_ids"] == ["EV-000001-001", "EV-000001-002", "EV-000007-001", "EV-000007-002"], "照成员登记的次序"
    assert len(sheet["batch"]["sampled"]) == 3 and set(sheet["batch"]["sampled"]) < set(sheet["batch"]["evidence_ids"])
    assert sheet["batch"]["decision"] == "pending"
    # 已经复核过的组：成员都看过了，只有后来写的那句数据概览还没看，补一张
    extra = ds["reviews"]["RVW-000002"]
    assert extra["title"] == "CMP-000001 的复核单（补）" and "batch" not in extra
    assert [(it["target_id"], it["reason"]) for it in extra["items"]] == [("ASM-000001", "overview")], "组已经专业复核过，不再问档别"
    assert "示例膜 X-1 的能量效率比基准膜高 3.6 个百分点" in extra["items"][0]["why"] and "EV-000001-002" in extra["items"][0]["why"]
    assert "只有一个来源、一个电流密度" in extra["items"][0]["why"]


def test_draft_leaves_alone_what_is_already_under_way():
    with T.example_copy() as data:
        before = snapshot(data)
        code, out, err = run("--data", data, "draft", "--write")
        assert code == 0 and "没有要起草的复核单" in out
        for cid, rid in (("CMP-000001", "RVW-000002"), ("CMP-000002", "RVW-000003"), ("CMP-000003", "RVW-000004")):
            assert f"{cid}：不用起草，已经有一张还没复核完的复核单 {rid}" in out
        assert snapshot(data) == before, "没有要起草的，什么也不写"
        without_drafts(data)
        clean = snapshot(data)
        code, out, err = run("--data", data, "draft", "--comparison", "CMP-000003")
        assert code == 0 and "# RVW-000002　CMP-000003 的复核单" in out and "没有写进数据（加 --write 才写）" in out
        assert snapshot(data) == clean, "不加 --write 只看不写"
        assert run("--data", data, "draft", "--comparison", "CMP-000009")[0] == 1
        code, out, err = run("--data", data, "draft", "--by", "Some One")
        assert code == 1 and "起草人写代号" in err
        # 数据概览那一句也复核过了：这一组就没有要起草的了
        T.edit_json(data, os.path.join("public", "topics", "TOP-000001", "assessments.json"),
                    lambda doc: doc[0].update(status="reviewed", reviewed_by="kai", reviewed_at="2026-11-11"))
        T.edit_json(data, REVIEWS, lambda doc: doc[0]["items"].append(
            {"target_id": "ASM-000001", "reason": "overview", "why": "（虚构）", "suggestion": "（虚构）", "decision": "confirm"}))
        code, out, err = run("--data", data, "draft", "--comparison", "CMP-000001")
        assert code == 0 and "CMP-000001：不用起草，成员都在复核完的复核单里了" in out


def test_statement_spanning_two_groups_is_listed_once():
    with T.example_copy() as data:
        T.edit_json(data, ASSESSMENTS, lambda doc: doc[0]["basis"].append("CMP-000003"))
        T.edit_json(data, REVIEWS, lambda doc: doc.__setitem__(slice(None), [r for r in doc if r["id"] != "RVW-000004"]))
        ds, ctx = load(data)
        sheet, why = R.draft_group(ctx, ds["comparisons"]["CMP-000003"], "RVW-000004", "claude", "2026-11-12")
        assert [it["target_id"] for it in sheet["items"]] == ["CMP-000003"], "那句陈述已经在 CMP-000001 的单子里了，不再列一遍"
        T.edit_json(data, REVIEWS, lambda doc: doc.__setitem__(slice(None), [r for r in doc if r["id"] != "RVW-000002"]))
        ds, ctx = load(data)
        sheet, why = R.draft_group(ctx, ds["comparisons"]["CMP-000003"], "RVW-000004", "claude", "2026-11-12")
        assert [it["target_id"] for it in sheet["items"]] == ["CMP-000003", "ASM-000001"], "哪张单子里都没有的，列进来"
        T.edit_json(data, ASSESSMENTS, lambda doc: doc[0].update(status="withdrawn"))
        ds, ctx = load(data)
        sheet, why = R.draft_group(ctx, ds["comparisons"]["CMP-000003"], "RVW-000004", "claude", "2026-11-12")
        assert [it["target_id"] for it in sheet["items"]] == ["CMP-000003"], "撤下的陈述不用复核"


def _member(cid, eid, **more):
    return lambda doc: next(c for c in doc if c["id"] == cid)["members"].append(dict({"evidence_id": eid, "role": "member"}, **more))


def _group(cid, **fields):
    return lambda doc: next(c for c in doc if c["id"] == cid).update(fields)


# 改一处数据，再给 CMP-000003 起草：(名字, 怎么改, 期望)。期望写 (条目, 理由, 具体说明里要有的话)，或者 "batch"、"absent"
REASON_CASES = [
    ("来源之间矛盾", lambda d: T.edit_evidence(d, "EV-000004-002", lambda e: e.update(conflicts_with=["EV-000001-001"])),
     ("EV-000004-002", "conflict", ["这一条是 84.0%", "EV-000001-001 是 85.6%"], "建议都保留并标“存疑”，写明分歧")),
    ("已经标了存疑", lambda d: T.edit_evidence(d, "EV-000004-002", lambda e: e.update(verification_status="disputed", dispute_note="两处写法不一样（虚构）")),
     ("EV-000004-002", "other", ["核对时已经标了存疑：两处写法不一样（虚构）"], "建议保留“存疑”；要用就写明分歧")),
    ("核对时标了数值离群", lambda d: T.edit_evidence(d, "EV-000004-002", lambda e: e["risk"].update(tier="high", reasons=["outlier"], note="比同族的高出很多（虚构）")),
     ("EV-000004-002", "outlier", ["核对时标了数值离群：比同族的高出很多（虚构）"], "建议标“存疑”，或者核对单位")),
    ("必填的条件没报告", lambda d: T.edit_evidence(d, "EV-000004-002", lambda e: e["conditions"].update(temperature="not_reported")),
     ("EV-000004-002", "missing_condition", ["原文没有报告：温度"], "建议留在本组并注明缺哪项，或者降到“参考性资料”")),
    ("必填的条件根本没写", lambda d: T.edit_evidence(d, "EV-000004-002", lambda e: e["conditions"].pop("acid_conc")),
     ("EV-000004-002", "missing_condition", ["原文没有报告：硫酸浓度"], "建议留在本组并注明缺哪项，或者降到“参考性资料”")),
    ("条件写得含糊", lambda d: T.edit_evidence(d, "EV-000004-002", lambda e: e["conditions"].update(temperature={"reported": "室温"})),
     ("EV-000004-002", "missing_condition", ["温度写的是“室温”，解析不出数值"], "建议留在本组并注明缺哪项，或者降到“参考性资料”")),
    ("企业声明没有条件", lambda d: T.edit_evidence(d, "EV-000004-002", lambda e: (e.update(evidence_type="company_claim"), e["conditions"].update(temperature="not_reported"))),
     ("EV-000004-002", "claim_without_conditions", ["企业声明，原文没有报告：温度"], "建议不进可比组，只列在参考里")),
    ("几种理由都有：主要的在前", lambda d: T.edit_evidence(d, "EV-000004-002", lambda e: (e.update(conflicts_with=["EV-000001-001"]), e["conditions"].update(temperature="not_reported"))),
     ("EV-000004-002", "conflict", ["和别的来源的数不一样", "。另外：原文没有报告：温度"], "建议都保留并标“存疑”，写明分歧")),
    ("条件不适用，不算缺", lambda d: T.edit_evidence(d, "EV-000004-002", lambda e: e["conditions"].update(temperature="not_applicable")), "batch"),
    ("选填的条件没报告，不算缺", lambda d: T.edit_evidence(d, "EV-000004-002", lambda e: e["conditions"].update(thickness="not_reported")), "batch"),
    ("图上读数不单列：复读是人工核对的事", lambda d: T.edit_evidence(d, "EV-000004-002", lambda e: e.update(obtained_from="figure_read")), "batch"),
    ("排除的成员不进单子", lambda d: T.edit_json(d, COMPARISONS, lambda doc: next(c for c in doc if c["id"] == "CMP-000003")["members"][1].update(role="excluded", note="定义不同（虚构）")),
     "absent"),
    ("成员指向证据库里没有的证据：不进单子，校验会报", lambda d: T.edit_json(d, COMPARISONS, _member("CMP-000003", "EV-000009-001")), "extra-absent"),
    ("直接可比但原文漏写条件：档别有两种归法", lambda d: T.edit_json(d, COMPARISONS, _group("CMP-000003", tier="direct", missing_conditions=["temperature"], same_setup_note="图 3 的图注写明同一套电池（虚构）")),
     ("CMP-000003", "tier_ambiguous", ["预归为直接可比，但原文没有写温度", "图 3 的图注写明同一套电池（虚构）"], "定为直接可比。理由：电流密度相同，其余条件的差异列出")),
    ("漏写条件又没写依据", lambda d: T.edit_json(d, COMPARISONS, _group("CMP-000003", tier="direct", missing_conditions=["temperature"])),
     ("CMP-000003", "tier_ambiguous", ["没有写认为是同一套条件的依据"], "定为直接可比。理由：电流密度相同，其余条件的差异列出")),
    ("已经有人定过档", lambda d: T.edit_json(d, COMPARISONS, _group("CMP-000003", status="decided", decided_by="yu", decided_at="2026-11-12")),
     ("CMP-000003", "other", ["yu 2026-11-12 定为条件化比较，还没有专业复核"], "定为条件化比较。理由：电流密度相同，其余条件的差异列出")),
    ("数据不足的组写明缺什么", lambda d: T.edit_json(d, COMPARISONS, _group("CMP-000003", tier="insufficient", missing="缺同一电流密度下的基准膜数据（虚构）")),
     ("CMP-000003", "other", ["要由人来定"], "定为数据不足。理由：电流密度相同，其余条件的差异列出。缺：缺同一电流密度下的基准膜数据（虚构）")),
]


def test_reasons_the_script_can_see():
    for name, change, want in REASON_CASES:
        with T.example_copy() as data:
            without_drafts(data)
            change(data)
            ds, ctx = load(data)
            sheet, why = R.draft_group(ctx, ds["comparisons"]["CMP-000003"], "RVW-000002", "claude", "2026-11-12")
            assert sheet, f"{name}：{why}"
            items = {it["target_id"]: it for it in sheet["items"]}
            batch = (sheet.get("batch") or {}).get("evidence_ids", [])
            everything = set(items) | set(batch)
            if want == "batch":
                assert "EV-000004-002" in batch and "EV-000004-002" not in items, name
            elif want == "absent":
                assert "EV-000004-002" not in everything and everything == {"CMP-000003", "EV-000001-001"}, name
            elif want == "extra-absent":
                assert everything == {"CMP-000003", "EV-000001-001", "EV-000004-002"}, name
            else:
                target, reason, said, suggestion = want
                it = items[target]
                assert it["reason"] == reason and it["suggestion"] == suggestion and it["decision"] == "pending", f"{name}：{it}"
                assert all(x in it["why"] for x in said), f"{name}：{it['why']}"
                assert target not in batch, f"{name}：要逐条看的不放在成批确认里"
            assert set(items) & set(batch) == set(), name
            assert not [i for i in V.check_structure(dict(ds, reviews={"RVW-000002": sheet}), SCHEMA) if i.record == "RVW-000002"], \
                f"{name}：起草出来的单子结构要对"


SAMPLE_SIZES = [(1, 1), (2, 2), (3, 3), (4, 3), (30, 3), (31, 4), (45, 5), (200, 20)]


def test_sample_is_fixed_by_the_sheet_number():
    ids = [f"EV-000001-{n:03d}" for n in range(1, 201)]
    for count, want in SAMPLE_SIZES:
        got = R.sample_ids("RVW-000007", ids[:count])
        assert len(got) == want, f"{count} 条里抽 {want} 条：至少 3 条或者一成"
        assert got == [i for i in ids[:count] if i in got], "抽出来的照原来的次序排"
        assert got == R.sample_ids("RVW-000007", ids[:count]), "同一张单子每次抽到的一样"
    assert R.sample_ids("RVW-000007", ids[:60]) != R.sample_ids("RVW-000008", ids[:60]), "换一张单子抽到的不一样"
    assert R.sample_ids("RVW-000007", []) == []


def test_sheet_for_what_is_outside_any_group():
    """不在可比组里的条目另开一张（规格 3.13）：非学术来源的证据、跨组的描述。"""
    with T.example_copy() as data:
        code, out, err = run("--data", data, "draft", "--targets", "EV-000005-001", "EV-000004-001", "--date", "2026-11-12", "--write")
        assert code == 0 and "RVW-000005" in out, out + err
        ds, ctx = load(data)
        sheet = ds["reviews"]["RVW-000005"]
        assert "comparison_id" not in sheet and sheet["title"] == "不在可比组里的条目的复核单（2 条）" and sheet["items"] == []
        assert sheet["batch"] == {"evidence_ids": ["EV-000005-001", "EV-000004-001"], "sampled": ["EV-000005-001", "EV-000004-001"], "decision": "pending"}
        assert problems(data) == []
        text = R.render_text(ctx, sheet)
        assert "不在可比组里的条目，共 2 条" in text and "看板里的位置" not in text
        assert run("--data", data, "questions", "RVW-000005", "--send", "--out", os.devnull)[0] == 0
        path = answers_file(data, {"reviewer": "kai", "date": "2026-11-13", "minutes": 3, "batch": {"decision": "confirm"}})
        code, out, err = run("--data", data, "apply", "RVW-000005", "--answers", path)
        assert code == 0 and "2 条证据标成专业已复核" in out, out + err
        ds = V.load_dataset(data)
        assert [ds["evidence"][i]["verification_status"] for i in ("EV-000005-001", "EV-000004-001")] == ["expert_reviewed"] * 2
        assert problems(data) == []
        # 数据概览的陈述也可以单开一张；作废的、不认识的、别的东西不行
        ds, ctx = load(data)
        loose = R.draft_loose(ctx, ["ASM-000001"], "RVW-000006", "claude", "2026-11-13")
        assert [(it["target_id"], it["reason"]) for it in loose["items"]] == [("ASM-000001", "overview")] and "batch" not in loose
        for targets, said in ((["EV-000099-001"], "不是证据库里的证据"), (["CMP-000001"], "不是证据库里的证据"), ([], "要给出条目的编号"),
                              (["EV-000005-001", "EV-000005-001"], "条目有重复")):
            try:
                R.draft_loose(ctx, targets, "RVW-000006", "claude", "2026-11-13")
                raise AssertionError(f"{targets} 应当起草不了")
            except R.ReviewError as exc:
                assert said in str(exc), exc
        ds["evidence"]["EV-000005-001"].update(verification_status="void")
        try:
            R.draft_loose(ctx, ["EV-000005-001"], "RVW-000006", "claude", "2026-11-13")
            raise AssertionError("作废的证据不用复核")
        except R.ReviewError as exc:
            assert "已作废" in str(exc)
        assert run("--data", data, "draft", "--targets", "EV-000005-001", "--comparison", "CMP-000001")[0] == 2, "两种起草法只能用一种"


# 给 RVW-000003 加一条要逐条看的：(名字, 参数, 期望的报错；None 是加得上)
ADD_CASES = [
    ("成批确认里的一条挪出来逐条看", dict(target="EV-000007-002", reason="baseline_anomaly", why="比同型号常见的值低（虚构）", suggestion="比值照列，组上注明"), None),
    ("理由的代码不认识", dict(target="EV-000007-002", reason="strange", why="x", suggestion="y"), "理由 'strange' 不认识"),
    ("没写具体说明", dict(target="EV-000007-002", reason="outlier", why="  ", suggestion="y"), "要写具体说明"),
    ("已经是要逐条看的", dict(target="EV-000003-001", reason="outlier", why="x", suggestion="y"), "已经是这张单子里要逐条看的一项"),
    ("不是这一组的成员", dict(target="EV-000002-001", reason="outlier", why="x", suggestion="y"), "不是 CMP-000002 的成员"),
    ("证据库里没有", dict(target="EV-000099-001", reason="outlier", why="x", suggestion="y"), "证据库里没有 EV-000099-001"),
    ("别的可比组", dict(target="CMP-000001", reason="tier_ambiguous", why="x", suggestion="y"), "只能加这张单子的可比组"),
    ("数据概览里没有的陈述", dict(target="ASM-000009", reason="overview", why="x", suggestion="y"), "数据概览里没有 ASM-000009"),
]


def test_adding_what_needs_judgment():
    for name, kw, want in ADD_CASES:
        with T.example_copy() as data:
            before = snapshot(data)
            code, out, err = run("--data", data, "add", "RVW-000003", "--target", kw["target"], "--reason", kw["reason"],
                                 "--why", kw["why"], "--suggestion", kw["suggestion"])
            if want:
                assert code == 1 and want in err and snapshot(data) == before, f"{name}：{err}"
                continue
            assert code == 0, f"{name}：{err}"
            sheet = V.load_dataset(data)["reviews"]["RVW-000003"]
            assert sheet["items"][-1] == {"target_id": "EV-000007-002", "reason": "baseline_anomaly", "why": "比同型号常见的值低（虚构）",
                                          "suggestion": "比值照列，组上注明", "decision": "pending"}
            assert sheet["batch"]["evidence_ids"] == ["EV-000001-001", "EV-000001-002", "EV-000007-001"]
            assert set(sheet["batch"]["sampled"]) <= set(sheet["batch"]["evidence_ids"]), "抽看的重新抽，不留着已经挪走的"
            assert problems(data) == []
    with T.example_copy() as data:
        # 成批确认的都挪走了，那一块就没有了；复核完的单子不能再加
        for eid in ("EV-000001-001", "EV-000004-002"):
            assert run("--data", data, "add", "RVW-000004", "--target", eid, "--reason", "other", "--why", "看一下（虚构）", "--suggestion", "同意")[0] == 0
        assert "batch" not in V.load_dataset(data)["reviews"]["RVW-000004"] and problems(data) == []
        code, out, err = run("--data", data, "add", "RVW-000001", "--target", "EV-000001-001", "--reason", "other", "--why", "x", "--suggestion", "y")
        assert code == 1 and "已经复核完了，不能再加" in err
        assert run("--data", data, "add", "RVW-000009", "--target", "EV-000001-001", "--reason", "other", "--why", "x", "--suggestion", "y")[0] == 1


# ---------------------------------------------------------------- 给人看、出点选题

def test_sheet_as_people_read_it():
    ds, ctx = load(T.EXAMPLE)
    text = R.render_text(ctx, ds["reviews"]["RVW-000003"])
    for said in ("# RVW-000003　CMP-000002 的复核单", "起草中｜起草 claude，2026-11-11｜还没有复核", "看板里的位置：对标视图 #CMP-000002",
                 "还不能交给复核人，这几条没有人工核对过：EV-000007-001（机器已核）、EV-000007-002（机器已核）",
                 "- 名称：跨来源：与各自基准膜之比（相对 P-212）", "- 层级和指标：组件或器件｜能量效率", "- 成员：参与比较 2，基准 2，只作参考 1",
                 "- 档别：条件化比较（AI 预归类）", "- 归一化方法：与同一来源里的基准之比", "## 要逐条看的（2 条）",
                 "1. CMP-000002（这一组的档别）", "   为什么要看：这一组的档别是 AI 预归的，要由人来定。",
                 "2. EV-000003-001　Y-2（示例非氟材料族 N（虚构）｜SRC-000003），能量效率 > 84%",
                 "   条件：电流密度 80 mA cm-2；钒离子浓度 未报告；硫酸浓度 未报告；温度 未报告",
                 "   出处：《示例论文 B（虚构）》（示例作者二 等，示例期刊二，2024），摘要",
                 "   为什么要看：条件缺失或含糊。原文没有报告：钒离子浓度、硫酸浓度、温度。", "   决定：未定",
                 "## 不用逐条看的（4 条，默认成批确认）", "随机抽了 3 条：", "其余：EV-000001-001",
                 "## 同一个基准膜在各来源里的数", "- EV-000001-002　P-212（示例商业膜 P（虚构）｜SRC-000001），能量效率 82.0%",
                 "- EV-000007-002　N-212（示例商业膜 P（虚构）｜SRC-000007），能量效率 79.9%"):
        assert said in text, f"单子上应当有：{said}\n{text}"
    assert "其他。" not in text, "理由是“其他”的只写具体说明"
    done = R.render_text(ctx, ds["reviews"]["RVW-000001"])
    assert "已复核｜起草 claude，2026-11-11｜复核人 kai，2026-11-11" in done and "还不能交给复核人" not in done
    assert "   为什么要看：基准膜的数值异常。基准膜的数比同型号常见的值偏低（虚构）。" in done and done.count("决定：同意") == 3
    small = R.render_text(ctx, ds["reviews"]["RVW-000004"])
    assert "随机抽了" not in small and "## 不用逐条看的（2 条，默认成批确认）" in small, "两条都列出来，就不说随机抽"
    assert "同一个基准膜在各来源里的数" not in small, "这一组没有基准膜"
    assert "同一个基准膜在各来源里的数" not in R.render_text(ctx, ds["reviews"]["RVW-000002"]), "这张单子里没有证据"
    # 单子坏了也写得出来
    broken = {"id": "RVW-000009", "topic_id": "TOP-000001", "comparison_id": "CMP-000099", "items": ["x", {"target_id": "EV-000099-001"}],
              "batch": {"evidence_ids": ["EV-000099-002"], "sampled": ["EV-000099-002"]}}
    text = R.render_text(ctx, broken)
    assert "CMP-000099（可比组里没有这个编号）" in text and "证据库里没有这一条，或者显示不出来" in text
    assert [q["key"] for r in R.question_pack(ctx, broken)["rounds"] for q in r] == ["EV-000099-001", "batch"], "出题也不会垮"


def test_list_says_where_each_sheet_stands():
    with T.example_copy() as data:
        code, out, err = run("--data", data, "list")
        assert code == 0 and out.splitlines() == [
            "RVW-000001　CMP-000001　已复核，kai 2026-11-11：逐条看 2 条，成批确认 1 条（同意）",
            "RVW-000002　CMP-000001　起草中：逐条看 1 条（未定 1）",
            "RVW-000003　CMP-000002　起草中：逐条看 2 条（未定 2），成批确认 4 条（未定），2 条还没有人工核对",
            "RVW-000004　CMP-000003　起草中：逐条看 1 条（未定 1），成批确认 2 条（未定），1 条还没有人工核对"], out + err
        without_drafts(data)
        code, out, err = run("--data", data, "list")
        assert out.splitlines()[-1] == "还没有复核单的可比组：CMP-000002、CMP-000003"
    code, out, err = run("list")
    assert code == 0 and out.strip() == "没有复核单，也没有可比组", "仓库里真的数据现在是空的"


def _many_items(data):
    """把 CMP-000002 的单子弄成九题：八条逐条看的加一题成批确认。"""
    T.edit_json(data, COMPARISONS, lambda doc: [_member("CMP-000002", eid)(doc) for eid in ("EV-000001-003", "EV-000001-004", "EV-000004-002")])
    for eid in ("EV-000001-001", "EV-000001-002", "EV-000007-001", "EV-000007-002", "EV-000001-003", "EV-000001-004"):
        T.edit_json(data, REVIEWS, lambda doc: (
            next(r for r in doc if r["id"] == "RVW-000003")["items"].append(
                {"target_id": eid, "reason": "other", "why": "看一下（虚构）。", "suggestion": "同意（虚构）。", "decision": "pending"})))
    T.edit_json(data, REVIEWS, lambda doc: next(r for r in doc if r["id"] == "RVW-000003")["batch"].update(
        evidence_ids=["EV-000004-002"], sampled=["EV-000004-002"]))


def test_questions_fit_the_click_tool():
    """对话里的点选工具：一次最多四题，短标题不超过 12 个字，每题二到四个选项。题目自带背景（D-27）。"""
    with T.example_copy() as data:
        _many_items(data)
        ds, ctx = load(data)
        packs = [R.question_pack(ctx, ds["reviews"][rid]) for rid in ("RVW-000001", "RVW-000002", "RVW-000003", "RVW-000004")]
    assert [sum(len(r) for r in p["rounds"]) for p in packs] == [3, 1, 9, 2] and [len(r) for r in packs[2]["rounds"]] == [4, 4, 1]
    for pack in packs:
        keys = [q["key"] for r in pack["rounds"] for q in r]
        assert len(set(keys)) == len(keys), "每题的 key 不重复，回答照它填"
        assert set(pack["answers"]["items"]) == set(keys) - {"batch"} and (("batch" in pack["answers"]) == ("batch" in keys))
        assert all(a == {"decision": "pending", "note": ""} for a in pack["answers"]["items"].values())
        assert pack["answers"]["reviewer"] == "" and pack["answers"]["minutes"] is None, "复核人和分钟数留给人填，脚本不代填"
        for r in pack["rounds"]:
            assert 1 <= len(r) <= 4
            for q in r:
                assert 0 < len(q["header"]) <= 12 and q["multiSelect"] is False, q["header"]
                assert 2 <= len(q["options"]) <= 4 and all(0 < len(o["label"]) <= 12 and o["description"] for o in q["options"])
                assert q["options"][0]["decision"] == "confirm", "第一个选项是参考判断"
                assert {o["decision"] for o in q["options"]} <= {"confirm", "modify", "pending"}
                assert "。。" not in q["question"] and "None" not in q["question"]
    pack = packs[2]
    assert pack["sheet"] == "RVW-000003" and pack["comparison_id"] == "CMP-000002" and pack["status"] == "draft"
    assert [x["evidence_id"] for x in pack["not_ready"]] == ["EV-000007-001", "EV-000007-002", "EV-000001-004", "EV-000004-002"]
    assert pack["intro"][0] == "名称：跨来源：与各自基准膜之比（相对 P-212）" and len(pack["how"]) == 4
    first, second = pack["rounds"][0][0], pack["rounds"][0][1]
    assert first["key"] == "CMP-000002" and first["header"] == "条目 1/9" and first["options"][0]["label"] == "同意，条件化比较"
    for said in ("可比组 CMP-000002“跨来源：与各自基准膜之比（相对 P-212）”的档别。", "层级和指标：组件或器件｜能量效率", "只作参考 1",
                 "档别：条件化比较（AI 预归类）", "为什么要你看：这一组的档别是 AI 预归的，要由人来定。", "参考判断：定为条件化比较。"):
        assert said in first["question"], said
    for said in ("里的一条证据 EV-000003-001：Y-2（示例非氟材料族 N（虚构）｜SRC-000003），能量效率 > 84%。", "条件：电流密度 80 mA cm-2；钒离子浓度 未报告",
                 "出处：《示例论文 B（虚构）》（示例作者二 等，示例期刊二，2024），摘要。", "为什么要你看：条件缺失或含糊。原文没有报告：钒离子浓度、硫酸浓度、温度。",
                 "参考判断：这一条在组里已经只作参考；建议维持（仅摘要，条件不全）。"):
        assert said in second["question"], said
    assert second["options"][0] == {"label": "同意参考判断", "description": "这一条在组里已经只作参考；建议维持（仅摘要，条件不全）", "decision": "confirm"}
    last = pack["rounds"][2][0]
    assert last["key"] == "batch" and last["header"] == "成批 9/9" and [o["decision"] for o in last["options"]] == ["confirm", "pending", "pending"]
    assert "其余 1 条证据" in last["question"] and "都列在这里：EV-000004-002：实施例 1" in last["question"] and "这 1 条成批确认吗？" in last["question"]
    assert "随机抽了 2 条给你看" not in packs[3]["rounds"][0][1]["question"] and "都列在这里" in packs[3]["rounds"][0][1]["question"]
    overview = packs[1]["rounds"][0][0]
    assert overview["key"] == "ASM-000001" and overview["options"][0]["label"] == "同意这句陈述" and "数据概览里的一句陈述（ASM-000001）" in overview["question"]
    assert json.loads(store.dumps(pack)) == pack, "存成文件再读回来是一样的"


def test_sending_needs_every_member_checked_by_hand():
    with T.example_copy() as data:
        before = snapshot(data)
        code, out, err = run("--data", data, "questions", "RVW-000003", "--send")
        assert code == 1 and "还不能交给复核人，这几条证据没有人工核对过：EV-000007-001（机器已核）、EV-000007-002（机器已核）" in err
        assert snapshot(data) == before and out == "", "没交出去，什么也不改"
        code, out, err = run("--data", data, "questions", "RVW-000003")
        assert code == 0 and json.loads(out)["status"] == "draft" and len(json.loads(out)["not_ready"]) == 2, "不交只看，照样出得来"
        assert snapshot(data) == before
        verify_by_hand(data, "EV-000007-001")
        assert run("--data", data, "questions", "RVW-000003", "--send")[0] == 1, "还差一条"
        T.edit_evidence(data, "EV-000007-002", lambda e: e.update(verification_status="disputed", dispute_note="（虚构）"))
        code, out, err = run("--data", data, "questions", "RVW-000003", "--send")
        assert code == 1 and "EV-000007-002（存疑）" in err, "存疑但没有人工核对过的，也不行"
        # 存疑的只要人工核对过就行
        T.edit_evidence(data, "EV-000007-002", lambda e: e.update(verification_status="disputed", dispute_note="（虚构）", verified_by="yu", verified_at="2026-11-12"))
        target = os.path.join(os.path.dirname(data), "q.json")
        code, out, err = run("--data", data, "questions", "RVW-000003", "--send", "--out", target)
        assert code == 0 and "RVW-000003 交给复核人了，状态改成已交复核人" in err and out == "", err
        assert json.load(open(target, encoding="utf-8"))["status"] == "sent"
        assert V.load_dataset(data)["reviews"]["RVW-000003"]["status"] == "sent" and problems(data) == []
        again = snapshot(data)
        code, out, err = run("--data", data, "questions", "RVW-000003", "--send")
        assert code == 0 and "交给复核人了" not in err and snapshot(data) == again, "已经交了的再交一次，不改什么"
        code, out, err = run("--data", data, "questions", "RVW-000001", "--send")
        assert code == 1 and "已经复核完了" in err
        assert run("--data", data, "questions", "RVW-000009")[0] == 1
        # 没有证据的单子（只有一句数据概览）直接交得出去
        assert run("--data", data, "questions", "RVW-000002", "--send", "--out", os.devnull)[0] == 0


# ---------------------------------------------------------------- 把回答写回数据

def test_answers_close_the_sheet_and_carry_over():
    with ready_copy() as data:
        before = V.load_dataset(data)
        code, out, err = run("--data", data, "apply", "RVW-000003", "--answers", answers_file(data, FULL))
        assert code == 0, out + err
        assert out.splitlines() == ["RVW-000003 复核完了：同意 2 条，改 0 条，成批确认 4 条", "CMP-000002 标成专业已复核",
                                    "3 条证据标成专业已复核", "工作记录加了一条 LOG-000005"]
        ds = V.load_dataset(data)
        sheet = ds["reviews"]["RVW-000003"]
        assert (sheet["status"], sheet["reviewer"], sheet["reviewed_at"]) == ("closed", "kai", "2026-11-12")
        assert list(sheet)[:9] == ["id", "topic_id", "comparison_id", "title", "status", "created_by", "created_at", "reviewer", "reviewed_at"]
        assert [it["decision"] for it in sheet["items"]] == ["confirm", "confirm"] and sheet["batch"]["decision"] == "confirm"
        assert "note" not in sheet["items"][0] and sheet["items"][1]["note"] == "维持只作参考"
        group = ds["comparisons"]["CMP-000002"]
        assert (group["status"], group["decided_by"], group["decided_at"], group["expert_reviewed_by"], group["expert_reviewed_at"]) == \
            ("expert_reviewed", "kai", "2026-11-12", "kai", "2026-11-12"), "档别原来是 AI 预归的：定档人记复核人"
        keys = list(group)
        assert keys[keys.index("status"):keys.index("status") + 5] == ["status", "decided_by", "decided_at", "expert_reviewed_by", "expert_reviewed_at"]
        for eid in ("EV-000003-001", "EV-000007-001", "EV-000007-002"):
            e = ds["evidence"][eid]
            assert (e["verification_status"], e["expert_reviewed_by"], e["expert_reviewed_at"]) == ("expert_reviewed", "kai", "2026-11-12"), eid
            keys = list(e)
            assert keys.index("expert_reviewed_by") == keys.index("verified_at") + 1, "补上的字段跟在人工核对的后面"
        for eid in ("EV-000001-001", "EV-000001-002"):
            assert ds["evidence"][eid] == before["evidence"][eid], "早先在别的单子里复核过的不动（复核人、日期照旧）"
        assert ds["comparisons"]["CMP-000003"] == before["comparisons"]["CMP-000003"] and ds["assessments"] == before["assessments"]
        assert ds["worklog"][-1] == {"id": "LOG-000005", "date": "2026-11-12", "topic_id": "TOP-000001", "arm": "C", "step": "expert_review",
                                     "actor_kind": "human", "actor": "kai", "summary": "看 RVW-000003（CMP-000002），复核完", "minutes": 9,
                                     "refs": ["RVW-000003"], "counts": {"confirmed": 2, "modified": 0, "left_pending": 0, "evidence_reviewed": 3}}
        assert ds["worklog"][:-1] == before["worklog"], "工作记录只在末尾加"
        assert problems(data) == [], "写回之后校验通过"
        code, out, err = run("--data", data, "apply", "RVW-000003", "--answers", answers_file(data, FULL))
        assert code == 1 and "已经复核完了，不能再改" in err


def test_disputed_stays_disputed():
    """存疑的证据复核过了也还是存疑：存疑不抹掉，也不由复核单改成别的状态（规格第 4 节）。"""
    with ready_copy() as data:
        T.edit_evidence(data, "EV-000007-002", lambda e: e.update(verification_status="disputed", dispute_note="和另一处写法不一样（虚构）"))
        code, out, err = run("--data", data, "apply", "RVW-000003", "--answers", answers_file(data, FULL))
        assert code == 0 and "2 条证据标成专业已复核" in out, out + err
        ds = V.load_dataset(data)
        e = ds["evidence"]["EV-000007-002"]
        assert e["verification_status"] == "disputed" and "expert_reviewed_by" not in e
        assert ds["worklog"][-1]["counts"]["evidence_reviewed"] == 2 and ds["comparisons"]["CMP-000002"]["status"] == "expert_reviewed"
        assert problems(data) == []


def test_answers_in_two_sittings():
    with ready_copy() as data:
        first = {"reviewer": "kai", "date": "2026-11-12", "minutes": 4, "items": {"CMP-000002": {"decision": "confirm"}}}
        code, out, err = run("--data", data, "apply", "RVW-000003", "--answers", answers_file(data, first))
        assert code == 0 and out.splitlines() == ["RVW-000003 记下了回答，还没有复核完：1 条还没有定；成批确认的那一项还没有定", "工作记录加了一条 LOG-000005"], out + err
        ds = V.load_dataset(data)
        sheet = ds["reviews"]["RVW-000003"]
        assert sheet["status"] == "sent" and "reviewer" not in sheet and [it["decision"] for it in sheet["items"]] == ["confirm", "pending"]
        assert ds["comparisons"]["CMP-000002"]["status"] == "draft" and ds["evidence"]["EV-000007-001"]["verification_status"] == "human_verified"
        assert ds["worklog"][-1]["summary"] == "看 RVW-000003（CMP-000002），还没有复核完" and ds["worklog"][-1]["minutes"] == 4
        assert ds["worklog"][-1]["counts"] == {"confirmed": 1, "modified": 0, "left_pending": 1, "evidence_reviewed": 0}
        assert problems(data) == []
        # 先不定的可以留一句话；过一天接着答完，没记分钟数就写说明
        hold = {"reviewer": "kai", "date": "2026-11-12", "minutes": 1, "items": {"EV-000003-001": {"decision": "pending", "note": "等我查一下原文"}}}
        assert run("--data", data, "apply", "RVW-000003", "--answers", answers_file(data, hold))[0] == 0
        assert V.load_dataset(data)["reviews"]["RVW-000003"]["items"][1] == dict(
            target_id="EV-000003-001", reason="missing_condition", why="原文没有报告：钒离子浓度、硫酸浓度、温度",
            suggestion="这一条在组里已经只作参考；建议维持（仅摘要，条件不全）", decision="pending", note="等我查一下原文")
        # 逐条看的都定了，成批的那一项还没答：单子还不算复核完
        items_only = {"reviewer": "kai", "date": "2026-11-13", "minutes": 2, "items": {"EV-000003-001": {"decision": "confirm"}}}
        code, out, err = run("--data", data, "apply", "RVW-000003", "--answers", answers_file(data, items_only))
        assert code == 0 and "RVW-000003 记下了回答，还没有复核完：成批确认的那一项还没有定" in out, out + err
        assert V.load_dataset(data)["reviews"]["RVW-000003"]["status"] == "sent"
        rest = {"reviewer": "kai", "date": "2026-11-13", "minutes_note": "当时没有记时间", "batch": {"decision": "confirm"}, "notes": "分两次看的"}
        code, out, err = run("--data", data, "apply", "RVW-000003", "--answers", answers_file(data, rest))
        assert code == 0 and "RVW-000003 复核完了：同意 2 条，改 0 条，成批确认 4 条" in out, out + err
        ds = V.load_dataset(data)
        sheet = ds["reviews"]["RVW-000003"]
        assert (sheet["status"], sheet["reviewed_at"], sheet["notes"]) == ("closed", "2026-11-13", "分两次看的")
        assert sheet["items"][1]["note"] == "等我查一下原文", "先前留的话还在"
        assert [w["id"] for w in ds["worklog"][-4:]] == ["LOG-000005", "LOG-000006", "LOG-000007", "LOG-000008"], "每坐下来看一次记一条"
        assert "minutes" not in ds["worklog"][-1] and ds["worklog"][-1]["minutes_note"] == "当时没有记时间"
        assert ds["worklog"][-1]["counts"] == {"confirmed": 0, "modified": 0, "left_pending": 0, "evidence_reviewed": 3}
        assert problems(data) == []


def test_modify_goes_with_its_change_record():
    """复核人说要改：先改数据、记变化记录，再连同变化记录的编号一起写回。这里是把一条成员从组里排除。"""
    with ready_copy() as data:
        want = copy.deepcopy(FULL)
        want["items"]["EV-000003-001"] = {"decision": "modify", "note": "只有摘要，移出这一组"}
        before = snapshot(data)
        code, out, err = run("--data", data, "apply", "RVW-000003", "--answers", answers_file(data, want))
        assert code == 1 and "先照复核人说的改数据、记变化记录，再把变化记录的编号填进 change_ids 一起写回" in err and snapshot(data) == before
        T.edit_json(data, COMPARISONS, lambda doc: next(c for c in doc if c["id"] == "CMP-000002")["members"][4].update(role="excluded", note="只有摘要，专业复核时移出"))
        with open(os.path.join(data, "changes.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": "CHG-000002", "date": "2026-11-12", "kind": "reclassify", "topic_id": "TOP-000001", "target_id": "CMP-000002",
                                 "field": "members", "before": "EV-000003-001 只作参考", "after": "EV-000003-001 排除", "reason": "专业复核：只有摘要，移出这一组",
                                 "detected_by": "expert", "impact": "changed", "recorded_by": "claude"}, ensure_ascii=False) + "\n")
        assert problems(data) == []
        want["items"]["EV-000003-001"]["change_ids"] = ["CHG-000002"]
        code, out, err = run("--data", data, "apply", "RVW-000003", "--answers", answers_file(data, want))
        assert code == 0 and "RVW-000003 复核完了：同意 1 条，改 1 条，成批确认 4 条" in out, out + err
        ds = V.load_dataset(data)
        item = ds["reviews"]["RVW-000003"]["items"][1]
        assert (item["decision"], item["change_ids"], item["note"]) == ("modify", ["CHG-000002"], "只有摘要，移出这一组")
        assert list(item)[-3:] == ["decision", "change_ids", "note"]
        assert ds["comparisons"]["CMP-000002"]["status"] == "expert_reviewed"
        assert ds["worklog"][-1]["counts"] == {"confirmed": 1, "modified": 1, "left_pending": 0, "evidence_reviewed": 3}
        assert problems(data) == []


def test_group_tier_changed_by_the_reviewer():
    """复核人把档别改了：定档人改记复核人，哪怕原来已经有人定过。"""
    with ready_copy() as data:
        T.edit_json(data, COMPARISONS, _group("CMP-000002", status="decided", decided_by="yu", decided_at="2026-11-12"))
        ds = V.load_dataset(data)
        same, touched, log = R.apply_answers(ds, SCHEMA, "RVW-000003", copy.deepcopy(FULL))
        assert (ds["comparisons"]["CMP-000002"]["decided_by"], ds["comparisons"]["CMP-000002"]["expert_reviewed_by"]) == ("yu", "kai"), "同意的话，原来的定档人照旧"
        T.edit_json(data, COMPARISONS, _group("CMP-000002", tier="reference", tier_reason="条件差得多，只作参考（虚构）"))
        with open(os.path.join(data, "changes.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": "CHG-000002", "date": "2026-11-12", "kind": "reclassify", "topic_id": "TOP-000001", "target_id": "CMP-000002",
                                 "field": "tier", "before": "conditional", "after": "reference", "reason": "专业复核改档", "detected_by": "expert",
                                 "impact": "changed", "recorded_by": "claude"}, ensure_ascii=False) + "\n")
        want = copy.deepcopy(FULL)
        want["items"]["CMP-000002"] = {"decision": "modify", "note": "改成参考性资料", "change_ids": ["CHG-000002"]}
        assert run("--data", data, "apply", "RVW-000003", "--answers", answers_file(data, want))[0] == 0
        group = V.load_dataset(data)["comparisons"]["CMP-000002"]
        assert (group["tier"], group["status"], group["decided_by"], group["decided_at"], group["expert_reviewed_by"]) == \
            ("reference", "expert_reviewed", "kai", "2026-11-12", "kai")
        assert problems(data) == []


def test_reviewed_statement_and_later_members():
    with T.example_copy() as data:
        # 数据概览的一句：同意了就标已复核
        assert run("--data", data, "questions", "RVW-000002", "--send", "--out", os.devnull)[0] == 0
        said = {"reviewer": "kai", "date": "2026-11-12", "minutes": 2, "items": {"ASM-000001": {"decision": "confirm"}}}
        code, out, err = run("--data", data, "apply", "RVW-000002", "--answers", answers_file(data, said))
        assert code == 0 and out.splitlines() == ["RVW-000002 复核完了：同意 1 条，改 0 条", "ASM-000001 标成已复核", "工作记录加了一条 LOG-000005"], out + err
        ds = V.load_dataset(data)
        a = ds["assessments"]["ASM-000001"]
        assert (a["status"], a["reviewed_by"], a["reviewed_at"]) == ("reviewed", "kai", "2026-11-12")
        assert list(a)[list(a).index("drafted_by") + 1:list(a).index("drafted_by") + 3] == ["reviewed_by", "reviewed_at"]
        assert ds["comparisons"]["CMP-000001"]["expert_reviewed_at"] == "2026-11-11", "这一组早就复核过了，不重标"
        assert problems(data) == []
        # 复核完的组后来加了成员：校验会报没覆盖；再起草的一张只列新加的，不再问档别
        T.edit_json(data, COMPARISONS, _member("CMP-000001", "EV-000001-003"))
        assert ("V-48", "CMP-000001") in problems(data)
        code, out, err = run("--data", data, "draft", "--comparison", "CMP-000001", "--date", "2026-11-13", "--write")
        assert code == 0, out + err
        extra = V.load_dataset(data)["reviews"]["RVW-000005"]
        assert extra["title"] == "CMP-000001 的复核单（补）" and extra["items"] == [] and extra["batch"]["evidence_ids"] == ["EV-000001-003"]
        assert run("--data", data, "questions", "RVW-000005", "--send", "--out", os.devnull)[0] == 0
        more = {"reviewer": "kai", "date": "2026-11-13", "minutes": 1, "batch": {"decision": "confirm"}}
        code, out, err = run("--data", data, "apply", "RVW-000005", "--answers", answers_file(data, more))
        assert code == 0 and "1 条证据标成专业已复核" in out and "CMP-000001 标成专业已复核" not in out, out + err
        assert ("V-48", "CMP-000001") not in problems(data)


def test_group_waits_until_every_member_has_been_seen():
    """单子复核完了，但组里还有成员不在任何一张复核完的单子里：这一组先不标专业已复核，只算定了档。"""
    with ready_copy() as data:
        T.edit_json(data, COMPARISONS, _member("CMP-000002", "EV-000001-003", role="reference", note="后来加的（虚构）"))
        assert problems(data) == []
        code, out, err = run("--data", data, "apply", "RVW-000003", "--answers", answers_file(data, FULL))
        assert code == 0 and "CMP-000002 还有成员不在复核完的单子里：EV-000001-003；这一组先不标专业已复核" in out, out + err
        group = V.load_dataset(data)["comparisons"]["CMP-000002"]
        assert (group["status"], group["decided_by"]) == ("decided", "kai") and "expert_reviewed_by" not in group
        assert problems(data) == []


def _set(path, value):
    def change(a):
        node = a
        for key in path[:-1]:
            node = node[key]
        if value is DROP:
            node.pop(path[-1], None)
        else:
            node[path[-1]] = value
    return change


DROP = object()
# 不合规矩的回答：(名字, 怎么改一份好好的回答, 报错里要有的话)。每一种都一个字也不能写
BAD_ANSWERS = [
    ("AI 当复核人", _set(["reviewer"], "claude"), "复核人必须是人"),
    ("脚本当复核人", _set(["reviewer"], "script"), "复核人必须是人"),
    ("没写复核人", _set(["reviewer"], DROP), "复核人必须是人"),
    ("复核人没写代号", _set(["reviewer"], "Kai Zhang"), "复核人必须是人（写代号"),
    ("日期写法不对", _set(["date"], "12/11/2026"), "日期要写成"),
    ("没记分钟数也没写说明", _set(["minutes"], DROP), "工作记录要实记复核人用的分钟数"),
    ("分钟数是负的", _set(["minutes"], -3), "minutes 要是不小于 0 的数"),
    ("分钟数不是数", _set(["minutes"], "十分钟"), "minutes 要是不小于 0 的数"),
    ("分钟数写成了真假", _set(["minutes"], True), "minutes 要是不小于 0 的数"),
    ("单子里没有的条目", _set(["items", "EV-000001-003"], {"decision": "confirm"}), "不是 RVW-000003 里要逐条看的条目"),
    ("成批确认里的条目不能单独答", _set(["items", "EV-000007-001"], {"decision": "confirm"}), "不是 RVW-000003 里要逐条看的条目"),
    ("决定不认识", _set(["items", "CMP-000002"], {"decision": "agree"}), "决定要是 confirm、modify、pending 之一"),
    ("回答里多了别的字段", _set(["items", "CMP-000002"], {"decision": "confirm", "tier": "direct"}), "的回答应是"),
    ("改却没说改成什么", _set(["items", "CMP-000002"], {"decision": "modify", "change_ids": ["CHG-000001"]}), "要在 note 里写改成什么"),
    ("改却没有变化记录", _set(["items", "CMP-000002"], {"decision": "modify", "note": "改成参考性资料"}), "先照复核人说的改数据、记变化记录"),
    ("变化记录的编号不存在", _set(["items", "CMP-000002"], {"decision": "modify", "note": "改", "change_ids": ["CHG-000009"]}), "有变化记录里没有的编号"),
    ("同意却带了变化记录", _set(["items", "CMP-000002"], {"decision": "confirm", "change_ids": ["CHG-000001"]}), "的决定不是改，不用写 change_ids"),
    ("成批的不能整批说改", _set(["batch"], {"decision": "modify"}), "成批确认的回答只能是 confirm 或 pending"),
    ("备注是空的", _set(["notes"], "  "), "notes 要是一句话"),
    ("多了不认识的字段", _set(["approved"], True), "回答文件里有不认识的字段：approved"),
    ("items 不是对象", _set(["items"], ["CMP-000002"]), "items 应是"),
    ("note 不是一句话", _set(["items", "CMP-000002"], {"decision": "confirm", "note": 3}), "note 要是一句话"),
]


def test_bad_answers_write_nothing():
    for name, change, want in BAD_ANSWERS:
        with ready_copy() as data:
            answers = copy.deepcopy(FULL)
            change(answers)
            before = snapshot(data)
            code, out, err = run("--data", data, "apply", "RVW-000003", "--answers", answers_file(data, answers))
            assert code == 1 and want in err, f"{name}：{err}"
            assert snapshot(data) == before, f"{name}：不合规矩的回答一个字也不能写"
    with ready_copy() as data:
        before = snapshot(data)
        path = answers_file(data, ["不是对象"])
        assert run("--data", data, "apply", "RVW-000003", "--answers", path)[0] == 1
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{坏了")
        assert run("--data", data, "apply", "RVW-000003", "--answers", path)[0] == 2
        assert run("--data", data, "apply", "RVW-000003", "--answers", os.path.join(data, "没有这个文件.json"))[0] == 2
        path = answers_file(data, {"reviewer": "kai", "minutes": 1, "batch": {"decision": "confirm"}})
        code, out, err = run("--data", data, "apply", "RVW-000002", "--answers", path)
        assert code == 1 and "还没有交给复核人：先用 questions --send 交出去" in err, "没交出去的不能写回"
        assert run("--data", data, "apply", "RVW-000009", "--answers", path)[0] == 1
        assert run("--data", data, "questions", "RVW-000002", "--send", "--out", os.devnull)[0] == 0
        sent = snapshot(data)
        code, out, err = run("--data", data, "apply", "RVW-000002", "--answers", path)
        assert code == 1 and "RVW-000002 没有成批确认的条目" in err and snapshot(data) == sent
        assert snapshot(data) != before and run("--data", os.path.join(data, "nothing"), "show", "RVW-000001")[0] == 2


def test_nothing_is_written_if_validation_would_fail():
    """写之前先在内存里校验一遍：照回答写回去会多出校验问题的，一个字也不写。"""
    with ready_copy() as data:
        # 有人把“这一组的档别”那一项从单子里删了：复核完之后这一组会变成专业已复核却没有人定过档（V-43）
        T.edit_json(data, REVIEWS, lambda doc: next(r for r in doc if r["id"] == "RVW-000003")["items"].pop(0))
        answers = copy.deepcopy(FULL)
        answers["items"].pop("CMP-000002")
        before = snapshot(data)
        code, out, err = run("--data", data, "apply", "RVW-000003", "--answers", answers_file(data, answers))
        assert code == 1 and "照这份回答写回之后校验不过，什么也没有写" in err and "V-43　CMP-000002　定档要由人来定，并写日期" in err, err
        assert snapshot(data) == before
    with ready_copy() as data:
        # 交出去之后有一条证据被退回了机器已核：不能做专业复核
        T.edit_evidence(data, "EV-000007-001", lambda e: (e.update(verification_status="machine_checked"), e.pop("verified_by"), e.pop("verified_at")))
        before = snapshot(data)
        code, out, err = run("--data", data, "apply", "RVW-000003", "--answers", answers_file(data, FULL))
        assert code == 1 and "这几条证据还没有人工核对过，不能做专业复核：EV-000007-001" in err and snapshot(data) == before
    with ready_copy() as data:
        # 数据里有读不进来的记录：写回会把它丢掉，所以不写
        T.edit_json(data, REVIEWS, lambda doc: doc.append({"title": "没有编号的一张"}))
        before = snapshot(data)
        code, out, err = run("--data", data, "apply", "RVW-000003", "--answers", answers_file(data, FULL))
        assert code == 1 and "数据里有读不了的文件或重复的编号，先修好再写回" in err and snapshot(data) == before
        assert run("--data", data, "add", "RVW-000003", "--target", "EV-000007-002", "--reason", "other", "--why", "x", "--suggestion", "y")[0] == 1
        assert snapshot(data) == before


def test_whole_way_from_draft_to_reviewed():
    """命令行从头走一遍：起草、看、交出去、写回，再生成看板。"""
    with T.example_copy() as data:
        without_drafts(data)
        verify_by_hand(data, "EV-000004-002")
        code, out, err = run("--data", data, "draft", "--comparison", "CMP-000003", "--by", "yu", "--date", "2026-11-12", "--write")
        assert code == 0 and "起草了 1 张，写进了 reviews.json：RVW-000002" in out, out + err
        code, out, err = run("--data", data, "show", "RVW-000002")
        assert code == 0 and "起草中｜起草 yu，2026-11-12｜还没有复核" in out and "还不能交给复核人" not in out
        target = os.path.join(os.path.dirname(data), "q.json")
        assert run("--data", data, "questions", "RVW-000002", "--send", "--out", target)[0] == 0
        pack = json.load(open(target, encoding="utf-8"))
        answers = pack["answers"]
        answers.update(reviewer="expert-01", date="2026-11-14", minutes=6.5)
        answers.pop("minutes_note")
        for q in [q for r in pack["rounds"] for q in r]:
            choice = q["options"][0]["decision"]
            if q["key"] == "batch":
                answers["batch"]["decision"] = choice
            else:
                answers["items"][q["key"]] = {"decision": choice}
        code, out, err = run("--data", data, "apply", "RVW-000002", "--answers", answers_file(data, answers))
        assert code == 0 and "CMP-000003 标成专业已复核" in out and "1 条证据标成专业已复核" in out, out + err
        ds = V.load_dataset(data)
        assert ds["reviews"]["RVW-000002"]["reviewer"] == "expert-01" and ds["worklog"][-1]["minutes"] == 6.5 and ds["worklog"][-1]["actor"] == "expert-01"
        assert ds["evidence"]["EV-000004-002"]["expert_reviewed_by"] == "expert-01"
        assert ds["evidence"]["EV-000001-001"]["expert_reviewed_by"] == "kai", "这一条早先由 kai 复核过，不改成后来的人"
        assert problems(data) == []
        b = T.Built(data)
        assert b.code == 0 and "数据校验：全部通过" in b.log
        card = b.dom.one("section", "group-card", id="CMP-000003")
        assert card.all("div", "tags")[0].clean.startswith("条件化比较状态：专业已复核")
        review = card.one("div", "review", id="RVW-000002")
        assert review.one("div", "tags").clean == "状态：已复核 起草人：yu，2026-11-12 复核人：expert-01，2026-11-14"
    code, out, err = run("draft")
    assert code == 0 and "没有要起草的复核单" in out, "仓库里真的数据现在没有可比组"
    assert run("show")[0] == 2 and run("nothing")[0] == 2


# ---------------------------------------------------------------- 看板上的复核单

def test_group_card_shows_its_sheets():
    b = T.example()
    card = b.dom.one("section", "group-card", id="CMP-000001")
    sheets = card.all("div", "review")
    assert [r.attrs["id"] for r in sheets] == ["RVW-000001", "RVW-000002"]
    done = sheets[0]
    assert done.one("div", "block-name").text == "复核单 RVW-000001　CMP-000001 的复核单（示例）"
    assert done.one("div", "tags").clean == "状态：已复核 起草人：claude，2026-11-11 复核人：kai，2026-11-11"
    assert [th.text for th in done.one("thead").all("th")] == ["要复核人看的条目", "为什么要看", "具体说明", "参考判断", "复核人的决定"]
    lines = [[td.clean for td in tr.all("td")] for tr in done.one("tbody").all("tr")]
    assert lines == [["CMP-000001 这一组的档别", "可比档有两种归法", "同一批测试，条件齐全（虚构）", "定为直接可比", "同意"],
                     ["EV-000001-002 P-212 能量效率 82.0%", "基准膜的数值异常", "基准膜的数比同型号常见的值偏低（虚构）", "比值照列，组上注明", "同意"]]
    assert [a.attrs["href"] for a in done.one("tbody").all("a")] == ["#EV-000001-002"], "证据点得进证据表；档别那一项不是链接"
    assert done.all("p", "note")[0].clean == "成批确认的条目 1 条：EV-000001-001（抽看）｜复核人的决定：同意"
    assert done.all("span", "missing") == [], "都定了，没有要标出来的"
    waiting = sheets[1]
    assert waiting.one("div", "tags").clean == "状态：起草中 起草人：claude，2026-11-11 复核人：还没有复核"
    assert [td.clean for td in waiting.one("tbody").all("td")][0::4][:1] == ["ASM-000001 数据概览的陈述"]
    assert [x.text for x in waiting.all("span", "missing")] == ["未定"], "还没定的标出来"
    other = b.dom.one("section", "group-card", id="CMP-000002").one("div", "review", id="RVW-000003")
    assert other.all("p", "note")[0].clean == ("成批确认的条目 4 条：EV-000001-001、EV-000001-002（抽看）、EV-000007-001（抽看）、EV-000007-002（抽看）"
                                               "｜复核人的决定：未定")
    assert len(other.all("span", "missing")) == 3, "两条逐条看的和成批的那一项都还没定"
    ids = {n.attrs["id"] for n in b.dom.walk() if n.attrs.get("id")}
    assert all(a.attrs["href"][1:] in ids for a in card.all("a") + other.all("a") if a.attrs.get("href", "").startswith("#"))


def test_card_without_sheet_and_with_a_broken_one():
    with T.example_copy() as data:
        T.edit_json(data, REVIEWS, lambda doc: doc.__setitem__(slice(None), [r for r in doc if r["id"] != "RVW-000004"] + [
            {"id": "RVW-000004", "topic_id": "TOP-000001", "comparison_id": "CMP-000002", "title": "坏的一张<b>", "status": "strange",
             "created_by": "claude", "created_at": "2026-11-11", "items": ["不是对象", {"target_id": "EV-000099-001", "reason": "odd", "decision": "maybe"}],
             "batch": {"evidence_ids": "EV-000001-001", "decision": None}}]))
        b = T.Built(data)
        assert b.code == 0 and "对标视图" not in b.log.split("数据校验")[0], "单子坏了，对标视图照样生成"
        assert b.dom.one("section", "group-card", id="CMP-000003").all("p", "note")[-1].text == "这一组还没有复核单。"
        bad = b.dom.one("section", "group-card", id="CMP-000002").one("div", "review", id="RVW-000004")
        assert bad.one("div", "block-name").text == "复核单 RVW-000004　坏的一张<b>" and bad.all("b") == [], "名称里的尖括号原样显示成字"
        assert bad.one("div", "tags").clean == "状态：strange 起草人：claude，2026-11-11 复核人：还没有复核"
        assert [td.clean for td in bad.one("tbody").all("td")] == ["EV-000099-001 证据库里没有这一条", "odd", "", "", "maybe"]
        assert bad.one("tbody").all("a") == [] and [x.text for x in bad.all("span", "missing")] == ["maybe", "（没有填）"]


def test_helpers_keep_files_tidy():
    obj = {"a": 1, "b": 2, "c": 3}
    store.put_after(obj, "x", 9, ["zz", "b"])
    assert list(obj.items()) == [("a", 1), ("b", 2), ("x", 9), ("c", 3)], "插在头一个找得到的字段后面"
    store.put_after(obj, "a", 5, ["c"])
    assert list(obj.items()) == [("a", 5), ("b", 2), ("x", 9), ("c", 3)], "已经有的原地改"
    store.put_after(obj, "y", 7, ["zz"])
    assert list(obj)[-1] == "y", "都找不到就放最后"
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "log.jsonl")
        store.append_jsonl(path, {"id": "一"})
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('{"id": "二"}')          # 手工加的一行，末尾没有换行
        store.append_jsonl(path, {"id": "三"})
        assert open(path, encoding="utf-8").read() == '{"id": "一"}\n{"id": "二"}\n{"id": "三"}\n'
    with T.example_copy() as data:
        ds = V.load_dataset(data)
        path, ids = ds["topic_files"][("TOP-000001", "reviews")]
        assert ids == ["RVW-000001", "RVW-000002", "RVW-000003", "RVW-000004"] and path.endswith(REVIEWS)
        assert store.save_topic(ds, "TOP-000001", "reviews") is False, "没改就不写"
        ds["reviews"]["RVW-000009"] = dict(ds["reviews"]["RVW-000004"], id="RVW-000009")
        assert store.save_topic(ds, "TOP-000001", "reviews", ["RVW-000009"]) is True
        assert [r["id"] for r in json.load(open(path, encoding="utf-8"))] == ids + ["RVW-000009"], "原有的照原来的次序，新加的接在后面"
        os.remove(path)
        fresh = V.load_dataset(data)
        fresh["reviews"]["RVW-000001"] = ds["reviews"]["RVW-000001"]
        assert store.save_topic(fresh, "TOP-000001", "reviews", ["RVW-000001"]) is True and os.path.exists(path), "题目原来没有这个文件也写得出来"


if __name__ == "__main__":
    failed = skipped = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("通过 ", name)
            except unittest.SkipTest as exc:
                skipped += 1
                print("跳过 ", name, exc)
            except AssertionError as exc:
                failed += 1
                print("失败 ", name, exc)
    cases = len(REASON_CASES) + len(SAMPLE_SIZES) + len(ADD_CASES) + len(BAD_ANSWERS)
    print(f"{cases} 处对错的用例" + ("，结果都和预期的一样" if not failed else ""), "｜失败", failed, "｜跳过", skipped)
    sys.exit(1 if failed else 0)
