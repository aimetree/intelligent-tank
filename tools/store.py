#!/usr/bin/env python3
"""读写 data/ 里的文件，给改数据的脚本共用。

写法和仓库里现有的文件一致：JSON，缩进两格，中文不转义，末尾一个换行。
这样脚本写回去之后，没改的地方在 git 里一行都不变。
"""
import datetime
import json
import os


def today():
    return datetime.date.today().isoformat()


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def write_json(path, obj):
    """内容没变就不写。返回有没有写。"""
    text = dumps(obj)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True


def save_sources(ds, source_ids):
    """把这些来源的文件写回去（来源登记、样品登记和证据在同一个文件里）。

    ds 是 validate.load_dataset() 读出来的：ds["files"][来源编号] 是 (路径, 整个文件)，
    ds["sources"]、ds["evidence"] 里的记录就是文件里的那几个对象，直接改它们就行。
    返回写了的来源编号。
    """
    written = []
    for sid in sorted(set(source_ids)):
        path, doc = ds["files"][sid]
        if write_json(path, doc):
            written.append(sid)
    return written
