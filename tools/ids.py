#!/usr/bin/env python3
"""分配编号（规格 1.4）：取现有最大号加一，一经分配不复用。

用法
  python3 tools/ids.py SRC                           下一个来源编号
  python3 tools/ids.py EV --source SRC-000012        这个来源的下一个证据编号
  python3 tools/ids.py EV --source SRC-000012 --count 20
  python3 tools/ids.py LOG --data tools/tests/example

种类：TOP SRC ENT EV REL CMP ASM CHG LOG RPT RVW。每行输出一个编号。

记录不删除（作废的证据、并掉的实体都留着），所以最大号加一不会用到分过的号。
两个对话同时各分一个号会撞：撞了的话文件名或编号重复，校验脚本的 V-01 会报出来。
"""
import argparse
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate as V  # noqa: E402

COLLECTIONS = {"TOP": "topics", "SRC": "sources", "ENT": "entities", "REL": "relations", "CMP": "comparisons",
               "ASM": "assessments", "RPT": "reports", "RVW": "reviews"}
LOGS = {"CHG": "changes", "LOG": "worklog"}
KINDS = sorted(list(COLLECTIONS) + list(LOGS) + ["EV"])


def used_numbers(ds, kind, source_id=None):
    """这一类已经用掉的序号。"""
    if kind == "EV":
        prefix = "EV-" + source_id.split("-")[1] + "-"
        return [int(i[len(prefix):]) for i in ds["evidence"] if i.startswith(prefix) and i[len(prefix):].isdigit()]
    if kind in COLLECTIONS:
        ids = list(ds[COLLECTIONS[kind]])
        # 读不了的文件、没有题目卡的目录不在 ds 里，但号已经占了：按文件名、目录名再数一遍
        if kind == "SRC":
            ids += [os.path.splitext(os.path.basename(p))[0]
                    for p in glob.glob(os.path.join(ds["dir"], "public", "sources", "*.json"))]
        if kind == "TOP":
            ids += [os.path.basename(os.path.normpath(p))
                    for p in glob.glob(os.path.join(ds["dir"], "public", "topics", "*", ""))]
    else:
        ids = [r.get("id") for r in ds[LOGS[kind]] if isinstance(r, dict)]
    out = []
    for i in ids:
        m = re.match(rf"^{kind}-(\d{{6}})$", i) if isinstance(i, str) else None
        if m:
            out.append(int(m.group(1)))
    return out


def next_ids(ds, kind, count=1, source_id=None):
    """接下来的 count 个编号。证据编号要给来源编号（来源还没建文件也可以，从 001 起）。"""
    if kind not in KINDS:
        raise ValueError(f"不认识的种类 {kind!r}，应为 {'、'.join(KINDS)}")
    if count < 1:
        raise ValueError("count 至少是 1")
    if kind == "EV":
        if not (isinstance(source_id, str) and re.match(V.ID_PATTERNS["SRC"], source_id)):
            raise ValueError("证据编号要给来源编号，如 --source SRC-000012")
        start = max(used_numbers(ds, kind, source_id), default=0) + 1
        seq = source_id.split("-")[1]
        return [f"EV-{seq}-{n:03d}" for n in range(start, start + count)]
    start = max(used_numbers(ds, kind), default=0) + 1
    return [f"{kind}-{n:06d}" for n in range(start, start + count)]


def main(argv=None):
    ap = argparse.ArgumentParser(description="分配下一个编号")
    ap.add_argument("kind", choices=KINDS, help="编号的种类")
    ap.add_argument("--source", metavar="SRC-编号", help="证据编号所属的来源")
    ap.add_argument("--count", type=int, default=1, help="要几个，默认 1")
    ap.add_argument("--data", default=V.DEFAULT_DATA, help="数据目录，默认是仓库里的 data/")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.data):
        print(f"找不到数据目录：{args.data}", file=sys.stderr)
        return 2
    try:
        ids = next_ids(V.load_dataset(args.data), args.kind, args.count, args.source)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    print("\n".join(ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())
