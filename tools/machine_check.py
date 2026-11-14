#!/usr/bin/env python3
"""机器核对（方案 5.1 第 4 步；规格 3.6 的 machine_check）和风险档预填（方案 5.6，D-80）。

对每条待核或机器已核的证据查三样，写进 machine_check：
  identifier  它的来源的标识通过了解析（来源的 id_check，由 tools/check_identifiers.py 写）
  snippet     原文片段在来源文本里逐字找得到（有条件的片段也一起查）
  value_unit  数值在片段里；片段里数值后面紧跟着单位的，和记录的单位一致。
              分类型、陈述型没有数值可核，写 na；图上读数的 snippet、value_unit 都写 na
都过了的，状态从待核改成机器已核；原来是机器已核、现在没过的，退回待核。
人工已核及以上的证据不动。然后按字段推出风险理由，预填风险档（人工核对之前要标好）。

来源文本不进仓库（规格 9.1 第 6 项）：处理时放在本机的一个目录里，一份来源一个文件，
文件名是来源编号，如 work/texts/SRC-000012.txt（.txt 或 .md）。没有文本的来源，片段没法查，
这条证据不写结果，留在待核。

用法
  python3 tools/machine_check.py --texts work/texts                 只看结果，不改文件
  python3 tools/machine_check.py --texts work/texts --write         写回 data/
  python3 tools/machine_check.py --texts work/texts --source SRC-000012 --write

退出码  0 都通过；1 有没通过的或没法查的；2 用法不对。
"""
import argparse
import json
import os
import sys
from collections import Counter, namedtuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store  # noqa: E402
import textmatch as T  # noqa: E402
import validate as V  # noqa: E402

OPEN = ("pending", "machine_checked")     # 只动这两种状态的证据
CHECKS = ("identifier", "snippet", "value_unit")
MANUAL_REASONS = {"outlier", "other"}     # 脚本推不出来、由人或 Claude 标的风险理由，重跑时留着
REASON_ORDER = list(V.RISK_REASON_TIER) + ["other"]

Row = namedtuple("Row", "id outcome notes status tier")


def load_text(texts_dir, source_id):
    for ext in (".txt", ".md"):
        path = os.path.join(texts_dir, source_id + ext)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
    return None


def check_one(e, source, measure, text, at):
    """查一条证据。返回 (machine_check, 说明)；没有来源文本、片段没法查时 machine_check 是 None。"""
    notes = []
    ident = "pass" if (source.get("id_check") or {}).get("result") == "pass" else "fail"
    if ident == "fail":
        notes.append("来源的标识还没有通过解析（id_check）")
    if e.get("obtained_from") == "figure_read":
        return {"identifier": ident, "snippet": "na", "value_unit": "na", "at": at}, notes
    if text is None:
        return None, ["没有这个来源的文本，片段没法查"]
    snip = "pass"
    for field, name in (("snippet", "原文片段"), ("conditions_snippet", "条件的片段")):
        if field == "snippet" and not e.get(field):
            snip = "fail"
            notes.append("没有原文片段")
        elif e.get(field):
            found, how = T.find_snippet(e[field], text)
            if not found:
                snip = "fail"
                notes.append(f"{name}：{how}")
    if e.get("content_kind") == "numeric":
        units = [u.get("unit") for u in (measure or {}).get("units_accepted", [])]
        vu, how = T.check_value_unit(e.get("value_reported") or "", e.get("unit_reported") or "", units,
                                     e.get("snippet") or "")
        if vu == "fail" or "没法核" in how:
            notes.append(how)
    else:
        vu = "na"
    return {"identifier": ident, "snippet": snip, "value_unit": vu, "at": at}, notes


def fill_risk(lk, e, at, by):
    """按字段推出风险理由，预填或更新风险档。脚本推得出的理由每次重算；人标的（离群、其他）留着。"""
    old = e.get("risk") or {}
    kept = set(old.get("reasons") or []) & MANUAL_REASONS
    reasons = lk.derive_risk(e) | kept
    rank = V.TIER_RANK[V.risk_floor(reasons)]
    if "other" in kept:   # “其他”不限档，沿用原来标的档
        rank = max(rank, V.TIER_RANK.get(old.get("tier"), 0))
    tier = next(k for k, v in V.TIER_RANK.items() if v == rank)
    if old and old.get("tier") == tier and set(old.get("reasons") or []) == reasons:
        return
    risk = {"tier": tier, "reasons": sorted(reasons, key=REASON_ORDER.index)}
    if old.get("note"):
        risk["note"] = old["note"]
    risk.update(set_by=by, set_at=at)
    e["risk"] = risk


def run(ds, texts_dir, at, sources=None, risk_by="script"):
    """查 ds 里待核和机器已核的证据，结果直接改在 ds 上。返回 (逐条的结果, 改动了的来源编号)。"""
    lk = V.Lookups(ds)
    rows, touched = [], set()
    for i in sorted(ds["evidence"]):
        e = ds["evidence"][i]
        sid = e.get("source_id")
        if (sources and sid not in sources) or e.get("verification_status") not in OPEN:
            continue
        before = json.dumps(e, sort_keys=True, ensure_ascii=False)
        mc, notes = check_one(e, ds["sources"].get(sid) or {}, lk.measure_of(e)[1], load_text(texts_dir, sid), at)
        if mc is None:
            outcome = "no_text"
        else:
            old = e.get("machine_check") or {}
            if all(old.get(k) == mc[k] for k in CHECKS):
                mc["at"] = old.get("at", at)   # 结果没变，日期不动
            e["machine_check"] = mc
            ok = V.machine_check_ok(e)
            if ok and e["verification_status"] == "pending":
                e["verification_status"] = "machine_checked"
            elif not ok and e["verification_status"] == "machine_checked":
                e["verification_status"] = "pending"
            outcome = "pass" if ok else "fail"
        fill_risk(lk, e, at, risk_by)
        if json.dumps(e, sort_keys=True, ensure_ascii=False) != before:
            touched.add(sid)
        rows.append(Row(i, outcome, notes, e["verification_status"], e["risk"]["tier"]))
    return rows, touched


def summary(rows):
    n = Counter(r.outcome for r in rows)
    tiers = Counter(r.tier for r in rows)
    return (f"证据 {len(rows)} 条：通过 {n['pass']}，没通过 {n['fail']}，没有来源文本 {n['no_text']}"
            f"｜风险档 高 {tiers['high']}、中 {tiers['medium']}、低 {tiers['low']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="机器核对和风险档预填")
    ap.add_argument("--texts", required=True, help="放来源文本的目录，文件名是来源编号（.txt 或 .md）")
    ap.add_argument("--data", default=V.DEFAULT_DATA, help="数据目录，默认是仓库里的 data/")
    ap.add_argument("--source", nargs="*", default=[], metavar="SRC-编号", help="只查这些来源")
    ap.add_argument("--write", action="store_true", help="把结果写回 data/；不加只看结果")
    ap.add_argument("--date", default=store.today(), help="检查日期，默认今天")
    ap.add_argument("--risk-by", default="script", help="风险档的 set_by，默认 script")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.data) or not os.path.isdir(args.texts):
        print(f"找不到目录：{args.data if not os.path.isdir(args.data) else args.texts}", file=sys.stderr)
        return 2
    ds = V.load_dataset(args.data)
    unknown = [s for s in args.source if s not in ds["sources"]]
    if unknown:
        print(f"没有这些来源：{'、'.join(unknown)}", file=sys.stderr)
        return 2
    rows, touched = run(ds, args.texts, args.date, set(args.source), args.risk_by)
    for r in rows:
        if r.outcome != "pass" or r.notes:
            mark = {"pass": "通过", "fail": "没通过", "no_text": "没法查"}[r.outcome]
            print(f"{mark}  {r.id}: {'；'.join(r.notes)}")
    print(summary(rows))
    if args.write:
        written = store.save_sources(ds, touched)
        print(f"写回了 {len(written)} 个来源文件" + (f"：{'、'.join(written)}" if written else ""))
    elif touched:
        print(f"有 {len(touched)} 个来源文件会改动；没有写回（加 --write 才写）")
    return 1 if any(r.outcome != "pass" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
