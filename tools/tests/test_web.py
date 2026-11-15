#!/usr/bin/env python3
"""网页前端（web/）的测试。直接运行：python3 tools/tests/test_web.py

先构建：cd web && npm ci && npm run build。要用机器上的 Chrome 和 node。
环境变量 WEB_TESTS=required 时，没构建、没 node、没浏览器都算失败（GitHub Actions 上这样跑）；不设就跳过并写明。

A 2.0（Yu 2026-11-15 选的新样子）之后测四样：
1. 页面上的数和数据对得上：证据表每一行、右边的详情、对标视图的每个点和比值、总览的核验四步和覆盖图的每一格，
   都和导出的 views.json（由看板的 Python 函数算好）逐项比。期望值从数据文件里读，不从页面上抄。
2. 还用旧写法的两页（数据概览与缺口、非学术来源）和旧看板逐个元素对得上；数据换成二十几种样子再比。
3. 怎么点：筛选、查找、跳转、⌘K 查找面板、深浅色、复制、下载、嵌在框里；字和底色的对比度、控件大小、手机宽度，深浅两套都量。
4. 在线版、离线版、数据版本对不上、一页出错、不跑脚本。
"""
import contextlib
import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)

import build_dashboard as B  # noqa: E402
import export_site_data as X  # noqa: E402
import store  # noqa: E402
import test_dashboard as T  # noqa: E402
import test_step3 as T3  # noqa: E402
import test_step5 as T5  # noqa: E402
import validate as V  # noqa: E402

WEB = os.path.join(os.path.dirname(TOOLS), "web")
DIST = os.path.join(WEB, "dist")
EXAMPLE = T.EXAMPLE
VERSION = T.VERSION
REQUIRED = os.environ.get("WEB_TESTS") == "required"

def _need(what, ok):
    if ok:
        return
    if REQUIRED:
        raise AssertionError(f"要求跑网页前端的测试（WEB_TESTS=required），但{what}")
    raise unittest.SkipTest(f"{what}，网页前端这一项没测")


def ready():
    _need("没有找到 node", shutil.which("node"))
    _need("web/dist 还没有构建（cd web && npm ci && npm run build）", os.path.exists(os.path.join(DIST, "index.html")))
    return T._browser()


def export_to(data, out, version=VERSION, change_views=None):
    """把 data 导出成前端读的数据文件，写到 out。change_views 可以在写之前改 views.json，用来造坏数据。"""
    files = X.export(data, version=version)
    if change_views:
        change_views(files["views.json"])
    os.makedirs(out, exist_ok=True)
    for name, content in files.items():
        store.write_json(os.path.join(out, name), content)
    return files


def offline(data_dir, out_file):
    r = subprocess.run(["node", os.path.join(WEB, "scripts", "offline.mjs"), "--dist", DIST, "--data", data_dir, "--out", out_file],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr + r.stdout
    return out_file


@contextlib.contextmanager
def built_web(data=EXAMPLE, change_views=None):
    """新前端的离线版：一个网页文件。给出它的路径。"""
    with tempfile.TemporaryDirectory() as tmp:
        export_to(data, os.path.join(tmp, "site-data"), change_views=change_views)
        yield offline(os.path.join(tmp, "site-data"), os.path.join(tmp, "web", "index.html"))


@contextlib.contextmanager
def browser(script=True, size=(1280, 900)):
    sync_playwright, exe = ready()
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
        context = b.new_context(java_script_enabled=script, viewport={"width": size[0], "height": size[1]}, reduced_motion="reduce")
        try:
            yield context
        finally:
            b.close()


def watch(page):
    seen = {"requests": [], "errors": []}
    page.on("request", lambda r: seen["requests"].append(r.url))
    page.on("pageerror", lambda e: seen["errors"].append(str(e)))
    page.on("console", lambda m: seen["errors"].append(m.text) if m.type == "error" else None)
    return seen


@contextlib.contextmanager
def opened_web(data=EXAMPLE, script=True, size=(1280, 900), frame=False, change_views=None):
    """和旧看板测试里的 opened 一样的用法，打开的是新前端（离线版）。"""
    with built_web(data, change_views) as page_file:
        site = os.path.dirname(page_file)
        if frame:  # 网页版的查看器是把页面放在一个沙盒框里显示的，这里照样放进去
            with open(os.path.join(site, "frame.html"), "w", encoding="utf-8") as fh:
                fh.write('<!DOCTYPE html><title>frame</title><iframe sandbox="allow-scripts" src="index.html" '
                         'width="1200" height="800"></iframe>')
        base = "file://" + os.path.join(site, "frame.html" if frame else "index.html")
        with browser(script, size) as context:
            page = context.new_page()
            seen = watch(page)

            def go(name=""):
                page.goto(base + ("#" + name if name else ""))
                (page.frames[1] if frame else page).wait_for_selector("#app > *", timeout=10000)
                (page.frames[1] if frame else page).wait_for_timeout(50)
                return page

            yield go, page, seen


# ---------------------------------------------------------------- 1. 页面上的数和数据对得上

def views_of(data=EXAMPLE):
    """导出的 views.json 里这个题目的那一块；写成 {"$row": 编号} 的地方换回那一行（和前端读进来时一样）。"""
    topic = X.export(data, version=VERSION)["views.json"]["topics"][0]
    rows = {r["id"]: r for r in topic["rows"]}

    def back(x):
        if isinstance(x, list):
            return [back(v) for v in x]
        if isinstance(x, dict):
            if set(x) == {"$row"}:
                return rows[x["$row"]]
            if "$html" in x:
                return x
            return {k: back(v) for k, v in x.items()}
        return x
    return {k: (v if k == "rows" else back(v)) for k, v in topic.items()}


def visible_rows(page):
    return page.eval_on_selector_all("tr.ev-row", "rows => rows.map(r => r.id)")


def side_text(page):
    return page.inner_text("#ev-side")


def test_evidence_rows_and_detail_match_the_data():
    v = views_of()
    with opened_web() as (go, page, seen):
        go("evidence")
        assert visible_rows(page) == [r["id"] for r in v["rows"]]
        for r in v["rows"]:
            row = page.inner_text(f"tr#{r['id']}")
            assert r["value"] in row and r["measure"] in row and r["id"] in row, (r["id"], row)
            page.click(f"tr#{r['id']} .pick")
            assert page.get_attribute(f"tr#{r['id']}", "aria-selected") == "true"
            side = side_text(page)
            for want in [r["id"], r["value"], r["status_label"], r["type_label"]] + [c["text"] for c in r["conditions"]] + [t for _, t in r["history"]]:
                assert want in side, (r["id"], want)
            if r["snippet"]:
                assert r["snippet"].replace("\n", " ").split()[0] in side
        page.click("tr#EV-000001-001 .pick")
        assert page.inner_text("#ev-side mark") == "85.6", "原文片段里把数值标出来"
        assert seen["errors"] == []


def test_compare_points_and_ratios_match_the_data():
    v = views_of()
    groups = [g for lv in v["compare"]["levels"] for g in lv["groups"]]
    with opened_web() as (go, page, seen):
        for g in groups:
            go(g["id"])
            T.wait_until(page, "id => document.querySelector(`[data-group='${id}']`).getAttribute('aria-pressed') === 'true'", g["id"])
            with_ratio = [m for m in g["members"] if m["row"] and m["role"] != "baseline" and m["ratio"] and m["ratio"]["ratio"] is not None]
            tabs = page.eval_on_selector_all("[data-tab]", "b => b.map(x => [x.dataset.tab, x.getAttribute('aria-selected')])")
            if with_ratio:
                assert tabs[0] == ["ratio", "true"], "有比值的组默认看与基准之比（Yu 2026-11-15 定）"
                drawn = page.eval_on_selector_all("svg.chart g.hit", "gs => gs.map(g => [g.dataset.evidence, g.querySelector('text.val').textContent])")
                assert drawn == [[m["id"], B.fmt_num(m["ratio"]["ratio"])] for m in with_ratio], drawn
            page.click("[data-tab=table]")
            body = page.inner_text("#compare table")
            for m in g["members"]:
                assert m["id"] in body, m["id"]
                if m["row"]:
                    assert m["row"]["value"] in body
            page.click("[data-tab]")
        assert seen["errors"] == []


def test_series_chart_points_match_the_data():
    v = views_of()
    levels = [lv for lv in v["compare"]["levels"] if lv["series"]]
    assert levels, "示例数据里应该有“随条件变化”的图"
    with opened_web() as (go, page, seen):
        go("compare")
        for lv in levels:
            if lv["groups"]:
                page.click(f"[data-level-tab='{lv['code']}']")
            figs = page.eval_on_selector_all("section[aria-label='同一批测试里随条件变化'] figure", """fs => fs.map(f => ({
                points: [...f.querySelectorAll('svg a[data-evidence]')].map(a => a.dataset.evidence).sort(),
                lines: f.querySelectorAll('svg polyline.line').length }))""")
            assert len(figs) == len(lv["series"]), figs
            for f, s in zip(figs, lv["series"]):
                want = sorted(p["evidence"] for line in s["lines"] for p in line["points"])
                assert f["points"] == want, (f, want)
                assert f["lines"] == sum(1 for line in s["lines"] if len(line["points"]) > 1), "一个样品两个点以上才连线"
        stroke = lambda: page.eval_on_selector("section[aria-label='同一批测试里随条件变化'] polyline.line", "l => getComputedStyle(l).stroke")
        light = stroke()
        page.click("#theme-toggle")
        assert page.get_attribute("html", "data-theme") == "dark" and stroke() != light, "深色下的线跟着主题色换"
        assert seen["errors"] == []


def bigger(tmp, k):
    """把示例数据复制成大的一份：每个来源复制 k 份，编号换掉、样品名加后缀。用来测证据多了以后页面怎么分批画。"""
    import re
    out = os.path.join(tmp, "big")
    shutil.copytree(EXAMPLE, out)
    sdir = os.path.join(out, "public", "sources")
    orig = sorted(f[:-5] for f in os.listdir(sdir))
    texts = {s: open(os.path.join(sdir, s + ".json"), encoding="utf-8").read() for s in orig}
    pat = re.compile("|".join(re.escape(s) for s in orig) + "|" + "|".join(re.escape("EV-" + s[4:] + "-") for s in orig))
    for i in range(1, k + 1):
        to = {s: f"SRC-{int(s[4:]) + 1000 * i:06d}" for s in orig}
        for s, text in texts.items():
            new = pat.sub(lambda m: to[m.group(0)] if m.group(0).startswith("SRC") else "EV-" + to["SRC-" + m.group(0)[3:9]][4:] + "-", text)
            new = new.replace('"label": "X-1"', f'"label": "X-1·{i}"').replace('"sample_label": "X-1"', f'"sample_label": "X-1·{i}"')
            with open(os.path.join(sdir, to[s] + ".json"), "w", encoding="utf-8") as fh:
                fh.write(new)
    return out


def test_many_rows_are_drawn_in_batches():
    with tempfile.TemporaryDirectory() as tmp:
        data = bigger(tmp, 20)
        v = views_of(data)
        ids = [r["id"] for r in v["rows"]]
        assert len(ids) > 200
        with opened_web(data) as (go, page, seen):
            go("evidence")
            assert visible_rows(page) == ids[:200], "先画 200 行"
            assert "再显示" in page.inner_text("#ev-more")
            go(ids[-1])
            T.wait_until(page, "id => !!document.getElementById(id)", ids[-1])
            assert page.get_attribute(f"tr#{ids[-1]}", "aria-selected") == "true", "跳到排在后面的证据也找得到"
            assert visible_rows(page) == ids, "为了显示选中的那条，前面的也都画出来"
            go("evidence")
            page.click("tr.ev-row .pick")
            page.click("#ev-more")
            assert visible_rows(page) == ids[:400], "再显示 200 条"
            go("overview")
            cov = v["overview"]["coverage"]["rows"]
            assert len(cov) > 40
            heads = lambda: page.eval_on_selector_all("#coverage .heat .rowhead", "r => r.length")
            assert heads() == 40, "覆盖图先画 40 张膜"
            page.click("#heat-all")
            assert heads() == len(cov)
            assert seen["errors"] == []


def test_overview_steps_and_coverage_match_the_data():
    v = views_of()
    model = v["overview"]
    counts = {code: n for code, _, n in model["status"]}
    depth = {"pending": 1, "machine_checked": 2, "human_verified": 3, "expert_reviewed": 4}
    with opened_web() as (go, page, seen):
        go("overview")
        shown = page.eval_on_selector_all("button.step", "b => b.map(x => [x.dataset.step, x.querySelector('.n').textContent])")
        live = sum(n for code, n in counts.items() if code != "void")
        want = [["1", str(live)]] + [[str(d), str(sum(n for c, n in counts.items() if depth.get(c, 0) >= d))] for d in (2, 3, 4)]
        assert shown == want
        cells = page.eval_on_selector_all(".heat .cell", "cs => cs.map(c => [c.dataset.state, c.getAttribute('href'), c.textContent])")
        expect = []
        for r in model["coverage"]["rows"]:
            for c in r["cells"]:
                best = c["best"]
                expect.append([c["state"], f"#{best['id']}" if best else None, best["value"] + (" · 疑" if c["disputed"] else "") if best else None])
        assert [[s, h, (t if h else None)] for s, h, t in cells] == expect
        page.click("button.step[data-step='4']")
        dim = page.eval_on_selector_all(".heat .cell", "cs => cs.map(c => c.classList.contains('dim'))")
        assert dim == [not (e[0] == "expert_reviewed") for e in expect], "点了“专业已复核”，只亮专业已复核的格子"
        page.hover(".heat a.cell")
        assert page.inner_text(".hoverline").count("EV-") >= 1
        page.click(".heat a.cell")
        T.wait_view(page, "evidence")
        assert seen["errors"] == []


# ---------------------------------------------------------------- 2. 还用旧写法的两页和旧看板逐项对得上

# 页面上要比的几块：A 2.0 之后，只有这两页还是旧看板的写法
PARTS = ["#gaps", "#non-academic"]

# 一个元素的样子：标签、属性、字。连着的几段字并成一段、空白并成一个空格再比。
# 有意不同、不比的：随页面状态变的几个属性；SVG 的 xmlns（新前端由浏览器按 SVG 的命名空间建元素）。
IGNORED = ("aria-expanded", "aria-pressed", "aria-current", "tabindex", "style", "xmlns")
SIGNATURE = """(root) => {
  const out = [];
  let text = '';
  const flush = () => { const t = text.replace(/\\s+/g, ' ').trim(); if (t) out.push('T ' + t); text = ''; };
  const skip = %s;
  const walk = (n) => {
    if (n.nodeType === 3) { text += n.textContent; return; }
    if (n.nodeType !== 1) return;
    flush();
    const tag = n.tagName.toLowerCase();
    const attrs = [...n.attributes].map(a => a.name).filter(a => !skip.includes(a)).sort()
      .map(a => a + '=' + (a === 'class' ? n.getAttribute(a).split(/\\s+/).filter(c => c && !['active', 'open', 'target'].includes(c)).sort().join(' ') : n.getAttribute(a)));
    out.push('E ' + tag + ' ' + attrs.join(' '));
    for (const c of n.childNodes) walk(c);
    flush();
    out.push('/' + tag);
  };
  if (root) walk(root);
  return out;
}""" % json.dumps(list(IGNORED))


def signatures(page):
    out = {part: page.eval_on_selector(part, SIGNATURE) if page.query_selector(part) else None for part in PARTS}
    out["banners"] = page.eval_on_selector_all(".banner", f"bs => bs.map({SIGNATURE})")
    return out


def differences(data):
    """同一份数据，旧看板和新前端在这两页、页面顶上的提示上的不同之处：[(哪一块, 头几处不同)]。"""
    import difflib
    with tempfile.TemporaryDirectory() as old, built_web(data) as new, browser() as context:
        assert B.build(data, old, version=VERSION, log=lambda *_: None) == 0
        got = {}
        for name, url in (("old", "file://" + os.path.join(old, B.PAGE_NAME)), ("new", "file://" + new)):
            page = context.new_page()
            seen = watch(page)
            page.goto(url)
            page.wait_for_selector("main .view")
            got[name] = signatures(page)
            assert seen["errors"] == [], f"{name}：{seen['errors']}"
            page.close()
    diffs = []
    for key in got["old"]:
        a, b = got["old"][key], got["new"][key]
        if a != b:
            if isinstance(a, list) and isinstance(b, list):
                lines = [x for x in difflib.unified_diff(a, b, lineterm="", n=0) if x[:1] in "+-" and x[:3] not in ("+++", "---")]
            else:
                lines = [f"- {a!r}", f"+ {b!r}"]
            diffs.append((key, lines[:12]))
    return diffs


def _poison(data):
    """旧看板测试里“来源里的文字不会被当成网页代码”那一份数据。"""
    def poison(e):
        for key, text in T.HOSTILE:
            e[key] = text
        e["locator"]["text"] = "<iframe src=//x>"
    T.edit_evidence(data, "EV-000001-001", poison)

    def poison_source(doc):
        doc["source"].update(title="<style>*{display:none}</style>", creators="<a href=javascript:alert(7)>x</a>",
                             url="javascript:alert(8)", archive_url="data:text/html,<script>alert(9)</script>")
        doc["source"]["identifiers"]["doi"] = "10.1234/x\" onmouseover=\"alert(10)"
    T.edit_source(data, "SRC-000001", poison_source)
    T.edit_json(data, "public/entities.json", lambda rows: rows[0].update(name="<img src=x onerror=alert(11)> & Co"))
    T.edit_json(data, "meta.json", lambda m: m.update(note="<script>alert(12)</script>"))
    T.edit_json(data, "public/topics/TOP-000001/topic.json", lambda t: t.update(title="</title><script>alert(13)</script>"))


def _many_problems(data):
    for sid in sorted(f[:-5] for f in os.listdir(os.path.join(data, "public", "sources"))):
        T.edit_source(data, sid, lambda doc: [e.update(level="nowhere", evidence_type="rumour", obtained_from="hearsay",
                                                       visibility="everyone") for e in doc["evidence"]])


def _crowded_cell(data):
    """一览表的一格里放 8 条：多的只列前 6 条，写“另有几条”。"""
    def add(doc):
        first = next(e for e in doc["evidence"] if e["id"] == "EV-000001-001")
        for i in range(5, 13):
            doc["evidence"].append(dict(first, id=f"EV-000001-{i:03d}", value_reported=f"8{i % 10}.0"))
    T.edit_source(data, "SRC-000001", add)


# 名字、怎么改示例数据的一份拷贝（None 是不改）
PARITY_CASES = (
    [("示例数据", None), ("塞了网页代码的数据", _poison), ("校验问题超过 50 处", _many_problems),
     ("坏得厉害的数据（第 5 步的测试）", T5._break_everything), ("一览表的一格里条数多", _crowded_cell)]
    + [(f"改坏的证据：{name}", change) for name, change, _, _ in T.BROKEN_CASES]
    + [(f"改坏的可比组：{case[0]}", case[1]) for case in T3.BROKEN_GROUPS]
)


def test_two_old_style_pages_match_the_old_dashboard():
    ready()
    failed = []
    for name, change in PARITY_CASES:
        with T.example_copy() as data:
            if change:
                change(data)
            diffs = differences(data)
        if diffs:
            failed.append((name, diffs))
    assert not failed, "\n".join(f"{name}：\n" + "\n".join(f"  {k}: " + "\n    ".join(lines) for k, lines in diffs) for name, diffs in failed)
    print(f"      两页新旧对照：{len(PARITY_CASES)} 份数据都一样")


def test_two_old_style_pages_match_on_the_repo_data():
    ready()
    assert differences(V.DEFAULT_DATA) == []


def test_the_comparison_itself_catches_differences():
    """比的办法本身要管用：少一个字、多一个属性、换一个链接，都要比出来。"""
    ready()
    for js in ["document.querySelector('#gaps-count').textContent += '。'",
               "document.querySelector('#gaps a[href=\"#evidence\"]').setAttribute('href', '#compare')",
               "document.querySelector('#non-academic .tile').remove()"]:
        with tempfile.TemporaryDirectory() as old, built_web(EXAMPLE) as new, browser() as context:
            assert B.build(EXAMPLE, old, version=VERSION, log=lambda *_: None) == 0
            a = context.new_page()
            a.goto("file://" + os.path.join(old, B.PAGE_NAME))
            b = context.new_page()
            b.goto("file://" + new)
            b.wait_for_selector("main .view")
            b.evaluate(js)
            assert signatures(a) != signatures(b), f"没比出来：{js}"


# ---------------------------------------------------------------- 3. 怎么点

def test_pages_switch_and_hash_jumps():
    with opened_web() as (go, page, seen):
        go()
        T.wait_view(page, "overview")
        for name in ("evidence", "compare", "gaps", "non-academic", "overview"):
            page.click(f"nav.rail a[data-view='{name}']")
            T.wait_view(page, name)
            assert page.get_attribute(f"nav.rail a[data-view='{name}']", "aria-current") == "page"
        go("no-such-thing")
        T.wait_view(page, "overview")
        go("EV-000007-002")
        T.wait_view(page, "evidence")
        assert page.get_attribute("tr#EV-000007-002", "aria-selected") == "true"
        T.wait_until(page, "document.activeElement && document.activeElement.closest('tr') && document.activeElement.closest('tr').id === 'EV-000007-002'")
        go("CMP-000003")
        T.wait_view(page, "compare")
        assert page.get_attribute("[data-group='CMP-000003']", "aria-pressed") == "true"
        go("ASM-000001")
        T.wait_view(page, "gaps")
        T.wait_until(page, "document.getElementById('ASM-000001').classList.contains('target')")
        go("SRC-000004")
        T.wait_view(page, "non-academic")
        page.go_back()
        T.wait_view(page, "gaps")
        assert seen["errors"] == []


def test_facets_filter_and_recount():
    v = views_of()
    rows = v["rows"]
    with opened_web() as (go, page, seen):
        go("evidence")
        page.click("[data-filter=status][data-value=pending]")
        assert visible_rows(page) == [r["id"] for r in rows if r["f"]["status"] == "pending"]
        level_counts = page.eval_on_selector_all("[data-filter=level]", "b => b.map(x => [x.dataset.value, x.querySelector('.l .num').textContent])")
        want = [[code, str(sum(1 for r in rows if r["f"]["status"] == "pending" and r["f"]["level"] == code))] for code, _, _ in v["filters"]["level"]]
        assert level_counts == want, "别的筛选项的条数跟着变"
        status_counts = page.eval_on_selector_all("[data-filter=status]", "b => b.map(x => [x.dataset.value, x.querySelector('.l .num').textContent])")
        assert status_counts == [[code, str(n)] for code, _, n in v["filters"]["status"]], "选中的这一项自己的条数不跟着自己变，别的状态照样看得到有几条"
        page.click("[data-filter=status][data-value=pending]")
        assert len(visible_rows(page)) == len(rows)
        page.fill("#ev-q", "AREA resistance")
        assert visible_rows(page) == ["EV-000002-001"]
        page.fill("#ev-q", "x-1  80 mA")
        assert visible_rows(page) == [r["id"] for r in rows if r["sample"] == "X-1" and any("80 mA" in c["text"] for c in r["conditions"])]
        page.fill("#ev-q", "这几个字哪里都没有")
        assert visible_rows(page) == [] and page.is_visible("#ev-empty")
        page.click("#ev-clear")
        assert len(visible_rows(page)) == len(rows)
        page.click("[data-filter=srctype][data-value=patent]")
        go("EV-000001-001")   # 被筛选挡住的证据：跳过去时清掉筛选
        T.wait_until(page, "!!document.getElementById('EV-000001-001')")
        assert len(visible_rows(page)) == len(rows)
        assert seen["errors"] == []


def test_palette_finds_and_jumps():
    with opened_web() as (go, page, seen):
        go("overview")
        page.keyboard.press("Control+k")
        page.wait_for_selector("#palette-q")
        page.fill("#palette-q", "Z-1")
        first = page.inner_text("#palette-list li:first-child")
        assert "EV-000007-001" in first, first
        page.keyboard.press("Enter")
        T.wait_view(page, "evidence")
        assert page.get_attribute("tr#EV-000007-001", "aria-selected") == "true"
        assert page.query_selector("#palette-q") is None
        page.click("#find-open")
        page.fill("#palette-q", "CMP-000002")
        page.keyboard.press("Enter")
        T.wait_view(page, "compare")
        page.keyboard.press("/")
        page.wait_for_selector("#palette-q")
        page.keyboard.press("Escape")
        assert page.query_selector("#palette-q") is None
        assert seen["errors"] == []


def test_theme_follows_the_system_and_toggles():
    for scheme in ("light", "dark"):
        with built_web() as f, browser() as context:
            page = context.new_page()
            page.emulate_media(color_scheme=scheme)
            page.goto("file://" + f)
            page.wait_for_selector("main .view")
            assert page.get_attribute("html", "data-theme") == scheme
            page.click("#theme-toggle")
            assert page.get_attribute("html", "data-theme") == ("light" if scheme == "dark" else "dark")


def test_text_is_readable_and_controls_are_big_enough_in_both_themes():
    small_js = """() => Array.from(document.querySelectorAll('nav.rail a, button, select, input, a.btn, a.cell, summary'))
      .filter(el => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden')
      .map(el => [el.id || el.getAttribute('data-view') || el.className || el.tagName, Math.round(el.getBoundingClientRect().height)])
      .filter(pair => pair[1] < 44)"""
    for size in T.LOOK_SIZES:
        for scheme in ("light", "dark"):
            with built_web() as f, browser(size=size) as context:
                page = context.new_page()
                page.emulate_media(color_scheme=scheme)
                seen = watch(page)
                for where in ("overview", "evidence", "EV-000001-003", "compare", "CMP-000002", "gaps", "non-academic"):
                    page.goto("file://" + f + "#" + where)
                    page.wait_for_selector("main .view.active")
                    found = page.evaluate(T.CONTRAST_JS, T.LOW_CONTRAST_FLOOR)
                    label = f"{size[0]} 宽，{scheme}，{where}"
                    assert found["measured"] > 5, label
                    assert found["bad"] == {}, f"{label}：对比度不够：{found['bad']}"
                    assert page.evaluate(small_js) == [], f"{label}：控件矮于 44 像素：{page.evaluate(small_js)}"
                    widths = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
                    assert widths[0] <= widths[1] + 1, f"{label}：页面比屏幕宽 {widths}"
                page.click("#legend-open")
                found = page.evaluate(T.CONTRAST_JS, T.LOW_CONTRAST_FLOOR)
                assert found["bad"] == {}, f"{size[0]} 宽，{scheme}，图例：{found['bad']}"
                assert seen["errors"] == []


def test_copy_download_and_viewer_frame():
    with opened_web() as (go, page, seen):
        go("evidence")
        assert page.is_visible("#ev-download")
        page.click("[data-filter=status][data-value=pending]")
        page.click("#ev-copy")
        T.wait_until(page, "!!document.getElementById('ev-copy-note')")
        if not page.inner_text("#ev-copy-note").startswith("已复制"):
            lines = page.input_value("#ev-copy-box").split("\n")
            assert len(lines) == 1 + len(visible_rows(page)) and lines[1].split("\t")[0] == visible_rows(page)[0]
    with opened_web(frame=True) as (go, page, seen):
        go()
        inner = page.frames[1]
        inner.click("nav.rail a[data-view=evidence]")
        inner.wait_for_selector("#ev-copy", state="visible", timeout=5000)
        assert inner.query_selector("#ev-download") is None, "查看器的框里不让下载，不显示下载链接"


def test_text_from_sources_is_never_markup():
    with T.example_copy() as data:
        _poison(data)
        with opened_web(data) as (go, page, seen):
            for where in ("overview", "EV-000001-001", "compare", "gaps", "non-academic"):
                go(where)
                page.wait_for_selector("main .view.active")
                assert page.evaluate("document.querySelectorAll('img, iframe, b, script:not([type]), script[type=module]').length") <= 1
                assert page.evaluate("[...document.querySelectorAll('*')].some(n => [...n.attributes].some(a => a.name.startsWith('on')))") is False
                assert page.evaluate("[...document.querySelectorAll('a[href]')].every(a => /^(#|https?:|blob:)/.test(a.getAttribute('href')))")
            go("EV-000001-001")
            assert "<script>alert(1)</script>" in page.inner_text("#ev-side")
            page.keyboard.press("Control+k")
            page.fill("#palette-q", "img")
            assert "<img src=x" in page.inner_text("#palette-list")
            assert page.evaluate("typeof window.alert") == "function" and seen["errors"] == []


# ---------------------------------------------------------------- 3. 新前端自己的

class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@contextlib.contextmanager
def served(root):
    handler = functools.partial(_Quiet, directory=root)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


def test_online_version_reads_only_its_own_data_files():
    """在线版：构建产物加旁边的 site-data/。只向自己的网站要这几样：页面、脚本、样式、图标、三个数据文件。"""
    ready()
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copytree(DIST, tmp, dirs_exist_ok=True)
        shutil.rmtree(os.path.join(tmp, "site-data"), ignore_errors=True)
        export_to(EXAMPLE, os.path.join(tmp, "site-data"))
        with served(tmp) as url, browser() as context:
            page = context.new_page()
            seen = watch(page)
            page.goto(url + "#EV-000001-003")
            page.wait_for_selector("tr#EV-000001-003[aria-selected=true]")
            names = sorted({r[len(url):].split("?")[0] for r in seen["requests"]})
            assert all(r.startswith(url) for r in seen["requests"]), seen["requests"]
            assert [n for n in names if n.startswith("site-data/")] == ["site-data/labels.json", "site-data/meta.json", "site-data/views.json"]
            assert {n for n in names if not n.startswith("site-data/")} <= {"", "favicon.svg"} | {n for n in names if n.startswith("assets/")}
            assert seen["errors"] == [], seen["errors"]
            csp = page.get_attribute("meta[http-equiv=Content-Security-Policy]", "content")
            assert "default-src 'none'" in csp and "unsafe-inline" not in csp and "unsafe-eval" not in csp


def test_offline_version_is_one_file_and_asks_for_nothing():
    """离线版：一个网页文件，本机直接打开，除了它自己不要任何东西；同样的构建和数据，写出来逐字节相同。"""
    ready()
    with tempfile.TemporaryDirectory() as tmp:
        export_to(EXAMPLE, os.path.join(tmp, "d"))
        a = offline(os.path.join(tmp, "d"), os.path.join(tmp, "a", "index.html"))
        b = offline(os.path.join(tmp, "d"), os.path.join(tmp, "b", "index.html"))
        assert open(a, "rb").read() == open(b, "rb").read()
        assert os.listdir(os.path.dirname(a)) == ["index.html"]
        text = open(a, encoding="utf-8").read()
        assert 'src="' not in text and 'rel="stylesheet"' not in text, "脚本、样式都写在页面里"
        with browser() as context:
            page = context.new_page()
            seen = watch(page)
            page.goto("file://" + a + "#compare")
            page.wait_for_selector("#compare.active")
            page.click("nav.rail a[data-view=evidence]")
            page.click("[data-filter=status][data-value=pending]")
            page.keyboard.press("Control+k")
            page.fill("#palette-q", "Z-1")
            assert set(seen["requests"]) == {"file://" + a}, seen["requests"]
            assert seen["errors"] == [], seen["errors"]


def test_offline_script_refuses_what_it_should_not_pack():
    ready()
    with tempfile.TemporaryDirectory() as tmp:
        files = X.export(EXAMPLE, "external", version=VERSION)
        for name, content in files.items():
            store.write_json(os.path.join(tmp, name), content)
        r = subprocess.run(["node", os.path.join(WEB, "scripts", "offline.mjs"), "--dist", DIST, "--data", tmp, "--out", os.path.join(tmp, "x.html")],
                           capture_output=True, text=True)
        assert r.returncode == 2 and not os.path.exists(os.path.join(tmp, "x.html")), r.stderr


def test_data_from_another_version_is_explained():
    """数据文件的写法和页面认的对不上：页面上写明为什么、怎么办，不显示半截的内容。"""
    for change, words in ((lambda v: v.update(format=99), "views.json 的写法是第 99 版"),):
        with opened_web(change_views=change) as (go, page, seen):
            go()
            assert words in page.inner_text("#load-error")
            assert page.query_selector("main") is None


def test_one_page_failing_does_not_take_the_others_down():
    """一页画的时候出了错：这一页写明生成不了，原因列在页面顶上，别的页面照样出。"""
    def broken(views):
        views["topics"][0]["compare"]["levels"][1]["groups"] = [7]   # 一组写成了一个数
    with opened_web(change_views=broken) as (go, page, seen):
        go("compare")
        assert "这一页生成不了" in page.inner_text("#compare")
        assert "对标视图：显示不出来" in page.text_content("#problems")
        go("evidence")
        assert len(visible_rows(page)) == 13
        go("gaps")
        assert page.is_visible("#summary-table")


def test_without_script_says_it_needs_script():
    with built_web() as page_file, browser(script=False) as context:
        page = context.new_page()
        page.goto("file://" + page_file)
        assert "要开着浏览器的脚本才能看" in page.inner_text("body")


def test_download_gives_the_same_table_as_the_old_dashboard():
    """下载的表格文件和旧看板旁边那一份逐字节相同。"""
    with tempfile.TemporaryDirectory() as old:
        assert B.build(EXAMPLE, old, version=VERSION, log=lambda *_: None) == 0
        want = open(os.path.join(old, B.CSV_NAME), "rb").read()
        with opened_web() as (go, page, seen):
            go("evidence")
            with page.expect_download() as d:
                page.click("#ev-download")
            got = open(d.value.path(), "rb").read()
            assert d.value.suggested_filename == B.CSV_NAME
    assert got == want


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
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print("失败 ", name, str(exc)[:3000])
    print(f"网页前端的测试 ｜失败 {failed} ｜跳过 {skipped}")
    sys.exit(1 if failed else 0)
