#!/usr/bin/env python3
"""迁移脚本（tools/migrate.py）和校验脚本里“规格版本”那一条的测试。

    python3 tools/tests/test_migrate.py        也可以用 pytest 跑

查四件事：
1. 登记的步子连得起来，最后一步到的是 schema 现在的版本；仓库的 data/ 和示例数据都已经是这一版。
2. 数据的版本和脚本要的不一样，校验脚本报得出来，话说得明白该怎么办。
3. 迁移照步子的次序改，只写变了的文件，没变的一个字节都不动，日志不碰。
4. 迁不了的时候（没有路、数据比脚本新、迁完校验不过、文件读不了），一个字也不写。
示例数据全部虚构；这里用的步子多数是为测试编的，登记的那一步另有一项测试。
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
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)

import migrate as M  # noqa: E402
import test_dashboard as T  # noqa: E402
import validate as V  # noqa: E402

SCHEMA = V.load_schema()
NOW = V.spec_version_of(SCHEMA)
SOURCE = "public/sources/SRC-000001.json"
ENTITIES = "public/entities.json"


def schema_at(version):
    """同一份 schema，版本号换成 version。测试里用它当“以后的版本”。"""
    return dict(SCHEMA, **{"$id": f"urn:intelligent-tank:schema:{version}"})


def set_version(data, version):
    T.edit_json(data, "meta.json", lambda doc: doc.update(spec_version=version))


def snapshot(data):
    out = {}
    for base, _, files in os.walk(data):
        for name in files:
            with open(os.path.join(base, name), "rb") as fh:
                out[os.path.relpath(os.path.join(base, name), data).replace(os.sep, "/")] = fh.read()
    return out


def changed_files(before, after):
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


def run(data, steps, version, write=True):
    said = []
    code = M.migrate(data, write, steps, schema_at(version), said.append)
    return code, "\n".join(said)


def version_in(data):
    with open(os.path.join(data, "meta.json"), encoding="utf-8") as fh:
        return json.load(fh)["spec_version"]


# 测试里编的两步：都只改写法，改完数据照样过得了校验
def retitle(files):
    """来源的题名后面加一个记号。"""
    for _, doc in files.each("public/sources/*.json"):
        doc["source"]["title"] = doc["source"]["title"] + "（迁过第一步）"


def rename_entity_note(files):
    """实体的名字后面加一个记号。"""
    for _, doc in files.each(ENTITIES):
        for ent in doc:
            ent["name"] = ent["name"] + "（迁过第二步）"


def nothing(files):
    pass


def breaks_data(files):
    """把一条证据的必填字段删掉：迁完校验过不了。"""
    for _, doc in files.each(SOURCE):
        del doc["evidence"][0]["topic_id"]


def refuses(files):
    raise M.MigrateError("有一条数据这一步迁不了，要人先处理")


def adds_a_file(files):
    files.docs["public/extra.json"] = {}


def touches_log(files):
    """想改日志：Files 里根本没有日志，拿不到。"""
    assert files.paths("*.jsonl") == [] and "worklog.jsonl" not in files.docs and "changes.jsonl" not in files.docs


A, B, C = "7.1", "7.2", "7.3"      # 测试里用的三个假版本号，和真的版本号岔开
TWO_STEPS = [M.Step(A, B, "来源题名加记号", retitle), M.Step(B, C, "实体名字加记号", rename_entity_note)]


# ---------------------------------------------------------------- 1. 登记的步子

def test_registered_steps_form_a_chain_to_the_schema_version():
    assert V.version_key(NOW) is not None, f"schema 的 $id 末尾要是版本号，现在是 {SCHEMA.get('$id')!r}"
    assert M.STEPS, "至少登记了一步"
    for a, b in zip(M.STEPS, M.STEPS[1:]):
        assert a.target == b.source, f"{a.source}→{a.target} 的下一步要从 {a.target} 起，现在是 {b.source}"
    for s in M.STEPS:
        assert V.version_key(s.source) < V.version_key(s.target), f"{s.source}→{s.target} 要往上走"
        assert isinstance(s.what, str) and len(s.what) >= 6 and callable(s.apply), "每一步写明改了什么"
    assert M.STEPS[-1].target == NOW, f"最后一步到的是 {M.STEPS[-1].target}，schema 现在是 {NOW}：改了 schema 的版本号要登记一步"
    assert len({s.source for s in M.STEPS}) == len(M.STEPS), "一个版本往上只有一步"


def test_repo_data_and_example_are_at_the_schema_version():
    for data in (V.DEFAULT_DATA, T.EXAMPLE):
        assert version_in(data) == NOW, f"{data} 是 {version_in(data)} 版，schema 是 {NOW} 版：跑 python3 tools/migrate.py --data {data} --write"
        before = snapshot(data)
        said = []
        assert M.migrate(data, True, log=said.append) == 0 and said == [f"数据已经是 {NOW} 版，不用迁移"]
        assert snapshot(data) == before
    assert f"数据结构_字段规格_v{NOW}.md" in SCHEMA["description"] and f"v{NOW}" in SCHEMA["title"], "schema 的说明里写的规格版本要跟着改"
    assert os.path.exists(os.path.join(V.REPO, "docs", "03_技术与开发", f"数据结构_字段规格_v{NOW}.md")), "这一版的规格正文要在仓库里"


def test_the_registered_step_brings_older_data_up():
    """登记的步子从头走一遍：示例数据倒回最早的那一版，迁到现在的版本，校验通过。"""
    first = M.STEPS[0].source
    with T.example_copy() as data:
        set_version(data, first)
        before = snapshot(data)
        said = []
        assert M.migrate(data, True, log=said.append) == 0, said
        assert version_in(data) == NOW and V.validate(V.load_dataset(data), SCHEMA) == []
        assert changed_files(before, snapshot(data)) == ["meta.json"], "这几步数据的写法都没变，只有版本号变"
        assert said[0] == f"数据是 {first} 版，脚本要 {NOW} 版，要走 {len(M.STEPS)} 步"


# ---------------------------------------------------------------- 2. 校验脚本报版本不一致

VERSION_CASES = [
    # (数据写的版本, 报出来的话里要有的字)
    ("0.1", "数据是旧版的，先跑 python3 tools/migrate.py 把它升上来"),
    ("0.2", "数据是旧版的，先跑 python3 tools/migrate.py 把它升上来"),
    ("99.0", "数据比脚本新，先把脚本更新到和数据一样的版本"),
    ("0.10", "数据比脚本新"),                       # 0.10 比 0.3 新：按数比，不按字面比
    ("v0.3", "这个版本号认不出来"),
    ("最新", "这个版本号认不出来"),
]


def test_validate_reports_a_version_mismatch():
    assert V.validate(V.load_dataset(T.EXAMPLE), SCHEMA) == []
    for have, words in VERSION_CASES:
        if have == NOW:
            continue
        with T.example_copy() as data:
            set_version(data, have)
            issues = V.validate(V.load_dataset(data), SCHEMA)
            assert [(i.rule, i.record) for i in issues] == [("V-00", "meta.json")], (have, issues)
            assert issues[0].message == f"数据的规格版本是 {have}，脚本要的是 {NOW}：" + next(
                full for full in ("数据是旧版的，先跑 python3 tools/migrate.py 把它升上来", "数据比脚本新，先把脚本更新到和数据一样的版本",
                                  "这个版本号认不出来") if words in full), (have, issues[0].message)


def test_version_numbers_compare_as_numbers():
    assert V.version_key("0.10") > V.version_key("0.9") > V.version_key("0.3") and V.version_key("1.0") > V.version_key("0.99")
    for bad in ("", "v0.3", "0.3 ", "0..3", "0.x", None, 0.3, ".3", "3."):
        assert V.version_key(bad) is None, bad
    assert V.spec_version_of({"$id": "urn:intelligent-tank:schema:1.4"}) == "1.4" and V.spec_version_of({}) == ""


def test_mismatch_shows_on_the_dashboard_too():
    """看板顶上也写出来：照旧版数据生成的页面不能悄悄当真。"""
    with T.example_copy() as data:
        set_version(data, "0.1")
        problems = T.Built(data).problems()
        assert any("数据的规格版本是 0.1" in p and "tools/migrate.py" in p for p in problems), problems


# ---------------------------------------------------------------- 3. 迁移怎么改

def test_steps_run_in_order_and_only_changed_files_are_written():
    with T.example_copy() as data:
        set_version(data, A)
        before = snapshot(data)
        code, said = run(data, TWO_STEPS, C)
        after = snapshot(data)
        assert code == 0, said
        sources = sorted(k for k in before if k.startswith("public/sources/"))
        assert changed_files(before, after) == sorted([ENTITIES, "meta.json"] + sources), "只写变了的文件"
        assert version_in(data) == C
        ds = V.load_dataset(data)
        assert all(src["title"].endswith("（迁过第一步）") for src in ds["sources"].values())
        assert all(ent["name"].endswith("（迁过第二步）") for ent in ds["entities"].values())
        assert said.index("第 1 步　7.1 → 7.2　来源题名加记号") < said.index("第 2 步　7.2 → 7.3　实体名字加记号")
        assert f"迁好了：{A} → {C}，写了 {len(sources) + 2} 个文件" in said
        for name in ("changes.jsonl", "worklog.jsonl"):
            assert after[name] == before[name], "日志一个字节都不动"
        for rel in changed_files(before, after):
            text = after[rel].decode("utf-8")
            assert text == json.dumps(json.loads(text), ensure_ascii=False, indent=2) + "\n", f"{rel} 的写法和仓库里一致"
        # 再跑一遍：已经是这一版了，什么都不做
        code, said = run(data, TWO_STEPS, C)
        assert code == 0 and said == f"数据已经是 {C} 版，不用迁移" and snapshot(data) == after


def test_starting_in_the_middle_runs_only_the_remaining_steps():
    with T.example_copy() as data:
        set_version(data, B)
        code, said = run(data, TWO_STEPS, C)
        ds = V.load_dataset(data)
        assert code == 0 and "要走 1 步" in said and "来源题名加记号" not in said
        assert not any(src["title"].endswith("（迁过第一步）") for src in ds["sources"].values()), "前面的步子不重做"
        assert all(ent["name"].endswith("（迁过第二步）") for ent in ds["entities"].values())


def test_without_write_nothing_is_written():
    with T.example_copy() as data:
        set_version(data, A)
        before = snapshot(data)
        code, said = run(data, TWO_STEPS, C, write=False)
        assert code == 0 and snapshot(data) == before, "不加 --write 只看不写"
        assert "要改　meta.json" in said and f"要改　{ENTITIES}" in said and f"要改　{SOURCE}" in said
        assert said.endswith("没有写回，加 --write 才写") and "迁好了" not in said


def test_files_that_did_not_change_keep_their_bytes():
    """没变的文件原样留着，哪怕它的排版和仓库的写法不一样。"""
    with T.example_copy() as data:
        set_version(data, A)
        path = os.path.join(data, "public", "relations.json")
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)          # 挤成一行，没有末尾的换行
        before = snapshot(data)
        code, said = run(data, [M.Step(A, B, "只改版本号的一步", nothing)], B)
        assert code == 0, said
        assert changed_files(before, snapshot(data)) == ["meta.json"]
        assert "（数据不用动）" in said and "写了 1 个文件" in said


def test_schema_and_templates_are_not_data():
    """仓库的 data/ 里有 schema 和空白模板两个目录：它们不是数据，迁移不读也不写。"""
    with tempfile.TemporaryDirectory() as tmp:
        data = os.path.join(tmp, "data")
        shutil.copytree(V.DEFAULT_DATA, data)
        assert os.path.isdir(os.path.join(data, "schema")) and os.path.isdir(os.path.join(data, "templates"))
        files = M.Files(data)
        assert not [p for p in files.paths() if p.startswith(("schema/", "templates/"))]
        assert "meta.json" in files.paths() and "labels.json" in files.paths() and files.paths("public/topics/*/topic.json")
        assert files.paths("*.jsonl") == [], "日志不在里面"
        os.makedirs(os.path.join(data, "public", "schema"))      # 只跳过最上面一层的这两个名字
        with open(os.path.join(data, "public", "schema", "x.json"), "w", encoding="utf-8") as fh:
            fh.write("{}\n")
        assert "public/schema/x.json" in M.Files(data).paths()


def test_a_step_cannot_reach_the_logs():
    with T.example_copy() as data:
        set_version(data, A)
        code, said = run(data, [M.Step(A, B, "想改日志的一步", touches_log)], B)
        assert code == 0, said


# ---------------------------------------------------------------- 4. 迁不了的时候

REFUSED_CASES = [
    # (说的是什么, 数据写的版本, 步子, 脚本要的版本, 说出来的话里要有的字)
    ("数据比脚本新", "7.9", TWO_STEPS, C, "数据是 7.9 版，比脚本要的 7.3 版新：先把脚本更新到和数据一样的版本"),
    ("从数据的版本往上没有步子", "6.0", TWO_STEPS, C, "从 6.0 版往上没有登记迁移的步子，到不了 7.3 版"),
    ("中间断了一步", A, TWO_STEPS[:1], C, "从 7.2 版往上没有登记迁移的步子，到不了 7.3 版"),
    ("一步都没有登记", A, [], B, "从 7.1 版往上没有登记迁移的步子"),
    ("同一个版本登记了两步", A, [M.Step(A, B, "一步", nothing), M.Step(A, C, "又一步", nothing)], C, "从 7.1 版往上登记了 2 步，只能有一步"),
    ("往回走的一步", B, [M.Step(B, A, "往回走", nothing)], C, "7.2 → 7.1 这一步不是往上走的"),
    ("原地不动的一步", B, [M.Step(B, B, "不动", nothing)], C, "7.2 → 7.2 这一步不是往上走的"),
    ("越过了脚本要的版本", A, [M.Step(A, C, "跳过头", nothing)], B, "7.1 → 7.3 这一步越过了脚本要的 7.2 版"),
    ("数据的版本号认不出来", "最新", TWO_STEPS, C, "数据的规格版本写的是 '最新'，认不出来"),
    ("迁完校验不过", A, [M.Step(A, B, "删掉必填字段", breaks_data)], B, "迁完之后校验不过，一个字也没有写"),
    ("步子自己说迁不了", A, [M.Step(A, B, "迁不了的一步", refuses)], B, "迁不了：有一条数据这一步迁不了，要人先处理"),
    ("步子加了文件", A, [M.Step(A, B, "加文件的一步", adds_a_file)], B, "7.1 → 7.2 这一步增减了文件；迁移只改已有的文件"),
]


def test_when_it_cannot_migrate_nothing_is_written():
    for what, have, steps, want, words in REFUSED_CASES:
        with T.example_copy() as data:
            set_version(data, have)
            before = snapshot(data)
            code, said = run(data, steps, want)
            assert code == 1, f"{what}：应该迁不了，退出码是 {code}"
            assert words in said, f"{what}：说的是 {said!r}"
            assert snapshot(data) == before, f"{what}：迁不了的时候一个字也不能写"


def test_validation_failure_names_the_problem():
    with T.example_copy() as data:
        set_version(data, A)
        code, said = run(data, [M.Step(A, B, "删掉必填字段", breaks_data)], B)
        assert code == 1 and "V-20  EV-000001-001:" in said and "topic_id" in said, said


def test_unreadable_or_missing_meta():
    with T.example_copy() as data:
        os.remove(os.path.join(data, "meta.json"))
        before = snapshot(data)
        code, said = run(data, TWO_STEPS, C)
        assert code == 1 and "meta.json 里没有 spec_version，不知道数据是哪一版" in said and snapshot(data) == before
    with T.example_copy() as data:
        T.edit_json(data, "meta.json", lambda doc: doc.pop("spec_version"))
        code, said = run(data, TWO_STEPS, C)
        assert code == 1 and "meta.json 里没有 spec_version" in said
    with T.example_copy() as data:
        set_version(data, A)
        with open(os.path.join(data, "public", "entities.json"), "w", encoding="utf-8") as fh:
            fh.write("[{")
        before = snapshot(data)
        code, said = run(data, TWO_STEPS, C)
        assert code == 1 and "public/entities.json 读不了，先修好再迁移" in said and snapshot(data) == before


def test_command_line():
    with T.example_copy() as data, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        assert M.main(["--data", os.path.join(data, "没有这个目录")]) == 2
        assert M.main(["--data", data]) == 0 and M.main(["--data", data, "--write"]) == 0, "已经是现在的版本"
        set_version(data, M.STEPS[-1].source)
        before = snapshot(data)
        assert M.main(["--data", data]) == 0 and snapshot(data) == before, "不加 --write 不写"
        assert M.main(["--data", data, "--write"]) == 0 and version_in(data) == NOW
        other = os.path.join(data, "schema.json")
        with open(other, "w", encoding="utf-8") as fh:
            json.dump(schema_at("99.0"), fh)
        assert M.main(["--data", data, "--schema", other]) == 1, "要到 99.0 版没有登记的步子"


def test_steps_get_the_parsed_files_in_place():
    """步子拿到的是解析好的文件，就地改；each 的次序照路径的字面。"""
    with T.example_copy() as data:
        files = M.Files(data)
        got = files.each("public/sources/*.json")
        assert [p for p, _ in got] == sorted(p for p, _ in got) and len(got) == 11
        assert all(set(doc) >= {"source", "evidence"} for _, doc in got)
        assert files.changed() == []
        got[0][1]["source"]["title"] += "改"
        assert files.changed() == [got[0][0]]
        original = copy.deepcopy(files.docs[ENTITIES])
        files.docs[ENTITIES].reverse()
        assert ENTITIES in files.changed(), "次序变了也算变了"
        files.docs[ENTITIES][:] = original
        assert ENTITIES not in files.changed()


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
    cases = len(VERSION_CASES) + len(REFUSED_CASES)
    print(f"{cases} 处对错的用例" + ("，结果都和预期的一样" if not failed else ""), "｜失败", failed, "｜跳过", skipped)
    sys.exit(1 if failed else 0)
