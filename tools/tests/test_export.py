#!/usr/bin/env python3
"""导出给网页前端的数据文件（tools/export_site_data.py）的测试。直接运行：python3 tools/tests/test_export.py"""
import json
import os
import re
import sys
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import access as A  # noqa: E402
import build_dashboard as B  # noqa: E402
import export_site_data as X  # noqa: E402
import site_views as S  # noqa: E402
import validate as V  # noqa: E402
from htmlgen import Raw, el  # noqa: E402

EXAMPLE = os.path.join(HERE, "example")
FILES = {"meta.json", "topics.json", "sources.json", "entities.json", "evidence.json", "comparisons.json",
         "relations.json", "logs.json", "labels.json", "views.json"}


def test_internal_export_has_everything():
    files, ds = X.export(EXAMPLE), V.load_dataset(EXAMPLE)
    assert set(files) == FILES
    assert [e["id"] for e in files["evidence.json"]] == sorted(ds["evidence"])
    assert files["evidence.json"] == [ds["evidence"][i] for i in sorted(ds["evidence"])]
    assert [s["source"]["id"] for s in files["sources.json"]] == sorted(ds["sources"])
    c = files["meta.json"]["counts"]
    assert (c["evidence"], c["sources"], c["entities"]) == (len(ds["evidence"]), len(ds["sources"]), len(ds["entities"]))
    assert files["meta.json"]["audience"] == "internal" and files["meta.json"]["format"] == X.FORMAT
    assert files["meta.json"]["files"] == sorted(FILES)


def test_external_export_drops_internal_things():
    files, ds = X.export(EXAMPLE, "external"), V.load_dataset(EXAMPLE)
    ev = files["evidence.json"]
    assert ev, "示例数据里有可对外、已核的证据"
    for e in ev:
        assert not (set(e) & set(V.INTERNAL_ONLY)), e["id"]
        full = ds["evidence"][e["id"]]
        assert full["visibility"] == "external" and full["verification_status"] in X.OUTSIDE_OK
    want = sorted(i for i, e in ds["evidence"].items()
                  if e.get("visibility") == "external" and e.get("verification_status") in X.OUTSIDE_OK)
    assert [e["id"] for e in ev] == want
    assert files["comparisons.json"]["reviews"] == [] and files["logs.json"]["worklog"] == []
    assert "views.json" not in files and files["meta.json"]["files"] == sorted(FILES - {"views.json"}), "对外的导出里没有五页的内容"
    assert all(x.get("visibility") == "external" for x in files["entities.json"] + files["relations.json"])
    text = json.dumps(files, ensure_ascii=False)
    for e in ds["evidence"].values():
        if e.get("snippet") and len(e["snippet"]) > 12:
            assert e["snippet"] not in text, "原文片段不能出现在对外的导出里"


def test_same_input_same_bytes_and_bad_audience():
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        for d in (a, b):
            assert X.main(["--data", EXAMPLE, "--out", d]) == 0
        for name in FILES:
            assert open(os.path.join(a, name), "rb").read() == open(os.path.join(b, name), "rb").read(), name
    try:
        X.export(EXAMPLE, "client")
    except ValueError:
        pass
    else:
        raise AssertionError("不认识的 audience 要报错")
    assert X.main(["--data", "/no/such/dir", "--out", "/tmp/x"]) == 2


# ---------------------------------------------------------------- views.json（tools/site_views.py）

def _walk(x, seen):
    """把 views.json 里的 {"$row": 编号}、{"$html": ...} 都找出来。"""
    if isinstance(x, dict):
        if set(x) == {"$row"}:
            seen["rows"].append(x["$row"])
            return
        if "$html" in x:
            seen["html"].append(x["$html"])
            return
        for v in x.values():
            _walk(v, seen)
    elif isinstance(x, list):
        for v in x:
            _walk(v, seen)


def _to_html(nodes):
    """把节点拼回 HTML，好和看板原来写的比。"""
    out = []
    for n in nodes:
        if isinstance(n, str):
            out.append(n)
        else:
            out.append(el(n["t"], n.get("a"), Raw(_to_html(n.get("c", [])))))
    return "".join(out)


def test_views_carry_what_the_dashboard_computes():
    ds = A.load(EXAMPLE)
    views = X.export(EXAMPLE)["views.json"]
    assert views["format"] == S.FORMAT and [v["key"] for v in views["views"]] == [v[0] for v in B.VIEWS]
    assert [t["topic_id"] for t in views["topics"]] == A.topic_ids(ds)
    t = views["topics"][0]
    m = B.build_model(ds, V.load_schema(), B.load_labels(EXAMPLE), t["topic_id"], t["version"])
    # 每一行原样带着，只少了原始记录 e；元组变成数组
    assert [r["id"] for r in t["rows"]] == [r["id"] for r in m["rows"]]
    for got, row in zip(t["rows"], m["rows"]):
        assert "e" not in got
        got = dict(got)
        x = got.pop("x")
        assert got == json.loads(json.dumps({k: v for k, v in row.items() if k != "e"})), row["id"]
        assert set(x) == {"num", "unit", "mark"}
    by = {r["id"]: r for r in t["rows"]}
    assert by["EV-000001-001"]["x"] == {"num": 85.6, "unit": "%", "mark": [14, 18]}   # 片段 “X-1 98.1 87.3 85.6”
    assert by["EV-000001-001"]["snippet"][14:18] == "85.6"
    assert by["EV-000003-001"]["x"]["num"] is None or isinstance(by["EV-000003-001"]["x"]["num"], float)
    assert t["csv"] == B.evidence_csv(m) and t["stamp"] == B.stamp(m)
    for key in ("compare", "overview", "gaps", "nonacademic"):
        assert t[key] is not None, key
    # 页面模型里别处用到的行都写成编号，个个对得上
    seen = {"rows": [], "html": []}
    for key in ("filters", "compare", "overview", "gaps", "nonacademic"):
        _walk(t[key], seen)
    ids = {r["id"] for r in t["rows"]}
    assert seen["rows"] and set(seen["rows"]) <= ids
    assert seen["html"], "图和最近的变化里有 HTML 片段"
    text = json.dumps(t, ensure_ascii=False)
    assert '"e": {' not in text


def test_html_fragments_round_trip_exactly():
    """拆成节点的 HTML 片段，拼回去和看板原来写的一字不差。"""
    ds = A.load(EXAMPLE)
    m = B.build_model(ds, V.load_schema(), B.load_labels(EXAMPLE), A.topic_ids(ds)[0], "x")
    raws = [g["chart"] for lv in m["compare"]["levels"] for g in lv["groups"] if g["chart"]]
    raws += [s["chart"] for lv in m["compare"]["levels"] for s in lv["series"]]
    raws += [B.sprite()] + [x for _, _, text in m["overview"]["recent"] for x in text if isinstance(x, Raw)]
    assert len(raws) >= 5
    for raw in raws:
        nodes = S.to_json(raw, {})["$html"]
        # 证据类型的记号写成了 <circle .../> 这样自己关上的；拼回去是 <circle ...></circle>，意思一样
        assert _to_html(nodes) == re.sub(r"<(\w+)([^<>]*)/>", r"<\1\2></\1>", raw), raw[:80]
    assert S.html_nodes('<svg viewBox="0 0 1 1" preserveAspectRatio="none"></svg>')[0]["a"] == {"viewBox": "0 0 1 1", "preserveAspectRatio": "none"}
    assert S.html_nodes("<p>a &lt;b&gt; &amp; c</p>") == [{"t": "p", "c": ["a <b> & c"]}]
    for bad in ("<div><span></div>", "<div>"):
        try:
            S.html_nodes(bad)
        except ValueError:
            continue
        raise AssertionError(f"没关上的标签要报错：{bad}")


def test_snippet_mark_only_when_sure():
    assert S.snippet_mark("X-1 98.1 87.3 85.6", "85.6") == [14, 18]
    assert S.snippet_mark("EE 85.6 % and 85.6 %", "85.6") is None, "出现两次不猜"
    assert S.snippet_mark("X-1 185.6", "85.6") is None, "185.6 里的 85.6 不算"
    assert S.snippet_mark("X-185.6", "85.6") is None
    assert S.snippet_mark("ＥＥ 85.6", "85.6") is None, "片段要规范化才对得上的，不给位置"
    assert S.snippet_mark("", "1") is None and S.snippet_mark("a 1", None) is None


def test_to_json_refuses_what_it_cannot_write():
    assert S.to_json({"a": (1, 2), "b": {3, 1}}, {}) == {"a": [1, 2], "b": [1, 3]}
    assert S.to_json({frozenset(("y", "x")): 1}, {}) == {"$pairs": [[["x", "y"], 1]]}
    row = {"id": "EV-1"}
    assert S.to_json({"r": row, "l": [row]}, {id(row): "EV-1"}) == {"r": {"$row": "EV-1"}, "l": [{"$row": "EV-1"}]}
    for bad in ({1: "a"}, object(), {"x": b"bytes"}):
        try:
            S.to_json(bad, {})
        except TypeError:
            continue
        raise AssertionError(f"写不成 JSON 的要报错：{bad!r}")


def test_field_titles_follow_the_schema():
    schema = V.load_schema()
    f = S.field_titles(schema)
    names = B.Names({}, None, schema)
    assert f["evidence"]["snippet"] == names.field("evidence", "snippet")
    assert f["review"]["items.decision"] == names.field("review", "items", "decision")
    assert f["review"]["batch.decision"] == names.field("review", "batch", "decision")


def test_views_are_written_compact_and_without_unused_parts():
    import site_views
    files = X.export(EXAMPLE, version="v")
    text = site_views.dumps(files["views.json"])
    assert "\n" not in text.rstrip("\n") and ": " not in text[:200], "views.json 不缩进"
    assert json.loads(text) == files["views.json"] and text == site_views.dumps(X.export(EXAMPLE, version="v")["views.json"])
    cmp = files["views.json"]["topics"][0]["compare"]
    assert all("chart" not in g for lv in cmp["levels"] for g in lv["groups"])
    assert all("chart" not in s and s["lines"] for lv in cmp["levels"] for s in lv["series"])
    assert all("rows" not in b and "sources" not in b for b in files["views.json"]["topics"][0]["nonacademic"]["blocks"])
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, os.path.join(os.path.dirname(HERE), "export_site_data.py"), "--data", EXAMPLE, "--out", tmp, "--version", "v"],
                       check=True, capture_output=True)
        with open(os.path.join(tmp, "views.json"), encoding="utf-8") as fh:
            assert fh.read() == text


def test_required_jurisdictions_come_from_the_topic_card():
    """法域表里必查的列：题目卡写了“必查的法域”就照它，没写照 D-96 的四个（Yu 2026-11-15 定）。"""
    import test_dashboard as T
    na = X.export(EXAMPLE, version="v")["views.json"]["topics"][0]["nonacademic"]
    assert na["cols"] == ["中国", "英国", "欧盟", "美国", "国际组织和多国"] and na["cols_need"] == [True, True, True, True, False]
    assert any(g["key"] == "jurisdiction" and "英国" in g["text"] for g in na["gaps"])
    with T.example_copy() as data:
        T.edit_json(data, "public/topics/TOP-000001/topic.json", lambda t: t.update(jurisdictions=["cn", "intl", "other"]))
        na = X.export(data, version="v")["views.json"]["topics"][0]["nonacademic"]
    assert na["cols"] == ["中国", "欧盟", "美国", "国际组织和多国", "其他"], "英国不必查、又没有来源，不列；欧盟、美国有来源照列"
    assert na["cols_need"] == [True, False, False, True, True] and na["cols_empty"] == [False, False, False, False, True]
    gap = next(g for g in na["gaps"] if g["key"] == "jurisdiction")
    assert gap["text"] == "还没有来源的法域：其他。"


def test_views_survive_broken_pages():
    """哪一页的数据坏到算不出来：这一页是 null，原因记在 errors 里，别的照出（和旧看板一样）。"""
    real = B.gaps_view.build
    B.gaps_view.build = lambda *a: (_ for _ in ()).throw(RuntimeError("故意弄坏的"))
    try:
        t = X.export(EXAMPLE)["views.json"]["topics"][0]
    finally:
        B.gaps_view.build = real
    assert t["gaps"] is None and t["errors"] == [["数据概览与缺口", "RuntimeError: 故意弄坏的"]]
    assert t["overview"] and t["compare"] and t["nonacademic"]


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("通过 ", name)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print("失败 ", name, repr(exc)[:300])
    print(f"导出数据文件的测试 ｜失败 {failed}")
    sys.exit(1 if failed else 0)
