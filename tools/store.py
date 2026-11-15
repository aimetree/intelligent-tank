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


def put_after(obj, key, value, after):
    """给一条记录设一个字段。已经有就原地改；没有就插在 after 里头一个存在的字段后面，都不在就放最后。
    这样新加的字段落在它该在的位置，文件里别的行不动。"""
    if key in obj:
        obj[key] = value
        return
    anchor = next((k for k in after if k in obj), None)
    if anchor is None:
        obj[key] = value
        return
    items = list(obj.items())
    obj.clear()
    for k, v in items:
        obj[k] = v
        if k == anchor:
            obj[key] = value


TOPIC_FILES = {"comparisons": "comparisons.json", "assessments": "assessments.json", "reports": "reports.json",
               "reviews": "reviews.json"}


def save_topic(ds, topic_id, coll, new_ids=()):
    """把一个题目的可比组、描述、报告登记或复核单写回它的文件。文件里是一个数组：
    原有的记录照原来的次序，new_ids 是这次新加的，接在后面。返回有没有写。

    ds["topic_files"][(题目编号, 类别)] 是 (文件路径, 读进来的编号)；记录就是 ds[类别] 里的那几个对象，直接改它们就行。
    文件里有读不进来的记录（没有编号、编号重复）时不能用它写回：那样会把读不进来的那几条丢掉。调用的人先看 ds["problems"]。
    """
    path, ids = ds["topic_files"].get((topic_id, coll)) or (
        os.path.join(ds["dir"], "public", "topics", topic_id, TOPIC_FILES[coll]), [])
    ids = list(ids) + [i for i in new_ids if i not in ids]
    ds["topic_files"][(topic_id, coll)] = (path, ids)
    return write_json(path, [ds[coll][i] for i in ids])


def append_jsonl(path, record):
    """在日志末尾加一行。两个日志只在末尾加，已有的行不动（V-72）。"""
    lead = ""
    if os.path.exists(path) and os.path.getsize(path):
        with open(path, "rb") as f:
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                lead = "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(lead + json.dumps(record, ensure_ascii=False) + "\n")


def stage(ds, coll, record):
    """把一条新记录先放进内存里的数据，还没有写进文件：后面的校验和编号分配看得到它。
    写进文件用 save_topic（给 new_ids）或 save_sources。"""
    ds[coll][record["id"]] = record


def stage_log(ds, log):
    """工作记录先在内存里加一条，还没有写进文件。写进文件用 append_worklog。"""
    ds["worklog"].append(log)


def append_worklog(ds, log):
    """在工作记录的文件末尾加这一条。"""
    append_jsonl(os.path.join(ds["dir"], "worklog.jsonl"), log)


def has_file(ds, source_id):
    """这个来源是不是从它自己的文件里读进来的（是的话 save_sources 才写得回去）。"""
    return source_id in ds["files"]


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
