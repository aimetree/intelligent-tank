#!/usr/bin/env python3
"""导出给网页前端的数据文件（tools/export_site_data.py）的测试。直接运行：python3 tools/tests/test_export.py"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import export_site_data as X  # noqa: E402
import validate as V  # noqa: E402

EXAMPLE = os.path.join(HERE, "example")
FILES = {"meta.json", "topics.json", "sources.json", "entities.json", "evidence.json", "comparisons.json",
         "relations.json", "logs.json", "labels.json"}


def test_internal_export_has_everything():
    files, ds = X.export(EXAMPLE), V.load_dataset(EXAMPLE)
    assert set(files) == FILES
    assert [e["id"] for e in files["evidence.json"]] == sorted(ds["evidence"])
    assert files["evidence.json"] == [ds["evidence"][i] for i in sorted(ds["evidence"])]
    assert [s["source"]["id"] for s in files["sources.json"]] == sorted(ds["sources"])
    c = files["meta.json"]["counts"]
    assert (c["evidence"], c["sources"], c["entities"]) == (len(ds["evidence"]), len(ds["sources"]), len(ds["entities"]))
    assert files["meta.json"]["audience"] == "internal" and files["meta.json"]["format"] == X.FORMAT


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
