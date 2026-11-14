#!/usr/bin/env python3
"""第 5 步的测试：总览、数据概览与缺口、非学术来源三页，和报告这一侧的导出（tools/report_export.py）。

    python3 tools/tests/test_step5.py        也可以用 pytest 跑

做法和前几组一样：示例数据（全部虚构）生成出来，页面上的每个数要和数据对得上；再一处一处改数据，
看页面和导出的文件跟着怎么变。给对方的文件里不能带出只留内部的字段；没到对外门槛的不进附录。
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import build_dashboard as B  # noqa: E402
import gaps_view as G  # noqa: E402
import report_export as X  # noqa: E402
import test_dashboard as T  # noqa: E402
import topicdata as TD  # noqa: E402
import validate as V  # noqa: E402
from display import Names  # noqa: E402

SCHEMA = V.load_schema()
TOPIC = os.path.join("public", "topics", "TOP-000001")
REPORTS = os.path.join(TOPIC, "reports.json")
REVIEWS = os.path.join(TOPIC, "reviews.json")
EE, AR = "IN-12", "IN-02"     # 示例字典里的两项核心指标：能量效率、面电阻


def view(b, name):
    return b.dom.one("section", "view", id=name)


def card(b, card_id):
    return b.dom.one("section", id=card_id)


def lines(node):
    """卡片里一行一行的数：[(名字, 数)]。"""
    return [(x.all("span")[0].clean, x.all("span", "strong")[-1].clean) for x in node.all("div", "line")]


def edit_jsonl(data, name, change):
    path = os.path.join(data, name)
    rows = [json.loads(x) for x in open(path, encoding="utf-8").read().splitlines() if x.strip()]
    change(rows)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def model(data):
    ds = V.load_dataset(data)
    return ds, B.build_model(ds, SCHEMA, B.load_labels(data), "TOP-000001", T.VERSION)


def members(data):
    ds, m = model(data)
    return {x["key"]: x for x in TD.membranes(ds, "TOP-000001", m["names"], m["rows"])}, m


def group(m, no):
    return next(g for g in TD.indicator_groups(m["names"]) if g["no"] == no)


def set_status(data, eid, status, **more):
    def change(e):
        e["verification_status"] = status
        for k in ("verified_by", "verified_at", "expert_reviewed_by", "expert_reviewed_at", "dispute_note", "void_reason"):
            e.pop(k, None)
        if status in ("human_verified", "expert_reviewed", "disputed"):
            e.update(verified_by="yu", verified_at="2026-11-12")
        if status == "expert_reviewed":
            e.update(expert_reviewed_by="kai", expert_reviewed_at="2026-11-13")
        e.update(more)
    T.edit_evidence(data, eid, change)


# ---------------------------------------------------------------- 三页共用的整理

def test_membranes_follow_the_sample_registers():
    """膜照样品登记：实验室样品一个来源里一个样品名算一张；商业膜按产品实体算，几篇都用到的是同一张。"""
    mems, m = members(T.EXAMPLE)
    assert list(mems) == ["SRC-000001|X-1", "SRC-000001|X-0", "SRC-000003|Y-2", "SRC-000004|实施例 1", "SRC-000007|Z-1", "entity|ENT-000003"]
    assert [x["kind"] for x in mems.values()] == ["lab"] * 5 + ["product"]
    p = mems["entity|ENT-000003"]
    assert p["label"] == "示例商业膜 P（虚构）" and p["used_by"] == ["SRC-000001", "SRC-000007"] and p["roles"] == ["baseline"]
    assert [r["id"] for r in p["rows"]] == ["EV-000001-002", "EV-000002-001", "EV-000007-002"], "两篇里的基准膜和规格书是同一张膜"
    assert [r["id"] for r in mems["SRC-000001|X-1"]["rows"]] == ["EV-000001-001", "EV-000001-003"]
    assert TD.facet_text(mems["SRC-000001|X-1"]) == "聚苯并咪唑｜非氟｜酸掺杂", "材料族取对象的材料族，含氟类别和传导类型取样品登记"
    assert TD.facet_text(p) == "全氟磺酸｜全氟｜阳离子交换", "商业膜的分类记在产品上，材料族取它所属的材料族"
    assert TD.facet_text(mems["SRC-000007|Z-1"]) == "磺化聚酰亚胺｜部分含氟｜与全氟磺酸共混或复合｜阳离子交换"
    every = {r["id"] for x in mems.values() for r in x["rows"]}
    assert every == {r["id"] for r in m["rows"] if r["sample"] or r["subject_id"] == "ENT-000003"}, "专利权利要求、政策条款、报告里的数不是哪一张膜的"
    with T.example_copy() as data:
        T.edit_evidence(data, "EV-000003-001", lambda e: e.update(sample_label="没登记的样品"))
        T.edit_source(data, "SRC-000008", lambda doc: doc.update(samples=[{"label": "排除的来源里的", "role": "studied", "subject_id": "ENT-000001"}]))
        mems, _ = members(data)
        assert "SRC-000003|没登记的样品" in mems and mems["SRC-000003|没登记的样品"]["rows"][0]["id"] == "EV-000003-001", "证据写了登记里没有的样品名：照实列一张"
        assert mems["SRC-000003|Y-2"]["rows"] == [] and not any("排除的来源里的" in k for k in mems), "排除的来源不算"
    with T.example_copy() as data:   # 补充材料没有自己的样品登记：它的数算在所属论文的那个样品上
        doc = json.load(open(os.path.join(data, "public", "sources", "SRC-000001.json"), encoding="utf-8"))
        doc["source"].update(id="SRC-000012", source_type="supplement", parent_id="SRC-000001", title="示例论文 A 的补充材料（虚构）")
        doc["source"]["topics"][0].pop("core_check")
        doc["evidence"] = [dict(doc["evidence"][3], id="EV-000012-001", source_id="SRC-000012", sample_label="X-1")]
        doc.pop("samples")
        with open(os.path.join(data, "public", "sources", "SRC-000012.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
        mems, _ = members(data)
        assert [r["id"] for r in mems["SRC-000001|X-1"]["rows"]] == ["EV-000001-001", "EV-000001-003", "EV-000012-001"] and "SRC-000012|X-1" not in mems


def test_indicator_columns_merge_keys_with_the_same_list_number():
    dic = {"indicators": [
        {"key": "ce", "list_no": "IN-12", "name_zh": "库仑效率", "level": "component", "grade": "core"},
        {"key": "thick", "list_no": "IN-01", "name_zh": "厚度", "level": "material", "grade": "extended"},
        {"key": "ee", "list_no": "IN-12", "name_zh": "能量效率", "level": "component", "grade": "extended"},
        {"key": "maxj", "list_no": "IN-16", "name_zh": "最高电流密度", "level": "component", "grade": "core", "entry": "derived"},
        {"key": "has", "list_no": "IN-42", "name_zh": "有没有产品", "level": "product_supply", "grade": "core", "entry": "relations"},
        {"key": "bare", "name_zh": "没有清单编号的", "level": "material"}]}
    names = Names({}, dic, SCHEMA)
    got = TD.indicator_groups(names)
    assert [(g["no"], g["keys"], g["label"], g["level"], g["core"]) for g in got] == [
        ("IN-12", ["ce", "ee"], "库仑效率／能量效率", "component", True), ("IN-01", ["thick"], "厚度", "material", False),
        ("bare", ["bare"], "没有清单编号的", "material", False)], "同一个清单编号的并成一列，照字典的次序；算出来的和用关系表达的不单列"
    assert TD.skipped_indicators(names) == [("最高电流密度", "由别的指标的证据算出来"), ("有没有产品", "用实体和关系表达")]


CELL_CASES = [
    # (说的是什么, 怎么改数据, 哪张膜, 哪一列, 期望的状态, 另有几条存疑, 这一格几条)
    ("核得最深的那条说了算", None, "SRC-000001|X-1", EE, "expert_reviewed", 0, 2),
    ("商业膜：两篇里的数算在一起", None, "entity|ENT-000003", EE, "expert_reviewed", 0, 2),
    ("另有一条存疑", lambda d: set_status(d, "EV-000001-003", "disputed", dispute_note="两处不一致"), "SRC-000001|X-1", EE, "expert_reviewed", 1, 2),
    ("只有存疑的", lambda d: set_status(d, "EV-000003-001", "disputed", dispute_note="摘要和正文不一致"), "SRC-000003|Y-2", EE, "disputed", 0, 1),
    ("作废的不算，这一格就没有数据了", lambda d: set_status(d, "EV-000003-001", "void", void_reason="重复"), "SRC-000003|Y-2", EE, "none", 0, 0),
    ("找过，原文没有报告", None, "SRC-000001|X-1", AR, "not_reported", 0, 0),
    ("找过，不适用", lambda d: T.edit_source(d, "SRC-000001", lambda doc: doc["source"]["topics"][0]["core_check"].update(area_resistance="not_applicable")),
     "SRC-000001|X-0", AR, "not_applicable", 0, 0),
    ("这一篇别的样品有、这张没有", lambda d: set_status(d, "EV-000001-004", "void", void_reason="重复"), "SRC-000001|X-0", EE, "none", 0, 0),
    ("没有逐项找过的来源", None, "SRC-000003|Y-2", AR, "none", 0, 0),
    ("商业膜没有哪一篇的逐项找过可看", None, "entity|ENT-000003", AR, "machine_checked", 0, 1),
]


def test_cell_states():
    for what, change, key, no, state, disputed, n in CELL_CASES:
        with T.example_copy() as data:
            if change:
                change(data)
            mems, m = members(data)
            c = TD.cell(mems[key], group(m, no))
            assert (c["state"], c["disputed"], len(c["rows"])) == (state, disputed, n), (what, c["state"], c["disputed"], len(c["rows"]))
            assert (c["best"] is None) == (n == 0), what


# ---------------------------------------------------------------- 总览

def test_overview_numbers_match_the_data():
    b = T.example()
    v = view(b, "overview")
    tiles = {t.attrs["data-tile"]: (t.one("div", "tile-n").text, t.one("div", "tile-sub").clean) for t in v.all("div", "tile")}
    assert tiles == {
        "sources": ("10", "论文 3，预印本 1，更正声明 1，专利文献 1，厂商规格书 1，政策法规 1，咨询公司的报告 1，资助记录 1；其中 8 个录了证据"),
        "membranes": ("6", "实验室样品 5，商业产品 1"),
        "evidence": ("13", "已核实事实 3，企业声明 1，第三方分析 1，实验数据 8"),
        "groups": ("3", "直接可比 1，条件化比较 2"),
        "disputed": ("0", "没有")}
    counts = [(x.attrs["data-status"], x.one("span", "strong").text) for x in card(b, "overview-status").all("span", "status-count")]
    assert counts == [("expert_reviewed", "2"), ("human_verified", "4"), ("machine_checked", "5"), ("pending", "2"), ("disputed", "0")]
    segs = card(b, "overview-status").one("svg", "statusbar").all("rect")
    assert [float(x.attrs["width"]) for x in segs] == [round(1000 * n / 13, 2) for n in (2, 4, 5, 2)], "横条各段的宽度照条数的比例；没有的不画"
    assert abs(sum(float(x.attrs["width"]) for x in segs) - 1000) < 0.05
    cov = card(b, "coverage")
    assert cov.one("div", id="coverage-count").text == "12 格里 7 格有数据，3 格是找过、原文没有报告"
    head = [th.clean for th in cov.one("thead").all("th")]
    assert head == ["膜", "能量效率 组件或器件", "面电阻 材料"], "列是核心指标，照字典的次序；算出来的那一项不单列"
    got = {tr.attrs["data-membrane"]: [(td.attrs["data-state"], td.clean) for td in tr.all("td")] for tr in cov.one("tbody").all("tr")}
    assert got == {
        "SRC-000001|X-1": [("expert_reviewed", "复 2 条"), ("not_reported", "未")],
        "SRC-000001|X-0": [("machine_checked", "机"), ("not_reported", "未")],
        "SRC-000003|Y-2": [("human_verified", "人"), ("none", "—")],
        "SRC-000004|实施例 1": [("machine_checked", "机"), ("none", "—")],
        "SRC-000007|Z-1": [("machine_checked", "机"), ("not_reported", "未")],
        "entity|ENT-000003": [("expert_reviewed", "复 2 条"), ("machine_checked", "机")]}
    links = {tr.attrs["data-membrane"]: [a.attrs["href"] for a in tr.all("a", "cov-link")] for tr in cov.one("tbody").all("tr")}
    assert links["SRC-000001|X-1"] == ["#EV-000001-001"] and links["entity|ENT-000003"] == ["#EV-000001-002", "#EV-000002-001"], "点了去核得最深的那条"
    assert cov.one("tbody").all("tr")[0].one("th").clean == "X-1 聚苯并咪唑｜非氟｜酸掺杂｜SRC-000001"
    assert "没有单列的：最高测试电流密度（由别的指标的证据算出来）" in cov.clean


def test_overview_recent_reading_and_effort():
    b = T.example()
    recent = [li.clean for li in card(b, "overview-recent").all("li")]
    assert recent == [
        "2026-11-11 EV-000001-001：人工核对发现两位数字抄反；由“86.5”改为“85.6”（核验更正，错误类型：数值或单位抄错，CHG-000001）",
        "2026-11-11 专业复核过了 2 条。", "2026-11-11 人工核对过了 6 条。", "2026-11-11 新登记 11 个来源、13 条证据。"]
    assert card(b, "overview-recent").one("a").attrs["href"] == "#EV-000001-001"
    assert lines(card(b, "overview-reading")) == [
        ("全文｜读取工具直接读", "5"), ("全文｜成员下载后上传", "1"), ("全文｜成员在官方系统里代查", "1"),
        ("仅摘要｜读取工具直接读", "2"), ("仅题录｜脚本经接口取", "1"), ("付费来源，只用了公开部分", "1"), ("登记了、排除的", "1")]
    effort = card(b, "overview-effort")
    assert lines(effort) == [("来源获取", "6 分钟"), ("核验", "25 分钟"), ("专业复核", "10 分钟")]
    assert [p.text for p in effort.all("p", "note")] == ["AI 的工作记了 2 条，其中 2 条没有记费用。", "首版只显示累计数，明细页以后再做。"]


def _many_changes(rows):
    for i in range(2, 12):
        rows.append({"id": f"CHG-0000{i:02d}", "date": f"2026-11-{10 + i}", "kind": "other", "topic_id": "TOP-000001", "target_id": "EV-000001-002",
                     "reason": f"第 {i} 次", "impact": "none", "recorded_by": "yu"})


OVERVIEW_CASES = [
    # (说的是什么, 怎么改数据, 在哪张卡片里, 应该出现的字, 不应该出现的字)
    ("一条存疑：点得到，分歧写在旁边", lambda d: set_status(d, "EV-000001-003", "disputed", dispute_note="图上读数和正文不一致"),
     "overview", ["存疑 1 EV-000001-003：图上读数和正文不一致", "复·疑 2 条"], ["没有 核到哪一步"]),
    ("两条存疑：列编号", lambda d: (set_status(d, "EV-000001-003", "disputed", dispute_note="甲"), set_status(d, "EV-000003-001", "disputed", dispute_note="乙")),
     "overview", ["存疑 2 EV-000001-003、EV-000003-001", "疑"], []),
    ("作废的不算进证据数，另外说一句", lambda d: set_status(d, "EV-000001-004", "void", void_reason="重复"),
     "overview", ["证据 12", "另有作废 1 条，不算在内", "作废 1"], []),
    ("人做的工作没记分钟数：照实说没记", lambda d: edit_jsonl(d, "worklog.jsonl", lambda rows: (rows[1].pop("minutes"), rows[1].update(minutes_note="当时没有记"))),
     "overview-effort", ["另有 1 条人做的工作当时没有记分钟数。"], ["核验 25 分钟"]),
    ("AI 的费用按币种加", lambda d: edit_jsonl(d, "worklog.jsonl", lambda rows: (rows[0]["ai"].update(cost=1.25, currency="USD"), rows[4]["ai"].update(cost=0.5, currency="USD"))),
     "overview-effort", ["AI 调用的费用 1.75 USD", "AI 的工作记了 2 条。"], ["没有记费用"]),
    ("同一步的几次加起来", lambda d: edit_jsonl(d, "worklog.jsonl", lambda rows: rows.append(dict(rows[1], id="LOG-000006", minutes=5.5))),
     "overview-effort", ["核验 30.5 分钟"], ["核验 25 分钟"]),
    ("别的题目的变化不列", lambda d: edit_jsonl(d, "changes.jsonl", lambda rows: rows[0].update(topic_id="TOP-000009")),
     "overview-recent", ["专业复核过了 2 条。"], ["CHG-000001"]),
    ("别的题目的工时不算", lambda d: edit_jsonl(d, "worklog.jsonl", lambda rows: rows[2].update(topic_id="TOP-000009")),
     "overview-effort", ["核验 25 分钟"], ["来源获取"]),
    ("变化多了只列最近的八条", lambda d: edit_jsonl(d, "changes.jsonl", _many_changes),
     "overview-recent", ["2026-11-21 EV-000001-002：第 11 次", "更早的还有 6 条"], ["第 3 次"]),
    ("只由人读的来源另外标出", lambda d: T.edit_source(d, "SRC-000006", lambda doc: doc["source"].update(reading_mode="human_only")),
     "overview-reading", ["全文｜成员在官方系统里代查｜只由人读 1"], []),
    ("还没定纳入不纳入的来源", lambda d: T.edit_source(d, "SRC-000009", lambda doc: doc["source"]["topics"][0].update(decision="pending")),
     "overview-reading", ["登记了、还没定纳入不纳入的 1"], ["仅题录"]),
]


def test_overview_follows_the_data():
    for what, change, where, wanted, unwanted in OVERVIEW_CASES:
        with T.example_copy() as data:
            change(data)
            b = T.Built(data)
            node = view(b, where) if where == "overview" else card(b, where)
            for text in wanted:
                assert text in node.clean, (what, text, node.clean[:400])
            for text in unwanted:
                assert text not in node.clean, (what, text)


# ---------------------------------------------------------------- 数据概览与缺口

def entries(b, key):
    """一览表里一张膜的各格：每格是 [(数值, 后面的小字)]，没有数据的格子是它显示的字。"""
    tr = next(tr for tr in card(b, "summary-table").one("tbody").all("tr") if tr.attrs["data-membrane"] == key)
    out = []
    for td in tr.all("td")[1:]:
        found = [(e.one("span", "strong").clean, e.one("span", "sub").clean) for e in td.all("div", "entry")]
        out.append(found or td.clean)
    return out


def test_summary_table_puts_every_value_with_what_goes_with_it():
    b = T.example()
    table = card(b, "summary-table")
    assert [th.clean for th in table.one("thead").all("th")] == ["膜", "类别", "能量效率 组件或器件", "面电阻 材料"]
    assert view(b, "gaps").one("p", id="gaps-count").text == "6 张膜，2 项指标有数据；数据概览 1 句，其中已复核 0 句。"
    assert entries(b, "SRC-000001|X-1") == [
        [("85.6%", "80 mA cm-2｜与同文基准之比 1.044（换算值，基准 EV-000001-002）｜EV-000001-001｜专业已复核"),
         ("81.2%", "120 mA cm-2｜图上读数｜EV-000001-003｜人工已核")], "未报告 找过，原文没有写"]
    assert entries(b, "SRC-000003|Y-2") == [[("> 84%", "80 mA cm-2｜缺钒离子浓度、硫酸浓度、温度｜仅摘要｜EV-000003-001｜人工已核")], "—"]
    assert entries(b, "SRC-000004|实施例 1") == [[("84.0%", "80 mA cm-2｜专利实施例，未经同行评议｜EV-000004-002｜机器已核")], "—"]
    assert entries(b, "SRC-000007|Z-1")[0] == [("80.5%", "80 mA cm-2｜预印本，未经同行评议｜与同文基准之比 1.008（换算值，基准 EV-000007-002）｜EV-000007-001｜机器已核")]
    assert entries(b, "entity|ENT-000003") == [
        [("82.0%", "80 mA cm-2｜EV-000001-002｜专业已复核"), ("79.9%", "80 mA cm-2｜预印本，未经同行评议｜EV-000007-002｜机器已核")],
        [("0.45 Ω cm²", "缺温度｜企业声明｜EV-000002-001｜机器已核")]]
    rows = table.one("tbody").all("tr")
    assert [tr.one("th").clean for tr in rows][:2] == ["X-1 SRC-000001｜研究对象", "X-0 SRC-000001｜同文对照（未改性的原膜）"]
    assert rows[-1].one("th").clean == "示例商业膜 P（虚构） 商业产品｜同文基准" and rows[-1].all("td")[0].text == "全氟磺酸｜全氟｜阳离子交换"
    assert [a.attrs["href"] for a in rows[0].all("a")] == ["#EV-000001-001", "#EV-000001-003"], "每条都点得到证据"
    with T.example_copy() as data:   # 一格里条数多了：只列前几条，其余说一声
        old = G.MAX_LINES
        try:
            G.MAX_LINES = 1
            b = T.Built(data)
        finally:
            G.MAX_LINES = old
        td = next(tr for tr in card(b, "summary-table").one("tbody").all("tr") if tr.attrs["data-membrane"] == "SRC-000001|X-1").all("td")[1]
        assert len(td.all("div", "entry")) == 1 and td.attrs["data-n"] == "2" and "另有 1 条，在证据表里。" in td.clean
    with T.example_copy() as data:   # 有数据的指标才成列；核心指标里一条都没有的说一声；存疑的标出来
        set_status(data, "EV-000002-001", "void", void_reason="重复")
        set_status(data, "EV-000003-001", "disputed", dispute_note="摘要和正文不一致")
        b = T.Built(data)
        table = card(b, "summary-table")
        assert [th.clean for th in table.one("thead").all("th")] == ["膜", "类别", "能量效率 组件或器件"]
        assert "核心指标里一条数据都还没有的：面电阻。" in table.clean
        assert [x.text for x in table.all("span", "flag")] == ["存疑"]


def test_statements_show_their_basis_and_what_is_not_reviewed_yet():
    b = T.example()
    st = card(b, "statements").one("div", "statement", id="ASM-000001")
    assert st.attrs["data-status"] == "draft"
    assert st.one("div", "statement-text").clean == "在 CMP-000001 这一组里，示例膜 X-1 的能量效率比基准膜高 3.6 个百分点。 不能判断的部分：只有一个来源、一个电流密度"
    side = st.one("div", "statement-side")
    assert side.clean == "ASM-000001｜Q1｜草稿 CMP-000001｜直接可比 EV-000001-001｜专业已复核 EV-000001-002｜专业已复核 起草人 claude"
    assert [a.attrs["href"] for a in side.all("a")] == ["#CMP-000001", "#EV-000001-001", "#EV-000001-002"]
    assert st.all("span", "missing") == [], "依据都到了专业已复核，不用提醒"
    with T.example_copy() as data:
        def change(doc):
            doc[0]["basis"] += ["EV-000001-003", "CMP-000002", "REL-000004", "EV-000099-001"]
            doc.append(dict(doc[0], id="ASM-000002", status="withdrawn", statement="撤下的一句（虚构）"))
            doc.append(dict(doc[0], id="ASM-000003", topic_id="TOP-000009", statement="别的题目的一句（虚构）"))
        T.edit_json(data, os.path.join(TOPIC, "assessments.json"), change)
        b = T.Built(data)
        st = card(b, "statements").one("div", "statement", id="ASM-000001")
        assert "依据里还没有到“专业已复核”的：EV-000001-003、CMP-000002、EV-000099-001" in st.clean, "人工已核的证据、还是草稿的组、数据里没有的编号"
        assert "REL-000004｜受资助" in st.clean and "EV-000099-001｜数据里没有这个编号" in st.clean
        assert card(b, "statements").one("div", "statement", id="ASM-000002").one("span", "asm").attrs["class"] == "asm asm-withdrawn"
        assert view(b, "gaps").one("p", id="gaps-count").text.endswith("数据概览 2 句，其中已复核 0 句。"), "别的题目的不算"
        assert [x.attrs["id"] for x in card(b, "statements").all("div", "statement")] == ["ASM-000001", "ASM-000002"]
    with T.example_copy() as data:
        T.edit_json(data, os.path.join(TOPIC, "assessments.json"), lambda doc: doc.clear())
        assert "这个题目还没有写数据概览。" in card(T.Built(data), "statements").clean


def test_search_funnel_and_missing_conditions():
    b = T.example()
    funnel = card(b, "search-funnel")
    assert lines(funnel) == [("登记的来源", "11"), ("纳入", "10"), ("排除 SRC-000008", "1"), ("纳入的里面：全文", "7"),
                             ("纳入的里面：仅摘要 SRC-000003、SRC-000011", "2"), ("纳入的里面：仅题录 SRC-000009", "1")]
    log = funnel.one("table", id="search-log")
    assert [[td.text for td in tr.all("td")] for tr in log.one("tbody").all("tr")] == [
        ["2026-11-11", "示例检索库（虚构）", "示例膜 AND 示例电池，2021 年起", "41", "36", "5"]]
    assert "排除的原因：SRC-000008 E7 同一工作的另一个版本" in funnel.clean
    missing = card(b, "missing-conditions")
    got = [(x.attrs["data-condition"], x.one("div", "line").clean, x.one("svg", "bar").all("rect")[1].attrs["width"]) for x in missing.all("div", "meter")]
    assert got == [("current_density", "电流密度 0 / 4", "0"), ("vanadium_conc", "钒离子浓度 1 / 4", "25"),
                   ("acid_conc", "硫酸浓度 1 / 4", "25"), ("temperature", "温度 1 / 4", "25")], "只有摘要的那一篇没有报告三项"
    assert "组件或器件这一层：按在这一层有证据的 4 个来源算，只看这一层统一必填的 4 项。" in missing.clean
    with T.example_copy() as data:
        edit_jsonl(data, "worklog.jsonl", lambda rows: rows.pop())
        T.edit_evidence(data, "EV-000001-004", lambda e: e["conditions"].update(temperature="not_reported"))
        for eid in ("EV-000007-001", "EV-000007-002"):
            T.edit_evidence(data, eid, lambda e: e["conditions"].update(temperature="not_applicable"))
        b = T.Built(data)
        assert "工作记录里还没有检索的记录。" in card(b, "search-funnel").clean
        temp = next(x for x in card(b, "missing-conditions").all("div", "meter") if x.attrs["data-condition"] == "temperature")
        assert temp.one("div", "line").clean == "温度 2 / 4", "数的是来源：一篇里有一条没报告就算；不适用不算没报告"
        set_status(data, "EV-000003-001", "void", void_reason="重复")
        got = [x.one("div", "line").clean for x in card(T.Built(data), "missing-conditions").all("div", "meter")]
        assert got == ["电流密度 0 / 3", "钒离子浓度 0 / 3", "硫酸浓度 0 / 3", "温度 1 / 3"], "作废的不算"


def _extra_sample(doc):
    doc["samples"].append({"label": "X-9", "role": "studied", "subject_id": "ENT-000001",
                           "facets": {"fluorine_class": "non_fluorinated", "conduction_type": "acid_doped"}})


GAP_CASES = [
    # (说的是什么, 怎么改数据, 哪一条缺口, 期望的一整句；None 是不该有这一条)
    ("没有同文基准膜的来源", None, "no_baseline", "登记了样品的 4 个来源里，2 个没有同文基准膜，它的数据算不了与基准之比：SRC-000003、SRC-000004。"),
    ("只读到摘要的", None, "abstract_only", "仅摘要的来源 2 个，从中取的数都带着这个标注：SRC-000003、SRC-000011。"),
    ("只有题录的", None, "metadata_only", "仅题录的来源 1 个，没有从中取数：SRC-000009。"),
    ("付费没有买的", None, "not_purchased", "付费没有买、只用了公开部分的来源 1 个：SRC-000011。"),
    ("来源已更正", None, "source_status", "已更正的来源 1 个：SRC-000003。"),
    ("图上读数", None, "figure_read", "13 条证据里 1 条是图上读数，其中 1 条由人复读过：EV-000001-003。"),
    ("还不能用在报告里的", None, "not_verified", "待核 2 条、机器已核 5 条，还不能用在报告里。"),
    ("三层里还没有归组的数值", None, "ungrouped", "材料、器件、系统三层里，还没有进任何可比组的数值 3 条：EV-000001-003、EV-000001-004、EV-000002-001。"),
    ("没有数据不足的组就不写", None, "insufficient", None),
    ("数据不足的组写明缺什么", lambda d: T.edit_json(d, os.path.join(TOPIC, "comparisons.json"), lambda doc: doc[2].update(tier="insufficient", missing="每侧电解液体积")),
     "insufficient", "数据不足的可比组：缺 每侧电解液体积：CMP-000003。"),
    ("来源撤稿了", lambda d: T.edit_source(d, "SRC-000007", lambda doc: doc["source"].update(status="retracted")), "source_status", "已更正的来源 1 个：SRC-000003。"),
    ("图上读数没有人复读", lambda d: T.edit_evidence(d, "EV-000001-003", lambda e: [e["figure_read"].pop(k, None) for k in ("reread_by", "reread_at", "reread_value")]),
     "figure_read", "13 条证据里 1 条是图上读数，其中 0 条由人复读过：EV-000001-003。"),
    ("登记了、还没有证据的膜", lambda d: T.edit_source(d, "SRC-000001", _extra_sample), "no_evidence", "样品登记里有、还没有任何证据的膜 1 张：X-9（SRC-000001）。"),
    ("没有这种情况就不写", None, "no_evidence", None),
    ("存疑的也列", lambda d: set_status(d, "EV-000001-003", "disputed", dispute_note="不一致"), "not_verified", "存疑 1 条、待核 2 条、机器已核 5 条，还不能用在报告里。"),
    ("作废的不算", lambda d: set_status(d, "EV-000002-001", "void", void_reason="重复"), "ungrouped", "材料、器件、系统三层里，还没有进任何可比组的数值 2 条：EV-000001-003、EV-000001-004。"),
]


def test_other_gaps_are_counted_from_the_data():
    for what, change, key, want in GAP_CASES:
        with T.example_copy() as data:
            if change:
                change(data)
            b = T.Built(data)
            found = [g.clean for g in card(b, "other-gaps").all("div", "gap") if g.attrs["data-gap"] == key]
            assert found[:1] == ([want] if want else []), (what, found)
    with T.example_copy() as data:   # 来源撤稿：另起一条
        T.edit_source(data, "SRC-000007", lambda doc: doc["source"].update(status="retracted"))
        found = [g.clean for g in card(T.Built(data), "other-gaps").all("div", "gap") if g.attrs["data-gap"] == "source_status"]
        assert found == ["已更正的来源 1 个：SRC-000003。", "已撤稿的来源 1 个：SRC-000007。"]


def _loose_sheets(doc):
    base = {"topic_id": "TOP-000001", "status": "draft", "created_by": "claude", "created_at": "2026-11-12"}
    item = {"reason": "other", "why": "示例", "suggestion": "示例", "decision": "pending"}
    doc.append(dict(base, id="RVW-000005", title="跨组的描述（虚构）", items=[dict(item, target_id="ASM-000001", reason="overview")]))
    doc.append(dict(base, id="RVW-000006", title="专利和资助的证据（虚构）",
                    items=[dict(item, target_id="EV-000004-001")], batch={"evidence_ids": ["EV-000006-001"], "sampled": [], "decision": "pending"}))
    doc.append(dict(base, id="RVW-000007", title="论文和专利各一条（虚构）", items=[dict(item, target_id="EV-000004-001"), dict(item, target_id="EV-000003-001")]))
    doc.append(dict(base, id="RVW-000008", topic_id="TOP-000009", title="别的题目的", items=[dict(item, target_id="ASM-000001")]))


def test_review_sheets_outside_any_group_are_shown_on_the_right_page():
    """不属于可比组的复核单：条目都是非学术来源的证据的，在非学术来源页；别的在数据概览与缺口页（规格 3.13）。"""
    b = T.example()
    assert b.dom.all("section", id="loose-reviews") == [], "示例里的四张都属于可比组，在对标视图里"
    with T.example_copy() as data:
        T.edit_json(data, REVIEWS, _loose_sheets)
        b = T.Built(data)
        on = {name: [r.attrs["id"] for r in view(b, name).all("div", "review")] for name in ("gaps", "non-academic")}
        assert on == {"gaps": ["RVW-000005", "RVW-000007"], "non-academic": ["RVW-000006"]}, "别的题目的不显示"
        assert sorted(r.attrs["id"] for r in view(b, "compare").all("div", "review")) == ["RVW-000001", "RVW-000002", "RVW-000003", "RVW-000004"]
        sheet = view(b, "non-academic").one("div", "review", id="RVW-000006")
        assert "复核单 RVW-000006 专利和资助的证据（虚构）" in sheet.clean and [a.attrs["href"] for a in sheet.all("a")] == ["#EV-000004-001", "#EV-000006-001"]


# ---------------------------------------------------------------- 非学术来源

def doc_card(b, sid):
    c = view(b, "non-academic").one("div", "doc-card", id=sid)
    pairs = dict(zip([x.text for x in c.one("dl").all("dt")], [x.text for x in c.one("dl").all("dd")]))
    return c, pairs


def test_non_academic_blocks_match_the_sources():
    b = T.example()
    v = view(b, "non-academic")
    tiles = {t.attrs["data-tile"]: [x.clean for x in t.all("div")] for t in v.all("div", "tile")}
    assert tiles == {"patent": ["专利", "1 件", "授权公告 1", "证据 2 条"], "policy": ["政策法规和标准", "1 项", "在审 1", "证据 1 条"],
                     "market": ["产业和市场的数字", "1 份", "装机 1 条", "证据 1 条"], "grant": ["科研资助", "1 条", "对得上 1 个来源", "证据 1 条"]}
    assert v.one("p", id="na-status").text == "5 条证据：待核 2 条，机器已核 1 条，人工已核 2 条。状态查的日期：2026-11-11；每次出报告前再查一次。"
    table = v.one("table", id="jurisdictions")
    assert [th.text for th in table.one("thead").all("th")] == ["类别", "中国", "英国", "欧盟", "美国", "国际组织和多国"]
    assert [[c.clean for c in tr.all("th") + tr.all("td")] for tr in table.one("tbody").all("tr")] == [
        ["专利文献", "—", "—", "—", "1", "—"], ["政策法规", "—", "—", "1", "—", "—"],
        ["咨询公司的报告", "—", "—", "—", "—", "1"], ["资助记录", "1", "—", "—", "—", "—"]]

    c, pairs = doc_card(b, "SRC-000004")
    assert c.one("div", "doc-head").clean == "US0000000B2 Active（数据库注明是推定） SRC-000004"
    assert pairs["申请人或专利权人"] == "示例大学（虚构）" and pairs["发明人"] == "示例发明人甲、示例发明人乙" and pairs["法域"] == "美国"
    assert pairs["同族编号"] == "示例数据库 00000000｜同族 4 件：US0000000B2、CN000000000B、EP0000000A1、WO2020000000A1"
    assert pairs["法律状态"] == "Active（数据库注明是推定）｜照 示例专利数据库 2026-11-11 的记录", "照数据库的记录写，写明在哪里、哪天查的"
    assert [li.attrs["data-ev"] for li in c.all("li") if "data-ev" in li.attrs] == ["EV-000004-001", "EV-000004-002"]
    assert "实施例 1｜能量效率：84.0%" in c.clean and "专利实施例，未经同行评议" in c.clean
    assert "登记内容人工核对：yu，2026-11-11" in c.clean

    c, pairs = doc_card(b, "SRC-000005")
    assert c.one("span", "chip-static").text == "在审" and pairs["现在的状态"] == "在审｜意见草案征求意见中（虚构）｜照 示例监管机构网站 2026-11-11 的记录"
    assert pairs["下一个时间点"] == "第二个委员会出最终意见（虚构）｜预计 2026｜第 2 页"
    events = [(li.attrs["class"], li.clean) for li in v.one("div", id="policy-events").all("li")]
    assert events == [("event expected", "2026，预计 示例限制提案（虚构）：第二个委员会出最终意见（虚构） 第 2 页"),
                      ("event", "2026-03-02 示例限制提案（虚构）：第一个委员会通过意见（虚构） 新闻稿"),
                      ("event", "2025-03-01 示例限制提案（虚构）：发布提案（虚构） 第 1 页")], "新的在前，时间表上预计的在最前面并写明是预计"

    market = card(b, "block-market")
    item = market.one("div", "meter")
    assert item.attrs["data-ev"] == "EV-000011-001" and item.one("div", "line").clean == "示例行业报告（虚构）｜咨询公司的报告｜2026-03 > 15 GWh"
    assert "年份 2025；范围 全球；口径 新增装机" in item.clean and market.all("svg", "bar") == [], "只有一个数，不画条"
    assert "还没有人工核对、不进报告的 1 条：EV-000011-001。" in market.clean
    _, pairs = doc_card(b, "SRC-000011")
    assert pairs["读到哪里"] == "仅摘要｜付费来源，只用了公开部分"

    c, pairs = doc_card(b, "SRC-000006")
    assert pairs["资助机构"] == "示例基金（虚构）" and pairs["金额"] == "58 万元" and pairs["起止"] == "2022–2025" and pairs["法域"] == "中国"
    assert "示例论文 A（虚构）（SRC-000001） — 受资助 — 示例项目：示例膜的研究（虚构）（SRC-000006） REL-000004｜有出处｜待核" in c.clean
    assert "4 个论文类的来源里，查到资助项目记录的是 1 个。" in card(b, "block-grant").clean

    rels = [(r.attrs["id"], r.attrs["data-inferred"], r.one("span", "chip-static").text) for r in card(b, "na-relations").all("div", "rel")]
    assert rels == [("REL-000003", "yes", "AI 推断，还没有人确认"), ("REL-000004", "no", "有出处")], "只列和这四块有关的关系；推断的标明"
    gaps = {g.attrs["data-gap"]: g.clean for g in card(b, "na-gaps").all("div", "gap")}
    assert gaps == {"jurisdiction": "还没有来源的法域：英国。", "abstract_only": "只读到摘要的：SRC-000011。",
                    "not_purchased": "付费没有买、只用了公开部分的：SRC-000011。",
                    "not_verified": "还没有人工核对、不能进报告的证据 3 条：EV-000004-002、EV-000011-001、EV-000006-001。"}


def _second_report(pct):
    def change(data):
        doc = json.load(open(os.path.join(data, "public", "sources", "SRC-000011.json"), encoding="utf-8"))
        doc["source"].update(id="SRC-000012", title="示例行业报告二（虚构）", source_type="government_report", jurisdiction="us")
        e = dict(doc["evidence"][0], id="EV-000012-001", source_id="SRC-000012", value_reported="30", value_qualifier="eq")
        if pct:
            e["unit_reported"] = "MWh"
        doc["evidence"] = [e]
        with open(os.path.join(data, "public", "sources", "SRC-000012.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
    return change


NA_CASES = [
    # (说的是什么, 怎么改数据, 页面上应该有的字, 不应该有的字)
    ("状态查得比截至日期早：出报告前要再查", lambda d: T.edit_source(d, "SRC-000004", lambda doc: doc["source"]["doc"]["status"].update(checked_at="2026-10-01")),
     ["状态是在题目的截至日期（2026-11-11）之前查的，出报告前要再查一次：SRC-000004。", "状态查的日期：2026-10-01 至 2026-11-11"], []),
    ("登记内容没有人工核对", lambda d: T.edit_source(d, "SRC-000005", lambda doc: [doc["source"].pop(k) for k in ("record_verified_by", "record_verified_at")]),
     ["登记内容（著录项目和状态）还没有人工核对的，报告用到之前要核对：SRC-000005。", "登记内容还没有人工核对"], []),
    ("AI 核对的不算人工核对", lambda d: T.edit_source(d, "SRC-000006", lambda doc: doc["source"].update(record_verified_by="claude")),
     ["还没有人工核对的，报告用到之前要核对：SRC-000006。"], ["登记内容人工核对：claude"]),
    ("排除的来源不在这一页", lambda d: T.edit_source(d, "SRC-000006", lambda doc: doc["source"]["topics"][0].update(decision="excluded", exclusion_reason="E1 示例")),
     ["科研资助：这一批里还没有来源。", "0 条"], ["示例基金（虚构）"]),
    ("法域没有填的单列一栏", lambda d: T.edit_source(d, "SRC-000011", lambda doc: doc["source"].pop("jurisdiction")),
     ["类别中国英国欧盟美国（没有填）"], ["国际组织和多国"]),
    ("人确认过的推断", lambda d: T.edit_json(d, "public/relations.json", lambda doc: doc[2].update(basis="inferred_human", confirmed_by="kai")),
     ["人工推断，kai 已确认"], ["还没有人确认"]),
    ("市场的数核过了就不在“还不能用”里", lambda d: set_status(d, "EV-000011-001", "human_verified"),
     ["还没有人工核对、不能进报告的证据 2 条：EV-000004-002、EV-000006-001。"], ["不进报告的 1 条"]),
    ("作废的证据不列", lambda d: set_status(d, "EV-000004-002", "void", void_reason="重复"),
     ["专利 1 件 授权公告 1 证据 1 条", "4 条证据：待核 2 条，人工已核 2 条。"], ["EV-000004-002", "实施例 1｜能量效率"]),
    ("指向资助项目的别的关系不算“受资助”", lambda d: T.edit_json(d, "public/relations.json", lambda doc: doc[1].update(subject="SRC-000003", relation_type="other", object="SRC-000006")),
     ["对得上 1 个来源", "查到资助项目记录的是 1 个。", "REL-000002 示例论文 B（虚构）（SRC-000003） — 其他 — 示例项目：示例膜的研究（虚构）（SRC-000006）"], []),
    ("别的专利族的关系也列", lambda d: T.edit_json(d, "public/relations.json", lambda doc: doc[0].update(object="ENT-000006")),
     ["REL-000001 示例膜公司（虚构） — 制造或供应 — 示例专利族（虚构）"], []),
]


def test_non_academic_page_follows_the_data():
    for what, change, wanted, unwanted in NA_CASES:
        with T.example_copy() as data:
            change(data)
            text = view(T.Built(data), "non-academic").clean
            for x in wanted:
                assert x in text, (what, x)
            for x in unwanted:
                assert x not in text, (what, x)
    for pct, bars in ((False, 2), (True, 0)):   # 同一项、同一个单位有两个数才画条；单位不一样不画
        with T.example_copy() as data:
            _second_report(pct)(data)
            b = T.Built(data)
            market = card(b, "block-market")
            assert len(market.all("div", "meter")) == 2 and len(market.all("svg", "bar")) == bars, (pct, bars)
            if bars:
                assert [x.all("rect")[1].attrs["width"] for x in market.all("svg", "bar")] == ["50", "100"], "条长按这一项里最大的数算"
                assert "不同报告对同一件事给的数不一样时照实列出，不合并成一个数" in market.clean
                assert "咨询公司的报告 1，政府部门的报告 1" not in market.clean and view(b, "non-academic").one("div", "tile", data_tile="market").all("div")[1].text == "2 份"


HOSTILE = "<img src=x onerror=alert(1)><script>alert(2)</script>"


def test_text_from_data_is_never_markup_on_the_new_pages():
    with T.example_copy() as data:
        T.edit_json(data, os.path.join(TOPIC, "assessments.json"), lambda doc: doc[0].update(statement=HOSTILE, unknowns=HOSTILE))
        T.edit_source(data, "SRC-000004", lambda doc: (doc["source"]["doc"].update(applicants=[HOSTILE]), doc["source"]["doc"]["status"].update(stated=HOSTILE),
                                                        doc["samples"][0].update(label=HOSTILE)))
        T.edit_source(data, "SRC-000005", lambda doc: doc["source"]["doc"]["status"]["events"][0].update(summary=HOSTILE))
        edit_jsonl(data, "worklog.jsonl", lambda rows: rows[4]["search"].update(where=HOSTILE, query=HOSTILE))
        edit_jsonl(data, "changes.jsonl", lambda rows: rows[0].update(reason=HOSTILE, after=HOSTILE))
        T.edit_json(data, "public/relations.json", lambda doc: doc[3].update(summary=HOSTILE))
        b = T.Built(data)
        assert b.code == 0 and len(b.dom.all("script")) == 2 and b.dom.all("img") == []
        for name in ("overview", "gaps", "non-academic"):
            assert HOSTILE in view(b, name).text, name


def _break_everything(data):
    T.edit_source(data, "SRC-000001", lambda doc: (doc.update(samples="不是清单"), doc["source"].update(topics="不是清单")))
    T.edit_source(data, "SRC-000004", lambda doc: doc["source"].update(doc="不是对象", identifiers=7))
    T.edit_source(data, "SRC-000005", lambda doc: doc["source"]["doc"].update(status={"events": "不是清单", "next_step": 3, "stage": 5}))
    T.edit_source(data, "SRC-000006", lambda doc: doc["source"].update(paid="不是对象", jurisdiction=9))
    T.edit_json(data, os.path.join(TOPIC, "assessments.json"), lambda doc: (doc[0].update(basis="不是清单"), doc.append({"id": "ASM-000002", "topic_id": "TOP-000001"})))
    T.edit_json(data, "public/relations.json", lambda doc: (doc[2].update(locator="不是对象", basis=None), doc[3].pop("object")))
    T.edit_json(data, os.path.join(TOPIC, "dictionary.json"), lambda doc: (doc.update(level_conditions="不是对象"), doc["indicators"].append("不是对象"),
                                                                           doc["rules"].append({"key": "坏的", "applies_to": None})))
    edit_jsonl(data, "worklog.jsonl", lambda rows: (rows[0].update(ai="不是对象"), rows[1].update(minutes="很多"), rows[4].update(search={"hits": "很多"})))
    edit_jsonl(data, "changes.jsonl", lambda rows: rows.append({"id": "CHG-000002", "date": 20261111, "target_id": None}))


def test_pages_survive_badly_broken_data():
    """数据坏成什么样都要出页面：能显示的照样显示，坏的地方由校验报在页面顶上。"""
    with T.example_copy() as data:
        _break_everything(data)
        b = T.Built(data)
        assert b.code == 0 and b.dom.one("div", id="problems") is not None
        for name, title in (("overview", "总览"), ("gaps", "数据概览与缺口"), ("non-academic", "非学术来源")):
            v = view(b, name)
            assert v.all("h2")[0].text == title and "生成不了" not in v.text, name
        assert len(card(b, "coverage").one("tbody").all("tr")) >= 4
    with T.example_copy() as data:   # 真的垮了的那一页说明生成不了，别的页面照样出
        def boom(*args):
            raise RuntimeError("坏了")

        for name in ("summary_table", "render_table"):   # 整理数据的时候垮、写网页的时候垮，都一样
            old = getattr(G, name)
            try:
                setattr(G, name, boom)
                b = T.Built(data)
            finally:
                setattr(G, name, old)
            assert b.code == 0 and "这一页生成不了，原因列在页面顶上。" in view(b, "gaps").text, name
            assert "数据概览与缺口：显示不出来（RuntimeError: 坏了）" in b.dom.one("div", id="problems").text, name
            assert "12 格里 7 格有数据" in view(b, "overview").text and len(b.dom.one("table", "ev-table").all("tbody", "ev")) == 13
            assert T.Built(data, strict=True).code == 0, "改回去之后一切照旧"
    with T.example_copy() as data:   # 刚定了题、一个来源都还没有登记的题目
        for name in os.listdir(os.path.join(data, "public", "sources")):
            os.remove(os.path.join(data, "public", "sources", name))
        for name in ("comparisons.json", "assessments.json", "reviews.json"):
            T.edit_json(data, os.path.join(TOPIC, name), lambda doc: doc.clear())
        T.edit_json(data, "public/relations.json", lambda doc: doc.clear())
        for name in ("worklog.jsonl", "changes.jsonl"):
            edit_jsonl(data, name, lambda rows: rows.clear())
        b = T.Built(data, strict=True)
        assert b.code == 0, b.log
        assert "样品登记里还没有膜" in view(b, "overview").text and "0 格里 0 格有数据" in view(b, "overview").text
        assert [t.one("div", "tile-n").text for t in view(b, "overview").all("div", "tile")] == ["0"] * 5
        assert "这个题目还没有写数据概览。" in view(b, "gaps").text and "工作记录里还没有检索的记录。" in view(b, "gaps").text
        assert "这一批里还没有非学术来源。" in view(b, "non-academic").text and "还没有记到和这四块有关的关系。" in view(b, "non-academic").text


def test_browser_new_pages_jump_and_link():
    with T.opened() as (go, page, seen):
        go("ASM-000001")
        T.wait_view(page, "gaps")
        T.wait_until(page, "document.getElementById('ASM-000001').classList.contains('target')")
        go("SRC-000004")
        T.wait_view(page, "non-academic")
        T.wait_until(page, "document.getElementById('SRC-000004').classList.contains('target')")
        go("overview")
        T.wait_view(page, "overview")
        page.click("#coverage tr[data-membrane='SRC-000001|X-1'] a.cov-link")
        T.wait_view(page, "evidence")
        T.wait_until(page, "document.getElementById('EV-000001-001').classList.contains('open')")
        assert seen["errors"] == []
    with T.opened(script=False) as (go, page, seen):   # 不跑脚本：五页都摊开，三页的内容照样看得到
        go("overview")
        for card_id in ("coverage", "summary-table", "block-patent"):
            assert page.is_visible(f"#{card_id}"), card_id


# ---------------------------------------------------------------- 报告这一侧的导出

MARKERS = {"snippet": "只留内部的原文片段", "conditions_snippet": "只留内部的条件片段", "internal_note": "只留内部的备注"}
REPORT = {"id": "RPT-000001", "topic_id": "TOP-000001", "title": "示例报告草样（虚构）", "language": "zh", "version": "0.1", "status": "draft"}


@contextlib.contextmanager
def report_copy(**fields):
    """示例数据的一份副本，加一份报告登记。"""
    with T.example_copy() as data:
        T.edit_json(data, REPORTS, lambda doc: doc.append(dict(REPORT, **fields)))
        yield data


def export(data, text=None, with_csv=False):
    ds = V.load_dataset(data)
    return X.build_export(ds, SCHEMA, B.load_labels(data), "RPT-000001", T.VERSION, text, with_csv)


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = X.main(list(argv))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def test_exported_rows_carry_no_internal_fields():
    """给对方的文件里不能带出原文片段、内部备注、风险档、机器核对结果、操作人（V-64，D-56）。"""
    with report_copy(evidence_ids=["EV-000004-001", "EV-000005-001"], cmp_ids=["CMP-000001"]) as data:
        for eid in ("EV-000001-001", "EV-000004-001", "EV-000002-001"):
            T.edit_evidence(data, eid, lambda e: e.update({k: f"{v}（{e['id']}）" for k, v in MARKERS.items()}))
        calls, real = [], V.strip_internal
        try:
            V.strip_internal = lambda e: calls.append(e["id"]) or real(e)
            files, result, _ = export(data, with_csv=True)
        finally:
            V.strip_internal = real
        assert sorted(calls) == sorted(["EV-000001-001", "EV-000001-002", "EV-000004-001", "EV-000005-001"] + [
            "EV-000001-001", "EV-000001-002", "EV-000001-003", "EV-000001-004", "EV-000002-001", "EV-000003-001", "EV-000004-001", "EV-000004-002",
            "EV-000005-001"]), "每一行都先过 strip_internal（V-64）：附录 4 行，数据文件 9 行"
        assert sorted(files) == ["appendix-evidence.json", "appendix-evidence.md", "charts/CMP-000001.svg", "check.txt", "evidence-data.csv", "evidence-data.json"]
        blob = "\n".join(files.values())
        for text in list(MARKERS.values()) + ["同一来源里有多个样品", "高档", "risk", "machine_check", "verified_by", "created_by", "entry_method",
                                              "double_extraction", "两遍", "yu", "kai", "claude"]:
            assert text not in blob, text
        full = json.loads(files["evidence-data.json"])
        assert [c["key"] for c in full["columns"]] == [k for k, _ in X.COLUMNS] and all(list(row) == [k for k, _ in X.COLUMNS] for row in full["evidence"])
        assert (full["report"], full["cutoff_date"], full["data_version"], full["topic"]["id"]) == ("RPT-000001", "2026-11-11", T.VERSION, "TOP-000001")
        row = next(r for r in full["evidence"] if r["id"] == "EV-000001-003")
        assert row == {
            "id": "EV-000001-003", "subject": "示例非氟材料族 N（虚构）", "sample_label": "X-1", "level": "组件或器件", "measure": "能量效率",
            "value": "81.2%", "value_std": "", "range": "", "summary": "",
            "conditions": "电流密度 120 mA cm-2；钒离子浓度 1.6 M；硫酸浓度 3.0 M H2SO4；温度 25 °C", "evidence_type": "实验数据",
            "obtained_from": "图上读数", "flags": "图上读数（读数误差 ± 0.5）", "source_id": "SRC-000001", "source_type": "论文", "jurisdiction": "",
            "source": "示例论文 A（虚构）；示例作者 等；示例期刊；2023-05；出版版；https://doi.org/10.0000/example.0001", "locator": "第 7 页，图 4b",
            "obtained_at": "2026-11-11", "last_verified_at": "2026-11-11", "verification_status": "人工已核", "dispute_note": "", "scope_note": "",
            "groups": "", "questions": ""}
        first = next(r for r in full["evidence"] if r["id"] == "EV-000001-001")
        assert first["groups"] == "CMP-000001（直接可比，参与比较）", "只列专业复核过的组：还是草稿的组，档别是预归的，不出去"
    with report_copy() as data:   # 草稿的组就算标了可对外也不列；复核过但只留内部的组也不列
        T.edit_json(data, os.path.join(TOPIC, "comparisons.json"), lambda doc: (doc[1].update(visibility="external"), doc[0].update(visibility="internal")))
        full = json.loads(export(data)[0]["evidence-data.json"])
        assert next(r for r in full["evidence"] if r["id"] == "EV-000001-001")["groups"] == ""


def test_data_file_has_every_exportable_evidence_with_its_status():
    with report_copy() as data:
        set_status(data, "EV-000004-002", "void", void_reason="重复")
        T.edit_source(data, "SRC-000003", lambda doc: doc["source"].update(external_use="link_only"))
        files, _, summary = export(data, with_csv=True)
        full = json.loads(files["evidence-data.json"])
        assert [r["id"] for r in full["evidence"]] == ["EV-000001-001", "EV-000001-002", "EV-000001-003", "EV-000001-004", "EV-000002-001",
                                                       "EV-000004-001", "EV-000005-001"], "内部的 4 条、作废的、来源只给题录和链接的不进"
        assert {r["verification_status"] for r in full["evidence"]} == {"专业已复核", "人工已核", "机器已核"}, "还没有人工核对的照实带着状态（D-102）"
        assert [x for x in summary if x.startswith("没有进数据文件的")] == ["没有进数据文件的 4 条：可见范围不是“可对外”", "没有进数据文件的 1 条：已作废",
                                                                         "没有进数据文件的 1 条：来源只能给题录和链接"]
        text = files["evidence-data.csv"]
        assert text.startswith("﻿") and text.count("\r\n") == 8
        import csv as csv_module
        table = list(csv_module.reader(io.StringIO(text[1:])))
        assert table[0] == [n for _, n in X.COLUMNS] and [r[0] for r in table[1:]] == [r["id"] for r in full["evidence"]]
        assert table[5][5] == "0.45 Ω cm²" and table[5][10] == "企业声明"
    with report_copy() as data:   # 表格软件不会把格子当公式算
        T.edit_evidence(data, "EV-000004-001", lambda e: e.update(summary="=HYPERLINK(\"http://x\")"))
        files, _, _ = export(data, with_csv=True)
        assert "'=HYPERLINK" in files["evidence-data.csv"]


THRESHOLD_CASES = [
    # (说的是什么, 怎么改数据, 哪一条, 进不进附录, 不进的原因)
    ("人工已核、正文直接引用的进附录", None, "EV-000004-001", True, ""),
    ("专业已复核、在引用的可比组里的进附录", None, "EV-000001-001", True, ""),
    ("机器已核的不进", lambda d: set_status(d, "EV-000004-001", "machine_checked"), "EV-000004-001", False, "没到对外门槛（至少人工已核）"),
    ("待核的不进", lambda d: set_status(d, "EV-000005-001", "pending"), "EV-000005-001", False, "没到对外门槛（至少人工已核）"),
    ("存疑、人工核对过并写明分歧的可以进", lambda d: set_status(d, "EV-000004-001", "disputed", dispute_note="两处说法不一致"), "EV-000004-001", True, ""),
    ("存疑、没有写分歧的不进", lambda d: set_status(d, "EV-000004-001", "disputed"), "EV-000004-001", False, "没到对外门槛（至少人工已核）"),
    ("只留内部的不进", lambda d: T.edit_evidence(d, "EV-000005-001", lambda e: e.update(visibility="internal")), "EV-000005-001", False, "可见范围不是“可对外”"),
    ("来源只给题录和链接的不进", lambda d: T.edit_source(d, "SRC-000004", lambda doc: doc["source"].update(external_use="link_only")),
     "EV-000004-001", False, "来源只能给题录和链接"),
    ("作废的不进", lambda d: set_status(d, "EV-000005-001", "void", void_reason="重复"), "EV-000005-001", False, "已作废"),
    ("进了对比、只到人工已核的不进", lambda d: set_status(d, "EV-000001-002", "human_verified"), "EV-000001-002", False, "进了对比或作了描述的依据，还没有专业复核"),
    ("数据里没有的编号", lambda d: T.edit_json(d, REPORTS, lambda doc: doc[0]["evidence_ids"].append("EV-000099-001")), "EV-000099-001", False,
     "数据里没有这一条，或者这一条显示不出来"),
]


def test_appendix_holds_only_cited_evidence_that_meets_the_threshold():
    for what, change, eid, inside, why in THRESHOLD_CASES:
        with report_copy(evidence_ids=["EV-000004-001", "EV-000005-001"], cmp_ids=["CMP-000001"]) as data:
            if change:
                change(data)
            files, _, summary = export(data)
            rows = json.loads(files["appendix-evidence.json"])["evidence"]
            assert (eid in [r["id"] for r in rows]) == inside, what
            assert (f"引用到、没有进附录的 {eid}：{why}" in summary) == (not inside), (what, summary)
            if "分歧" in what and inside:
                assert next(r for r in rows if r["id"] == eid)["dispute_note"] == "两处说法不一致", "存疑的要用就写明分歧"
    with report_copy(evidence_ids=["EV-000004-001", "EV-000005-001"], cmp_ids=["CMP-000001"]) as data:
        files, _, _ = export(data)
        rows = json.loads(files["appendix-evidence.json"])["evidence"]
        assert [r["id"] for r in rows] == ["EV-000001-001", "EV-000001-002", "EV-000004-001", "EV-000005-001"], "只有引用到的，照编号排"
        md = files["appendix-evidence.md"].splitlines()
        assert md[2] == f"报告 RPT-000001｜截至 2026-11-11｜数据版本 {T.VERSION}｜正文引用到的证据 4 条。全部证据见随报告给的数据文件 evidence-data.json。"
        assert md[4] == "| 证据编号 | 对象 | 层级 | 指标或事实项 | 数值 | 条件 | 证据类型 | 来源 | 出处位置 | 核验状态 | 所在可比组和档别 |"
        assert md[6].startswith("| EV-000001-001 | 示例非氟材料族 N（虚构）（X-1） | 组件或器件 | 能量效率 | 85.6% | 电流密度 80 mA cm-2；")
        assert md[8].split(" | ")[4] == "独立权利要求保护一种示例膜和用它的液流电池（虚构）" and len(md) == 10
    with report_copy(evidence_ids=["EV-000004-001"]) as data:   # 格子里的竖线和换行不能把表拆开
        T.edit_evidence(data, "EV-000004-001", lambda e: e.update(summary="第一行 | 带竖线\n第二行"))
        md = export(data)[0]["appendix-evidence.md"].splitlines()
        assert len(md) == 7 and "第一行 ｜ 带竖线 第二行" in md[6] and md[6].count(" | ") == 10
    with report_copy(asm_ids=["ASM-000001"]) as data:   # 描述的依据算引用到的；依据里的组没有列进登记就提醒
        files, result, _ = export(data)
        assert [r["id"] for r in json.loads(files["appendix-evidence.json"])["evidence"]] == ["EV-000001-001", "EV-000001-002"]
        assert "描述 ASM-000001 的依据里有可比组 CMP-000001，报告登记的 cmp_ids 里没有列它；它的成员这里照样算作引用到的" in result["notes"]


def test_report_charts_show_only_expert_reviewed_members():
    with report_copy(cmp_ids=["CMP-000001", "CMP-000002"]) as data:
        files, _, summary = export(data)
        assert [k for k in files if k.startswith("charts/")] == ["charts/CMP-000001.svg"]
        svg = files["charts/CMP-000001.svg"]
        assert svg.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg"') and "<a" not in svg and "href" not in svg
        assert "style=" not in svg and "<script" not in svg and ">X-1<" in svg and "示例商业膜 P（虚构）" in svg
        assert "CMP-000002 还没有专业复核，没有出图" in summary
        note = next(x for x in summary if x.startswith("charts/CMP-000001.svg"))
        assert note.endswith(f"截至 2026-11-11｜数据版本 {T.VERSION}｜图中的数都经过专业复核") and "图上 2 个点" in note
    with report_copy(cmp_ids=["CMP-000001"]) as data:   # 组里有一条还没到专业已复核：图里不放，说明里写出来
        set_status(data, "EV-000001-001", "human_verified")
        files, _, summary = export(data)
        note = next(x for x in summary if "CMP-000001" in x)
        assert "charts/CMP-000001.svg" in files and ">X-1<" not in files["charts/CMP-000001.svg"] and "示例商业膜 P（虚构）" in files["charts/CMP-000001.svg"]
        assert note.endswith("没有放进图的成员 1 条（还没有专业复核，或不可对外）：EV-000001-001") and "图上 1 个点" in note


READY = dict(evidence_ids=["EV-000004-001", "EV-000005-001"], cmp_ids=["CMP-000001"], data_version="abc1234", issued_at="2026-11-20",
             evidence_file="reports/RPT-000001/evidence-data.json")
CHECK_CASES = [
    # (说的是什么, 报告登记多写什么, 怎么改数据, 应该报出的问题里的字)
    ("齐了就没有问题", {}, None, []),
    ("没记数据版本和发出日期", {"data_version": None}, None, ["V-60　RPT-000001：已发出的报告要记数据版本和发出日期"]),
    ("没附数据文件", {"evidence_file": None}, None, ["V-60　RPT-000001：已发出的报告要随附全部证据的数据文件"]),
    ("引用的描述还是草稿", {"asm_ids": ["ASM-000001"]}, None, ["V-61　ASM-000001：报告引用的描述要已复核"]),
    ("引用的组还没有专业复核", {"cmp_ids": ["CMP-000002"]}, None, ["V-61　CMP-000002：对外用的可比组要专业已复核"]),
    ("引用的证据只到机器已核", {"evidence_ids": ["EV-000004-002"]}, None, ["V-60　EV-000004-002：报告引用的证据至少要人工已核"]),
    ("引用了只留内部的证据", {"evidence_ids": ["EV-000006-001"]}, None, ["V-63　EV-000006-001：不可对外"]),
    ("状态查得比截至日期早", {}, lambda d: T.edit_source(d, "SRC-000004", lambda doc: doc["source"]["doc"]["status"].update(checked_at="2026-10-01")),
     ["V-66　SRC-000004：出报告前要再查一次状态"]),
    ("专利的登记内容没有人工核对", {}, lambda d: T.edit_source(d, "SRC-000004", lambda doc: [doc["source"].pop(k) for k in ("record_verified_by", "record_verified_at")]),
     ["V-60　SRC-000004：报告用到的专利、政策法规、标准、资助记录，登记内容（doc）要人工核对过"]),
    ("数据本身没通过校验", {}, lambda d: T.edit_evidence(d, "EV-000002-001", lambda e: e.pop("level")), ["V-20　EV-000002-001"]),
    ("引用了数据里没有的证据", {"evidence_ids": ["EV-000099-001"]}, None, ["V-02　RPT-000001"]),
]


def test_check_treats_the_draft_as_if_it_were_issued():
    for what, fields, change, wanted in CHECK_CASES:
        merged = {k: v for k, v in dict(READY, **fields).items() if v is not None}
        with report_copy(**merged) as data:
            if change:
                change(data)
            before = open(os.path.join(data, REPORTS), encoding="utf-8").read()
            ds = V.load_dataset(data)
            result = X.check(ds, SCHEMA, "RPT-000001")
            assert ds["reports"]["RPT-000001"]["status"] == "draft", "只在内存里当它已经发出，查完改回去"
            assert open(os.path.join(data, REPORTS), encoding="utf-8").read() == before, "检查不写数据"
            assert bool(result["problems"]) == bool(wanted), (what, result["problems"])
            for text in wanted:
                assert any(text in p for p in result["problems"]), (what, text, result["problems"])
    with report_copy(**READY) as data:
        ds = V.load_dataset(data)
        assert X.check(ds, SCHEMA, "RPT-000001", version="def5678")["notes"] == ["报告登记的数据版本是 abc1234，现在的数据是 def5678"]
        assert X.check_text("RPT-000001", X.check(ds, SCHEMA, "RPT-000001")) == "RPT-000001 发出前检查：没有查出问题\n"
    with report_copy() as data:
        assert "报告登记里还没有列引用到的证据（evidence_ids、cmp_ids、asm_ids）" in X.check(V.load_dataset(data), SCHEMA, "RPT-000001")["notes"]


TEXT_CASES = [
    # (说的是什么, 正文, 应该报的问题, 应该请人看的, 不应该请人看的)
    ("数和证据对得上", "X-1 的能量效率是 85.6%（EV-000001-001），基准膜是 82.0%（EV-000001-002）。", [], [], ["85.6", "82.0"]),
    ("数抄错了", "X-1 的能量效率是 86.5%（EV-000001-001）。", [], ["“86.5%”在所引证据（EV-000001-001）"], []),
    ("比值和差值是算出来的也认", "比值是 1.044，高 3.6 个百分点（CMP-000001）。", [], [], ["1.044", "3.6"]),
    ("比值写错了", "比值是 1.05（CMP-000001）。", [], ["“1.05”在所引证据（EV-000001-001、EV-000001-002）"], []),
    ("少写一位小数的比值也认", "比值约 1.04（CMP-000001）。", [], [], ["1.04"]),
    ("条件里的数也认", "在 1.6 M 钒、3.0 M 硫酸、80 mA cm-2 下是 85.6%（EV-000001-001）。", [], [], ["1.6", "3.0", "85.6"]),
    ("条件写错了", "在 1.5 M 钒下是 85.6%（EV-000001-001）。", [], ["“1.5”在所引证据（EV-000001-001）"], ["“85.6"]),
    ("表格的一行算一句", "| X-1 | 85.9% | EV-000001-001 |\n| 基准 | 82.0% | EV-000001-002 |", [], ["“85.9%”"], ["82.0"]),
    ("一句只查它自己引的证据", "X-1 是 82.0%（EV-000001-001）；基准膜是 82.0%（EV-000001-002）。", [], ["“82.0%”在所引证据（EV-000001-001）"], []),
    ("条数和年份不查", "2023 年的 3 种膜里有 2 种高于基准（EV-000001-001）；另见示例期刊，2023（EV-000001-001）。", [], [], ["2023", "“3”", "“2”"]),
    ("三位以上的整数要查", "循环 500 次（EV-000001-001）。", [], ["“500”在所引证据"], []),
    ("描述引的是它的依据", "高 3.6 个百分点（ASM-000001）。", ["正文引用了 ASM-000001，报告登记里没有列"], [], ["3.6"]),
    ("正文里的编号数据里没有", "见 EV-000099-001。", ["正文里的 EV-000099-001 数据里没有"], [], []),
    ("正文引用了、登记里没有列", "见 EV-000003-001 和 CMP-000002。", ["正文引用了 EV-000003-001，报告登记里没有列", "正文引用了 CMP-000002，报告登记里没有列"], [], []),
    ("登记里列了、正文没出现", "只提 EV-000004-001 和 CMP-000001。", [], ["登记里列了 EV-000005-001，正文里没有出现"], ["登记里列了 EV-000004-001"]),
    ("一段编号写成“至”，中间的也算引用到", "85.6% 和 82.0%（EV-000001-001 至 EV-000001-003）。", ["正文引用了 EV-000001-003，报告登记里没有列"], [], ["85.6", "82.0"]),
    ("带千分位和科学记数的写法", "渗透率 2.1×10⁻⁷，价格 3,200（EV-000001-001）。", [], ["“2.1×10⁻⁷”", "“3,200”"], []),
    ("没带编号的句子没法查", "有的膜到了 99.9%。", [], [], ["99.9"]),
]


def test_check_reads_ids_and_numbers_in_the_report_text():
    for what, text, problems, hints, quiet in TEXT_CASES:
        with report_copy(**READY) as data:
            ds = V.load_dataset(data)
            result = X.check(ds, SCHEMA, "RPT-000001", text)
            got = [p for p in result["problems"] if p.startswith("正文")]
            assert len(got) == len(problems) and all(any(w in p for p in got) for w in problems), (what, got)
            for w in hints:
                assert any(w in h for h in result["hints"]), (what, w, result["hints"])
            for w in quiet:
                assert not any(w in h for h in result["hints"]), (what, w, result["hints"])
    with report_copy(**READY) as data:   # 写成 a×10ⁿ、带千分位的数，和数据一样就不提
        T.edit_evidence(data, "EV-000002-001", lambda e: e.update(value_reported="2.1×10⁻⁷"))
        ds = V.load_dataset(data)
        hints = X.check(ds, SCHEMA, "RPT-000001", "面电阻 2.1×10⁻⁷（EV-000002-001）；另一处 2.1 x 10^-7（EV-000002-001）。")["hints"]
        assert not any("2.1" in h for h in hints), hints
        T.edit_evidence(data, "EV-000001-001", lambda e: e["conditions"]["vanadium_conc"].update(reported="1600 mol m-3"))
        ds = V.load_dataset(data)   # 条件原文的写法换了单位：解析出来的值也认
        assert not any("“1.6”" in h for h in X.check(ds, SCHEMA, "RPT-000001", "在 1.6 M 钒下是 85.6%（EV-000001-001）。")["hints"])
        note = X.check(ds, SCHEMA, "RPT-000001", "2023 年 3 种膜里 85.6%（EV-000001-001）。没有编号的 77.7%。")["notes"][-1]
        assert note.startswith("数值：带编号的句子里查了 1 个数，对不上的 0 个；另有 1 个整数没有查"), "写成“2023 年”的当日期去掉，不算数"
        assert note.endswith("1 个数所在的句子没有带编号、没法查")
    assert X.ids_in("EV-000001-001、EV-000001-0010、XEV-000001-002、CMP-000001、CMP-0000019、REL-000004，EV-000001-001") == {
        "EV": ["EV-000001-001", "EV-000001-0010"], "CMP": ["CMP-000001"], "ASM": [], "REL": ["REL-000004"]}, "不认粘在别的字母数字后面的；重复的只算一次"


DRAFT_TEXT = """# 示例报告草样（虚构）

在 80 mA cm-2 下，X-1 的能量效率是 85.6%（EV-000001-001），同文基准膜是 82.0%（EV-000001-002），比值 1.044（CMP-000001）。
专利的独立权利要求保护一种示例膜（EV-000004-001）。提案把示例含氟聚合物列在范围内（EV-000005-001）。
论文致谢写明受这个项目资助（REL-000004）。另见 EV-000099-001。
"""


def test_cite_brings_the_register_in_line_with_the_text():
    with report_copy(evidence_ids=["EV-000003-001"]) as data, tempfile.TemporaryDirectory() as tmp:
        text = os.path.join(tmp, "正文.md")
        with open(text, "w", encoding="utf-8") as fh:
            fh.write(DRAFT_TEXT)
        before = open(os.path.join(data, REPORTS), encoding="utf-8").read()
        code, out, err = run("--data", data, "cite", "RPT-000001", "--text", text)
        assert code == 0 and out.splitlines() == [
            "evidence_ids：正文里 4 个，要加 EV-000001-001、EV-000001-002、EV-000004-001、EV-000005-001，要去掉 EV-000003-001",
            "  正文里的 EV-000099-001 数据里没有，不写进登记", "rel_ids：正文里 1 个，要加 REL-000004", "cmp_ids：正文里 1 个，要加 CMP-000001",
            "asm_ids：正文里 0 个，和登记一样"]
        assert open(os.path.join(data, REPORTS), encoding="utf-8").read() == before, "不加 --write 只看不写"
        code, out, err = run("--data", data, "cite", "RPT-000001", "--text", text, "--write")
        assert code == 0 and out.splitlines()[-1] == "写回了 RPT-000001 的登记"
        saved = json.load(open(os.path.join(data, REPORTS), encoding="utf-8"))[0]
        assert list(saved) == ["id", "topic_id", "title", "language", "version", "status", "evidence_ids", "rel_ids", "cmp_ids", "asm_ids"][:9], "四个清单照模板的次序"
        assert saved["evidence_ids"] == ["EV-000001-001", "EV-000001-002", "EV-000004-001", "EV-000005-001"] and saved["rel_ids"] == ["REL-000004"]
        assert V.validate(V.load_dataset(data), SCHEMA) == []
        code, out, err = run("--data", data, "cite", "RPT-000001", "--text", text, "--write")
        assert code == 0 and out.splitlines()[-1] == "登记不用改"
    for fields, change, message in (
            ({"status": "issued", "issued_at": "2026-11-20", "data_version": "abc1234", "evidence_file": "x.json"}, None, "RPT-000001 不是草稿，登记不由脚本改"),
            ({}, lambda d: T.edit_evidence(d, "EV-000002-001", lambda e: e.pop("level")), "改完之后校验不过，没有写：V-20 EV-000002-001"),
            ({}, lambda d: T.edit_json(d, REVIEWS, lambda doc: doc.append({"title": "没有编号的一张"})), "数据里有读不了的文件或重复的编号，先修好再写")):
        with report_copy(**fields) as data, tempfile.TemporaryDirectory() as tmp:
            if change:
                change(data)
            text = os.path.join(tmp, "正文.md")
            with open(text, "w", encoding="utf-8") as fh:
                fh.write(DRAFT_TEXT)
            before = open(os.path.join(data, REPORTS), encoding="utf-8").read()
            code, out, err = run("--data", data, "cite", "RPT-000001", "--text", text, "--write")
            assert code == 2 and message in err, (message, err)
            assert open(os.path.join(data, REPORTS), encoding="utf-8").read() == before, "不合规矩就一个字也不写"


def test_command_line_from_text_to_files():
    with report_copy(**{k: v for k, v in READY.items() if k not in ("evidence_ids", "cmp_ids")}) as data, tempfile.TemporaryDirectory() as tmp:
        text, out_dir = os.path.join(tmp, "正文.md"), os.path.join(tmp, "出", "RPT-000001")
        with open(text, "w", encoding="utf-8") as fh:
            fh.write(DRAFT_TEXT.replace("另见 EV-000099-001。", ""))
        assert run("--data", data, "cite", "RPT-000001", "--text", text, "--write")[0] == 0
        code, out, err = run("--data", data, "--version", "abc1234", "check", "RPT-000001", "--text", text)
        assert code == 1 and "问题　V-65　REL-000004：报告引用的关系要人工已核" in out and "问题　V-63　REL-000004：不可对外" in out
        T.edit_json(data, "public/relations.json", lambda doc: doc[3].update(verification_status="human_verified", verified_by="yu", verified_at="2026-11-12", visibility="external"))
        code, out, err = run("--data", data, "--version", "abc1234", "check", "RPT-000001", "--text", text)
        assert code == 0 and out.splitlines()[0] == "RPT-000001 发出前检查：没有查出问题" and "请人看" not in out, out
        code, out, err = run("--data", data, "--version", "abc1234", "export", "RPT-000001", "--out", out_dir, "--csv", "--text", text)
        assert code == 0 and out.splitlines()[0] == f"写到 {out_dir}：appendix-evidence.json、appendix-evidence.md、charts/CMP-000001.svg、check.txt、evidence-data.csv、evidence-data.json"
        first = {name: open(os.path.join(base, name), "rb").read() for base, _, names in os.walk(out_dir) for name in names}
        assert sorted(first) == ["CMP-000001.svg", "appendix-evidence.json", "appendix-evidence.md", "check.txt", "evidence-data.csv", "evidence-data.json"]
        assert "导出　报告登记里要写：data_version = abc1234；evidence_file = reports/RPT-000001/evidence-data.json" in first["check.txt"].decode("utf-8")
        assert run("--data", data, "--version", "abc1234", "export", "RPT-000001", "--out", out_dir, "--csv", "--text", text)[0] == 0
        again = {name: open(os.path.join(base, name), "rb").read() for base, _, names in os.walk(out_dir) for name in names}
        assert again == first, "同一份数据、同一个版本，导出的文件逐字节相同"
        assert not any(tmp.encode() in v or data.encode() in v for k, v in first.items() if k != "check.txt"), "文件里不带本机的路径"
    for argv, message in ((["check", "RPT-000009"], "报告登记里没有 RPT-000009"), (["cite", "RPT-000001", "--text", "/没有/这个文件.md"], "读不了正文文件")):
        with report_copy() as data:
            code, out, err = run("--data", data, *argv)
            assert code == 2 and message in err, err
    code, out, err = run("--data", "/没有/这个目录", "check", "RPT-000001")
    assert code == 2 and "找不到数据目录" in err


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
    cases = len(CELL_CASES) + len(OVERVIEW_CASES) + len(GAP_CASES) + len(NA_CASES) + len(THRESHOLD_CASES) + len(CHECK_CASES) + len(TEXT_CASES)
    print(f"{cases} 处对错的用例" + ("，结果都和预期的一样" if not failed else ""), "｜失败", failed, "｜跳过", skipped)
    sys.exit(1 if failed else 0)
