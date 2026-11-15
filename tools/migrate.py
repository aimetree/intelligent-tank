#!/usr/bin/env python3
"""数据契约改了之后，把旧的数据文件升到脚本要的规格版本。

用法：
    python3 tools/migrate.py                              只看：数据是哪一版，要走哪几步，会改哪些文件
    python3 tools/migrate.py --write                      照着改，写回数据文件
    python3 tools/migrate.py --data tools/tests/example --write

怎么回事（《开发蓝图》v0.1 第 5 节 B6；规格 1.7）：
- 数据的规格版本记在 data/meta.json 的 spec_version 里；脚本要的版本是 schema 的 $id 末尾那个号。
  两个不一样，校验脚本会报（V-00），看板和导出也会把这一条写在顶上：先跑这个脚本。
- 每改一次 schema，旧数据照新规则过不了的，就在下面的 STEPS 里加一步：从哪一版到哪一版、改了什么、怎么改。
  步子按版本号一步接一步走，不跳。数据的写法没变、只是规格的版本号往上走的，也记一步，apply 什么都不做。
- 改的是数据文件本身（JSON），不经过 validate.load_dataset：旧版的文件照新版的读法可能读不进来。
- 先在一份临时的拷贝上改，改完用现在的校验脚本查一遍，一条问题都没有才写回来；有问题就一个字也不写。
- 只写真的变了的文件，写法和仓库里现有的文件一致（tools/store.py）；没变的文件一个字节都不动。
- 不碰的东西：
  两份日志（changes.jsonl、worklog.jsonl）。它们只在末尾加、已有的行不改（V-72）。
  所以日志的字段只能加可选的；会让旧的行读不进来的改法不许做。
  data/schema/ 和 data/templates/。它们是脚本这一头的：schema 手工改，模板由 tools/make_templates.py 生成。
- 迁移只改写法，不改意思：不新增证据、不改数值、不改核验状态。要改意思的是数据修订，照常走变化记录。

加一步怎么写：
    def _rename_x(files):
        for path, doc in files.each("public/sources/*.json"):   # doc 是整个文件，就地改
            ...
    STEPS 里加一行 Step("0.3", "0.4", "把某某字段改名为某某", _rename_x)
再把 schema 的 $id 改成新的版本号，跑 python3 tools/migrate.py --write（仓库的 data/ 和 tools/tests/example/ 各跑一次），
然后跑 tools/tests/test_migrate.py。

退出码  0 不用迁移，或者迁好了（没加 --write 时是看过了、能迁）；1 迁不了；2 用法或环境不对。
"""
import argparse
import fnmatch
import json
import os
import shutil
import sys
import tempfile
from collections import namedtuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import store  # noqa: E402
import validate as V  # noqa: E402

Step = namedtuple("Step", "source target what apply")   # 从哪一版、到哪一版、改了什么（一句话）、怎么改（拿到 Files，就地改）
SKIPPED_DIRS = ("schema", "templates")                  # 数据目录最上面一层里不算数据的两个目录
META = "meta.json"
SHOWN = 10                                              # 迁完校验不过时，最多列几条问题


class MigrateError(Exception):
    pass


def _nothing_to_change(files):
    """数据的写法没有变。"""


# 每改一次 schema 加一步，接在最后。前一步的 target 就是后一步的 source；最后一步的 target 是 schema 现在的版本。
STEPS = [
    Step("0.2", "0.3", "规格正文补上已经认可的六处做法，并写明版本和迁移的规矩；数据的写法没有变", _nothing_to_change),
]


class Files:
    """一份数据里的 JSON 文件。步子拿到它，按相对路径取文件、就地改；写不写回去由 migrate() 定。"""

    def __init__(self, data_dir):
        self.root, self._text, self.docs = data_dir, {}, {}
        for base, dirs, names in os.walk(data_dir):
            top = os.path.normpath(base) == os.path.normpath(data_dir)
            dirs[:] = sorted(d for d in dirs if not (top and d in SKIPPED_DIRS))
            for name in sorted(names):
                if not name.endswith(".json"):
                    continue
                rel = os.path.relpath(os.path.join(base, name), data_dir).replace(os.sep, "/")
                with open(os.path.join(base, name), encoding="utf-8") as fh:
                    text = fh.read()
                try:
                    self.docs[rel] = json.loads(text)
                except ValueError as exc:
                    raise MigrateError(f"{rel} 读不了，先修好再迁移：{exc}")
                self._text[rel] = text

    def paths(self, pattern="*"):
        """相对路径的清单，照字面排。pattern 用 * 通配，如 public/sources/*.json、public/topics/*/dictionary.json。"""
        return [p for p in sorted(self.docs) if fnmatch.fnmatchcase(p, pattern)]

    def each(self, pattern="*"):
        """[(相对路径, 整个文件的内容)]。内容就地改。"""
        return [(p, self.docs[p]) for p in self.paths(pattern)]

    def changed(self):
        """内容变了的文件。只是排版和仓库的写法不一样的不算。"""
        return [p for p in sorted(self.docs) if store.dumps(self.docs[p]) != store.dumps(json.loads(self._text[p]))]


def plan(have, want, steps):
    """从 have 版到 want 版要走哪几步。走不到的抛 MigrateError，说明为什么。"""
    a, b = V.version_key(have), V.version_key(want)
    if a is None:
        raise MigrateError(f"数据的规格版本写的是 {have!r}，认不出来")
    if b is None:
        raise MigrateError(f"schema 的版本写的是 {want!r}，认不出来")
    if a > b:
        raise MigrateError(f"数据是 {have} 版，比脚本要的 {want} 版新：先把脚本更新到和数据一样的版本")
    chain, at = [], have
    while at != want:
        nxt = [s for s in steps if s.source == at]
        if len(nxt) != 1:
            raise MigrateError(f"从 {at} 版往上没有登记迁移的步子，到不了 {want} 版" if not nxt
                               else f"从 {at} 版往上登记了 {len(nxt)} 步，只能有一步")
        if V.version_key(nxt[0].target) is None or V.version_key(nxt[0].target) <= V.version_key(at):
            raise MigrateError(f"{at} → {nxt[0].target} 这一步不是往上走的")
        if V.version_key(nxt[0].target) > b:
            raise MigrateError(f"{at} → {nxt[0].target} 这一步越过了脚本要的 {want} 版")
        chain.append(nxt[0])
        at = nxt[0].target
    return chain


def migrate(data_dir, write=False, steps=None, schema=None, log=print):
    """把 data_dir 里的数据升到 schema 的版本。返回退出码。steps、schema 不给就用登记的步子和仓库里的 schema。"""
    steps = STEPS if steps is None else steps
    schema = V.load_schema() if schema is None else schema
    want = V.spec_version_of(schema)
    try:
        files = Files(data_dir)
        meta = files.docs.get(META)
        if not isinstance(meta, dict) or not isinstance(meta.get("spec_version"), str):
            raise MigrateError(f"{META} 里没有 spec_version，不知道数据是哪一版")
        have = meta["spec_version"]
        if have == want:
            log(f"数据已经是 {want} 版，不用迁移")
            return 0
        chain = plan(have, want, steps)
        log(f"数据是 {have} 版，脚本要 {want} 版，要走 {len(chain)} 步")
        for i, step in enumerate(chain, 1):
            before = set(files.changed())
            step.apply(files)
            if set(files.docs) != set(files._text):
                raise MigrateError(f"{step.source} → {step.target} 这一步增减了文件；迁移只改已有的文件")
            touched = [p for p in files.changed() if p not in before]
            log(f"  第 {i} 步　{step.source} → {step.target}　{step.what}" + (f"（改了 {len(touched)} 个文件）" if touched else "（数据不用动）"))
        meta["spec_version"] = want
        changed = files.changed()
    except MigrateError as exc:
        log(f"迁不了：{exc}")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        trial = os.path.join(tmp, "data")
        shutil.copytree(data_dir, trial)
        for rel in changed:
            store.write_json(os.path.join(trial, *rel.split("/")), files.docs[rel])
        issues = sorted(set(V.validate(V.load_dataset(trial), schema)), key=lambda x: (x.rule, str(x.record), x.message))
    if issues:
        log(f"迁完之后校验不过，一个字也没有写。共 {len(issues)} 处问题" + (f"，头 {SHOWN} 处：" if len(issues) > SHOWN else "："))
        for it in issues[:SHOWN]:
            log(f"  {it.rule}  {it.record}: {it.message}")
        return 1

    for rel in changed:
        log(f"  {'改' if write else '要改'}　{rel}")
    if not write:
        log(f"看过了，能迁：要改 {len(changed)} 个文件。没有写回，加 --write 才写")
        return 0
    for rel in changed:
        store.write_json(os.path.join(data_dir, *rel.split("/")), files.docs[rel])
    log(f"迁好了：{have} → {want}，写了 {len(changed)} 个文件。提交之前再跑一遍 python3 tools/validate.py")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="把数据文件升到脚本要的规格版本")
    ap.add_argument("--data", default=V.DEFAULT_DATA, help="数据目录，默认是仓库里的 data/")
    ap.add_argument("--schema", default=V.DEFAULT_SCHEMA, help="schema 文件")
    ap.add_argument("--write", action="store_true", help="写回数据文件；不加就只看")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.data):
        print(f"找不到数据目录：{args.data}", file=sys.stderr)
        return 2
    return migrate(args.data, args.write, schema=V.load_schema(args.schema))


if __name__ == "__main__":
    sys.exit(main())
