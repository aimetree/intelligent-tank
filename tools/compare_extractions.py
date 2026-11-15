#!/usr/bin/env python3
"""两遍抽取的比对（方案 5.1 第 2、3 步）。

同一个来源独立抽两遍，各存一个文件；这个脚本把两遍对起来：
  一致      两遍的对象、指标、数值、单位、条件、出处都一样 → double_extraction 记 agree
  图上读数  两遍都读了同一个点 → 记 na（图上读数靠人复读，D-34），两遍的读数并排列出
  不一致    对得上是同一条，但有字段不一样 → 交给人裁定，定下来的那条记 resolved
  只有一遍  另一遍没有抽到 → 也交给人
陈述型只比有没有抽到、出处在不在同一处，转述的措辞不比。
条件里只照抄原文写法、没有解析出值的（文字条件），只比有没有写，不比抄的是哪几个字。

每遍的文件：{"source_id": "SRC-000012", "evidence": [ … ]}，或者直接是证据的列表。
证据照字段规格写，不用带编号、状态这些登记时才有的字段。两遍的文件和报告都是处理时的
中间文件，不进仓库（放 work/ 下面）。

用法
  python3 tools/compare_extractions.py work/extractions/SRC-000012/pass1.json work/extractions/SRC-000012/pass2.json
  python3 tools/compare_extractions.py pass1.json pass2.json --out report.json

报告里 agree、figure_read 两组是第一遍的记录，已经写好 double_extraction，可以直接登记；
mismatch、only_pass1、only_pass2 要人看。退出码  0 比完了；2 用法不对。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store  # noqa: E402
import textmatch as T  # noqa: E402

PLAIN = ("subject_id", "sample_label", "level", "indicator", "fact", "content_kind", "unit_reported",
         "value_qualifier", "uncertainty_kind", "n", "category_value", "evidence_type", "obtained_from")
VALUES = ("range_low", "range_high", "uncertainty")
LOCATOR = ("page", "table", "figure")


def _condition(v):
    """条件的可比写法：解析出了值就比值和单位（数值条件、分类条件、写成规范一句的溶液）；
    只照抄了原文写法、没有解析出值的（测试方法、电极这类文字条件，或“室温”），只比有没有写，
    不比抄的是哪几个字：两遍各自摘的那一小段多半不一样长，不算不一致。
    一遍解析出了值、另一遍没有，或者一遍写了未报告，照样算不一致。"""
    if not isinstance(v, dict):
        return v
    parsed = {k: v[k] for k in ("value", "unit", "low", "high") if k in v}
    return parsed or {"reported": True}


def comparable(rec):
    """一条证据里拿来比的部分。图上读数不比数值。"""
    out = {}
    for f in PLAIN:
        v = rec.get(f) or ("eq" if f == "value_qualifier" else None)
        if v is not None:
            out[f] = v
    if rec.get("obtained_from") != "figure_read":
        if rec.get("value_reported") is not None:
            out["value_reported"] = T.norm(str(rec["value_reported"]))
        for f in VALUES:
            if rec.get(f) is not None:
                out[f] = rec[f]
    for k, v in (rec.get("conditions") or {}).items():
        out["conditions." + k] = _condition(v)
    for f in LOCATOR:
        v = (rec.get("locator") or {}).get(f)
        if v:
            out["locator." + f] = T.norm(str(v))
    if rec.get("questions"):
        out["questions"] = sorted(rec["questions"])
    return out


def differences(a, b):
    return [{"field": k, "pass1": a.get(k), "pass2": b.get(k)} for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]


def _same_item(rec):
    """同一个对象、同一个指标。"""
    who, what = rec.get("sample_label") or rec.get("subject_id"), rec.get("indicator") or rec.get("fact")
    return (who, what, rec.get("content_kind")) if who and what else None


def _same_value(rec):
    """指标和数值一样、对象不一样：多半是数值挂错了样品。"""
    what = rec.get("indicator") or rec.get("fact")
    if not what or rec.get("value_reported") is None or rec.get("obtained_from") == "figure_read":
        return None
    return (what, T.norm(str(rec["value_reported"])), rec.get("unit_reported"))


def compare(pass1, pass2):
    """把两遍对起来。返回报告（见文件头）。"""
    ca, cb = [comparable(r) for r in pass1], [comparable(r) for r in pass2]
    used_a, used_b, pairs = set(), set(), []

    def dump(c):
        return json.dumps(c, sort_keys=True, ensure_ascii=False)

    # 一、完全一致的先配对
    waiting = {}
    for j, c in enumerate(cb):
        waiting.setdefault(dump(c), []).append(j)
    for i, c in enumerate(ca):
        js = waiting.get(dump(c))
        if js:
            j = js.pop(0)
            used_a.add(i)
            used_b.add(j)
            pairs.append((i, j, []))

    # 二、剩下的：同一个对象同一个指标的，差得最少的配成一对；再看是不是数值挂错了对象
    def pair_up(key):
        cands = []
        for i, a in enumerate(pass1):
            if i in used_a or key(a) is None:
                continue
            for j, b in enumerate(pass2):
                if j not in used_b and key(b) == key(a):
                    cands.append((len(differences(ca[i], cb[j])), i, j))
        for _, i, j in sorted(cands):
            if i not in used_a and j not in used_b:
                used_a.add(i)
                used_b.add(j)
                pairs.append((i, j, differences(ca[i], cb[j])))

    pair_up(_same_item)
    pair_up(_same_value)

    report = {"agree": [], "figure_read": [], "mismatch": [], "only_pass1": [], "only_pass2": []}
    for i, j, diff in sorted(pairs):
        a, b = pass1[i], pass2[j]
        if diff:
            report["mismatch"].append({"pass1": a, "pass2": b, "differences": diff})
        elif a.get("obtained_from") == "figure_read":
            report["figure_read"].append({"record": dict(a, double_extraction="na"),
                                          "readings": [a.get("value_reported"), b.get("value_reported")]})
        else:
            report["agree"].append(dict(a, double_extraction="agree"))
    report["only_pass1"] = [r for i, r in enumerate(pass1) if i not in used_a]
    report["only_pass2"] = [r for j, r in enumerate(pass2) if j not in used_b]
    n = {k: len(v) for k, v in report.items()}
    compared = n["agree"] + n["mismatch"] + n["only_pass1"] + n["only_pass2"]
    report["summary"] = dict(n, pass1=len(pass1), pass2=len(pass2),
                             mismatch_rate=round((compared - n["agree"]) / compared, 4) if compared else 0.0)
    return report


def read_pass(path):
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    if isinstance(doc, dict):
        return doc.get("source_id"), doc.get("evidence") or []
    return None, doc


def _name(rec):
    return f"{rec.get('sample_label') or rec.get('subject_id') or '？'} / {rec.get('indicator') or rec.get('fact') or '？'}"


def describe(report):
    """给人看的几行。"""
    s = report["summary"]
    lines = [f"第一遍 {s['pass1']} 条，第二遍 {s['pass2']} 条：一致 {s['agree']}，图上读数 {s['figure_read']}，"
             f"不一致 {s['mismatch']}，只有第一遍有 {s['only_pass1']}，只有第二遍有 {s['only_pass2']}"
             f"｜不一致的比例 {s['mismatch_rate']:.1%}（不算图上读数）"]
    for m in report["mismatch"]:
        what = "；".join(f"{d['field']} 第一遍 {json.dumps(d['pass1'], ensure_ascii=False)}，"
                         f"第二遍 {json.dumps(d['pass2'], ensure_ascii=False)}" for d in m["differences"])
        lines.append(f"不一致  {_name(m['pass1'])}：{what}")
    for key, label in (("only_pass1", "只有第一遍有"), ("only_pass2", "只有第二遍有")):
        for r in report[key]:
            where = (r.get("locator") or {}).get("text", "")
            lines.append(f"{label}  {_name(r)}：{r.get('value_reported') or r.get('category_value') or ''} {where}".rstrip())
    for f in report["figure_read"]:
        lines.append(f"图上读数  {_name(f['record'])}：两遍读的是 {f['readings'][0]} 和 {f['readings'][1]}")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description="两遍抽取的比对")
    ap.add_argument("pass1", help="第一遍抽取的文件")
    ap.add_argument("pass2", help="第二遍抽取的文件")
    ap.add_argument("--out", help="把报告写成 JSON 文件")
    args = ap.parse_args(argv)
    try:
        (sid1, p1), (sid2, p2) = read_pass(args.pass1), read_pass(args.pass2)
    except (OSError, ValueError) as exc:
        print(f"读不了：{exc}", file=sys.stderr)
        return 2
    if sid1 and sid2 and sid1 != sid2:
        print(f"两个文件不是同一个来源：{sid1}、{sid2}", file=sys.stderr)
        return 2
    report = compare(p1, p2)
    if sid1 or sid2:
        report = dict({"source_id": sid1 or sid2}, **report)
    print("\n".join(describe(report)))
    if args.out:
        store.write_json(args.out, report)
        print(f"报告写到了 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
