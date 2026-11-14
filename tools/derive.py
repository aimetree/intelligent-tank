#!/usr/bin/env python3
"""派生值：由脚本从证据算出来的量。

用法：
    python3 tools/derive.py                          只看：value_std 该是多少、和现在写的一不一样；各派生指标是哪几条
    python3 tools/derive.py --write                  把算出来的 value_std 写回来源文件
    python3 tools/derive.py --source SRC-000012 --write

三种派生值（规格 1.5、3.2.1、3.6）：
1. 标准单位下的值 value_std：原文数值 × 指标字典里这个单位的换算系数。三种里只有这一项写回数据文件（V-23）。
   照原文记、不换算的单位（币种、GW 之类）不算、不写；原文数值的写法认不出的（范围、带单位）不猜，列出来等人处理。
2. 与同文基准之比：证据的 baseline_ref 指向同一来源、同一指标的基准膜那一条，两个标准单位下的值相除。
   不入库，出图出表时现算，页面上标“换算值”。
3. 派生指标：指标字典里 entry 为 derived 的（现在是 IN-16“最高测试电流密度”）。从同一批测试
   （同一来源、同一样品、同一个 series_label）里，derived_from 列的那些指标的证据中，取 derived_from 的条件最大的那一条。不入库。
作废的证据不参加第 2、3 种。

退出码  0 都算得出；1 有算不出、要人处理的；2 用法或环境不对。
"""
import argparse
import os
import sys
from collections import namedtuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import store  # noqa: E402
import validate as V  # noqa: E402

Row = namedtuple("Row", "evidence_id status have want note")  # status：same 一样；filled 补上；changed 改了；cleared 去掉；skipped 不换算；unknown 算不出
AFTER = ("value_qualifier", "unit_reported", "value_reported")   # value_std 写在这几个字段后面


def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) != float("inf")


def std_value(e, measure):
    """这条证据在标准单位下的值：返回 (值或 None, 说明)。说明为空就是算出来了。"""
    if e.get("content_kind") != "numeric":
        return None, "不是数值型"
    unit = e.get("unit_reported")
    entry = V.unit_entry(measure, unit)
    if entry is None:
        return None, f"单位 {unit} 不在指标字典允许的单位里"
    if entry.get("factor") is None:
        return None, "这个单位照原文记，不换算"
    number = V.parse_number(e.get("value_reported"))
    if number is None:
        return None, f"原文数值的写法认不出来：{e.get('value_reported')!r}"
    return float(f"{number * entry['factor']:.12g}"), ""


def comparable_value(e, measure):
    """出图出表用的数。数据里写了 value_std 就用它，没写就现算；这个单位不换算的、算不出的返回 None。"""
    if is_number(e.get("value_std")):
        return float(e["value_std"])
    return std_value(e, measure or {})[0]


def _same(a, b):
    return is_number(a) and abs(a - b) <= 1e-9 * max(1.0, abs(b))


def _put_after(e, key, value):
    """把字段写在它该在的位置（模板里的次序），不是甩在最后。"""
    if key in e:
        e[key] = value
        return
    items = list(e.items())
    at = max((i for i, (k, _) in enumerate(items) if k in AFTER), default=len(items) - 1) + 1
    e.clear()
    e.update(items[:at] + [(key, value)] + items[at:])


def fill_std(ds, sources=None):
    """算每条数值型证据的 value_std，直接改在 ds 里。返回 (各条的结果, 改动了的来源编号)。"""
    lk = V.Lookups(ds)
    rows, touched = [], set()
    for eid in sorted(ds["evidence"]):
        e = ds["evidence"][eid]
        if not isinstance(e, dict) or e.get("content_kind") != "numeric":
            continue
        if sources and e.get("source_id") not in sources:
            continue
        have = e.get("value_std")
        want, note = std_value(e, lk.measure_of(e)[1] or {})
        if want is None:
            if "不换算" in note:
                if have is not None:   # 不换算的单位不该有 value_std（V-23）
                    del e["value_std"]
                    touched.add(e.get("source_id"))
                    rows.append(Row(eid, "cleared", have, None, note))
                else:
                    rows.append(Row(eid, "skipped", None, None, note))
            else:
                rows.append(Row(eid, "unknown", have, None, note))
        elif _same(have, want):
            rows.append(Row(eid, "same", have, want, ""))
        else:
            _put_after(e, "value_std", want)
            touched.add(e.get("source_id"))
            rows.append(Row(eid, "filled" if have is None else "changed", have, want, ""))
    return rows, sorted(x for x in touched if x)


def baseline_ratio(e, ds, lk):
    """与同文基准之比。算得出：{"ratio", "base_id", "value", "base_value"}；算不出：{"ratio": None, "why": 原因}。"""
    def no(why):
        return {"ratio": None, "why": why}

    ref = e.get("baseline_ref")
    if not ref:
        return no("没有写同文基准")
    base = ds["evidence"].get(ref) if isinstance(ref, str) else None
    if not isinstance(base, dict):
        return no(f"同文基准 {ref} 不在证据库里")
    if "void" in (e.get("verification_status"), base.get("verification_status")):
        return no("这一条或它的基准已作废")
    if base.get("source_id") != e.get("source_id") or base.get("indicator") != e.get("indicator") or not e.get("indicator"):
        return no("基准不是同一来源、同一指标的")
    measure = lk.measure_of(e)[1] or {}
    value, base_value = comparable_value(e, measure), comparable_value(base, measure)
    if value is None or base_value is None:
        return no("这一条或它的基准没有标准单位下的值")
    if base_value == 0:
        return no("基准的值是 0")
    return {"ratio": value / base_value, "base_id": ref, "value": value, "base_value": base_value}


def derived_records(ds, topic_id):
    """派生指标的各条：每个派生指标、每一批测试一条。返回 (各条, 没用上的证据和原因)。
    一条里有：indicator 派生指标的键；source_id、subject_id、sample_label、series_label 是哪一批；
    condition 按哪个条件挑的；value、unit 那个条件最大是多少；tested 这一批里这个条件一共有几个不同的值；
    picked 各个指标在那一处的证据编号。"""
    d = ds["dictionaries"].get(topic_id) or {}
    cond_unit = {c.get("key"): c.get("unit_std") for c in d.get("conditions") or [] if isinstance(c, dict)}
    records, unused = [], []
    for ind in d.get("indicators") or []:
        src = ind.get("derived_from") if isinstance(ind, dict) else None
        if not isinstance(src, dict) or ind.get("entry") != "derived":
            continue
        keys, ck = src.get("indicators") or [], src.get("condition")
        batches = {}
        for eid in sorted(ds["evidence"]):
            e = ds["evidence"][eid]
            if not isinstance(e, dict) or e.get("topic_id") != topic_id or e.get("indicator") not in keys:
                continue
            if e.get("verification_status") == "void":
                continue
            cv = (e.get("conditions") or {}).get(ck) if isinstance(e.get("conditions"), dict) else None
            x = cv.get("value") if isinstance(cv, dict) else None
            if not is_number(x):
                unused.append((eid, "这个条件没有解析出的数值"))
            elif not e.get("series_label"):
                unused.append((eid, "没有同批测试标签 series_label，看不出和谁是同一批"))
            else:
                key = (str(e.get("source_id")), str(e.get("sample_label") or e.get("subject_id")), str(e["series_label"]))
                batches.setdefault(key, []).append((x, cv.get("unit") or cond_unit.get(ck), e))
        for key in sorted(batches):
            items = batches[key]
            top = max(x for x, _, _ in items)
            picked, first = {}, None
            for x, unit, e in items:
                if x == top:
                    first = first or (unit, e)
                    picked.setdefault(e["indicator"], e["id"])
            unit, e = first
            records.append({
                "indicator": ind.get("key"), "source_id": e.get("source_id"), "subject_id": e.get("subject_id"),
                "sample_label": e.get("sample_label"), "series_label": e.get("series_label"), "condition": ck,
                "value": top, "unit": unit, "tested": len({x for x, _, _ in items}),
                "picked": {k: picked[k] for k in keys if k in picked},
            })
    return records, unused


STATUS_TEXT = {"same": "一样", "filled": "补上", "changed": "改了", "cleared": "去掉", "skipped": "不换算", "unknown": "算不出"}


def main(argv=None):
    ap = argparse.ArgumentParser(description="派生值：算 value_std（可写回），列出派生指标")
    ap.add_argument("--data", default=V.DEFAULT_DATA, help="数据目录，默认是仓库里的 data/")
    ap.add_argument("--source", nargs="*", default=[], metavar="SRC-编号", help="只算这几个来源的证据")
    ap.add_argument("--write", action="store_true", help="把算出来的 value_std 写回来源文件")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.data):
        print(f"找不到数据目录：{args.data}", file=sys.stderr)
        return 2
    ds = V.load_dataset(args.data)
    rows, touched = fill_std(ds, set(args.source) or None)
    counts = {}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
        if r.status not in ("same", "skipped"):
            was = "没有填" if r.have is None else f"{r.have:g}"
            print(f"{r.evidence_id}  {STATUS_TEXT[r.status]}  原来 {was}" + (f" → {r.want:g}" if r.want is not None else "")
                  + (f"  {r.note}" if r.note else ""))
    print("标准单位下的值：" + ("、".join(f"{STATUS_TEXT[k]} {counts[k]}" for k in STATUS_TEXT if k in counts) or "没有数值型的证据"))
    if touched:
        if args.write:
            store.save_sources(ds, touched)
            print("写回了：" + "、".join(touched))
        else:
            print("没有写回（加 --write 才写）：" + "、".join(touched))
    for tid in sorted(ds["topics"]):
        records, unused = derived_records(ds, tid)
        for r in records:
            where = "｜".join(str(x) for x in (r["source_id"], r["sample_label"] or r["subject_id"], r["series_label"]))
            print(f"派生 {r['indicator']}  {where}  {r['condition']} 最大 {r['value']:g} {r['unit'] or ''}（这一批测了 {r['tested']} 个值）  "
                  + "、".join(f"{k} {v}" for k, v in r["picked"].items()))
        for eid, why in unused:
            print(f"派生时没用上 {eid}：{why}")
    return 1 if counts.get("unknown") else 0


if __name__ == "__main__":
    sys.exit(main())
