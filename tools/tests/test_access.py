#!/usr/bin/env python3
"""取数模块（tools/access.py）的测试。

    python3 tools/tests/test_access.py        也可以用 pytest 跑

查三件事：
1. 页面、导出、复核单这些脚本里，没有哪一处自己去翻数据：读数据都走取数模块，新加的脚本也一样。
2. 取数的函数给出的东西对：清单的次序、按题目筛、没有的编号、坏记录、没填题目的记录。
3. 同一份数据，记录不管照什么次序摆，生成的网页、表格文件、复核单、导出的文件都逐字相同。
   以后把数据文件换成数据库，靠的就是这一条：页面只认取数模块给的次序，不认文件里的次序。
示例数据全部虚构。
"""
import contextlib
import copy
import io
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)

import access as A  # noqa: E402
import build_dashboard as B  # noqa: E402
import derive as D  # noqa: E402
import ids as I  # noqa: E402
import report_export as X  # noqa: E402
import review_sheet as R  # noqa: E402
import store  # noqa: E402
import test_dashboard as T  # noqa: E402
import test_step4 as S4  # noqa: E402
import test_step5 as S5  # noqa: E402
import validate as V  # noqa: E402

SCHEMA = V.load_schema()
TOPIC = "TOP-000001"

# 直接读写数据文件的脚本：校验、存储、迁移、分配编号、流水线里的两步，加上取数模块自己。别的脚本都不许自己翻 ds
STORAGE = {"access.py", "validate.py", "store.py", "migrate.py", "ids.py", "machine_check.py", "check_identifiers.py"}
# 自己翻 ds 的写法：ds["…"]、ds.get(…)、ds.items() 这些；self.ds、ctx.ds 也算
DIRECT = re.compile(r"(?<![A-Za-z0-9_])ds\s*\[|(?<![A-Za-z0-9_])ds\.(?:get|items|values|keys|setdefault|pop|update)\(")
BYPASS = ("V.load_dataset(", "V.Lookups(", "validate.load_dataset(", "validate.Lookups(")


def scripts():
    return sorted(f for f in os.listdir(TOOLS) if f.endswith(".py"))


def source_of(name):
    with open(os.path.join(TOOLS, name), encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------- 1. 没有哪个脚本自己去翻数据

def test_every_script_reads_through_access():
    for name in scripts():
        if name in STORAGE:
            continue
        text = source_of(name)
        hits = [f"第 {text[:m.start()].count(chr(10)) + 1} 行 {m.group(0)}" for m in DIRECT.finditer(text)]
        assert not hits, f"{name} 自己去翻数据了，要改成走 tools/access.py：{hits}"
        used = [x for x in BYPASS if x in text]
        assert not used, f"{name} 绕过取数模块直接用了 {used}"


def test_the_list_of_users_is_right():
    """取数模块里写的“哪些脚本要走这里”，和实际用到它的脚本是同一批。"""
    using = {name for name in scripts() if re.search(r"^import access as A\b", source_of(name), re.M)}
    assert using == set(A.USERS), (sorted(using), sorted(A.USERS))
    for name in A.USERS:
        assert name not in STORAGE and "A." in source_of(name)


def test_the_check_itself_catches_direct_access():
    """查的办法本身要管用：这几种写法都认得出来，不相干的认不成。"""
    caught = ['x = ds["sources"]', "ds['evidence'].get(eid)", 'self.ds["reviews"][rid]', 'ctx.ds ["topics"]',
              "for k, v in ds.items():", 'note = ds.get("meta")', "ds.values()"]
    ignored = ['v = conds[key]', 'words[0]', "A.source(ds, sid)", "V.validate(ds, schema)", "kinds.get(x)", 'store.stage(ds, "reviews", sheet)']
    for line in caught:
        assert DIRECT.search(line), line
    for line in ignored:
        assert not DIRECT.search(line), line


# ---------------------------------------------------------------- 2. 取数的函数

def tiny():
    """一份手写的小数据：两个题目，记录故意不照编号的次序放，里头有坏记录和没填题目的记录。"""
    return {
        "dir": "", "problems": ["读不了的文件"], "meta": {"note": "这份数据的说明"}, "files": {}, "topic_files": {},
        "topics": {"TOP-000002": {"id": "TOP-000002"}, "TOP-000001": {"id": "TOP-000001"}},
        "dictionaries": {"TOP-000001": {"indicators": [{"key": "ee", "unit_std": "%"}], "facts": [{"key": "claim"}]}},
        "sources": {"SRC-000002": {"id": "SRC-000002", "parent_id": "SRC-000001"}, "SRC-000001": {"id": "SRC-000001"}},
        "samples": {"SRC-000001": [{"label": "乙"}, {"label": "甲"}]},
        "entities": {"ENT-000001": {"id": "ENT-000001", "name": "示例膜"}},
        "evidence": {
            "EV-000002-001": {"id": "EV-000002-001", "topic_id": "TOP-000002", "source_id": "SRC-000002"},
            "EV-000001-002": {"id": "EV-000001-002", "topic_id": "TOP-000001", "source_id": "SRC-000001", "fact": "claim"},
            "EV-000001-001": {"id": "EV-000001-001", "topic_id": "TOP-000001", "source_id": "SRC-000001", "indicator": "ee"},
            "EV-000003-001": {"id": "EV-000003-001"},
            "EV-000004-001": "坏记录",
        },
        "relations": {"REL-000002": {"id": "REL-000002"}, "REL-000001": {"id": "REL-000001"}},
        "comparisons": {"CMP-000002": {"id": "CMP-000002", "topic_id": "TOP-000001"},
                        "CMP-000001": {"id": "CMP-000001", "topic_id": "TOP-000002"}, "CMP-000003": ["坏记录"]},
        "assessments": {"ASM-000002": {"id": "ASM-000002", "topic_id": "TOP-000001"}, "ASM-000001": {"id": "ASM-000001", "topic_id": "TOP-000001"}},
        "reports": {"RPT-000001": {"id": "RPT-000001", "topic_id": "TOP-000001"}},
        "reviews": {"RVW-000003": {"id": "RVW-000003", "comparison_id": "CMP-000002"},
                    "RVW-000001": {"id": "RVW-000001", "comparison_id": "CMP-000002"},
                    "RVW-000002": {"id": "RVW-000002", "topic_id": "TOP-000001"}, "RVW-000004": 5},
        "changes": [{"id": "CHG-000002"}, {"id": "CHG-000001"}],
        "worklog": [{"id": "LOG-000002"}, {"id": "LOG-000001"}],
    }


ACCESS_CASES = [
    # (说的是什么, 怎么取, 应该得到什么)
    ("题目照编号排", lambda ds: A.topic_ids(ds), ["TOP-000001", "TOP-000002"]),
    ("没有的题目是 None", lambda ds: A.topic(ds, "TOP-000009"), None),
    ("题目的指标字典", lambda ds: A.dictionary(ds, "TOP-000001")["facts"], [{"key": "claim"}]),
    ("没有字典的题目是 None", lambda ds: A.dictionary(ds, "TOP-000002"), None),
    ("来源照编号排", lambda ds: A.source_ids(ds), ["SRC-000001", "SRC-000002"]),
    ("没有的来源是 None", lambda ds: A.source(ds, "SRC-000009"), None),
    ("样品登记照登记的次序，不排", lambda ds: [x["label"] for x in A.samples(ds, "SRC-000001")], ["乙", "甲"]),
    ("没有自己的样品登记是 None", lambda ds: A.samples(ds, "SRC-000002"), None),
    ("实体", lambda ds: A.entity(ds, "ENT-000001")["name"], "示例膜"),
    ("没有的实体是 None", lambda ds: A.entity(ds, "ENT-000009"), None),
    ("证据不筛：全部，照编号排，坏记录也在", lambda ds: A.evidence_ids(ds),
     ["EV-000001-001", "EV-000001-002", "EV-000002-001", "EV-000003-001", "EV-000004-001"]),
    ("证据按题目筛：只有这个题目的", lambda ds: A.evidence_ids(ds, "TOP-000001"), ["EV-000001-001", "EV-000001-002"]),
    ("另一个题目的证据", lambda ds: A.evidence_ids(ds, "TOP-000002"), ["EV-000002-001"]),
    ("给 None 是没填题目的那几条，不是全部，坏记录不在", lambda ds: A.evidence_ids(ds, None), ["EV-000003-001"]),
    ("没有的题目下没有证据", lambda ds: A.evidence_ids(ds, "TOP-000009"), []),
    ("坏记录原样给出，由用的人判断", lambda ds: A.evidence(ds, "EV-000004-001"), "坏记录"),
    ("没有的证据是 None", lambda ds: A.evidence(ds, "EV-000009-001"), None),
    ("可比组不筛", lambda ds: A.comparison_ids(ds), ["CMP-000001", "CMP-000002", "CMP-000003"]),
    ("可比组按题目筛", lambda ds: A.comparison_ids(ds, "TOP-000001"), ["CMP-000002"]),
    ("没有的可比组是 None", lambda ds: A.comparison(ds, "CMP-000009"), None),
    ("陈述按题目筛，照编号排", lambda ds: A.assessment_ids(ds, "TOP-000001"), ["ASM-000001", "ASM-000002"]),
    ("另一个题目没有陈述", lambda ds: A.assessment_ids(ds, "TOP-000002"), []),
    ("没有的陈述是 None", lambda ds: A.assessment(ds, "ASM-000009"), None),
    ("复核单不筛", lambda ds: A.review_ids(ds), ["RVW-000001", "RVW-000002", "RVW-000003", "RVW-000004"]),
    ("一个可比组的复核单", lambda ds: A.review_ids(ds, "CMP-000002"), ["RVW-000001", "RVW-000003"]),
    ("给 None 是不属于任何可比组的复核单", lambda ds: A.review_ids(ds, None), ["RVW-000002"]),
    ("没有复核单的可比组", lambda ds: A.review_ids(ds, "CMP-000001"), []),
    ("没有的复核单是 None", lambda ds: A.review(ds, "RVW-000009"), None),
    ("关系照编号排", lambda ds: A.relation_ids(ds), ["REL-000001", "REL-000002"]),
    ("没有的关系是 None", lambda ds: A.relation(ds, "REL-000009"), None),
    ("报告登记", lambda ds: A.report(ds, "RPT-000001")["topic_id"], "TOP-000001"),
    ("没有的报告是 None", lambda ds: A.report(ds, "RPT-000009"), None),
    ("变化记录照写入的先后，不排", lambda ds: [c["id"] for c in A.changes(ds)], ["CHG-000002", "CHG-000001"]),
    ("工作记录照写入的先后，不排", lambda ds: [w["id"] for w in A.worklog(ds)], ["LOG-000002", "LOG-000001"]),
    ("数据目录的说明", lambda ds: A.note(ds), "这份数据的说明"),
    ("打开时发现的问题", lambda ds: A.problems(ds), ["读不了的文件"]),
    ("有这个编号", lambda ds: A.exists(ds, "evidence", "EV-000001-001"), True),
    ("没有这个编号", lambda ds: A.exists(ds, "comparisons", "CMP-000009"), False),
    ("坏记录的编号也算有", lambda ds: A.exists(ds, "reviews", "RVW-000004"), True),
    ("这条证据的指标定义", lambda ds: A.lookups(ds).measure_of(A.evidence(ds, "EV-000001-001")), ("indicator", {"key": "ee", "unit_std": "%"})),
    ("这条证据的事实项定义", lambda ds: A.lookups(ds).measure_of(A.evidence(ds, "EV-000001-002")), ("fact", {"key": "claim"})),
    ("补充材料没有自己的样品登记，用所属论文的", lambda ds: sorted(A.lookups(ds).register_of("SRC-000002")), ["乙", "甲"]),
]


def test_access_functions():
    for what, get, want in ACCESS_CASES:
        got = get(tiny())
        assert got == want, f"{what}：得到 {got!r}，应该是 {want!r}"


def test_records_are_the_stored_objects():
    """给出的就是数据里的那一个对象，不是拷贝：改数据的脚本改了它，再写回文件（tools/store.py）。"""
    ds = tiny()
    pairs = [(A.topic(ds, "TOP-000001"), ds["topics"]["TOP-000001"]), (A.source(ds, "SRC-000001"), ds["sources"]["SRC-000001"]),
             (A.entity(ds, "ENT-000001"), ds["entities"]["ENT-000001"]), (A.evidence(ds, "EV-000001-001"), ds["evidence"]["EV-000001-001"]),
             (A.comparison(ds, "CMP-000002"), ds["comparisons"]["CMP-000002"]), (A.assessment(ds, "ASM-000001"), ds["assessments"]["ASM-000001"]),
             (A.review(ds, "RVW-000001"), ds["reviews"]["RVW-000001"]), (A.relation(ds, "REL-000001"), ds["relations"]["REL-000001"]),
             (A.report(ds, "RPT-000001"), ds["reports"]["RPT-000001"]), (A.dictionary(ds, "TOP-000001"), ds["dictionaries"]["TOP-000001"]),
             (A.samples(ds, "SRC-000001"), ds["samples"]["SRC-000001"]), (A.changes(ds), ds["changes"]), (A.worklog(ds), ds["worklog"])]
    for got, stored in pairs:
        assert got is stored


def test_edge_cases():
    ds = tiny()
    ds["meta"] = None
    assert A.note(ds) is None, "没有 meta.json 时说明是 None"
    for kind in A.KINDS:
        assert A.exists(ds, kind, "没有这个编号") is False
    for bad in ("worklog", "files", "samples", "没有这一类"):
        try:
            A.exists(ds, bad, "X")
        except ValueError:
            continue
        raise AssertionError(f"{bad} 不是能按编号问的记录类别，应该报错")


def test_load_reads_the_example():
    ds = A.load(T.EXAMPLE)
    assert A.problems(ds) == [] and A.topic_ids(ds) == [TOPIC]
    assert len(A.evidence_ids(ds, TOPIC)) == len(A.evidence_ids(ds)) == 13
    assert [A.evidence(ds, x)["id"] for x in A.evidence_ids(ds)] == A.evidence_ids(ds)
    with tempfile.TemporaryDirectory() as tmp:
        empty = A.load(tmp)
        assert A.topic_ids(empty) == [] and [p.rule for p in A.problems(empty)] == ["V-00"], "空目录：没有题目，问题里写着缺 meta.json"


def test_write_side_helpers():
    """改数据的脚本往内存里放新记录、记工作记录，也不自己翻 ds（tools/store.py）。"""
    with T.example_copy() as data:
        ds = A.load(data)
        sheet = dict(A.review(ds, "RVW-000004"), id="RVW-000009")
        store.stage(ds, "reviews", sheet)
        assert A.review(ds, "RVW-000009") is sheet and A.review_ids(ds)[-1] == "RVW-000009"
        before = len(A.worklog(ds))
        log = {"id": "LOG-000099", "date": "2026-11-14", "step": "review", "actor": "kai", "actor_kind": "human", "topic_id": TOPIC}
        store.stage_log(ds, log)
        assert A.worklog(ds)[-1] is log and len(A.worklog(ds)) == before + 1
        assert len(A.worklog(A.load(data))) == before, "先放在内存里，文件还没动"
        store.append_worklog(ds, log)
        assert A.worklog(A.load(data))[-1] == log, "写进文件之后，重新打开看得到"
        assert store.has_file(ds, "SRC-000001") is True and store.has_file(ds, "SRC-000099") is False


# ---------------------------------------------------------------- 3. 记录怎么摆，生成的东西都一样

COLLECTIONS = ("sources", "samples", "evidence", "entities", "relations", "topics", "dictionaries", "comparisons",
               "assessments", "reports", "reviews")


def rearranged(ds, order):
    """把每一类记录换一个次序摆。记录本身不动；一个来源的样品登记、两份日志的先后是数据的一部分，也不动。"""
    for coll in COLLECTIONS:
        items = order(list(ds[coll].items()))
        ds[coll].clear()
        ds[coll].update(items)
    return ds


def everything(data):
    """这份数据生成的全部东西：网页、表格文件、派生指标、每张复核单给人看的一份和点选题、复核单清单、导出的文件。"""
    def made(ds):
        labels = B.load_labels(data)
        m = B.build_model(ds, SCHEMA, labels, TOPIC, T.VERSION)
        out = {"网页": B.render_page(m, B.read_asset("style.css"), B.read_asset("app.js")), "表格文件": B.evidence_csv(m),
               "派生指标": repr(D.derived_records(ds, TOPIC)), "换算": repr(D.fill_std(ds))}
        ctx = R.Ctx(ds, SCHEMA, labels)
        for rid in A.review_ids(ds):
            out[f"{rid} 给人看的"] = R.render_text(ctx, A.review(ds, rid))
            out[f"{rid} 点选题"] = repr(R.question_pack(ctx, A.review(ds, rid)))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            R.cmd_list(None, ds, SCHEMA, ctx)
        out["复核单清单"] = buf.getvalue()
        files, result, summary = X.build_export(ds, SCHEMA, labels, "RPT-000001", T.VERSION, S5.DRAFT_TEXT, True)
        out.update({f"导出 {name}": text for name, text in files.items()})
        out["导出的检查"] = repr((result, summary))
        return out
    return made


def test_storage_order_does_not_change_anything():
    with S5.report_copy(**S5.READY) as data:
        make = everything(data)
        plain = make(A.load(data))
        assert len(plain["网页"]) > 100000 and len(plain) >= 20, "先确认真的生成了东西"
        orders = {"倒过来": lambda items: items[::-1],
                  "照编号倒排": lambda items: sorted(items, key=lambda kv: kv[0], reverse=True),
                  "前后两半对调": lambda items: items[len(items) // 2:] + items[:len(items) // 2]}
        for name, order in orders.items():
            ds = rearranged(A.load(data), order)
            assert list(ds["evidence"]) != list(A.load(data)["evidence"]), "次序真的换了"
            other = make(ds)
            assert sorted(other) == sorted(plain)
            for key in plain:
                assert other[key] == plain[key], f"记录{name}摆之后，{key} 不一样了"


def test_other_topics_do_not_leak_into_this_one():
    """数据里另有一个题目时，这个题目的网页和表格文件一个字都不变：只用它自己的证据、可比组、陈述、复核单、日志。
    第二个题目的记录是把头一个题目的各抄一份、换了编号和题目。校验先关掉：校验查的是整份数据，这里只看页面取了谁的数据。"""
    def page(ds):
        m = B.build_model(ds, SCHEMA, B.load_labels(T.EXAMPLE), TOPIC, T.VERSION)
        return B.render_page(m, B.read_asset("style.css"), B.read_asset("app.js")), B.evidence_csv(m)

    def second_topic(ds):
        other = "TOP-000002"
        store.stage(ds, "topics", dict(A.topic(ds, TOPIC), id=other))
        ds["dictionaries"][other] = A.dictionary(ds, TOPIC)
        renamed = {}
        for kind, ids, get, prefix in (("comparisons", A.comparison_ids, A.comparison, "CMP-0009"), ("assessments", A.assessment_ids, A.assessment, "ASM-0009"),
                                        ("reviews", A.review_ids, A.review, "RVW-0009"), ("evidence", A.evidence_ids, A.evidence, None)):
            for i, rid in enumerate(ids(ds)):
                rec = get(ds, rid)
                new = f"{prefix}{i:02d}" if prefix else f"{rid[:-3]}9{i % 100:02d}"
                renamed[rid] = new
                store.stage(ds, kind, copy.deepcopy(dict(rec, id=new, topic_id=other)))
        for new in renamed.values():                                   # 抄出来的证据把数值型的条件都放大十倍：漏进来的话，按条件挑的派生指标会变
            for cond in ((ds["evidence"].get(new) or {}).get("conditions") or {}).values():
                if isinstance(cond, dict) and isinstance(cond.get("value"), (int, float)):
                    cond["value"] *= 10
        for kind in ("comparisons", "assessments", "reviews"):        # 抄出来的记录互相指：组指抄出来的证据，陈述和单子指抄出来的组
            for new in renamed.values():
                rec = ds[kind].get(new)
                if rec is None:
                    continue
                if "members" in rec:
                    rec["members"] = [dict(m, evidence_id=renamed.get(m.get("evidence_id"), m.get("evidence_id"))) for m in rec["members"]]
                if "basis" in rec:
                    rec["basis"] = [renamed.get(x, x) for x in rec["basis"]]
                if rec.get("comparison_id"):
                    rec["comparison_id"] = renamed[rec["comparison_id"]]
                if "items" in rec:
                    rec["items"] = [dict(it, target_id=renamed.get(it.get("target_id"), it.get("target_id"))) for it in rec["items"]]
        # 另一个题目里还有一个组、一条陈述，指着的却是头一个题目的证据和组：也不该出现在头一个题目的页面上
        first = A.evidence_ids(ds, TOPIC)[:2]
        store.stage(ds, "comparisons", dict(A.comparison(ds, "CMP-000001"), id="CMP-000990", topic_id=other, tier="insufficient", missing="另一个题目缺的条件",
                                            status="draft", members=[{"evidence_id": x, "role": "member"} for x in first]))
        store.stage(ds, "assessments", dict(A.assessment(ds, A.assessment_ids(ds, TOPIC)[0]), id="ASM-000990", topic_id=other, basis=[first[0], "CMP-000001"]))
        ds["changes"].append({"id": "CHG-000099", "date": "2026-11-13", "topic_id": other, "target_id": renamed["CMP-000001"], "what": "另一个题目的变化"})
        store.stage_log(ds, {"id": "LOG-000099", "date": "2026-11-13", "step": "search", "actor": "claude", "actor_kind": "ai", "topic_id": other,
                             "search": {"where": "另一个题目的检索", "query": "别的", "hits": 999, "screened": 999, "included": 99}})
        return len(renamed)

    real = V.validate
    V.validate = lambda *args, **kwargs: []
    try:
        alone = page(A.load(T.EXAMPLE))
        ds = A.load(T.EXAMPLE)
        added = second_topic(ds)
        assert added >= 20 and A.topic_ids(ds) == [TOPIC, "TOP-000002"] and len(A.evidence_ids(ds, "TOP-000002")) == 13
        both = page(ds)
    finally:
        V.validate = real
    assert both[0] == alone[0], "另一个题目的数据漏进了这个题目的网页"
    assert both[1] == alone[1], "另一个题目的数据漏进了这个题目的表格文件"


def test_applied_answers_are_staged_in_memory():
    """复核人的回答写进内存之后，工作记录里就有了这一条：同一次运行里接着校验、接着分配编号，都看得到它。文件到 save_applied 才写。"""
    with S4.ready_copy() as data:
        ds = A.load(data)
        before = len(A.worklog(ds))
        said, touched, log = R.apply_answers(ds, SCHEMA, "RVW-000003", copy.deepcopy(S4.FULL))
        assert A.worklog(ds)[-1] is log and len(A.worklog(ds)) == before + 1
        assert I.next_ids(ds, "LOG")[0] > log["id"], "下一条工作记录的编号接着往下排，不和这一条撞"
        assert len(A.worklog(A.load(data))) == before, "这时文件还没有写"
        R.save_applied(ds, touched, log)
        assert A.worklog(A.load(data))[-1] == log


def test_drafting_does_not_depend_on_storage_order():
    """起草复核单：已有的单子不管照什么次序摆，起草出来的都一样。"""
    def drafted(ds):
        ctx = R.Ctx(ds, SCHEMA, B.load_labels(T.EXAMPLE))
        out = []
        for cid in A.comparison_ids(ds):
            sheet, why = R.draft_group(ctx, A.comparison(ds, cid), "RVW-000099", "claude", "2026-11-14")
            out.append((cid, sheet, why))
        return repr(out)
    plain = drafted(A.load(T.EXAMPLE))
    assert "RVW-" in plain
    assert drafted(rearranged(A.load(T.EXAMPLE), lambda items: items[::-1])) == plain


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
    print(f"{len(ACCESS_CASES)} 处对错的用例" + ("，结果都和预期的一样" if not failed else ""), "｜失败", failed, "｜跳过", skipped)
    sys.exit(1 if failed else 0)
