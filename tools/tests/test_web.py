#!/usr/bin/env python3
"""网页前端（web/）的测试。直接运行：python3 tools/tests/test_web.py

先构建：cd web && npm ci && npm run build。要用机器上的 Chrome 和 node。
环境变量 WEB_TESTS=required 时，没构建、没 node、没浏览器都算失败（GitHub Actions 上这样跑）；不设就跳过并写明。

测三样：
1. 新前端和旧看板逐项对得上（任务卡第 3 节第 6 条）：同一份数据，旧看板（tools/build_dashboard.py）和新前端各用 Chrome 打开，
   五页、页头、图例、页脚、页面顶上的提示，逐个元素比标签、属性和字。数据换成二十几种样子再比：示例数据、仓库里的数据、
   旧看板测试里改坏的各种数据、塞了网页代码的数据。只有几处是有意不同的，写在 IGNORED 里。
2. 旧看板测试里用浏览器点的那些（换页、筛选、展开、跳转、复制、手机宽度、对比度、控件大小、嵌在框里），
   原样对新前端再跑一遍：把它们用的“打开页面”换成打开新前端。三项是旧看板“不跑脚本时”的做法，新前端做不到，跳过并写明（BY_DESIGN）。
3. 新前端自己的：在线版从旁边的 site-data/ 取数据、不向别处发请求；离线版是一个文件；数据文件的写法对不上时说明为什么；
   一页画不出来时别的页照样出。
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

# 页面上要比的几块
PARTS = ["header.top", "nav.pages", "#overview", "#evidence", "#compare", "#gaps", "#non-academic", "#legend", "footer.foot"]

# 一个元素的样子：标签、属性、字。连着的几段字并成一段、空白并成一个空格再比。
# 有意不同、不比的：随页面状态变的几个属性（展开没有、按下没有、是哪一页、标出来的那一处）；
# SVG 的 xmlns（新前端由浏览器按 SVG 的命名空间建元素，不写这个属性）；
# 下载链接的地址（旧看板指向旁边的表格文件，新前端是页面里现做的一份）。
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
    const attrs = [...n.attributes].map(a => a.name)
      .filter(a => !skip.includes(a) && !(a === 'href' && n.id === 'ev-download'))
      .sort()
      .map(a => a + '=' + (a === 'class' ? n.getAttribute(a).split(/\\s+/).filter(c => c && !['active', 'open', 'target'].includes(c)).sort().join(' ') : n.getAttribute(a)));
    out.push('E ' + tag + ' ' + attrs.join(' '));
    for (const c of n.childNodes) walk(c);
    flush();
    out.push('/' + tag);
  };
  if (root) walk(root);
  return out;
}""" % json.dumps(list(IGNORED))


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
                return page

            yield go, page, seen


# ---------------------------------------------------------------- 1. 新旧逐项对得上

def signatures(page):
    out = {part: page.eval_on_selector(part, SIGNATURE) if page.query_selector(part) else None for part in PARTS}
    out["banners"] = page.eval_on_selector_all(".page > .banner", f"bs => bs.map({SIGNATURE})")
    out["title"] = page.title()
    return out


def differences(data):
    """同一份数据，旧看板和新前端的不同之处：[(哪一块, 头几处不同)]。"""
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


def test_new_frontend_matches_the_old_dashboard():
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
    print(f"      新旧对照：{len(PARITY_CASES)} 份数据，每份 {len(PARTS) + 2} 块，都一样")


def test_new_frontend_matches_on_the_repo_data():
    ready()
    assert differences(V.DEFAULT_DATA) == []


def test_new_frontend_matches_when_one_record_cannot_be_shown():
    """旧看板测试里“有一条证据坏到显示不出来”：两边一样占一行、写明原因，问题列在页面顶上。"""
    ready()
    real = B.condition_items

    def broken(e, measure, names):
        if e.get("id") == "EV-000001-002":
            raise RuntimeError("故意弄坏的")
        return real(e, measure, names)

    B.condition_items = broken
    try:
        assert differences(EXAMPLE) == []
    finally:
        B.condition_items = real


def test_the_comparison_itself_catches_differences():
    """比的办法本身要管用：新前端少一个字、多一个属性、换一个链接，都要比出来。"""
    ready()

    def tweak(js):
        return functools.partial(_tweaked, js)

    cases = [
        "document.querySelector('#gaps-count').textContent += '。'",
        "document.querySelector('#EV-000001-001').setAttribute('data-risk', 'x')",
        "document.querySelector('#overview a[href=\"#evidence\"]').setAttribute('href', '#gaps')",
        "document.querySelector('#legend .legend-item').remove()",
        "document.querySelector('#compare svg.chart circle').setAttribute('cy', '1')",
    ]
    for js in cases:
        assert tweak(js)(), f"没比出来：{js}"


def _tweaked(js):
    with tempfile.TemporaryDirectory() as old, built_web(EXAMPLE) as new, browser() as context:
        assert B.build(EXAMPLE, old, version=VERSION, log=lambda *_: None) == 0
        a = context.new_page()
        a.goto("file://" + os.path.join(old, B.PAGE_NAME))
        b = context.new_page()
        b.goto("file://" + new)
        b.wait_for_selector("main .view")
        b.evaluate(js)
        return signatures(a) != signatures(b)


# ---------------------------------------------------------------- 2. 旧看板的浏览器测试，对新前端再跑一遍

# 旧看板“不跑脚本时”的做法：五页摊开、内容照样看得到。新前端是用脚本画出来的，不跑脚本就只有一句“要开着脚本才能看”
# （Yu 2026-11-15 同意）。这四项不整项搬：两项只有一半是不跑脚本的，另一半照抄在下面单独跑，新前端另有一项测这句提示。
BY_DESIGN = {
    "test_browser_without_script_shows_everything": "新前端不跑脚本时只显示一句提示（Yu 2026-11-15 同意）",
    "test_browser_falls_back_when_the_script_fails": "旧看板出错时退回不跑脚本的样子；新前端是哪一页出错哪一页写明，另有一项测",
    "test_browser_compare_view_on_a_narrow_screen_and_without_script": "后半是不跑脚本；前半（手机宽度）另在下面单独跑",
    "test_browser_new_pages_jump_and_link": "后半是不跑脚本；前半（三页的跳转）另在下面单独跑",
}


def _old_browser_tests():
    """旧看板测试里用浏览器打开页面的那些：调用了 opened 的测试函数。"""
    import inspect
    out = []
    for module in (T, T3, T5):
        for name, fn in sorted(vars(module).items()):
            if name.startswith("test_") and callable(fn) and "opened(" in inspect.getsource(fn):
                out.append((module, name, fn))
    return out


def test_old_browser_tests_pass_on_the_new_frontend():
    ready()
    real = T.opened
    T.opened = opened_web
    ran, skipped, failed = [], [], []
    try:
        for module, name, fn in _old_browser_tests():
            if name in BY_DESIGN:
                skipped.append(name)
                continue
            try:
                fn()
                ran.append(name)
            except unittest.SkipTest:
                raise
            except Exception:  # noqa: BLE001
                failed.append(f"{module.__name__}.{name}\n{traceback.format_exc(limit=3)}")
    finally:
        T.opened = real
    assert not failed, "\n".join(failed)
    assert len(ran) + len(skipped) == len(_old_browser_tests()) and len(ran) >= 13, ran
    print(f"      旧看板的浏览器测试 {len(ran)} 项对新前端都通过；有意不搬 {len(skipped)} 项：{'、'.join(skipped)}")


def test_compare_view_on_a_narrow_screen():
    """旧看板那一项的前半：手机宽度上对标视图不用整页左右滑，表格在自己的框里滑。"""
    with opened_web(size=(390, 844)) as (go, page, seen):
        go("compare")
        T.wait_view(page, "compare")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "整页不该左右滑"
        assert page.is_visible("#CMP-000001 svg.chart")
        assert seen["errors"] == []


def test_new_pages_jump_and_link():
    """旧看板那一项的前半：跳到一条陈述、一个来源，点覆盖图的一格跳到证据并展开。"""
    with opened_web() as (go, page, seen):
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
            page.wait_for_selector("#EV-000001-003.open")
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
            page.click("nav.pages a[data-view=evidence]")
            page.click("#ev-expand")
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
        assert len(T.visible_ids(page)) == 13
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
