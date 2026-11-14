#!/usr/bin/env python3
"""看板生成脚本的测试。直接跑：python3 tools/tests/test_dashboard.py；也可以用 pytest。

和另外两组测试一个做法：tools/tests/example/ 的示例数据（全部虚构）生成出来，页面上的内容要和数据逐项对得上；
再逐处把数据改坏，每改一处，页面要么照实标出来，要么照样生成，不能垮，也不能把来源里的文字当成网页代码。

页面里的脚本（切换页面、筛选、展开、跳到一条证据、复制）要用浏览器才测得到。
装了 playwright 和 Chrome 就真的打开页面点一遍；没装就跳过这几项，并写明跳过了。
环境变量 DASHBOARD_BROWSER_TESTS=required 时不许跳过（GitHub Actions 上这样设）。
"""
import contextlib
import copy
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

import build_dashboard as B  # noqa: E402
import validate as V  # noqa: E402

EXAMPLE = os.path.join(HERE, "example")
VERSION = "测试版本"
ALL_VIEWS = ["overview", "evidence", "compare", "gaps", "non-academic"]


# ---------------------------------------------------------------- 读生成出来的页面

class Node:
    def __init__(self, tag, attrs=None, parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs or []), parent, []

    def walk(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.walk()

    def all(self, tag=None, cls=None, **attrs):
        out = []
        for n in self.walk():
            if n is self or (tag and n.tag != tag):
                continue
            if cls and cls not in (n.attrs.get("class") or "").split():
                continue
            if any(n.attrs.get(k.replace("_", "-")) != v for k, v in attrs.items()):
                continue
            out.append(n)
        return out

    def one(self, tag=None, cls=None, **attrs):
        found = self.all(tag, cls, **attrs)
        assert len(found) == 1, f"要找恰好一个 {tag} {cls} {attrs}，找到 {len(found)} 个"
        return found[0]

    @property
    def text(self):
        return "".join(c if isinstance(c, str) else c.text for c in self.children)

    @property
    def clean(self):
        return " ".join(self.text.split())


class Dom(HTMLParser):
    VOID = {"meta", "br", "input", "hr", "link", "img", "base", "source", "embed"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in self.VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def parse(page):
    dom = Dom()
    dom.feed(page)
    dom.close()
    return dom.root


class Built:
    """一次生成的结果：退出码、输出的文字、网页、解析好的网页、表格文件的各行。"""

    def __init__(self, data, **kw):
        lines = []
        with tempfile.TemporaryDirectory() as out:
            kw.setdefault("version", VERSION)
            self.code = B.build(data, out, log=lines.append, **kw)
            self.log = "\n".join(lines)
            self.files = sorted(os.listdir(out)) if os.path.isdir(out) else []
            self.page = self.raw_csv = ""
            if self.code != 2:
                with open(os.path.join(out, B.PAGE_NAME), encoding="utf-8", newline="") as fh:
                    self.page = fh.read()
                with open(os.path.join(out, B.CSV_NAME), "rb") as fh:
                    self.raw_csv = fh.read()
        self.dom = parse(self.page)
        text = self.raw_csv.decode("utf-8-sig") if self.raw_csv else ""
        self.table = list(csv.reader(io.StringIO(text, newline="")))

    def row(self, eid):
        return self.dom.one("tbody", "ev", id=eid)

    def cell(self, eid, cls):
        return self.row(eid).one("tr", "ev-main").one("td", cls)

    def detail(self, eid):
        return self.row(eid).one("tr", "ev-detail")

    def block(self, eid, name):
        """展开的一块里，名字以 name 开头的那一栏。"""
        found = [b for b in self.detail(eid).all("div", "block") if b.one("div", "block-name").text.startswith(name)]
        assert len(found) == 1, f"{eid} 里要找恰好一栏“{name}”，找到 {len(found)} 栏"
        return found[0]

    def csv_cell(self, eid, column):
        head = self.table[0]
        line = next(r for r in self.table[1:] if r[0] == eid)
        return line[head.index(column)]

    def problems(self):
        found = self.dom.all("div", "banner", id="problems")
        return [li.clean for li in found[0].all("li")] if found else []


def fresh():
    return V.load_dataset(EXAMPLE)


@contextlib.contextmanager
def example_copy():
    """示例数据的一份临时拷贝，改坏了再生成用。"""
    with tempfile.TemporaryDirectory() as tmp:
        data = os.path.join(tmp, "data")
        shutil.copytree(EXAMPLE, data)
        yield data


def edit_source(data, sid, change):
    """改一个来源文件：change 拿到整个文件 {source, samples, evidence}，就地改。"""
    path = os.path.join(data, "public", "sources", f"{sid}.json")
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    change(doc)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def edit_evidence(data, eid, change):
    sid = "SRC-" + eid.split("-")[1]
    edit_source(data, sid, lambda doc: change(next(e for e in doc["evidence"] if e["id"] == eid)))


def edit_json(data, rel, change):
    path = os.path.join(data, rel)
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    change(doc)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


EXAMPLE_BUILD = None


def example():
    """示例数据生成一次，好几项测试共用。"""
    global EXAMPLE_BUILD
    if EXAMPLE_BUILD is None:
        EXAMPLE_BUILD = Built(EXAMPLE)
    return EXAMPLE_BUILD


# ---------------------------------------------------------------- 示例数据：页面和数据对得上

def test_example_builds_clean():
    b = example()
    assert b.code == 0, b.log
    assert b.files == [B.CSV_NAME, B.PAGE_NAME], b.files
    assert "数据校验：全部通过" in b.log, b.log
    assert b.problems() == []
    assert not b.dom.all("div", "flag") or all("显示不出来" not in n.text for n in b.dom.all("div", "flag"))
    assert b.page.startswith("<!DOCTYPE html>\n")
    assert b.page.endswith("</html>\n")


def test_every_page_shows_cutoff_date_and_data_version():
    """题目、截至日期、数据版本在页头里，五个页面共用这个页头（设计方案 4.4 第 9 项）。"""
    b = example()
    assert b.dom.one("h1").text == "示例题目（虚构数据，仅用于说明字段）"
    assert b.dom.one("div", id="stamp").text == f"截至 2026-11-11｜数据版本 {VERSION}"
    assert b.dom.one("footer").text.endswith(f"截至 2026-11-11｜数据版本 {VERSION}")
    assert b.dom.one("div", id="notice").text == "测试用的示例数据，全部虚构，不是证据"
    assert b.dom.one("head").one("title").text == "示例题目（虚构数据，仅用于说明字段）｜对内看板"


def test_skeleton_has_the_five_pages():
    b = example()
    links = b.dom.one("nav", "pages").all("a")
    assert [(a.attrs["href"], a.attrs["data-view"], a.text) for a in links] == [
        ("#overview", "overview", "总览"), ("#evidence", "evidence", "证据表"), ("#compare", "compare", "对标视图"),
        ("#gaps", "gaps", "数据概览与缺口"), ("#non-academic", "non-academic", "非学术来源")]
    views = b.dom.one("main").all("section", "view")
    assert [v.attrs["id"] for v in views] == ALL_VIEWS
    done = {name for name, _, _, _, step in B.VIEWS if step is None}
    assert done == {"evidence", "compare"}, "做好了的页面：证据表、对标视图"
    for v in views:
        assert ("还没有做" in v.text) == (v.attrs["id"] not in done), v.attrs["id"]
    assert "13 条证据，来自 8 个来源" in b.dom.one("section", "view", id="overview").text
    # 网页版只让“字母、数字、连字符”的名字出现在 # 后面；settings、sidebar 等几个名字它自己占着
    for name in ALL_VIEWS:
        assert re.fullmatch(r"[a-z][a-z0-9-]*", name)
        assert name not in ("settings", "sidebar", "customize", "upgrade", "downloads") and not name.startswith("comment-")


def test_legend_is_the_same_everywhere_and_complete():
    """全站一套图例，放在五个页面共用的位置；六类证据类型、六档核验状态、四档可比性、三档风险都在。"""
    b = example()
    legend = b.dom.one("section", "legend")
    assert legend.parent.tag == "div" and "page" in legend.parent.attrs["class"], "图例要在五个页面之外，共用一份"
    cols = {c.one("h3").text: c for c in legend.all("div", "legend-col")}
    assert list(cols) == ["证据类型", "核验状态", "可比档", "风险档"]
    types = [(i.one("use").attrs["href"], i.clean) for i in cols["证据类型"].all("div", "legend-item")]
    assert types == [("#m-verified_fact", "已核实事实"), ("#m-company_claim", "企业声明"),
                     ("#m-third_party_analysis", "第三方分析"), ("#m-experimental", "实验数据"),
                     ("#m-model_simulation", "模型与模拟结果"), ("#m-expert_judgment", "专业判断")]
    shapes = {s.attrs["id"]: "".join(sorted(f"{c.tag}{sorted(c.attrs.items())}" for c in s.all())) for s in b.dom.all("symbol")}
    assert len(shapes) == 7 and len(set(shapes.values())) == 7, "六类证据类型加一个“不认识的类型”，形状要各不相同"
    statuses = [s.text for s in cols["核验状态"].all("span", "status")]
    assert statuses == ["待核", "机器已核", "人工已核", "专业已复核", "存疑", "作废"]
    assert [d.clean for d in cols["可比档"].all("div")][:4] == [
        "直接可比：可以定量比较", "条件化比较：并排时列出其余条件的差异", "参考性资料：分开呈现，不排名", "数据不足：写明缺什么"]
    risks = [i.clean for i in cols["风险档"].all("div", "legend-item")]
    assert risks[0] == "高 图上读数；两遍抽取不一致；机器核对没通过；数值离群"
    assert risks[1].startswith("中 经过单位换算；") and risks[2] == "低 以上都没有"
    # 颜色不单独表示含义：每个记号、每个状态块旁边或里面都有字
    for mark in b.dom.all("svg", "mark"):
        assert mark.parent.clean, "证据类型的记号旁边要有字"
    for badge in b.dom.all("span", "status") + b.dom.all("span", "risk"):
        assert badge.text.strip(), "状态块里要有字"


# 编号 → (对象, 样品名, 层级, 指标或事实项, 数值, 数值下面的小字, 关键条件, 证据类型, 类型下面的标注, 核验状态, 可比档和所在的组, 风险档)
# 这张表是对着 tools/tests/example/ 里的数据文件一条一条手写的，不是从生成结果抄的
EXPECTED_ROWS = {
    "EV-000001-001": ("示例非氟材料族 N（虚构）", "X-1", "组件或器件", "能量效率", "85.6%", [],
                      "电流密度 80 mA cm-2；钒离子浓度 1.6 M；硫酸浓度 3.0 M H2SO4；温度 25 °C", "实验数据", [], "专业已复核",
                      ["直接可比 CMP-000001", "条件化比较 CMP-000002", "条件化比较 CMP-000003"], "中"),
    "EV-000001-002": ("示例商业膜 P（虚构）", "P-212", "组件或器件", "能量效率", "82.0%", [],
                      "电流密度 80 mA cm-2；钒离子浓度 1.6 M；硫酸浓度 3.0 M H2SO4；温度 25 °C", "实验数据", [], "专业已复核",
                      ["直接可比 CMP-000001，基准", "条件化比较 CMP-000002，基准"], "中"),
    "EV-000001-003": ("示例非氟材料族 N（虚构）", "X-1", "组件或器件", "能量效率", "81.2%", ["读数误差 ± 0.5"],
                      "电流密度 120 mA cm-2；钒离子浓度 1.6 M；硫酸浓度 3.0 M H2SO4；温度 25 °C", "实验数据", ["图上读数"], "人工已核",
                      ["未归组"], "高"),
    "EV-000002-001": ("示例商业膜 P（虚构）", "", "材料", "面电阻", "0.45 Ω cm²", [],
                      "温度 未报告；膜厚 50 µm；测试介质 0.5 M H2SO4", "企业声明", [], "机器已核", ["未归组"], "还没标"),
    "EV-000003-001": ("示例非氟材料族 N（虚构）", "Y-2", "组件或器件", "能量效率", "> 84%", [],
                      "电流密度 80 mA cm-2；钒离子浓度 未报告；硫酸浓度 未报告；温度 未报告", "实验数据", ["仅摘要"], "人工已核",
                      ["条件化比较 CMP-000002，只作参考"], "中"),
    "EV-000004-001": ("示例非氟材料族 N（虚构）", "", "不分层", "专利保护的材料和做法",
                      "独立权利要求保护一种示例膜和用它的液流电池（虚构）", [], "", "已核实事实", [], "人工已核", ["未归组"], "低"),
    "EV-000004-002": ("示例非氟材料族 N（虚构）", "实施例 1", "组件或器件", "能量效率", "84.0%", [],
                      "电流密度 80 mA cm-2；钒离子浓度 1.6 M；硫酸浓度 3.0 M H2SO4；温度 25 °C", "实验数据",
                      ["专利实施例，未经同行评议"], "机器已核", ["条件化比较 CMP-000003"], "低"),
    "EV-000007-001": ("示例磺化聚酰亚胺族 S（虚构）", "Z-1", "组件或器件", "能量效率", "80.5%", [],
                      "电流密度 80 mA cm-2；钒离子浓度 1.6 M；硫酸浓度 3.0 M H2SO4；温度 25 °C", "实验数据",
                      ["预印本，未经同行评议"], "机器已核", ["条件化比较 CMP-000002"], "中"),
    "EV-000011-001": ("示例技术类别：示例液流电池（虚构）", "", "不分层", "装机", "> 15 GWh", [],
                      "年份 2025；范围 全球；口径 新增装机", "第三方分析", ["仅摘要", "付费来源，只用了公开部分"], "待核",
                      ["未归组"], "还没标"),
}


def test_rows_match_the_data():
    b = example()
    ids = [t.attrs["id"] for t in b.dom.all("tbody", "ev")]
    assert ids == sorted(fresh()["evidence"]), "一条证据一行，按编号排"
    assert [th.text for th in b.dom.one("table", "ev-table").one("thead").all("th")] == [
        "编号", "对象", "层级", "指标或事实项", "数值", "关键条件", "证据类型", "核验状态", "可比档和所在的组", "风险档"]
    for eid, want in EXPECTED_ROWS.items():
        subject = b.cell(eid, "c-subject")
        value = b.cell(eid, "c-value")
        kind = b.cell(eid, "c-type")
        group = b.cell(eid, "c-group")
        got = (
            subject.one("span", "strong").text,
            "".join(n.text for n in subject.all("span", "sub")),
            b.cell(eid, "c-level").clean,
            b.cell(eid, "c-measure").clean,
            "".join(c for c in value.one("div", "c").children if isinstance(c, str)).strip(),
            [n.text for n in value.all("span", "sub")],
            b.cell(eid, "c-cond").clean,
            kind.one("span", "type").clean,
            [n.text for n in kind.all("span", "sub")],
            b.cell(eid, "c-status").one("span", "status").text,
            [" ".join(x.text for x in g.all("span")) for g in group.all("span", "group")] or [group.clean],
            b.cell(eid, "c-risk").clean,
        )
        assert got == want, f"{eid}\n页面上：{got}\n应当是：{want}"
        assert b.cell(eid, "c-id").one("button").text == eid


def test_missing_conditions_are_marked_not_hidden():
    """原文没写的条件照实显示“未报告”，并且带记号（不只靠颜色：字本身就写着未报告）。"""
    b = example()
    marked = [n.text for n in b.cell("EV-000003-001", "c-cond").all("span", "missing")]
    assert marked == ["钒离子浓度 未报告", "硫酸浓度 未报告", "温度 未报告"], marked
    assert b.cell("EV-000001-001", "c-cond").all("span", "missing") == []


def test_detail_traces_a_number_to_its_source():
    """每个数都点得到来源：证据 → 原文片段和出处位置 → 来源和链接（设计方案 4.4 第 1 项）。"""
    b = example()
    eid = "EV-000001-001"
    assert b.block(eid, "原文片段").one("blockquote", "snippet").text == "X-1 98.1 87.3 85.6"
    assert "只在内部看板显示" in b.block(eid, "原文片段").one("div", "block-name").text
    assert b.block(eid, "出处").clean == "出处 SRC-000001｜第 6 页，表 2，第 3 行｜取得方式：表格"
    source = b.block(eid, "来源")
    pairs = dict(zip([d.text for d in source.all("dt")], [d.clean for d in source.all("dd")]))
    assert pairs["来源编号"] == "SRC-000001｜论文"
    assert pairs["题名"] == "示例论文 A（虚构）"
    assert pairs["作者或发布机构"] == "示例作者 等" and pairs["刊名或网站名"] == "示例期刊"
    assert pairs["发布日期"] == "2023-05" and pairs["版本"] == "出版版"
    assert pairs["取得日期"] == "2026-11-11｜开放获取的出版版｜全文｜读取工具直接读"
    assert pairs["许可类别"] == "开放许可，可再利用｜CC BY 4.0"
    links = {a.text: a.attrs for a in source.all("a")}
    assert links["10.0000/example.0001"]["href"] == "https://doi.org/10.0000/example.0001"
    assert links["https://example.org/a"]["href"] == "https://example.org/a"
    for attrs in links.values():
        assert attrs["rel"] == "noopener noreferrer" and attrs["target"] == "_blank"
    conds = b.block(eid, "测试条件")
    assert [d.text for d in conds.all("dt")] == ["电流密度", "钒离子浓度", "硫酸浓度", "温度"]
    assert [d.clean for d in conds.all("dd")] == ["80 mA cm-2 解析为 80 mA cm⁻²", "1.6 M 解析为 1.6 mol L⁻¹",
                                                   "3.0 M H2SO4 解析为 3 mol L⁻¹", "25 °C 解析为 25 °C"]


def test_detail_shows_verification_history_in_order():
    b = example()
    steps = [li.clean for li in b.block("EV-000001-001", "核验历史").all("li")]
    assert steps[0] == "2026-11-11 录入（AI 抽取），录入人 claude；两遍抽取：两遍一致"
    assert steps[1] == "2026-11-11 机器核对：标识能解析 通过；原文片段逐字找得到 通过；数值、单位与片段一致 通过"
    assert steps[2] == "2026-11-11 标风险档：中（同一来源里有多个样品或多张表），由 claude 标"
    assert steps[3] == "2026-11-11 人工已核，核对人 yu"
    assert steps[4] == "2026-11-11 专业已复核，复核人 kai"
    assert steps[5].startswith("2026-11-11 核验更正（CHG-000001）：原文数值 由“86.5”改为“85.6”；原因：人工核对发现两位数字抄反；"
                               "错误类型：数值或单位抄错；")
    assert steps[5].endswith("记录人：yu") and len(steps) == 6
    # 还没核过的只有录入一步
    assert [li.clean for li in b.block("EV-000006-001", "核验历史").all("li")] == [
        "2026-11-11 录入（AI 抽取），录入人 claude；两遍抽取：两遍一致"]


def test_history_is_sorted_by_date():
    """各步的日期不一样时按日期排，变化记录插在它发生的那一天；没有日期的排在最后。"""
    with example_copy() as data:
        edit_evidence(data, "EV-000001-001", lambda e: (
            e.update(created_at="2026-11-09", verified_at="2026-11-11", expert_reviewed_at="2026-11-13"),
            e["machine_check"].update(at="2026-11-10"), e["risk"].pop("set_at")))
        path = os.path.join(data, "changes.jsonl")
        with open(path, encoding="utf-8") as fh:
            change = json.loads(fh.readline())
        change["date"] = "2026-11-12"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(change, ensure_ascii=False) + "\n")
        steps = [li.clean for li in Built(data).block("EV-000001-001", "核验历史").all("li")]
        assert [s[:10] for s in steps[:5]] == ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"], steps
        assert [s[11:13] for s in steps[:5]] == ["录入", "机器", "人工", "核验", "专业"], steps
        assert steps[5].startswith("标风险档：中") and len(steps) == 6, steps


def test_detail_of_a_figure_reading():
    b = example()
    eid = "EV-000001-003"
    assert b.detail(eid).all("blockquote") == [], "图上读数没有原文片段"
    assert "图上读数不留片段" in b.block(eid, "原文片段").text
    record = b.block(eid, "图上读数的记录")
    pairs = dict(zip([d.text for d in record.all("dt")], [d.text for d in record.all("dd")]))
    assert pairs == {"读图的做法": "图上取点", "读图的人或 AI": "claude", "找没找过源数据表或补充材料": "找过源数据表和补充材料，没有",
                     "复读人": "yu", "复读日期": "2026-11-11", "复读的值": "81", "读数误差": "0.5"}
    steps = [li.clean for li in b.block(eid, "核验历史").all("li")]
    assert "2026-11-11 复读图上读数：81，复读人 yu" in steps
    assert steps[1] == "2026-11-11 机器核对：标识能解析 通过；原文片段逐字找得到 不适用；数值、单位与片段一致 不适用"
    assert b.block(eid, "风险档和理由").clean == "风险档和理由 高：图上读数；同一来源里有多个样品或多张表"
    assert b.block(eid, "出处").clean == "出处 SRC-000001｜第 7 页，图 4b｜取得方式：图上读数"


def test_detail_shows_groups_overviews_and_cross_references():
    b = example()
    eid = "EV-000001-001"
    groups = [li.one("span", "strong").text for li in b.block(eid, "所在可比组").all("li")]
    assert groups == ["CMP-000001｜直接可比｜参与比较｜专业已复核", "CMP-000002｜条件化比较｜参与比较｜AI 预归类",
                      "CMP-000003｜条件化比较｜参与比较｜AI 预归类"]
    assert "同一篇论文、同一套电池、条件一致" in b.block(eid, "所在可比组").text
    assert b.block(eid, "被这些数据概览引用").clean == "被这些数据概览引用 ASM-000001"
    assert b.block("EV-000007-001", "被这些数据概览引用").clean == "被这些数据概览引用 还没有被引用"
    assert b.block("EV-000003-001", "所在可比组").one("span", "sub").text == "跨来源：与各自基准膜之比（相对 P-212）　各来源条件不同，用与同型号基准膜之比对齐　仅摘要，条件不全"
    extra = b.block(eid, "其余字段")
    hrefs = {a.text: a.attrs["href"] for a in extra.all("a")}
    assert hrefs == {"EV-000001-002": "#EV-000001-002", "EV-000001-004": "#EV-000001-004"}, "同文基准、同文对照要能跳过去"
    pairs = dict(zip([d.text for d in extra.all("dt")], [d.clean for d in extra.all("dd")]))
    assert pairs["同文基准"] == "EV-000001-002" and pairs["同文对照"] == "EV-000001-004"
    assert pairs["可见范围"] == "可对外" and pairs["取得日期"] == "2026-11-11" and pairs["记录版本"] == "1"
    assert dict(zip([d.text for d in b.block("EV-000004-001", "其余字段").all("dt")],
                    [d.clean for d in b.block("EV-000004-001", "其余字段").all("dd")]))["对应题目卡的问题"] == "Q2"


def test_overview_cited_through_a_group_is_listed():
    with example_copy() as data:
        edit_json(data, "public/topics/TOP-000001/assessments.json", lambda rows: rows[0]["basis"].append("CMP-000002"))
        b = Built(data)
        assert b.block("EV-000007-001", "被这些数据概览引用").clean == "被这些数据概览引用 ASM-000001（经可比组 CMP-000002）"
        assert b.block("EV-000001-001", "被这些数据概览引用").clean == "被这些数据概览引用 ASM-000001", "直接引用的不再重复列"
        assert b.csv_cell("EV-000007-001", "被数据概览引用") == "ASM-000001（经 CMP-000002）"


def test_source_with_a_correction_notice_is_flagged():
    """来源有更正声明、已更正、已撤稿的，在来源一栏里标出来。"""
    b = example()
    source = b.block("EV-000003-001", "来源")
    pairs = dict(zip([d.text for d in source.all("dt")], [d.clean for d in source.all("dd")]))
    flagged = [n.clean for n in source.all("span", "flag")]
    assert pairs["更正声明"] == "SRC-000010" and "SRC-000010" in flagged
    assert any(x.startswith("已更正") for x in flagged), flagged
    assert b.block("EV-000001-001", "来源").all("span", "flag") == []


def test_filters_list_what_is_in_the_data():
    """筛选项和每项的条数，对着数据另算一遍。"""
    b, ds = example(), fresh()
    ev = list(ds["evidence"].values())

    def chips(key):
        return [(c.attrs["data-value"], c.clean) for c in b.dom.all("button", "chip", data_filter=key)]

    def options(key):
        return [(o.attrs["value"], o.text) for o in b.dom.one("select", data_filter=key).all("option")]

    def count(pred):
        return sum(1 for e in ev if pred(e))

    assert chips("level") == [("", "全部13"), ("material", "材料1"), ("component", "组件或器件8"), ("none", "不分层4")]
    assert chips("status") == [("", "全部13"), ("pending", "待核2"), ("machine_checked", "机器已核5"),
                               ("human_verified", "人工已核4"), ("expert_reviewed", "专业已复核2")]
    assert chips("srctype") == [("", "全部13"), ("paper", "论文5"), ("preprint", "预印本2"), ("patent", "专利文献2"),
                                ("datasheet", "厂商规格书1"), ("policy", "政策法规1"), ("consultancy_report", "咨询公司的报告1"),
                                ("grant_record", "资助记录1")]
    assert chips("risk") == [("", "全部13"), ("high", "高1"), ("medium", "中6"), ("low", "低3"), ("-", "还没标3")]
    assert count(lambda e: e["level"] == "none") == 4 and count(lambda e: e["verification_status"] == "pending") == 2
    assert count(lambda e: ds["sources"][e["source_id"]]["source_type"] == "paper") == 5
    assert count(lambda e: "risk" not in e) == 3 and count(lambda e: (e.get("risk") or {}).get("tier") == "medium") == 6
    assert options("type") == [("", "全部"), ("verified_fact", "已核实事实（3）"), ("company_claim", "企业声明（1）"),
                               ("third_party_analysis", "第三方分析（1）"), ("experimental", "实验数据（8）")]
    assert options("tier") == [("", "全部"), ("direct", "直接可比（2）"), ("conditional", "条件化比较（6）"), ("-", "未归组（7）")]
    assert options("vis") == [("", "全部"), ("internal", "内部（4）"), ("external", "可对外（9）")]
    assert options("subject") == [("", "全部"), ("ENT-000001", "示例非氟材料族 N（虚构）（7）"), ("ENT-000002", "示例全氟磺酸族 F（虚构）（1）"),
                                  ("ENT-000003", "示例商业膜 P（虚构）（3）"), ("ENT-000007", "示例磺化聚酰亚胺族 S（虚构）（1）"),
                                  ("ENT-000008", "示例技术类别：示例液流电池（虚构）（1）")]
    assert options("measure") == [("", "全部"), ("indicator:energy_efficiency", "能量效率（8）"), ("indicator:area_resistance", "面电阻（1）"),
                                  ("fact:patent_claim", "专利保护的材料和做法（1）"), ("fact:policy_clause", "政策法规和标准的有关条款（1）"),
                                  ("fact:deployment", "装机（1）"), ("fact:grant_content", "资助项目里与膜有关的内容（1）")]
    assert options("source")[1] == ("SRC-000001", "SRC-000001　示例论文 A（虚构）（4）") and len(options("source")) == 9
    # 每一行带着筛选要用的值，和数据一致
    for e in ev:
        row = b.row(e["id"]).attrs
        src = ds["sources"][e["source_id"]]
        tiers = sorted({c["tier"] for c in ds["comparisons"].values() if any(m["evidence_id"] == e["id"] for m in c["members"])})
        assert (row["data-level"], row["data-status"], row["data-type"], row["data-srctype"], row["data-vis"],
                row["data-subject"], row["data-source"], row["data-risk"], row["data-tier"]) == (
            e["level"], e["verification_status"], e["evidence_type"], src["source_type"], e["visibility"],
            e["subject_id"], e["source_id"], (e.get("risk") or {}).get("tier", "-"), " ".join(tiers) or "-"), e["id"]
        want = f"indicator:{e['indicator']}" if e.get("indicator") else f"fact:{e['fact']}"
        assert row["data-measure"] == want


# ---------------------------------------------------------------- 表格文件

def test_csv_export():
    b = example()
    assert b.raw_csv.startswith(b"\xef\xbb\xbf"), "带 BOM，表格软件直接打开不乱码"
    assert b"\r\n" in b.raw_csv and b.raw_csv.endswith(b"\r\n")
    head = b.table[0]
    assert len(b.table) == 14 and [r[0] for r in b.table[1:]] == sorted(fresh()["evidence"])
    assert all(len(r) == len(head) for r in b.table) and len(set(head)) == len(head)
    eid = "EV-000001-001"
    want = {"对象编号": "ENT-000001", "对象": "示例非氟材料族 N（虚构）", "原文里的样品名": "X-1", "层级": "组件或器件",
            "指标或事实项": "能量效率", "内容类别": "数值", "限定符": "等于", "原文数值": "85.6", "原文单位": "%",
            "标准单位下的值": "85.6", "标准单位": "%",
            "测试条件": "电流密度：80 mA cm-2；钒离子浓度：1.6 M；硫酸浓度：3.0 M H2SO4；温度：25 °C",
            "证据类型": "实验数据", "取得方式": "表格", "来源编号": "SRC-000001", "来源类别": "论文", "题名": "示例论文 A（虚构）",
            "出处位置": "第 6 页，表 2，第 3 行", "原文片段": "X-1 98.1 87.3 85.6", "核验状态": "专业已复核", "风险档": "中",
            "风险理由": "同一来源里有多个样品或多张表", "两遍抽取": "两遍一致", "人工核对人": "yu", "人工核对日期": "2026-11-11",
            "专业复核人": "kai", "专业复核日期": "2026-11-11",
            "所在可比组和档别": "CMP-000001（直接可比，参与比较）；CMP-000002（条件化比较，参与比较）；CMP-000003（条件化比较，参与比较）",
            "被数据概览引用": "ASM-000001", "可见范围": "可对外", "取得日期": "2026-11-11", "录入人": "claude",
            "截至日期": "2026-11-11", "数据版本": VERSION}
    for column, value in want.items():
        assert b.csv_cell(eid, column) == value, (column, b.csv_cell(eid, column))
    assert b.csv_cell("EV-000003-001", "限定符") == "大于" and b.csv_cell("EV-000003-001", "标注") == "仅摘要"
    assert b.csv_cell("EV-000004-001", "转述") == "独立权利要求保护一种示例膜和用它的液流电池（虚构）"
    assert b.csv_cell("EV-000004-001", "对应题目卡的问题") == "Q2"
    assert b.csv_cell("EV-000002-001", "测试条件") == "温度：未报告；膜厚：50 µm；测试介质：0.5 M H2SO4"
    assert b.csv_cell("EV-000001-003", "原文片段") == "" and b.csv_cell("EV-000002-001", "风险档") == ""
    link = b.dom.one("a", id="ev-download")
    assert link.attrs["href"] == B.CSV_NAME and "download" in link.attrs and "含只留内部的字段" in link.text


CSV_CELLS = [  # 表格软件会把 = + - @ 开头的格子当公式算：不是单纯的数字就加一个撇号
    ("=cmd|' /C calc'!A0", "'=cmd|' /C calc'!A0"), ("+1+cmd", "'+1+cmd"), ("-2+3", "'-2+3"), ("@SUM(A1)", "'@SUM(A1)"),
    ("\tx", "'\tx"), ("-0.5", "-0.5"), ("+12", "+12"), ("-3e-7", "-3e-7"), ("-5%", "-5%"), ("85.6", "85.6"),
    ("X-1 98.1", "X-1 98.1"), ("", ""), (None, ""), (81.0, "81.0"),
]


def test_csv_cells_cannot_become_formulas():
    for given, want in CSV_CELLS:
        assert B.csv_cell(given) == want, (given, B.csv_cell(given))
    with example_copy() as data:
        edit_evidence(data, "EV-000001-001", lambda e: e.update(snippet="=HYPERLINK(\"http://x\")\n第二行, 带逗号"))
        b = Built(data)
        assert b.csv_cell("EV-000001-001", "原文片段") == "'=HYPERLINK(\"http://x\")\n第二行, 带逗号"
        assert len(b.table) == 14, "片段里的换行和逗号不能把一行拆开"


# ---------------------------------------------------------------- 可重建、不联网、不把来源的文字当代码

def test_same_data_gives_identical_files():
    """同一个数据版本生成的文件逐字节相同；和数据放在哪个目录、写到哪个目录都无关。"""
    a = example()
    with example_copy() as data:
        b = Built(data)
        assert a.page == b.page and a.raw_csv == b.raw_csv
        assert tempfile.gettempdir() not in b.page and EXAMPLE not in a.page, "页面里不能带出本机的路径"
    c = Built(EXAMPLE, version="另一个版本")
    assert c.page != a.page and c.page.replace("另一个版本", VERSION) == a.page, "换了数据版本，只有版本号那几处不同"


NETWORK_WORDS = ["fetch(", "XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon", "import(", "importScripts",
                 "new Image", ".src =", "localStorage", "sessionStorage", "indexedDB", "document.cookie", "eval(",
                 "new Function", "document.write", "innerHTML", "window.open", "serviceWorker", "postMessage"]


def test_page_calls_no_external_service():
    """页面打开时不调用外部服务（设计方案 4.4 第 15 项）：没有外部文件、没有会发请求的写法，并且让浏览器拦住。"""
    b = example()
    for tag in ("link", "img", "iframe", "object", "embed", "form", "audio", "video", "source", "base", "picture"):
        assert b.dom.all(tag) == [], f"页面里不该有 <{tag}>"
    scripts, styles = b.dom.all("script"), b.dom.all("style")
    assert len(scripts) == 2 and len(styles) == 1
    assert all("src" not in s.attrs for s in scripts)
    for node in b.dom.walk():
        for name, value in node.attrs.items():
            assert not name.startswith("on"), f"<{node.tag}> 上不该有 {name}"
            assert name != "style", f"<{node.tag}> 上不该有 style 属性"
            if name in ("href", "src", "action", "poster", "data") and node.tag != "a" and node.tag != "use":
                raise AssertionError(f"<{node.tag} {name}={value}>")
    css, js = styles[0].text, scripts[1].text
    assert "url(" not in css and "@import" not in css and "http" not in css
    for word in NETWORK_WORDS:
        assert word not in js, f"页面脚本里不该出现 {word}"
    assert "http" not in js
    # 让浏览器拦：策略写在最前面，除了页面自己带的样式和脚本，什么都不许加载、不许连
    metas = b.dom.one("head").all("meta")
    assert metas[0].attrs == {"charset": "utf-8"}
    assert metas[1].attrs["http-equiv"] == "Content-Security-Policy"
    policy = dict(part.strip().split(" ", 1) for part in metas[1].attrs["content"].split(";"))
    assert policy["default-src"] == "'none'" and policy["base-uri"] == "'none'" and policy["form-action"] == "'none'"
    assert "connect-src" not in policy and "http" not in metas[1].attrs["content"] and "*" not in metas[1].attrs["content"]
    # 链接只有三种：页面里跳转、下载表格文件、来源的网址（人点了才打开，新开一页，不带来路）
    for a in b.dom.all("a"):
        href = a.attrs["href"]
        if href.startswith("#") or href == B.CSV_NAME:
            continue
        assert re.match(r"^https?://", href), href
        assert a.attrs.get("rel") == "noopener noreferrer" and a.attrs.get("referrerpolicy") == "no-referrer"
    assert b.dom.one("meta", name="referrer").attrs["content"] == "no-referrer"
    assert b.dom.one("meta", name="robots").attrs["content"] == "noindex, nofollow"


def test_page_script_is_the_checked_file():
    """写进页面的样式和脚本就是 tools/dashboard/ 里的两个文件；脚本的语法用 node 查一遍（没有 node 就跳过这一半）。"""
    b = example()
    assert b.dom.all("script")[1].text.strip() == B.read_asset("app.js").strip()
    assert b.dom.one("style").text.strip() == B.read_asset("style.css").strip()
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("没有 node，脚本的语法这里没查")
    done = subprocess.run([node, "--check", os.path.join(B.ASSETS, "app.js")], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


HOSTILE = [  # 来源里抄来的文字可以是任何东西。放在哪个字段、应当原样显示成什么
    ("snippet", "<script>alert(1)</script>"),
    ("summary", "</td></tr></tbody></table><script>alert(2)</script>"),
    ("sample_label", "<b onmouseover=alert(3)>X</b>"),
    ("scope_note", "\"><img src=x onerror=alert(4)>"),
    ("internal_note", "&lt;script&gt; & </textarea><svg onload=alert(5)>"),
    ("series_label", "' onclick='alert(6)"),
]


def test_text_from_sources_is_never_treated_as_markup():
    with example_copy() as data:
        def poison(e):
            for key, text in HOSTILE:
                e[key] = text
            e["locator"]["text"] = "<iframe src=//x>"
        edit_evidence(data, "EV-000001-001", poison)

        def poison_source(doc):
            doc["source"].update(title="<style>*{display:none}</style>", creators="<a href=javascript:alert(7)>x</a>",
                                 url="javascript:alert(8)", archive_url="data:text/html,<script>alert(9)</script>")
            doc["source"]["identifiers"]["doi"] = "10.1234/x\" onmouseover=\"alert(10)"
        edit_source(data, "SRC-000001", poison_source)
        edit_json(data, "public/entities.json", lambda rows: rows[0].update(name="<img src=x onerror=alert(11)> & Co"))
        edit_json(data, "meta.json", lambda m: m.update(note="<script>alert(12)</script>"))
        edit_json(data, "public/topics/TOP-000001/topic.json", lambda t: t.update(title="</title><script>alert(13)</script>"))
        b = Built(data)
        assert b.code == 0, b.log
        assert len(b.dom.all("script")) == 2 and len(b.dom.all("style")) == 1, "来源里的文字不能变成脚本或样式"
        for tag in ("img", "iframe", "b"):
            assert b.dom.all(tag) == [], tag
        for svg in b.dom.all("svg"):   # 页面自己的 svg 只有三种：记号、记号的那组形状、图
            assert svg.attrs.get("class") in ("mark", "sprite", "chart"), "不能多出别的 svg"
        for node in b.dom.walk():
            assert not any(k.startswith("on") for k in node.attrs), node.attrs
        hrefs = [a.attrs["href"] for a in b.dom.all("a")]
        assert not any(re.match(r"^\s*(javascript|data|vbscript):", h, re.I) for h in hrefs), hrefs
        eid = "EV-000001-001"
        assert b.block(eid, "原文片段").one("blockquote").text == "<script>alert(1)</script>"
        assert b.cell(eid, "c-subject").one("span", "sub").text == "<b onmouseover=alert(3)>X</b>"
        assert b.cell(eid, "c-subject").one("span", "strong").text == "<img src=x onerror=alert(11)> & Co"
        assert "</td></tr></tbody></table><script>alert(2)</script>" in b.cell(eid, "c-value").text
        extra = dict(zip([d.text for d in b.block(eid, "其余字段").all("dt")], [d.text for d in b.block(eid, "其余字段").all("dd")]))
        assert extra["适用范围与限制"] == "\"><img src=x onerror=alert(4)>"
        assert extra["内部备注"] == "&lt;script&gt; & </textarea><svg onload=alert(5)>"
        assert extra["同批测试标签"] == "' onclick='alert(6)"
        assert "<iframe src=//x>" in b.block(eid, "出处").text
        source = b.block(eid, "来源")
        pairs = dict(zip([d.text for d in source.all("dt")], [d.text for d in source.all("dd")]))
        assert pairs["题名"] == "<style>*{display:none}</style>" and pairs["作者或发布机构"] == "<a href=javascript:alert(7)>x</a>"
        assert pairs["实际访问的网址"] == "javascript:alert(8)" and source.all("a") == [], "不是 http、https 的网址只当文字显示"
        assert pairs["DOI"] == "10.1234/x\" onmouseover=\"alert(10)"
        assert b.dom.one("div", id="notice").text == "<script>alert(12)</script>"
        assert b.dom.one("h1").text == "</title><script>alert(13)</script>" == b.dom.one("head").one("title").text[:-5]
        assert b.csv_cell(eid, "原文片段") == "<script>alert(1)</script>"


def test_links_only_for_web_addresses():
    for good in ("https://example.org/a?b=1#c", "http://example.org"):
        assert B.safe_url(good) == good
    for bad in ("javascript:alert(1)", "data:text/html,x", "ftp://x", "//example.org", "https://a b", "https://a\"b",
                " https://example.org", "", None, 5, "HTTPS://EXAMPLE.ORG"):
        assert B.safe_url(bad) is None, bad
    assert B.doi_url("10.1000/182") == "https://doi.org/10.1000/182"
    assert B.doi_url("https://doi.org/10.1000/a b") is None
    assert B.doi_url("doi:10.1000/x<y>") == "https://doi.org/10.1000/x%3Cy%3E"
    for bad in ("11.1000/x", "10.1/x", "", None, "javascript:alert(1)"):
        assert B.doi_url(bad) is None, bad


def test_numbers_written_by_the_script():
    cases = [(85.6, "85.6"), (81.0, "81"), (3, "3"), (0.71, "0.71"), (0.7100000000000001, "0.71"), (2.1e-07, "2.1×10⁻⁷"),
             (1.5e21, "1.5×10²¹"), (-0.5, "-0.5"), (1234567.0, "1234567"), (None, ""), ("原样", "原样"), (True, "True")]
    for given, want in cases:
        assert B.fmt_num(given) == want, (given, B.fmt_num(given))
    assert B.with_unit("85.6", "%") == "85.6%" and B.with_unit("0.45", "Ω cm²") == "0.45 Ω cm²" and B.with_unit("3", "") == "3"
    assert B.with_unit("0.2", "%/圈") == "0.2%/圈"


# ---------------------------------------------------------------- 把数据改坏：照实标出来，不垮

def _dangling_subject(data):
    edit_evidence(data, "EV-000002-001", lambda e: e.update(subject_id="ENT-999999"))


def _unknown_indicator(data):
    edit_evidence(data, "EV-000002-001", lambda e: e.update(indicator="no_such_indicator"))


def _no_value(data):
    edit_evidence(data, "EV-000002-001", lambda e: e.pop("value_reported"))


def _required_condition_dropped(data):
    edit_evidence(data, "EV-000001-001", lambda e: e["conditions"].pop("temperature"))


def _conditions_wrong_type(data):
    edit_evidence(data, "EV-000001-001", lambda e: e.update(conditions=["80 mA cm-2"]))


def _unknown_status(data):
    edit_evidence(data, "EV-000002-001", lambda e: e.update(verification_status="looked at"))


def _unknown_unit(data):
    edit_evidence(data, "EV-000002-001", lambda e: e.update(unit_reported="furlong"))


def _unknown_type(data):
    edit_evidence(data, "EV-000002-001", lambda e: e.update(evidence_type="rumour"))


def _risk_missing_after_human_check(data):
    edit_evidence(data, "EV-000001-003", lambda e: e.pop("risk"))


def _locator_wrong_type(data):
    edit_evidence(data, "EV-000002-001", lambda e: e.update(locator="第 1 页"))


def _fields_stripped(data):
    def strip(e):
        for key in list(e):
            if key not in ("id", "topic_id", "source_id"):
                del e[key]
    edit_evidence(data, "EV-000002-001", strip)


def _nested_wrong_types(data):
    edit_evidence(data, "EV-000001-003", lambda e: e.update(
        risk="high", machine_check=["pass"], figure_read="read", questions="Q1", level=["a"], value_qualifier=3,
        subject_id={"x": 1}, value_std="85", unit_reported=7, verification_status=None, visibility=5))


def _disputed(data):
    edit_evidence(data, "EV-000001-004", lambda e: e.update(
        verification_status="disputed", dispute_note="摘要和表 2 的数对不上（虚构）", conflicts_with=["EV-000001-001"]))


def _void(data):
    edit_evidence(data, "EV-000001-004", lambda e: e.update(
        verification_status="void", void_reason="和 EV-000001-001 重复（虚构）", superseded_by="EV-000001-001"))


def _unit_converted(data):
    def change(e):
        e.update(value_reported="450", unit_reported="mohm*cm2", value_std=0.45, uncertainty=20, uncertainty_kind="sd", n=3,
                 range_low=430, range_high=470)
    edit_evidence(data, "EV-000002-001", change)
    edit_json(data, "public/topics/TOP-000001/dictionary.json", lambda d: next(
        i for i in d["indicators"] if i["key"] == "area_resistance")["units_accepted"].append({"unit": "mohm*cm2", "factor": 0.001}))


def _category_value(data):
    edit_evidence(data, "EV-000005-001", lambda e: (e.pop("fact"), e.pop("summary"), e.update(
        indicator="pfas_scope", level="compliance", content_kind="category", category_value="to_check",
        evidence_type="expert_judgment")))


def _retracted_source(data):
    edit_source(data, "SRC-000001", lambda doc: doc["source"].update(status="retracted"))


# 名字、怎么改、改完生成的退出码（不带 --strict）、页面上必须出现的（编号, 一栏的类名或 None 表示整行, 文字）、校验没通过的条数是否大于零
BROKEN_CASES = [
    ("对象指向实体库里没有的编号", _dangling_subject, [("EV-000002-001", "c-subject", "ENT-999999（实体库里没有这个编号）")], True),
    ("指标不在指标字典里", _unknown_indicator, [("EV-000002-001", "c-measure", "no_such_indicator（指标字典里没有）")], True),
    ("数值型没有填原文数值", _no_value, [("EV-000002-001", "c-value", "（没有填）")], True),
    ("必填的条件整项没有填", _required_condition_dropped, [("EV-000001-001", "c-cond", "温度 （没有填）")], True),
    ("测试条件的类型不对", _conditions_wrong_type, [("EV-000001-001", "c-cond", "电流密度 （没有填）")], True),
    ("核验状态是不认识的代码", _unknown_status, [("EV-000002-001", "c-status", "looked at")], True),
    ("单位没有显示名", _unknown_unit, [("EV-000002-001", "c-value", "0.45 furlong")], True),
    ("证据类型是不认识的代码", _unknown_type, [("EV-000002-001", "c-type", "rumour")], True),
    ("人工已核却没有风险档", _risk_missing_after_human_check, [("EV-000001-003", "c-risk", "还没标")], True),
    ("出处位置的类型不对", _locator_wrong_type, [("EV-000002-001", None, "SRC-000002｜第 1 页｜取得方式：表格")], True),
    ("一条证据只剩编号", _fields_stripped, [("EV-000002-001", "c-subject", "（没有填）"), ("EV-000002-001", "c-value", "（没有填）"),
                                    ("EV-000002-001", "c-measure", "（没有填）")], True),
    ("各个字段的类型都不对", _nested_wrong_types, [("EV-000001-003", "c-risk", "还没标")], True),
    ("存疑", _disputed, [("EV-000001-004", "c-status", "存疑"), ("EV-000001-004", None, "存疑：摘要和表 2 的数对不上（虚构）"),
                       ("EV-000001-004", None, "与之矛盾的证据")], None),
    ("作废", _void, [("EV-000001-004", "c-status", "作废"), ("EV-000001-004", None, "作废：和 EV-000001-001 重复（虚构）"),
                   ("EV-000001-004", None, "被哪条取代")], None),
    ("换算过单位，带范围、误差和样本数", _unit_converted, [
        ("EV-000002-001", "c-value", "450 mΩ cm²"), ("EV-000002-001", "c-value", "标准单位下 0.45 Ω cm²"),
        ("EV-000002-001", "c-value", "范围 430–470"), ("EV-000002-001", "c-value", "± 20（标准差）"),
        ("EV-000002-001", "c-value", "n = 3")], None),
    ("分类型的证据", _category_value, [("EV-000005-001", "c-value", "to_check"), ("EV-000005-001", "c-type", "专业判断"),
                                 ("EV-000005-001", "c-measure", "是否在 PFAS 限制提案范围内")], None),
    ("来源已撤稿", _retracted_source, [("EV-000001-001", None, "已撤稿"), ("EV-000001-004", None, "已撤稿")], None),
]


def test_broken_data_is_shown_as_it_is():
    for name, change, expected, must_flag in BROKEN_CASES:
        with example_copy() as data:
            change(data)
            b = Built(data)
            assert b.code == 0, f"{name}：改坏之后生成不了\n{b.log}"
            assert len(b.dom.all("tbody", "ev")) == 13, name
            assert not any("显示不出来" in p for p in b.problems()), f"{name}：{b.problems()}"
            for eid, cls, text in expected:
                where = b.cell(eid, cls) if cls else b.row(eid)
                assert text in where.clean, f"{name}：{eid} 的 {cls or '整行'} 里应当有“{text}”，页面上是：{where.clean[:300]}"
            if must_flag is True:
                assert b.problems(), f"{name}：校验没通过，页面顶上应当列出来"
                assert f"数据校验：有 {len(b.problems())} 处没通过" in b.log and "全部通过" not in b.log, b.log
                assert "没通过校验" in b.dom.one("div", id="problems").one("summary").text
                assert Built(data, strict=True).code == 1, f"{name}：带 --strict 时退出码应当是 1"
            assert len(b.table) == 14, f"{name}：表格文件也要照样写出"


def test_unknown_codes_still_filter():
    """不认识的代码原样显示，也照样能按它筛选。"""
    with example_copy() as data:
        _unknown_status(data)
        b = Built(data)
        chips = [(c.attrs["data-value"], c.clean) for c in b.dom.all("button", "chip", data_filter="status")]
        assert ("looked_at", "looked_at1") in chips, chips
        assert b.row("EV-000002-001").attrs["data-status"] == "looked_at"
        assert "s-lookedat" in b.cell("EV-000002-001", "c-status").one("span", "status").attrs["class"]


def test_one_unshowable_record_does_not_take_the_page_down():
    """万一有一条证据坏到显示不出来：这一行照样占位并写明，问题列在页面顶上，带 --strict 时退出码是 1。"""
    real = B.condition_items

    def broken(e, measure, names):
        if e.get("id") == "EV-000001-002":
            raise RuntimeError("故意弄坏的")
        return real(e, measure, names)

    B.condition_items = broken
    try:
        b = Built(EXAMPLE)
        strict = Built(EXAMPLE, strict=True)
    finally:
        B.condition_items = real
    assert b.code == 0 and strict.code == 1
    assert len(b.dom.all("tbody", "ev")) == 13
    assert "这条证据显示不出来：RuntimeError: 故意弄坏的" in b.detail("EV-000001-002").text
    assert b.problems() == ["EV-000001-002：显示不出来（RuntimeError: 故意弄坏的）"]
    assert len(b.dom.all("section", "group-card")) == 3, "对标视图照样出"
    assert "证据库里没有这一条" not in b.dom.one("section", "group-card", id="CMP-000002").text
    assert b.cell("EV-000001-001", "c-value").clean == "85.6%", "别的证据不受影响"
    assert len(b.table) == 14 and b.csv_cell("EV-000001-002", "原文数值") == "82.0", "表格文件里这一条也占一行"


def test_many_problems_are_capped_on_the_page():
    with example_copy() as data:
        for sid in sorted(f[:-5] for f in os.listdir(os.path.join(data, "public", "sources"))):
            edit_source(data, sid, lambda doc: [e.update(level="nowhere", evidence_type="rumour", obtained_from="hearsay",
                                                         visibility="everyone") for e in doc["evidence"]])
        b = Built(data)
        shown = b.problems()
        assert len(shown) == 51 and shown[-1].startswith("其余 ") and "tools/validate.py" in shown[-1], shown[-3:]
        total = int(re.search(r"有 (\d+) 处没通过校验", b.dom.one("div", id="problems").one("summary").text).group(1))
        assert total > 50 and shown[-1] == f"其余 {total - 50} 处见 python3 tools/validate.py 的输出"


# ---------------------------------------------------------------- 空的数据、题目、数据版本、命令行

def test_repo_data_builds_even_when_empty():
    """仓库里真的 data/：现在还没有证据，页面照样生成，写明还没有。"""
    b = Built(V.DEFAULT_DATA)
    assert b.code == 0, b.log
    assert b.problems() == [], b.problems()
    ds = V.load_dataset(V.DEFAULT_DATA)
    topic = ds["topics"]["TOP-000001"]
    assert b.dom.one("h1").text == topic["title"]
    cutoff = topic.get("cutoff_date") or "还没有定"
    assert b.dom.one("div", id="stamp").text == f"截至 {cutoff}｜数据版本 {VERSION}"
    count = sum(1 for e in ds["evidence"].values() if e.get("topic_id") == "TOP-000001")
    assert len(b.dom.all("tbody", "ev")) == count == len(b.table) - 1
    if not count:
        assert "这个题目还没有证据" in b.dom.one("p", id="ev-none").text
        assert b.dom.all("table") == [] and b.dom.all("section", "filters") == []
    assert b.dom.all("div", id="notice") == [], "真的数据没有“示例数据”的提示"


def test_topic_has_to_be_named_when_there_are_several():
    with example_copy() as data:
        topics = os.path.join(data, "public", "topics")
        shutil.copytree(os.path.join(topics, "TOP-000001"), os.path.join(topics, "TOP-000002"))
        edit_json(data, "public/topics/TOP-000002/topic.json", lambda t: t.update(id="TOP-000002", title="第二个题目（虚构）"))
        for name in ("comparisons.json", "assessments.json", "reviews.json", "reports.json"):
            edit_json(data, f"public/topics/TOP-000002/{name}", lambda rows: rows.clear())
        edit_json(data, "public/topics/TOP-000002/dictionary.json", lambda d: d.update(topic_id="TOP-000002"))
        none = Built(data)
        assert none.code == 2 and "--topic" in none.log and "TOP-000001、TOP-000002" in none.log and none.files == []
        wrong = Built(data, topic_id="TOP-000009")
        assert wrong.code == 2 and "没有题目 TOP-000009" in wrong.log
        second = Built(data, topic_id="TOP-000002")
        assert second.code == 0 and second.dom.one("h1").text == "第二个题目（虚构）"
        assert second.dom.all("tbody", "ev") == [], "别的题目的证据不进这个题目的页面"
        first = Built(data, topic_id="TOP-000001")
        assert len(first.dom.all("tbody", "ev")) == 13


def test_missing_data_directory():
    b = Built(os.path.join(EXAMPLE, "no-such-dir"))
    assert b.code == 2 and "找不到数据目录" in b.log


def _git(cwd, *args):
    done = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                           *args], cwd=cwd, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_data_version_is_the_commit_id():
    """数据版本就是提交号；有没提交的改动时照实加注，页面不冒充某次提交。"""
    if not shutil.which("git"):
        raise unittest.SkipTest("没有 git")
    with tempfile.TemporaryDirectory() as tmp:
        data = os.path.join(tmp, "repo", "data")
        shutil.copytree(EXAMPLE, data)
        assert B.data_version(data) is None, "不在 git 仓库里就没有提交号"
        loose = Built(data, version=None)
        assert "数据版本 没有版本号（不在 git 仓库里）" in loose.dom.one("div", id="stamp").text and "--version" in loose.log
        repo = os.path.join(tmp, "repo")
        _git(repo, "init", "-q")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "第一次")
        sha = _git(repo, "rev-parse", "--short=7", "HEAD")
        assert B.data_version(data) == sha and re.fullmatch(r"[0-9a-f]{7}", sha)
        clean = Built(data, version=None)
        assert clean.dom.one("div", id="stamp").text == f"截至 2026-11-11｜数据版本 {sha}"
        assert clean.csv_cell("EV-000001-001", "数据版本") == sha
        assert Built(data, version=None).page == clean.page, "同一次提交，生成两遍一样"
        edit_evidence(data, "EV-000001-001", lambda e: e.update(value_reported="85.7"))
        assert B.data_version(data) == sha + "＋没提交的改动"
        _git(repo, "checkout", "-q", "--", ".")
        assert B.data_version(data) == sha
        with open(os.path.join(data, "public", "sources", "SRC-000099.json"), "w", encoding="utf-8") as fh:
            fh.write("{}\n")
        assert B.data_version(data) == sha + "＋没提交的改动", "新加的、还没提交的文件也算"
    here = B.data_version(V.DEFAULT_DATA)
    assert here is None or re.fullmatch(r"[0-9a-f]{7}(＋没提交的改动)?", here), here


def test_command_line():
    out = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        site = os.path.join(tmp, "a", "site")
        assert B.main(["--data", EXAMPLE, "--out", site, "--version", "命令行"]) == 0
        assert sorted(os.listdir(site)) == [B.CSV_NAME, B.PAGE_NAME]
        with open(os.path.join(site, B.PAGE_NAME), encoding="utf-8") as fh:
            assert "数据版本 命令行" in fh.read()
        assert B.main(["--data", EXAMPLE, "--out", site, "--version", "命令行", "--strict"]) == 0
        assert B.main(["--data", os.path.join(tmp, "nothing"), "--out", site]) == 2
        with example_copy() as data:
            _no_value(data)
            assert B.main(["--data", data, "--out", site, "--version", "x"]) == 0
            assert B.main(["--data", data, "--out", site, "--version", "x", "--strict"]) == 1
    assert "证据 13 条，来源 8 个｜截至 2026-11-11｜数据版本 命令行" in out.getvalue()


# ---------------------------------------------------------------- 用浏览器打开点一遍

BROWSER_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")


def _browser():
    required = os.environ.get("DASHBOARD_BROWSER_TESTS") == "required"
    why = None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sync_playwright, why = None, "没有装 playwright"
    exe = next((p for p in map(shutil.which, BROWSER_NAMES) if p), None)
    if why is None and not exe:
        why = "没有找到 Chrome"
    if why:
        if required:
            raise AssertionError(f"要求跑浏览器测试（DASHBOARD_BROWSER_TESTS=required），但{why}")
        raise unittest.SkipTest(f"{why}，页面脚本这一项没测")
    return sync_playwright, exe


@contextlib.contextmanager
def opened(data=EXAMPLE, script=True, size=(1280, 900), frame=False):
    """把数据生成到临时目录，用浏览器打开。给出 (去哪一页的函数, 页面, 记下来的请求和报错)。"""
    sync_playwright, exe = _browser()
    with tempfile.TemporaryDirectory() as site:
        assert B.build(data, site, version=VERSION, log=lambda *_: None) == 0
        if frame:  # 网页版的查看器是把页面放在一个沙盒框里显示的，这里照样放进去
            with open(os.path.join(site, "frame.html"), "w", encoding="utf-8") as fh:
                fh.write('<!DOCTYPE html><title>frame</title><iframe sandbox="allow-scripts" src="index.html" '
                         'width="1200" height="800"></iframe>')
        base = "file://" + os.path.join(site, "frame.html" if frame else B.PAGE_NAME)
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
            # reduced_motion：样式表里的过渡在“减少动态效果”下是关掉的，测试里量颜色、量位置就不用等动画走完
            context = browser.new_context(java_script_enabled=script, viewport={"width": size[0], "height": size[1]},
                                          reduced_motion="reduce")
            page = context.new_page()
            seen = {"requests": [], "errors": []}
            page.on("request", lambda r: seen["requests"].append(r.url))
            page.on("pageerror", lambda e: seen["errors"].append(str(e)))
            page.on("console", lambda m: seen["errors"].append(m.text) if m.type == "error" else None)

            def go(name=""):
                page.goto(base + ("#" + name if name else ""))
                return page

            try:
                yield go, page, seen
            finally:
                browser.close()


def wait_until(page, expression, arg=None, seconds=5.0):
    """等到 expression 在页面里算出来为真。自己隔一会儿问一次，不用 playwright 的 wait_for_function：
    它要在页面里用 eval，而页面的策略连 eval 也不许（这正是我们要的）。"""
    deadline = time.time() + seconds
    while not page.evaluate(expression, arg):
        assert time.time() < deadline, f"等了 {seconds} 秒也没等到：{expression}"
        page.wait_for_timeout(50)


def visible_ids(page):
    """页面上真的看得见的证据（按浏览器算出来的样式，不是按页面自己记的状态）。"""
    return page.eval_on_selector_all("tbody.ev", "rows => rows.filter(r => getComputedStyle(r).display !== 'none').map(r => r.id)")


def shown_views(page):
    return page.eval_on_selector_all("main .view", "views => views.filter(v => getComputedStyle(v).display !== 'none').map(v => v.id)")


def wait_view(page, name):
    """点了导航之后，等页面换过去（浏览器是稍后才通知“# 后面变了”的）。"""
    wait_until(page, "name => getComputedStyle(document.getElementById(name)).display !== 'none'", name)
    assert shown_views(page) == [name]


def open_ids(page):
    return page.eval_on_selector_all(
        "tbody.ev", "rows => rows.filter(r => getComputedStyle(r.querySelector('tr.ev-detail')).display !== 'none').map(r => r.id)")


def test_browser_opens_without_any_request_or_error():
    with opened() as (go, page, seen):
        go()
        go("evidence")
        page.click("#ev-expand")
        go("EV-000001-003")
        assert seen["errors"] == [], seen["errors"]
        assert set(seen["requests"]) == {page.url.split("#")[0]}, f"除了页面自己，不该有别的请求：{seen['requests']}"


def test_browser_switches_pages():
    with opened() as (go, page, seen):
        go()
        assert shown_views(page) == ["overview"], "没有指定页面时先显示总览"
        assert page.get_attribute("nav.pages a[data-view=overview]", "aria-current") == "page"
        for name in ALL_VIEWS:
            page.click(f"nav.pages a[data-view={name}]")
            wait_view(page, name)
            assert page.eval_on_selector_all("nav.pages a[aria-current=page]", "links => links.map(a => a.dataset.view)") == [name]
            assert page.evaluate("location.hash") == "#" + name
        for name in ALL_VIEWS:  # 直接用带 # 的网址打开
            assert shown_views(go(name)) == [name]
        assert shown_views(go("no-such-page")) == ["overview"]
        page.click("section#overview a[href='#evidence']")
        wait_view(page, "evidence")
        page.go_back()
        wait_view(page, "overview")  # 浏览器的后退也跟着换页
        assert page.is_visible("#legend") and page.is_visible("#stamp"), "图例和截至日期、数据版本每一页都看得到"
        assert seen["errors"] == []


def _where(pred):
    ds = fresh()
    return sorted(eid for eid, e in ds["evidence"].items() if pred(e, ds))


def _in_group(tier):
    def pred(e, ds):
        tiers = {c["tier"] for c in ds["comparisons"].values() if any(m["evidence_id"] == e["id"] for m in c["members"])}
        return (tier in tiers) if tier else not tiers
    return pred


# 怎么筛（("chip", 筛选项, 值)、("select", 筛选项, 值)、("type", 文字)，可以叠加）→ 应当剩下哪些证据（对着数据另算）
FILTER_CASES = [
    ([("chip", "status", "pending")], lambda e, ds: e["verification_status"] == "pending"),
    ([("chip", "status", "expert_reviewed")], lambda e, ds: e["verification_status"] == "expert_reviewed"),
    ([("chip", "level", "none")], lambda e, ds: e["level"] == "none"),
    ([("chip", "level", "material")], lambda e, ds: e["level"] == "material"),
    ([("chip", "srctype", "patent")], lambda e, ds: ds["sources"][e["source_id"]]["source_type"] == "patent"),
    ([("chip", "risk", "high")], lambda e, ds: (e.get("risk") or {}).get("tier") == "high"),
    ([("chip", "risk", "-")], lambda e, ds: "risk" not in e),
    ([("select", "type", "company_claim")], lambda e, ds: e["evidence_type"] == "company_claim"),
    ([("select", "tier", "direct")], _in_group("direct")),
    ([("select", "tier", "conditional")], _in_group("conditional")),
    ([("select", "tier", "-")], _in_group(None)),
    ([("select", "vis", "internal")], lambda e, ds: e["visibility"] == "internal"),
    ([("select", "subject", "ENT-000003")], lambda e, ds: e["subject_id"] == "ENT-000003"),
    ([("select", "measure", "indicator:area_resistance")], lambda e, ds: e.get("indicator") == "area_resistance"),
    ([("select", "measure", "fact:deployment")], lambda e, ds: e.get("fact") == "deployment"),
    ([("select", "source", "SRC-000007")], lambda e, ds: e["source_id"] == "SRC-000007"),
    ([("type", "装机")], lambda e, ds: e["id"] == "EV-000011-001"),
    ([("type", "AREA resistance")], lambda e, ds: e["id"] == "EV-000002-001"),
    ([("type", "x-1  图 4b")], lambda e, ds: e["id"] == "EV-000001-003"),
    ([("type", "EV-000004")], lambda e, ds: e["id"].startswith("EV-000004")),
    ([("type", "这几个字哪里都没有")], lambda e, ds: False),
    ([("chip", "status", "machine_checked"), ("chip", "level", "component")],
     lambda e, ds: e["verification_status"] == "machine_checked" and e["level"] == "component"),
    ([("chip", "srctype", "paper"), ("select", "tier", "-"), ("type", "83.1")], lambda e, ds: e["id"] == "EV-000001-004"),
    ([("chip", "status", "pending"), ("chip", "status", "")], lambda e, ds: True),
]


def test_browser_filters():
    with opened() as (go, page, seen):
        for steps, pred in FILTER_CASES:
            go("evidence")
            page.reload()
            for step in steps:
                if step[0] == "chip":
                    page.click(f"button.chip[data-filter={step[1]}][data-value='{step[2]}']")
                elif step[0] == "select":
                    page.select_option(f"select[data-filter={step[1]}]", step[2])
                else:
                    page.fill("input[data-filter=q]", step[1])
            want = _where(pred)
            assert visible_ids(page) == want, f"{steps}\n页面上剩下：{visible_ids(page)}\n应当剩下：{want}"
            assert page.inner_text("#ev-shown") == str(len(want))
            assert page.is_visible("#ev-empty") == (not want)
            assert page.is_visible("#ev-clear") == (len(want) != 13), steps
            pressed = page.eval_on_selector_all(
                "button.chip[data-filter][aria-pressed=true]", "chips => chips.map(c => c.dataset.filter + '=' + c.dataset.value)")
            chosen = {s[1]: s[2] for s in steps if s[0] == "chip"}
            assert sorted(pressed) == sorted(f"{k}={chosen.get(k, '')}" for k in ("level", "status", "srctype", "risk")), steps
        # 清除筛选
        go("evidence")
        page.reload()
        page.click("button.chip[data-filter=status][data-value=pending]")
        page.select_option("select[data-filter=vis]", "internal")
        page.fill("input[data-filter=q]", "装机")
        assert visible_ids(page) == ["EV-000011-001"]
        page.click("#ev-clear")
        assert len(visible_ids(page)) == 13 and not page.is_visible("#ev-clear")
        assert page.input_value("input[data-filter=q]") == "" and page.input_value("select[data-filter=vis]") == ""
        assert seen["errors"] == []


def test_browser_expands_a_record():
    with opened() as (go, page, seen):
        go("evidence")
        assert open_ids(page) == [], "一开始都收着"
        button = "tbody#EV-000001-002 .ev-toggle"
        assert page.get_attribute(button, "aria-expanded") == "false"
        page.click(button)
        assert open_ids(page) == ["EV-000001-002"] and page.get_attribute(button, "aria-expanded") == "true"
        assert page.is_visible("#d-EV-000001-002 blockquote.snippet")
        page.click(button)
        assert open_ids(page) == [] and page.get_attribute(button, "aria-expanded") == "false"
        assert page.inner_text("#ev-expand") == "全部展开"
        page.click("#ev-expand")
        assert len(open_ids(page)) == 13 and page.inner_text("#ev-expand") == "全部收起"
        page.click("#ev-expand")
        assert open_ids(page) == [] and page.inner_text("#ev-expand") == "全部展开"
        # 筛选之后，“全部展开”只展开剩下的
        page.click("button.chip[data-filter=status][data-value=pending]")
        page.click("#ev-expand")
        assert open_ids(page) == _where(lambda e, ds: e["verification_status"] == "pending")
        # 清除筛选之后，原先展开的还展开着；再点两下回到全部收起
        page.click("#ev-clear")
        assert open_ids(page) == _where(lambda e, ds: e["verification_status"] == "pending")
        assert page.inner_text("#ev-expand") == "全部展开", "还有没展开的，按钮就还是“全部展开”"
        page.click("#ev-expand")
        page.click("#ev-expand")
        assert open_ids(page) == []
        # 用键盘也能展开
        page.focus("tbody#EV-000003-001 .ev-toggle")
        page.keyboard.press("Enter")
        assert open_ids(page) == ["EV-000003-001"]
        assert seen["errors"] == []


def test_browser_jumps_to_one_record():
    """网址里 # 后面写证据编号：换到证据表，展开这一条，并且滚到看得见的地方（不被钉在顶上的表头盖住）。"""
    with opened() as (go, page, seen):
        go("EV-000001-003")  # 表格靠前的一条：页面滚得动，表头会钉在它上面
        assert shown_views(page) == ["evidence"] and open_ids(page) == ["EV-000001-003"]
        wait_until(page, "document.activeElement.textContent === 'EV-000001-003'")  # 焦点落在这条证据上
        box = page.evaluate("""() => { const r = document.querySelector('#EV-000001-003 tr.ev-main').getBoundingClientRect();
                               const h = document.querySelector('.ev-table thead th').getBoundingClientRect();
                               return {top: r.top, head_top: h.top, head: h.bottom, height: innerHeight, scrolled: scrollY}; }""")
        assert box["scrolled"] > 0 and box["head_top"] == 0, f"表头应当钉在顶上：{box}"
        assert box["head"] <= box["top"] < box["height"] / 2, f"这条证据应当紧挨在表头下面：{box}"
        # 被筛选藏起来的证据，跳过去时筛选自动清掉
        go("evidence")
        page.reload()
        page.click("button.chip[data-filter=status][data-value=pending]")
        assert "EV-000001-001" not in visible_ids(page)
        page.evaluate("location.hash = '#EV-000001-001'")
        wait_until(page, "document.getElementById('EV-000001-001').classList.contains('open')")
        assert len(visible_ids(page)) == 13 and not page.is_visible("#ev-clear")
        # 展开的一块里点“同文基准”，跳到那一条
        page.click("#d-EV-000001-001 a[href='#EV-000001-002']")
        wait_until(page, "document.getElementById('EV-000001-002').classList.contains('open')")
        assert page.evaluate("location.hash") == "#EV-000001-002"
        wait_until(page, "document.activeElement.textContent === 'EV-000001-002'")
        # 不存在的编号：回到第一页，不报错
        assert shown_views(go("EV-999999-001")) == ["overview"]
        assert seen["errors"] == []


def test_browser_copies_the_visible_rows():
    with opened() as (go, page, seen):
        go("evidence")
        page.click("button.chip[data-filter=srctype][data-value=datasheet]")
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        page.click("#ev-copy")
        wait_until(page, "document.getElementById('ev-copy-note').textContent !== ''")
        note = page.inner_text("#ev-copy-note")
        if note.startswith("已复制"):
            text = page.evaluate("navigator.clipboard.readText()")
            assert not page.is_visible("#ev-copy-box")
        else:  # 浏览器不让自动复制：页面给出一个框，里面是同样的内容，可以手工复制
            assert note.startswith("浏览器没让自动复制") and page.is_visible("#ev-copy-box")
            text = page.input_value("#ev-copy-box")
        lines = [line.split("\t") for line in text.split("\n")]
        assert lines[0] == ["编号", "对象", "层级", "指标或事实项", "数值", "关键条件", "证据类型", "核验状态", "可比档和所在的组",
                            "风险档", "原文片段", "出处"], lines[0]
        assert lines[1:] == [["EV-000002-001", "示例商业膜 P（虚构）", "材料", "面电阻", "0.45 Ω cm²",
                              "温度 未报告；膜厚 50 µm；测试介质 0.5 M H2SO4", "企业声明", "机器已核", "未归组", "还没标",
                              "Area resistance 0.45 Ω cm²", "SRC-000002｜第 1 页，性能表｜取得方式：表格"]], lines[1:]
        assert seen["errors"] == []
    with example_copy() as data:  # 复制出去的格子同样不能变成公式；浏览器不让复制时走手工复制的框
        edit_evidence(data, "EV-000002-001", lambda e: e.update(snippet="=1+1"))
        with opened(data) as (go, page, seen):
            go("evidence")
            page.click("button.chip[data-filter=srctype][data-value=datasheet]")
            page.evaluate("() => { navigator.clipboard.writeText = () => Promise.reject(new Error('不让复制')); }")
            page.click("#ev-copy")
            page.wait_for_selector("#ev-copy-box", state="visible")
            assert page.inner_text("#ev-copy-note").startswith("浏览器没让自动复制")
            cells = page.input_value("#ev-copy-box").split("\n")[1].split("\t")
            assert cells[0] == "EV-000002-001" and cells[10] == "'=1+1", cells


def test_browser_without_script_shows_everything():
    """浏览器不跑脚本时：五页全部显示，每条证据都展开，内容一样看得到；只能靠脚本的筛选和按钮不显示。"""
    with opened(script=False) as (go, page, seen):
        go()
        assert shown_views(page) == ALL_VIEWS
        assert len(open_ids(page)) == 13
        assert not page.is_visible("section.filters") and not page.is_visible("#ev-expand") and not page.is_visible("#ev-copy")
        assert page.is_visible("#ev-download") and page.is_visible("#legend")
        assert page.is_visible("#d-EV-000001-001 blockquote.snippet")


def test_browser_falls_back_when_the_script_fails():
    """页面脚本万一中途出错：退回到不用脚本的样子，内容照样全部看得到，不会停在一个半截的状态。"""
    with opened() as (go, page, seen):
        page.add_init_script("Element.prototype.scrollIntoView = () => { throw new Error('故意弄坏的'); };")
        go("EV-000001-001")  # 跳到一条证据时要滚动，脚本就在这里出错
        assert page.evaluate("document.documentElement.className") == "no-js"
        assert shown_views(page) == ALL_VIEWS and len(open_ids(page)) == 13 and len(visible_ids(page)) == 13
        assert not page.is_visible("section.filters")
        assert any("故意弄坏的" in e for e in seen["errors"]), "出的错照样报出来，不吞掉"


def test_browser_narrow_screen_needs_no_sideways_scrolling():
    with opened(size=(390, 844)) as (go, page, seen):
        go("evidence")
        page.click("#ev-expand")
        widths = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
        assert widths[0] <= widths[1], f"窄屏上页面比屏幕宽：{widths}"
        label = page.evaluate("getComputedStyle(document.querySelector('#EV-000001-001 td.c-value'), '::before').content")
        assert "数值" in label, "窄屏上每个格子前面带着这一栏的名字"
        page.click("button.chip[data-filter=status][data-value=pending]")
        assert visible_ids(page) == _where(lambda e, ds: e["verification_status"] == "pending"), "窄屏上筛选照样管用"
        go("EV-000007-002")
        wait_until(page, "document.activeElement.textContent === 'EV-000007-002'")
        top = page.evaluate("document.querySelector('#EV-000007-002').getBoundingClientRect().top")
        assert 0 <= top < 844, top
        assert seen["errors"] == []


# 在页面里把每一处看得见的字都量一遍：字的颜色和它底下那块底色的对比度（WCAG 的算法）。
# 底色从最外层一层层往里叠出来（半透明的照透明度叠）。图里的字不在这里量，见 test_step3.py。
# 给回来的是不够 LOW_CONTRAST_FLOOR 的那些，同一种写法只报一次。
CONTRAST_JS = """floor => {
  const parse = c => { const m = /rgba?\\(([^)]+)\\)/.exec(c); if (!m) { return null; }
                       const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(parseFloat);
                       return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; };
  const over = (top, under) => ({r: top.r * top.a + under.r * (1 - top.a), g: top.g * top.a + under.g * (1 - top.a),
                                 b: top.b * top.a + under.b * (1 - top.a), a: 1});
  const lin = v => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const lum = c => 0.2126 * lin(c.r) + 0.7152 * lin(c.g) + 0.0722 * lin(c.b);
  const ratio = (a, b) => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05);
  const chain = el => { const out = []; for (let n = el; n; n = n.parentElement) { out.unshift(n); } return out; };
  const backdrop = el => chain(el).reduce((bg, n) => { const c = parse(getComputedStyle(n).backgroundColor);
                                                         return c && c.a > 0 ? over(c, bg) : bg; }, {r: 255, g: 255, b: 255, a: 1});
  const shown = el => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden'
                      && !chain(el).some(n => getComputedStyle(n).clipPath !== 'none');
  const hex = c => '#' + [c.r, c.g, c.b].map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
  const bad = {};
  let measured = 0;
  const measure = (el, colour, what) => {
    const bg = backdrop(el);
    let fg = parse(colour);
    if (!fg) { bad[what + '：认不出的颜色写法 ' + colour] = 0; return; }
    fg.a *= chain(el).reduce((o, n) => o * parseFloat(getComputedStyle(n).opacity), 1);
    fg = over(fg, bg);
    measured += 1;
    const r = ratio(fg, bg);
    if (r < floor) { bad[(el.className || el.tagName.toLowerCase()) + ' ' + hex(fg) + ' 在 ' + hex(bg) + ' 上（' + what + '）'] = Math.round(r * 100) / 100; }
  };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const el = node.parentElement;
    if (!node.nodeValue.trim() || el.closest('svg, script, style, select, textarea') || !shown(el)) { continue; }
    measure(el, getComputedStyle(el).color, node.nodeValue.trim().slice(0, 12));
  }
  for (const el of document.querySelectorAll('select, input, textarea')) {
    if (!shown(el)) { continue; }
    measure(el, getComputedStyle(el).color, '输入框里的字');
    if (el.placeholder) { measure(el, getComputedStyle(el, '::placeholder').color, '输入框里的提示'); }
  }
  for (const el of document.querySelectorAll('[data-label]')) {
    const before = getComputedStyle(el, '::before');
    if (shown(el) && before.content !== 'none' && before.content !== 'normal') { measure(el, before.color, '格子前面的栏名'); }
  }
  return {measured: measured, bad: bad};
}"""
LOW_CONTRAST_FLOOR = 4.5   # WCAG 2 的 AA：正文大小的字和底色的对比度不低于 4.5
# 能点的控件：页面导航、按钮、下拉框、输入框、做成按钮样子的链接。文字里的链接不算。给回来的是矮于 44 像素的
SMALL_CONTROLS_JS = """() => Array.from(document.querySelectorAll('nav.pages a, button, select, input, a.btn'))
  .filter(el => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden')
  .map(el => [el.id || el.getAttribute('data-view') || el.className, Math.round(el.getBoundingClientRect().height)])
  .filter(pair => pair[1] < 44)"""
LOOK_SIZES = [(1280, 900), (390, 844)]


def _look(page, where):
    found = page.evaluate(CONTRAST_JS, LOW_CONTRAST_FLOOR)
    assert found["measured"] > 5, f"{where}：没量到几处字，量法多半坏了"
    assert found["bad"] == {}, f"{where}：字和底色的对比度不到 {LOW_CONTRAST_FLOOR}：{found['bad']}"
    small = page.evaluate(SMALL_CONTROLS_JS)
    assert small == [], f"{where}：能点的控件矮于 44 像素：{small}"


def test_browser_text_is_readable_and_controls_are_big_enough():
    """换配色、换控件样子的时候守住两条：每一处字和它的底色对比度够；能点的控件够高。
    五页都看，证据全部展开了看，跳到对标视图的一行（带着“跳到这里”的底色）也看；宽屏、窄屏各一遍。"""
    for size in LOOK_SIZES:
        with opened(size=size) as (go, page, seen):
            for view in ALL_VIEWS:
                go(view)
                wait_view(page, view)
                _look(page, f"{size[0]} 宽，{view}")
            go("evidence")
            wait_view(page, "evidence")
            page.click("#ev-expand")
            wait_until(page, "document.querySelectorAll('tbody.ev.open').length === document.querySelectorAll('tbody.ev').length")
            _look(page, f"{size[0]} 宽，证据全部展开")
            go("CMP-000002--EV-000007-001")
            wait_until(page, "!!document.querySelector('.target')")
            _look(page, f"{size[0]} 宽，跳到对标视图的一行")
            assert seen["errors"] == []


def test_the_contrast_check_itself_catches_pale_text():
    """量对比度的办法自己也要验一下：把次要文字的颜色故意调浅，它得报出来。"""
    with opened() as (go, page, seen):
        go("evidence")
        wait_view(page, "evidence")
        page.evaluate("document.documentElement.style.setProperty('--muted', '#9A9AA0')")
        found = page.evaluate(CONTRAST_JS, LOW_CONTRAST_FLOOR)
        assert found["bad"] and all(r < LOW_CONTRAST_FLOOR for r in found["bad"].values()), found
        page.evaluate("Object.assign(document.querySelector('.chip').style, {minHeight: '0', height: '30px'})")
        assert page.evaluate(SMALL_CONTROLS_JS), "控件矮了要报出来"


def test_browser_hides_the_download_link_inside_a_viewer_frame():
    """网页版的查看器不让页面自己下载文件：嵌在框里时不显示下载链接，留“复制”；直接打开时显示。"""
    with opened() as (go, page, seen):
        go("evidence")
        assert page.is_visible("#ev-download") and page.is_visible("#ev-copy")
    with opened(frame=True) as (go, page, seen):
        go()
        inner = page.frames[1]
        inner.click("nav.pages a[data-view=evidence]")
        inner.wait_for_selector("#ev-copy", state="visible", timeout=5000)
        assert not inner.is_visible("#ev-download")
        assert len(visible_ids(inner)) == 13
        inner.click("button.chip[data-filter=risk][data-value=high]")
        assert visible_ids(inner) == ["EV-000001-003"]
        inner.click("#ev-copy")  # 框里通常不让自动复制：要么复制成功，要么给出手工复制的框，两样都行，不能没反应
        wait_until(inner, "document.getElementById('ev-copy-note').textContent !== ''")
        if not inner.inner_text("#ev-copy-note").startswith("已复制"):
            assert inner.input_value("#ev-copy-box").split("\n")[1].startswith("EV-000001-003\t")
        # 这里是本机文件放进沙盒框，浏览器不让框里的页面改网址（会记一条 Not allowed to load local resource），
        # 页面照样要换得过去；除了这一条和不让复制，不该有别的报错
        others = [e for e in seen["errors"] if "Not allowed to load local resource" not in e
                  and "clipboard" not in e.lower() and "permission" not in e.lower()]
        assert others == [], others


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
    cases = len(EXPECTED_ROWS) + len(BROKEN_CASES) + len(HOSTILE) + len(CSV_CELLS) + len(FILTER_CASES)
    print(f"{cases} 处对错的用例" + ("，结果都和预期的一样" if not failed else ""), "｜失败", failed, "｜跳过", skipped)
    sys.exit(1 if failed else 0)
