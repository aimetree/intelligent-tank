#!/usr/bin/env python3
"""派生值和对标视图（样品阶段脚本第 3 步）的测试。直接跑：python3 tools/tests/test_step3.py；也可以用 pytest。

做法照旧：示例数据（全部虚构）算出来、画出来的，要和对着数据文件手算的一样；再把数据改坏，页面照实标出来、不垮。
图是脚本直接写的 SVG，大部分不用浏览器就能查：点的个数、次序、实心空心、连不连线、坐标的先后。
换层级、从图上的点跳到成员那一行、再跳到证据，要用浏览器，规矩同 test_dashboard.py（没有浏览器就跳过并写明）。
"""
import contextlib
import copy
import io
import json
import os
import re
import sys
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)

import build_dashboard as B  # noqa: E402
import charts  # noqa: E402
import compare_view  # noqa: E402
import derive  # noqa: E402
import test_dashboard as T  # noqa: E402
import validate as V  # noqa: E402

BLUE, INK, GREY, WHITE = charts.BLUE, charts.INK, charts.GREY, charts.SURFACE
STAMP = f"截至 2026-11-11｜数据版本 {T.VERSION}"


def fresh():
    return V.load_dataset(T.EXAMPLE)


def ev(ds, i):
    return ds["evidence"][i]


def measure(ds, key, kind="indicators"):
    return next(x for x in ds["dictionaries"]["TOP-000001"][kind] if x["key"] == key)


# ---------------------------------------------------------------- 原文数值的写法

NUMBER_CASES = [
    ("85.6", 85.6), ("1.2e-6", 1.2e-6), ("3,200", 3200.0), ("1,234,567.5", 1234567.5), ("1.2×10⁻⁶", 1.2e-6),
    ("2.1 x 10^-7", 2.1e-7), ("6.8×10^(−7)", 6.8e-7), ("1.2×10-6", 1.2e-6), ("5×10⁴", 5e4), ("−0.5", -0.5), (".5", 0.5),
    ("3.", 3.0), (" 82.0 ", 82.0), ("+12", 12.0), ("１２", 12.0),
    # 认不出的不猜
    ("2×103", None), ("80–120", None), ("0,45", None), ("约 85", None), ("85.6 %", None), ("1_000", None), ("nan", None),
    ("inf", None), ("", None), (None, None), (85.6, None), ("1.2×10⁻", None), ("1,23", None), ("１２．５", None),
]


def test_numbers_as_written_in_sources():
    for given, want in NUMBER_CASES:
        got = V.parse_number(given)
        assert got == want, f"{given!r} 应当读成 {want}，读成了 {got}"


# ---------------------------------------------------------------- 标准单位下的值

def test_std_value():
    ds = fresh()
    area, deployment = measure(ds, "area_resistance"), measure(ds, "deployment", "facts")
    deployment["units_accepted"].append({"unit": "GW"})   # 仓库里真的字典这样写：GW 是功率，照原文记，不换算成 GWh

    def calc(value, unit, m, kind="numeric"):
        return derive.std_value({"content_kind": kind, "value_reported": value, "unit_reported": unit}, m)

    assert calc("0.45", "ohm*cm2", area) == (0.45, "")
    assert calc("450", "mohm*cm2", area) == (0.45, ""), "毫欧换成欧，不能带出一串浮点数的尾巴"
    assert calc("4.5×10⁻¹", "ohm*cm2", area) == (0.45, "")
    assert calc("15", "GWh", deployment) == (15.0, "") and calc("1,500", "MWh", deployment) == (1.5, "")
    value, note = calc("3", "GW", deployment)
    assert value is None and "不换算" in note, "照原文记的单位不算"
    value, note = calc("0.45", "furlong", area)
    assert value is None and "不在指标字典允许的单位里" in note
    value, note = calc("0.4–0.5", "ohm*cm2", area)
    assert value is None and "认不出来" in note
    assert calc("0.45", "ohm*cm2", area, kind="statement")[0] is None
    assert derive.comparable_value({"content_kind": "numeric", "value_std": 81.2}, {}) == 81.2, "数据里写了就用数据里的"
    assert derive.comparable_value({"content_kind": "numeric", "value_reported": "450", "unit_reported": "mohm*cm2"}, area) == 0.45
    assert derive.comparable_value({"content_kind": "numeric", "value_reported": "3", "unit_reported": "GW"}, deployment) is None


def test_fill_std_reproduces_the_example():
    ds = fresh()
    rows, touched = derive.fill_std(ds)
    assert touched == [] and {r.status for r in rows} == {"same"} and len(rows) == 10, [r for r in rows if r.status != "same"]
    assert V.validate(ds, V.load_schema()) == []


def _change_for_fill(data):
    T.edit_evidence(data, "EV-000001-001", lambda e: e.pop("value_std"))                       # 没填
    T.edit_evidence(data, "EV-000001-002", lambda e: e.update(value_std=28.0))                 # 填错了
    T.edit_evidence(data, "EV-000002-001", lambda e: e.update(value_reported="450", unit_reported="mohm*cm2"))  # 换了单位没重算
    T.edit_json(data, "public/topics/TOP-000001/dictionary.json", lambda d: next(
        f for f in d["facts"] if f["key"] == "deployment")["units_accepted"].append({"unit": "GW"}))
    T.edit_evidence(data, "EV-000011-001", lambda e: e.update(unit_reported="GW"))             # 不换算的单位却留着 value_std


def test_fill_std_writes_back():
    out = io.StringIO()
    with T.example_copy() as data, contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        _change_for_fill(data)
        assert {i.rule for i in V.validate(V.load_dataset(data), V.load_schema())} == {"V-23"}
        assert derive.main(["--data", data]) == 0, "不加 --write 只看不写"
        assert "value_std" not in ev(V.load_dataset(data), "EV-000001-001")
        assert derive.main(["--data", data, "--source", "SRC-000002", "--write"]) == 0
        ds = V.load_dataset(data)
        assert ev(ds, "EV-000002-001")["value_std"] == 0.45 and "value_std" not in ev(ds, "EV-000001-001"), "只写指定的来源"
        assert derive.main(["--data", data, "--write"]) == 0
        ds = V.load_dataset(data)
        assert ev(ds, "EV-000001-001")["value_std"] == 85.6 and ev(ds, "EV-000001-002")["value_std"] == 82.0
        assert "value_std" not in ev(ds, "EV-000011-001")
        keys = list(ev(ds, "EV-000001-001"))
        assert keys.index("value_std") == keys.index("unit_reported") + 1, "补上的字段放在它该在的位置，不是甩在最后"
        assert V.validate(ds, V.load_schema()) == [], "写回之后校验通过"
        assert derive.main(["--data", data, "--write"]) == 0 and "写回了" not in out.getvalue().split("\n标准单位下的值")[-1]
        # 认不出的写法：不猜，退出码是 1，数据不动
        T.edit_evidence(data, "EV-000001-001", lambda e: e.update(value_reported="85–86"))
        assert derive.main(["--data", data, "--write"]) == 1
        assert ev(V.load_dataset(data), "EV-000001-001")["value_std"] == 85.6
        assert derive.main(["--data", os.path.join(data, "nothing")]) == 2
    text = out.getvalue()
    assert "EV-000001-001  补上  原来 没有填 → 85.6" in text and "EV-000001-002  改了  原来 28 → 82" in text
    assert "EV-000011-001  去掉  原来 15" in text and "EV-000001-001  算不出" in text and "没有写回（加 --write 才写）" in text


# ---------------------------------------------------------------- 与同文基准之比

def test_baseline_ratio():
    ds = fresh()
    lk = V.Lookups(ds)
    got = derive.baseline_ratio(ev(ds, "EV-000001-001"), ds, lk)
    assert got == {"ratio": 85.6 / 82.0, "base_id": "EV-000001-002", "value": 85.6, "base_value": 82.0}
    assert abs(derive.baseline_ratio(ev(ds, "EV-000007-001"), ds, lk)["ratio"] - 80.5 / 79.9) < 1e-12

    def why(change, eid="EV-000001-001"):
        d = fresh()
        change(d)
        got = derive.baseline_ratio(ev(d, eid), d, V.Lookups(d))
        assert got["ratio"] is None
        return got["why"]

    assert "没有写同文基准" in why(lambda d: None, "EV-000001-002")
    assert "不在证据库里" in why(lambda d: ev(d, "EV-000001-001").update(baseline_ref="EV-000001-099"))
    assert "已作废" in why(lambda d: ev(d, "EV-000001-002").update(verification_status="void"))
    assert "已作废" in why(lambda d: ev(d, "EV-000001-001").update(verification_status="void"))
    assert "不是同一来源、同一指标" in why(lambda d: ev(d, "EV-000001-001").update(baseline_ref="EV-000007-002"))
    assert "不是同一来源、同一指标" in why(lambda d: ev(d, "EV-000001-002").update(indicator="area_resistance"))
    assert "值是 0" in why(lambda d: ev(d, "EV-000001-002").update(value_std=0))
    assert "没有标准单位下的值" in why(lambda d: (ev(d, "EV-000001-002").pop("value_std"), ev(d, "EV-000001-002").update(value_reported="约 82")))


# ---------------------------------------------------------------- 派生指标（IN-16）

def test_derived_indicator_takes_the_highest_condition_in_a_batch():
    ds = fresh()
    records, unused = derive.derived_records(ds, "TOP-000001")
    got = [(r["source_id"], r["sample_label"], r["series_label"], r["value"], r["unit"], r["tested"], r["picked"]) for r in records]
    assert got == [
        ("SRC-000001", "P-212", "S1", 80, "mA/cm2", 1, {"energy_efficiency": "EV-000001-002"}),
        ("SRC-000001", "X-0", "S1", 80, "mA/cm2", 1, {"energy_efficiency": "EV-000001-004"}),
        ("SRC-000001", "X-1", "S1", 120, "mA/cm2", 2, {"energy_efficiency": "EV-000001-003"}),   # 80 和 120 两处，取 120 那一条
        ("SRC-000004", "实施例 1", "E1", 80, "mA/cm2", 1, {"energy_efficiency": "EV-000004-002"}),
        ("SRC-000007", "N-212", "S1", 80, "mA/cm2", 1, {"energy_efficiency": "EV-000007-002"}),
        ("SRC-000007", "Z-1", "S1", 80, "mA/cm2", 1, {"energy_efficiency": "EV-000007-001"}),
    ], got
    assert {r["indicator"] for r in records} == {"max_current_density"} and {r["condition"] for r in records} == {"current_density"}
    assert unused == [("EV-000003-001", "没有同批测试标签 series_label，看不出和谁是同一批")]
    # 作废的不算：120 那一条作废之后，这一批最高的就是 80
    ev(ds, "EV-000001-003")["verification_status"] = "void"
    x1 = next(r for r in derive.derived_records(ds, "TOP-000001")[0] if r["sample_label"] == "X-1")
    assert (x1["value"], x1["tested"], x1["picked"]) == (80, 1, {"energy_efficiency": "EV-000001-001"})
    # 条件没有解析出数值的用不上
    ds = fresh()
    ev(ds, "EV-000001-003")["conditions"]["current_density"] = {"reported": "高电流密度"}
    records, unused = derive.derived_records(ds, "TOP-000001")
    assert ("EV-000001-003", "这个条件没有解析出的数值") in unused
    assert next(r for r in records if r["sample_label"] == "X-1")["value"] == 80
    # 别的题目、没有派生指标的字典：什么也没有
    assert derive.derived_records(ds, "TOP-000009") == ([], [])


def test_real_dictionary_says_where_in16_comes_from():
    """仓库里真的指标字典：IN-16 从三项效率里按电流密度取。"""
    ds = V.load_dataset(V.DEFAULT_DATA)
    d = ds["dictionaries"]["TOP-000001"]
    derived = [i for i in d["indicators"] if i.get("entry") == "derived"]
    assert [i["list_no"] for i in derived] == ["IN-16"]
    assert derived[0]["derived_from"] == {"indicators": ["coulombic_efficiency", "voltage_efficiency", "energy_efficiency"],
                                         "condition": "current_density"}
    assert V.validate(ds, V.load_schema()) == []


# ---------------------------------------------------------------- 坐标轴和图

SCALE_CASES = [  # 一组数 → 刻度、是不是对数轴
    ([82.0, 85.6], [82, 83, 84, 85, 86], False),
    ([1.0, 1.0439, 1.0075], [1, 1.02, 1.04, 1.06], False),
    ([80, 120], [80, 90, 100, 110, 120], False),
    ([0.38, 0.62], [0.3, 0.4, 0.5, 0.6, 0.7], False),
    ([5.0], [4.5, 5, 5.5], False),
    ([0.0], [-1, -0.5, 0, 0.5, 1], False),
    ([2.1e-7, 6.8e-5], [1e-7, 1e-6, 1e-5, 1e-4], True),
    ([1.0, 100.0], [1, 10, 100], True),
    ([3.0, 250.0], [0, 100, 200, 300], False),      # 差不到一百倍，不用对数轴
    ([-5.0, 600.0], [-200, 0, 200, 400, 600], False),  # 有负数，不能用对数轴
    ([], [0, 0.5, 1], False),
]


def test_axis_ticks():
    for values, ticks, log in SCALE_CASES:
        sc = charts.scale_for(values, 100, 500)
        assert sc.log == log, values
        assert len(sc.ticks) == len(ticks) and all(abs(a - b) <= 1e-9 * max(1, abs(b)) for a, b in zip(sc.ticks, ticks)), (values, sc.ticks)
        inside = [sc(v) for v in values]
        assert all(100 + charts.INSET - 1e-6 <= x <= 500 - charts.INSET + 1e-6 for x in inside), "点都落在图里，不压边"
        assert inside == sorted(inside) or values != sorted(values), "数越大越靠右"
    assert charts.INSET >= 12, "落在最小、最大刻度上的点，要离坐标轴和边框有一段距离"
    up = charts.scale_for([1, 2], 300, 20)   # 纵轴：数越大越靠上（像素越小）
    assert up(2) < up(1) and up(1) == 300 - charts.INSET and up(2) == 20 + charts.INSET
    for raw, want in ((0.9, 1), (1.3, 2), (3.7, 5), (7.2, 10), (0.013, 0.02), (240, 500)):
        assert abs(charts.nice_step(raw) - want) < 1e-12, raw
    plain, powers = charts.scale_for([1.0, 100.0], 0, 100), charts.scale_for([2.1e-7, 0.5], 0, 100)
    assert [plain.label(t) for t in plain.ticks] == ["1", "10", "100"]
    assert [powers.label(t) for t in powers.ticks] == ["10⁻⁷", "10⁻⁶", "10⁻⁵", "10⁻⁴", "10⁻³", "10⁻²", "10⁻¹", "10⁰"], "一根轴上不混着写"


def _rows():
    return [
        {"label": "甲", "sub": "来源一", "value": 3.0, "type": "experimental", "solid": True, "role": "member", "href": "#a", "title": "甲的提示", "evidence": "EV-1"},
        {"label": "乙", "sub": "来源一", "value": 1.0, "err": (0.8, 1.3), "type": "company_claim", "solid": False, "role": "baseline", "href": "#b",
         "title": "乙的提示", "evidence": "EV-2", "dashed": True},
        {"label": "丙 <b>", "sub": "来源二", "value": 2.0, "type": "no_such_type", "solid": False, "role": "reference", "title": "丙的提示", "evidence": "EV-3"},
    ]


def _svg(text):
    """把脚本写出来的 SVG 当成一个独立的文件来读：读得进去才算是完整的 SVG。"""
    root = ET.fromstring(text)
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    return root


def _local(node):
    return node.tag.split("}")[1]


def _find(root, name):
    return [n for n in root.iter() if _local(n) == name]


def _xy(g):
    x, y = re.match(r"translate\(([-\d.]+) ([-\d.]+)\)", g.get("transform")).groups()
    return float(x), float(y)


def test_dot_chart():
    text = charts.dot_chart(_rows(), "某个量，单位", "图的名字", ref=1.0, ref_label="基准 = 1")
    assert text == charts.dot_chart(_rows(), "某个量，单位", "图的名字", ref=1.0, ref_label="基准 = 1"), "同样的数据，画出来一字不差"
    root = _svg(text)
    assert root.get("aria-label") == "图的名字" and _find(root, "title")[0].text == "图的名字"
    links = _find(root, "a")
    assert [(a.get("href"), a.get("data-evidence"), a.get("aria-label")) for a in links] == [("#a", "EV-1", "甲的提示"), ("#b", "EV-2", "乙的提示")]
    marks = [g for g in _find(root, "g") if g.get("transform")]
    assert [(g.get("fill"), g.get("stroke")) for g in marks] == [(BLUE, BLUE), (WHITE, INK), (WHITE, GREY)], "实心空心看核验状态，基准、参考各有各的写法"
    assert [_local(g[0]) for g in marks] == ["circle", "rect", "rect"], "形状看证据类型；不认识的类型用一条短横"
    xs, ys = zip(*[_xy(g) for g in marks])
    assert ys == tuple(sorted(ys)), "照给的次序从上往下排，不按数值重排"
    assert xs[1] < xs[2] < xs[0], "数越大越靠右"
    words = [t.text for t in _find(root, "text")]
    assert "丙 <b>" in words and "来源二" in words and "某个量，单位" in words and "基准 = 1" in words and "3" in words
    dashed = [n for n in _find(root, "line") if n.get("stroke-dasharray") == "3 2"]
    assert len(dashed) == 1 and dashed[0].get("stroke") == INK, "图上读数的范围用虚线"
    assert all(t.get("font-size") and t.get("fill") for t in _find(root, "text")), "样式写在图自己身上，单独存成文件也一样"
    assert "class=\"chart\"" in text and "style=" not in text and "<script" not in text


def _contrast(a, b):
    """两种颜色的对比度（WCAG 的算法）。颜色写成 #RRGGBB。"""
    def lum(c):
        parts = [int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, b_ = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in parts]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b_
    hi, lo = sorted([lum(a), lum(b)], reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_chart_colours_can_be_told_apart_and_read():
    """换配色的时候守住三条：三种角色的颜色互不相同，也都不是底色；记号在底色上看得清（对比度不低于 3）；
    图上的字在底色上读得清（对比度不低于 4.5）。"""
    assert round(_contrast("#000000", "#FFFFFF"), 1) == 21.0 and round(_contrast("#777777", "#FFFFFF"), 2) == 4.48, "对比度的算法先对一下"
    roles = [charts.BLUE, charts.INK, charts.GREY]
    assert len(set(roles + [charts.SURFACE])) == 4, "基准、参与比较、只作参考，三种颜色要分得开"
    assert set(charts.ROLE_COLOR.values()) == {charts.INK, charts.GREY} and charts.BLUE not in charts.ROLE_COLOR.values()
    for colour in roles:
        assert _contrast(colour, charts.SURFACE) >= 3, f"记号的颜色 {colour} 在图的底色上太浅"
    for colour in (charts.INK, charts.MUTED):
        assert _contrast(colour, charts.SURFACE) >= 4.5, f"图上的字 {colour} 在图的底色上太浅"
    for colour in (charts.GRID, charts.AXIS):
        assert _contrast(colour, charts.SURFACE) < _contrast(charts.GREY, charts.SURFACE), "网格和坐标轴要比数据浅"
    svg = charts.dot_chart(_rows(), "某个量，单位", "图的名字", ref=1.0, ref_label="基准 = 1")
    used = set(re.findall(r"#[0-9A-Fa-f]{6}", svg))
    assert used <= {charts.INK, charts.BLUE, charts.GREY, charts.MUTED, charts.GRID, charts.AXIS, charts.SURFACE}, f"图里出现了没有登记的颜色：{used}"
    text_fills = {t.get("fill") for t in _find(_svg(svg), "text")}
    assert text_fills <= {charts.INK, charts.MUTED}, "图上的字只用墨色和次要文字的颜色，不跟着数据的颜色走"


def test_xy_chart_connects_only_what_it_is_told_to():
    def p(x, y, **more):
        return dict({"x": x, "y": y, "type": "experimental", "solid": True, "role": "member", "href": f"#p{x}", "title": f"{x},{y}", "evidence": f"E{x}"}, **more)

    series = [{"points": [p(120, 81.2, label="甲", y_err=(80.7, 81.7), dashed=True), p(80, 85.6)], "connect": True},
              {"points": [p(80, 82.0, label="乙", role="baseline")], "connect": True},
              {"points": [p(100, 83.0, label="丙"), p(110, 84.0)], "connect": False}]
    root = _svg(charts.xy_chart(series, "横轴", "纵轴", "两个量的图"))
    lines = _find(root, "polyline")
    assert len(lines) == 1, "只有说了要连、又不止一个点的那一组才连线"
    pairs = [tuple(float(v) for v in xy.split(",")) for xy in lines[0].get("points").split()]
    assert len(pairs) == 2 and pairs[0][0] < pairs[1][0] and pairs[0][1] < pairs[1][1], "按横坐标从左连到右；85.6 在上，81.2 在下"
    assert len(_find(root, "a")) == 5
    words = [t.text for t in _find(root, "text")]
    assert {"甲", "乙", "丙", "横轴", "纵轴", "80", "120"} <= set(words)
    assert len([n for n in _find(root, "line") if n.get("stroke-dasharray") == "3 2"]) == 1


# ---------------------------------------------------------------- 对标视图：示例数据

def card(b, cid):
    return b.dom.one("section", "group-card", id=cid)


def same_conditions(c):
    """卡片里“各成员都一样的条件”那一行。卡片后面还有复核单的说明，所以按开头的字找，不按位置找。"""
    return [p.clean for p in c.all("p", "note") if p.clean.startswith("各成员都一样的条件")]


def chart_points(node):
    """图上的点：[(证据编号, 跳到哪里, 填的颜色, 边的颜色, 横坐标)]。"""
    out = []
    for a in node.one("svg", "chart").all("a"):
        g = [x for x in a.all("g") if x.attrs.get("transform")][0]
        out.append((a.attrs["data-evidence"], a.attrs["href"], g.attrs["fill"], g.attrs["stroke"],
                    float(re.match(r"translate\(([-\d.]+) ", g.attrs["transform"]).group(1))))
    return out


def members(node):
    """卡片里的第一张表：成员的表。可比组的卡片后面还有复核单的表。"""
    return node.all("table", "cmp-table")[0]


def table(node):
    head = [th.clean for th in members(node).one("thead").all("th")]
    lines = [[td.clean for td in tr.all("td")] for tr in members(node).one("tbody").all("tr")]
    return head, lines


def test_compare_view_has_one_block_per_level():
    b = T.example()
    view = b.dom.one("section", "view", id="compare")
    assert "3 个可比组" in view.all("div", "view-head")[0].clean
    panels = view.all("section", "level")
    assert [(p.attrs["data-level-panel"], p.one("h3", "level-name").text) for p in panels] == [("material", "材料"), ("component", "组件或器件")]
    assert [(t.attrs["data-level-tab"], t.clean) for t in view.all("button", "chip")] == [("material", "材料0"), ("component", "组件或器件3")]
    assert "材料这一层还没有可比组" in panels[0].text and panels[0].all("svg", "chart") == []
    assert [c.attrs["id"] for c in panels[1].all("section", "group-card")] == ["CMP-000001", "CMP-000002", "CMP-000003"]
    assert "不按数值排名，不求平均" in view.text and "换算值，不是证据" in view.text


def test_direct_group():
    b = T.example()
    c = card(b, "CMP-000001")
    assert c.one("h3").text == "CMP-000001　同一来源、同一批测试的能量效率"
    assert c.one("span", "tier").text == "直接可比" and "t-direct" in c.one("span", "tier").attrs["class"]
    assert c.all("div", "tags")[0].clean == "直接可比 状态：专业已复核 用的可比规则：同文同批、条件一致才直接比 归一化方法：不做".replace(" ", "")
    notes = dict(zip([d.text for d in c.one("dl", "kv").all("dt")], [d.text for d in c.one("dl", "kv").all("dd")]))
    assert notes == {"定档理由": "同一篇论文、同一套电池、条件一致", "这条规则说的是": "同一来源、同一批测试，电流密度、电解液组成、温度一致"}
    points = chart_points(c)
    assert [p[:4] for p in points] == [("EV-000001-001", "#CMP-000001--EV-000001-001", BLUE, BLUE),
                                       ("EV-000001-002", "#CMP-000001--EV-000001-002", INK, INK)], "都是专业已复核：实心；基准用深色"
    assert points[0][4] > points[1][4], "85.6 在 82.0 右边"
    assert c.one("figcaption").text == f"对象数 2：参与比较 1，基准 1，只作参考 0｜图上 2 个点｜筛选：组件或器件，能量效率，CMP-000001｜{STAMP}"
    head, lines = table(c)
    assert head == ["证据", "对象", "角色", "数值", "与基准之比（换算值）", "电流密度（关键条件）", "证据类型", "核验状态"]
    assert lines == [
        ["EV-000001-001", "X-1 示例非氟材料族 N（虚构）｜SRC-000001", "参与比较", "85.6%", "1.0439（85.6 ÷ 82，基准 EV-000001-002）", "80 mA cm-2", "实验数据", "专业已复核"],
        ["EV-000001-002", "P-212 示例商业膜 P（虚构）｜SRC-000001", "基准", "82.0%", "—（它就是基准）", "80 mA cm-2", "实验数据", "专业已复核"]]
    assert abs(85.6 / 82.0 - 1.0439) < 5e-5
    assert same_conditions(c) == ["各成员都一样的条件：钒离子浓度 1.6 M；硫酸浓度 3.0 M H2SO4；温度 25 °C"]
    assert [tr.attrs["id"] for tr in members(c).one("tbody").all("tr")] == ["CMP-000001--EV-000001-001", "CMP-000001--EV-000001-002"]
    assert [a.attrs["href"] for a in members(c).one("tbody").all("a")] == ["#EV-000001-001", "#EV-000001-002"], "成员那一行点得进证据"


def test_ratio_group():
    """与基准之比的组：图上画的是比值，基准自己不画；只作参考的灰显；算不出比值的列出来。"""
    b = T.example()
    c = card(b, "CMP-000002")
    assert c.one("span", "tier").text == "条件化比较"
    notes = dict(zip([d.text for d in c.one("dl", "kv").all("dt")], [d.text for d in c.one("dl", "kv").all("dd")]))
    assert notes["基准膜"] == "示例商业膜 P（虚构）｜商业膜（原样或预处理过）" and notes["定档理由"] == "各来源条件不同，用与同型号基准膜之比对齐"
    points = chart_points(c)
    assert [p[:4] for p in points] == [("EV-000001-001", "#CMP-000002--EV-000001-001", BLUE, BLUE),
                                       ("EV-000007-001", "#CMP-000002--EV-000007-001", WHITE, BLUE)], "机器已核的还没复核：空心"
    assert points[0][4] > points[1][4], "1.0439 在 1.0075 右边"
    words = [t.text for t in c.one("svg", "chart").all("text")]
    assert "基准 = 1" in words and "1.0439" in words and "1.0075" in words and "能量效率：与同文基准之比（换算值）" in words
    assert abs(80.5 / 79.9 - 1.0075) < 5e-5
    assert c.one("figcaption").text == f"对象数 5：参与比较 2，基准 2，只作参考 1｜图上 2 个点｜筛选：组件或器件，能量效率，CMP-000002｜{STAMP}"
    head, lines = table(c)
    assert head == ["证据", "对象", "角色", "数值", "与基准之比（换算值）", "钒离子浓度", "硫酸浓度", "温度", "证据类型", "核验状态"]
    assert [r[0] for r in lines] == ["EV-000001-001", "EV-000001-002", "EV-000007-001", "EV-000007-002", "EV-000003-001"], "照登记的次序，不按数值排"
    assert [r[4] for r in lines] == ["1.0439（85.6 ÷ 82，基准 EV-000001-002）", "—（它就是基准）", "1.0075（80.5 ÷ 79.9，基准 EV-000007-002）",
                                     "—（它就是基准）", "没有写同文基准"]
    assert lines[4][2] == "只作参考 仅摘要，条件不全" and lines[4][5:8] == ["未报告", "未报告", "未报告"] and lines[4][8] == "实验数据 仅摘要"
    last = members(c).one("tbody").all("tr")[4]
    assert last.attrs["class"] == "role-reference" and len(last.all("span", "missing")) == 4, "没报告的条件、算不出的比值都标出来"
    assert [li.text for li in c.one("ul", "plain").all("li")] == ["EV-000003-001：没有写同文基准"]
    assert same_conditions(c) == ["各成员都一样的条件：电流密度 80 mA cm-2"]


def test_cross_source_group():
    b = T.example()
    c = card(b, "CMP-000003")
    points = chart_points(c)
    assert [p[:4] for p in points] == [("EV-000001-001", "#CMP-000003--EV-000001-001", BLUE, BLUE),
                                       ("EV-000004-002", "#CMP-000003--EV-000004-002", WHITE, BLUE)]
    notes = dict(zip([d.text for d in c.one("dl", "kv").all("dt")], [d.text for d in c.one("dl", "kv").all("dd")]))
    assert notes["这一组共同的条件"] == "电流密度 80 mA cm-2"
    head, lines = table(c)
    assert head == ["证据", "对象", "角色", "数值", "与基准之比（换算值）", "电流密度（关键条件）", "证据类型", "核验状态"]
    assert lines[1] == ["EV-000004-002", "实施例 1 示例非氟材料族 N（虚构）｜SRC-000004", "参与比较", "84.0%", "", "80 mA cm-2",
                        "实验数据 专利实施例，未经同行评议", "机器已核"]
    assert c.all("ul", "plain") == [], "都画进图里了"


def test_series_chart_within_one_batch():
    """同一批测试里随条件变化的图：同一个样品的点连成线，别的不连。"""
    b = T.example()
    panel = b.dom.one("section", "level", data_level_panel="component")
    cards = [c for c in panel.all("section", "card") if c.all("h3") and "的变化" in c.one("h3").text]
    assert [c.one("h3").text for c in cards] == ["能量效率随电流密度的变化｜SRC-000001｜同一批测试 S1"]
    svg = cards[0].one("svg", "chart")
    points = sorted((a.attrs["data-evidence"], a.attrs["href"], [g for g in a.all("g") if g.attrs.get("transform")][0].attrs["fill"],
                     [g for g in a.all("g") if g.attrs.get("transform")][0].attrs["stroke"]) for a in svg.all("a"))
    assert points == [("EV-000001-001", "#EV-000001-001", BLUE, BLUE), ("EV-000001-002", "#EV-000001-002", INK, INK),
                      ("EV-000001-003", "#EV-000001-003", WHITE, BLUE), ("EV-000001-004", "#EV-000001-004", WHITE, BLUE)]
    lines = svg.all("polyline")
    assert len(lines) == 1 and len(lines[0].attrs["points"].split()) == 2, "只有 X-1 有两个电流密度，连一条线"
    words = [t.text for t in svg.all("text")]
    assert sorted(w for w in words if w in ("X-1", "X-0", "P-212")) == ["P-212", "X-0", "X-1"], "每个样品的名字只写一次"
    assert "电流密度，mA cm⁻²" in words and "能量效率，%" in words
    assert len([n for n in svg.all("line") if n.attrs.get("stroke-dasharray") == "3 2"]) == 1, "图上读数的那一点带读数误差，用虚线"
    assert cards[0].one("figcaption").text == ("对象数 3｜图上 4 个点｜同一个样品的点连成线，不同样品之间不连｜"
                                               f"筛选：组件或器件，能量效率，SRC-000001｜{STAMP}")


def test_matrix():
    b = T.example()
    panel = b.dom.one("section", "level", data_level_panel="component")
    m = panel.one("table", "matrix")
    assert [th.clean.split(" ")[0] for th in m.one("thead").all("th")[1:]] == ["X-1", "P-212", "Z-1", "N-212", "Y-2", "实施例"]
    rows = {tr.one("th").clean.split(" ")[0]: [td.clean for td in tr.all("td")] for tr in m.one("tbody").all("tr")}
    assert rows["X-1"] == ["—", "直 CMP-000001", "条 CMP-000002", "条 CMP-000002", "参 CMP-000002", "条 CMP-000003"]
    assert rows["P-212"] == ["直 CMP-000001", "—", "条 CMP-000002", "条 CMP-000002", "参 CMP-000002", ""]
    assert rows["Y-2"] == ["参 CMP-000002"] * 4 + ["—", ""], "只作参考的成员，和谁并排都只算参考"
    assert rows["实施例"] == ["条 CMP-000003", "", "", "", "", "—"]
    for name, cells in rows.items():   # 对称
        for other, cell in zip(["X-1", "P-212", "Z-1", "N-212", "Y-2", "实施例"], cells):
            assert rows[other][["X-1", "P-212", "Z-1", "N-212", "Y-2", "实施例"].index(name)] == cell
    assert m.one("tbody").all("tr")[0].all("span", "tier")[0].attrs["title"] == "直接可比：CMP-000001"
    assert b.dom.one("section", "level", data_level_panel="material").all("table", "matrix") == []


def test_derived_table():
    b = T.example()
    panel = b.dom.one("section", "level", data_level_panel="component")
    c = [x for x in panel.all("section", "card") if x.all("h3") and x.one("h3").text == "派生指标（换算值）"][0]
    assert "不是证据" in c.one("div", "view-head").text
    head, lines = table(c)
    assert head == ["派生指标", "对象", "取到的值", "那一处的证据", "这一批测了几个值"] and len(lines) == 6
    assert lines[2] == ["最高测试电流密度", "X-1 SRC-000001｜同一批测试 S1", "电流密度 120 mA cm⁻²", "能量效率 81.2%（EV-000001-003）", "2 个"]
    assert lines[0] == ["最高测试电流密度", "P-212 SRC-000001｜同一批测试 S1", "电流密度 80 mA cm⁻²", "能量效率 82.0%（EV-000001-002）", "1 个"]
    assert [a.attrs["href"] for a in c.one("tbody").all("a")][2] == "#EV-000001-003"


def test_every_jump_inside_the_page_lands_somewhere():
    """页面里每个跳转（图上的点、成员行、可比组、同文基准）都有落点，没有一个是空的。"""
    b = T.example()
    ids = [n.attrs["id"] for n in b.dom.walk() if "id" in n.attrs]
    assert len(ids) == len(set(ids)), "页面里的编号不能重复"
    targets = {a.attrs["href"][1:] for a in b.dom.all("a") if a.attrs["href"].startswith("#")}
    assert targets <= set(ids), sorted(targets - set(ids))
    assert len(targets) >= 20
    for name in targets:   # 网页版只认字母、数字、连字符的名字
        assert re.fullmatch(r"[A-Za-z0-9-]+", name), name
    # 证据表里“所在可比组”点得进对标视图
    groups = b.block("EV-000001-001", "所在可比组")
    assert [a.attrs["href"] for a in groups.all("a")] == ["#CMP-000001", "#CMP-000002", "#CMP-000003"]


def test_charts_are_complete_svg_files():
    """每张图单独拿出来就是一个完整的 SVG 文件，可以直接放进报告。"""
    b = T.example()
    found = re.findall(r'<svg xmlns="http://www.w3.org/2000/svg" class="chart".*?</svg>', b.page, re.S)
    assert len(found) == 4, len(found)
    for text in found:
        root = _svg(text)
        assert root.get("viewBox") and root.get("width") and root.get("font-family")
        assert all(t.get("font-size") and t.get("fill") for t in _find(root, "text"))
        assert not [n for n in root.iter() if n.get("class") and n is not root], "图里面不靠页面的样式表"


# ---------------------------------------------------------------- 两个指标的散点图（示例数据里没有，这里临时加）

def add_scatter(data):
    def dictionary(d):
        base = next(i for i in d["indicators"] if i["key"] == "area_resistance")
        d["indicators"].append(dict(copy.deepcopy(base), key="vanadium_permeability", list_no="IN-03", name_zh="钒离子渗透率",
                                    name_en="Vanadium ion permeability", unit_std="cm2/min", units_accepted=[{"unit": "cm2/min", "factor": 1}]))
        d["rules"].append({"key": "material_pair", "name": "同文同批的两个指标（示例）", "applies_to": ["area_resistance", "vanadium_permeability"],
                           "level": "material", "statement": "示例", "tier_if_met": "direct", "status": "draft"})

    def source(doc):
        base = doc["evidence"][0]

        def clone(number, label, indicator, value, unit, std, **more):
            e = copy.deepcopy(base)
            e.update(id=f"EV-000002-{number:03d}", sample_label=label, indicator=indicator, value_reported=value, unit_reported=unit,
                     value_std=std, **more)
            return e

        doc["evidence"] += [
            clone(2, "Q-1", "area_resistance", "0.62", "ohm*cm2", 0.62, uncertainty=0.05, uncertainty_kind="sd"),
            clone(3, "Q-1", "vanadium_permeability", "2.1×10⁻⁷", "cm2/min", 2.1e-7),
            clone(4, "Q-2", "area_resistance", "0.38", "ohm*cm2", 0.38, verification_status="expert_reviewed"),
            clone(5, "Q-2", "vanadium_permeability", "6.8×10⁻⁵", "cm2/min", 6.8e-5, verification_status="expert_reviewed"),
        ]

    T.edit_json(data, "public/topics/TOP-000001/dictionary.json", dictionary)
    T.edit_source(data, "SRC-000002", source)
    T.edit_json(data, "public/topics/TOP-000001/comparisons.json", lambda rows: rows.append({
        "id": "CMP-000004", "topic_id": "TOP-000001", "title": "面电阻对钒离子渗透率（虚构）", "question": "Q1", "level": "material",
        "indicators": ["area_resistance", "vanadium_permeability"], "rule": "material_pair", "tier": "direct", "tier_reason": "示例",
        "normalization": "none", "members": [{"evidence_id": f"EV-000002-{k:03d}", "role": "member"} for k in (2, 3, 4, 5, 1)],
        "status": "draft", "visibility": "internal"}))


def test_scatter_of_two_indicators():
    with T.example_copy() as data:
        add_scatter(data)
        b = T.Built(data)
        assert b.code == 0 and not any("显示不出来" in p for p in b.problems()), b.problems()
        c = card(b, "CMP-000004")
        svg = c.one("svg", "chart")
        links = sorted(svg.all("a"), key=lambda a: a.attrs["data-evidence"])
        assert [(a.attrs["data-evidence"], a.attrs["href"]) for a in links] == [
            ("EV-000002-002", "#CMP-000004--EV-000002-002"), ("EV-000002-004", "#CMP-000004--EV-000002-004")], "一个对象一个点"
        marks = [[g for g in a.all("g") if g.attrs.get("transform")][0] for a in links]
        assert [g.attrs["fill"] for g in marks] == [WHITE, BLUE], "两个数都专业复核过的才画实心"
        (x1, y1), (x2, y2) = [tuple(float(v) for v in re.match(r"translate\(([-\d.]+) ([-\d.]+)\)", g.attrs["transform"]).groups()) for g in marks]
        assert x1 > x2 and y1 > y2, "Q-1 面电阻大，在右；渗透率小，在下"
        words = [t.text for t in svg.all("text")]
        assert {"面电阻，Ω cm²", "钒离子渗透率，cm² min⁻¹", "Q-1", "Q-2"} <= set(words)
        assert {"10⁻⁷", "10⁻⁶", "10⁻⁵", "10⁻⁴"} <= set(words), "差了两个数量级以上，纵轴用对数，刻度都写成 10 的几次方"
        assert "面电阻 0.62 Ω cm²" in links[0].one("title").text and "钒离子渗透率 2.1×10⁻⁷ cm² min⁻¹（EV-000002-003）" in links[0].one("title").text
        assert svg.all("polyline") == [], "不同对象的点不连线"
        assert [li.text for li in c.one("ul", "plain").all("li")] == ["EV-000002-001：这个对象在组里只有面电阻，凑不成一个点"]
        head, lines = table(c)
        assert head[:5] == ["证据", "对象", "指标", "角色", "数值"] and [r[2] for r in lines] == ["面电阻", "钒离子渗透率", "面电阻", "钒离子渗透率", "面电阻"]
        assert c.one("figcaption").text.startswith("对象数 3：参与比较 5，基准 0，只作参考 0｜图上 2 个点｜筛选：材料，面电阻、钒离子渗透率，CMP-000004｜")
        tabs = [(t.attrs["data-level-tab"], t.clean) for t in b.dom.one("section", "view", id="compare").all("button", "chip")]
        assert tabs == [("material", "材料1"), ("component", "组件或器件3")]
        # 有误差的那一点画了误差线（横着的一根加两头的短线）
        assert bars(svg) == 3
        T.edit_evidence(data, "EV-000002-002", lambda e: (e.pop("uncertainty"), e.pop("uncertainty_kind")))
        assert bars(card(T.Built(data), "CMP-000004").one("svg", "chart")) == 0


# ---------------------------------------------------------------- 把数据改坏：照实标出来，不垮

def _cmp(data, cid, change):
    T.edit_json(data, "public/topics/TOP-000001/comparisons.json", lambda rows: change(next(c for c in rows if c["id"] == cid)))


# 名字、怎么改、页面上哪个可比组里必须出现的文字
BROKEN_GROUPS = [
    ("成员指向证据库里没有的证据", lambda d: _cmp(d, "CMP-000001", lambda c: c["members"].append({"evidence_id": "EV-000099-001", "role": "member"})),
     "CMP-000001", ["EV-000099-001", "证据库里没有这一条"]),
    ("数据不足的组要写明缺什么", lambda d: _cmp(d, "CMP-000003", lambda c: c.update(tier="insufficient", missing="两篇的电解液体积都没有报告（虚构）")),
     "CMP-000003", ["数据不足", "缺什么", "两篇的电解液体积都没有报告（虚构）"]),
    ("直接可比的组里有没报告的条件", lambda d: _cmp(d, "CMP-000001", lambda c: c.update(missing_conditions=["temperature"], same_setup_note="图 3 的图注写明同一套电池（虚构）")),
     "CMP-000001", ["原文没写的条件", "温度", "同一套条件的依据", "图 3 的图注写明同一套电池（虚构）"]),
    ("成员被排除", lambda d: _cmp(d, "CMP-000002", lambda c: c["members"][2].update(role="excluded", note="预印本和正式版重复（虚构）")),
     "CMP-000002", ["EV-000007-001：排除：预印本和正式版重复（虚构）", "对象数 4：参与比较 1，基准 2，只作参考 1｜图上 1 个点"]),
    ("基准作废了", lambda d: T.edit_evidence(d, "EV-000001-002", lambda e: e.update(verification_status="void", void_reason="虚构")),
     "CMP-000002", ["这一条或它的基准已作废", "作废"]),
    ("成员的数值写法认不出来", lambda d: T.edit_evidence(d, "EV-000004-002", lambda e: (e.pop("value_std"), e.update(value_reported="84–85"))),
     "CMP-000003", ["EV-000004-002：没有标准单位下的数值", "84–85%", "图上 1 个点"]),
    ("组里的指标不止两个", lambda d: _cmp(d, "CMP-000001", lambda c: c.update(indicators=["energy_efficiency", "area_resistance", "max_current_density"])),
     "CMP-000001", ["这一组有 3 个指标，没有画图，只列表", "这一组没有画图"]),
    ("成员写成了别的类型", lambda d: _cmp(d, "CMP-000001", lambda c: c.update(members="EV-000001-001")), "CMP-000001", ["这一组没有画图", "对象数 0"]),
    ("没写指标、规则和档别", lambda d: _cmp(d, "CMP-000001", lambda c: [c.pop(k) for k in ("indicators", "rule", "tier", "normalization")]),
     "CMP-000001", ["（没有填）", "这一组有 0 个指标"]),
    ("原文给了范围", lambda d: T.edit_evidence(d, "EV-000001-001", lambda e: e.update(range_low=85.0, range_high=86.2)),
     "CMP-000001", ["范围 85–86.2"]),
]


def test_broken_groups_are_shown_as_they_are():
    for name, change, cid, expected in BROKEN_GROUPS:
        with T.example_copy() as data:
            change(data)
            b = T.Built(data)
            assert b.code == 0, f"{name}：生成不了\n{b.log}"
            assert not any("显示不出来" in p for p in b.problems()), f"{name}：{b.problems()}"
            text = card(b, cid).clean
            for want in expected:
                assert want in text, f"{name}：{cid} 里应当有“{want}”，页面上是：{text[:500]}"
            assert len(b.dom.all("tbody", "ev")) == 13, name


def bars(svg):
    """误差线的线段数：一根主线加两头的短线，线宽和网格线不一样。"""
    return len([n for n in svg.all("line") if n.attrs.get("stroke-width") == "1.4"])


def test_range_is_drawn_as_an_error_bar():
    with T.example_copy() as data:
        assert bars(card(T.Built(data), "CMP-000001").one("svg", "chart")) == 0
        T.edit_evidence(data, "EV-000001-001", lambda e: e.update(range_low=85.0, range_high=86.2))
        assert bars(card(T.Built(data), "CMP-000001").one("svg", "chart")) == 3, "原文给了范围就画出来"


def test_group_in_a_level_that_cannot_be_compared_is_still_shown():
    with T.example_copy() as data:
        _cmp(data, "CMP-000003", lambda c: c.update(level="product_supply"))
        b = T.Built(data)
        panels = [p.attrs["data-level-panel"] for p in b.dom.one("section", "view", id="compare").all("section", "level")]
        assert panels == ["material", "component", "product_supply"] and b.problems(), "照样显示，校验没通过的列在页面顶上"
        assert card(b, "CMP-000003").parent.attrs["data-level-panel"] == "product_supply"


def test_compare_view_failing_does_not_take_the_page_down():
    real = compare_view.build

    def broken(*args):
        raise RuntimeError("故意弄坏的")

    compare_view.build = broken
    try:
        b = T.Built(T.EXAMPLE)
        strict = T.Built(T.EXAMPLE, strict=True)
    finally:
        compare_view.build = real
    assert b.code == 0 and strict.code == 1
    assert b.problems() == ["对标视图：显示不出来（RuntimeError: 故意弄坏的）"]
    assert "这一页生成不了" in b.dom.one("section", "view", id="compare").text
    assert len(b.dom.all("tbody", "ev")) == 13 and b.cell("EV-000001-001", "c-value").clean == "85.6%", "证据表不受影响"
    assert b.block("EV-000001-001", "所在可比组").all("a") == [], "对标视图没有出来，就不做跳过去的链接"


def test_empty_repo_data_has_an_empty_compare_view():
    b = T.Built(V.DEFAULT_DATA)
    view = b.dom.one("section", "view", id="compare")
    assert [p.attrs["data-level-panel"] for p in view.all("section", "level")] == ["material", "component", "system"]
    assert view.all("svg", "chart") == [] and "0 个可比组" in view.all("div", "view-head")[0].clean
    assert all("这一层还没有可比组" in p.text for p in view.all("section", "level"))


# ---------------------------------------------------------------- 用浏览器点一遍

def shown_levels(page):
    return page.eval_on_selector_all("[data-level-panel]", "ps => ps.filter(p => getComputedStyle(p).display !== 'none').map(p => p.dataset.levelPanel)")


def test_browser_switches_levels():
    with T.opened() as (go, page, seen):
        go("compare")
        assert T.shown_views(page) == ["compare"]
        assert shown_levels(page) == ["component"], "先显示第一个有可比组的层级，一次只看一层"
        assert page.get_attribute("[data-level-tab=component]", "aria-pressed") == "true"
        page.click("[data-level-tab=material]")
        assert shown_levels(page) == ["material"] and page.get_attribute("[data-level-tab=component]", "aria-pressed") == "false"
        assert page.is_visible("text=材料这一层还没有可比组")
        page.click("[data-level-tab=component]")
        assert shown_levels(page) == ["component"] and page.is_visible("#CMP-000001 svg.chart")
        assert page.is_visible("#legend") and page.is_visible("#stamp") and seen["errors"] == []


def test_browser_from_a_point_to_its_row_to_its_evidence():
    """图上的点 → 成员表里那一行 → 证据表里那条证据（设计方案 4.4 第 1 项）。"""
    with T.opened() as (go, page, seen):
        go("compare")
        page.click("#CMP-000002 svg a[data-evidence='EV-000007-001']")
        T.wait_until(page, "document.getElementById('CMP-000002--EV-000007-001').classList.contains('target')")
        box = page.evaluate("(() => { const r = document.getElementById('CMP-000002--EV-000007-001').getBoundingClientRect(); return [r.top, innerHeight]; })()")
        assert 0 <= box[0] < box[1], f"那一行滚到了看得见的地方：{box}"
        assert T.shown_views(page) == ["compare"]
        page.click("#CMP-000001 svg a[data-evidence='EV-000001-002']")
        T.wait_until(page, "document.getElementById('CMP-000001--EV-000001-002').classList.contains('target')")
        assert page.eval_on_selector_all(".target", "ns => ns.map(n => n.id)") == ["CMP-000001--EV-000001-002"], "只标出最后跳到的那一处"
        page.click("#CMP-000001--EV-000001-002 a")
        T.wait_until(page, "document.getElementById('EV-000001-002').classList.contains('open')")
        assert T.shown_views(page) == ["evidence"]
        # 随条件变化的图上的点直接进证据
        go("compare")
        page.click("svg[aria-label^='能量效率随电流密度的变化'] a[data-evidence='EV-000001-003']")
        T.wait_until(page, "document.getElementById('EV-000001-003').classList.contains('open')")
        assert T.shown_views(page) == ["evidence"] and seen["errors"] == []


def test_browser_from_evidence_to_its_group():
    with T.example_copy() as data:
        add_scatter(data)
        with T.opened(data) as (go, page, seen):
            go("compare")
            assert shown_levels(page) == ["material"]
            page.click("[data-level-tab=component]")
            go("EV-000002-003")   # 材料层那个组的成员
            page.click("#d-EV-000002-003 a[href='#CMP-000004']")
            T.wait_until(page, "document.getElementById('CMP-000004').classList.contains('target')")
            assert T.shown_views(page) == ["compare"] and shown_levels(page) == ["material"], "跳过去时换到那个组所在的层级"
            assert shown_levels(go("CMP-000002")) == ["component"] and T.shown_views(page) == ["compare"]
            T.wait_until(page, "document.getElementById('CMP-000002').classList.contains('target')")
            assert shown_levels(go("CMP-000004--EV-000002-004")) == ["material"]
            assert seen["errors"] == []


def test_browser_compare_view_on_a_narrow_screen_and_without_script():
    with T.opened(size=(390, 844)) as (go, page, seen):
        go("compare")
        widths = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
        assert widths[0] <= widths[1], f"窄屏上页面比屏幕宽：{widths}"
        inner = page.evaluate("(() => { const f = document.querySelector('#CMP-000001 figure'); return [f.scrollWidth, f.clientWidth]; })()")
        assert inner[0] > inner[1], "图保持原来的大小，在自己的框里左右滑，字不会缩得看不清"
        assert seen["errors"] == []
    with T.opened(script=False) as (go, page, seen):
        go()
        assert shown_levels(page) == ["material", "component"], "不跑脚本时各层级都显示"
        assert page.is_visible("#CMP-000003 svg.chart") and not page.is_visible("[data-level-tab=material]")


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
    cases = len(NUMBER_CASES) + len(SCALE_CASES) + len(BROKEN_GROUPS)
    print(f"{cases} 处对错的用例" + ("，结果都和预期的一样" if not failed else ""), "｜失败", failed, "｜跳过", skipped)
    sys.exit(1 if failed else 0)
