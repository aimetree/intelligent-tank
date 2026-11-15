#!/usr/bin/env python3
"""报告这一侧的导出和发出前检查（设计方案 5.4、5.6、6.3 的关口 5；规格第 6 节；D-29、D-33、D-102）。

用法：
    python3 tools/report_export.py cite RPT-000001 --text 正文.md [--write]
        从正文里收集引用到的证据、可比组、描述、关系的编号，和报告登记里列的对一遍。
        加 --write：把登记里的四个清单照正文改好。只改草稿；改完先在内存里跑一遍校验，多出问题就不写。
    python3 tools/report_export.py check RPT-000001 [--text 正文.md]
        发出前检查。先当这份报告已经发出，查对外门槛（V-60 至 V-66）；
        给了正文，再查正文里的编号都在数据和登记里，并把和所引证据对不上的数列出来请人看。
    python3 tools/report_export.py export RPT-000001 [--out 目录] [--csv] [--text 正文.md]
        写出随报告走的几样：附录证据表（只放正文引用到、达到对外门槛的证据）、全部证据的数据文件、
        对标图（只放专业复核过的数）、检查结果。默认写到仓库的 reports/报告编号/。

几条规矩：
- 给对方的每一行都先过 validate.strip_internal()：原文片段、内部备注、风险档、机器核对结果、各个操作人不出去（V-64，D-56）。
- 附录只放正文引用到的证据；全部证据另做成一个数据文件，还没有人工核对的照实带着核验状态（D-102）。
  数据文件默认是 JSON，和报告放在一处（规格 9.1 第 15 项）；加 --csv 另出一份同样内容的表格文件。
- 可见范围不是“可对外”的、来源只能给题录和链接的、作废的，哪个文件都不进（V-63）。
- 对标图只放专业复核过的数，图注写明（D-103）。
- 脚本只查能写成规则的。数值那一项是提示：句子里带小数点、百分号、科学记数或三位以上的数，
  在这句话所引证据的数值、条件、与基准之比和两两之差里找不到的，列出来请人看；它不认识的写法会多报，人来定。
退出码：0 没有问题；1 查出了问题（文件照样写出）；2 用法或数据有误。
"""
import argparse
import csv
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_dashboard as B  # noqa: E402
import access as A  # noqa: E402
import compare_view  # noqa: E402
import derive  # noqa: E402
import store  # noqa: E402
import validate as V  # noqa: E402
from display import QUALIFIER_SIGN, ev_sort_key, fmt_num, s, with_unit  # noqa: E402

ID_RE = {"EV": r"EV-\d{6}-\d{3,}", "CMP": r"CMP-\d{6}", "ASM": r"ASM-\d{6}", "REL": r"REL-\d{6}"}
FIELD = {"EV": "evidence_ids", "CMP": "cmp_ids", "ASM": "asm_ids", "REL": "rel_ids"}
COLL = {"EV": "evidence", "CMP": "comparisons", "ASM": "assessments", "REL": "relations"}
ANY_ID = re.compile(r"(?:EV-\d{6}-\d{3,}|(?:CMP|ASM|REL|SRC|RPT|RVW|ENT|TOP|CHG|LOG)-\d{6})")
EV_RANGE = re.compile(r"EV-(\d{6})-(\d{3,})\s*(?:至|到|~|～|–|—)\s*EV-(\d{6})-(\d{3,})")
DATE = re.compile(r"\d{4}-\d{2}(?:-\d{2})?|(?:19|20)\d{2}\s*年")
NUMBER = re.compile(r"(?<![A-Za-z0-9_.])\d[\d,]*(?:\.\d+)?(?:\s*[×xX]\s*10\s*(?:\^\s*[-−+]?\d+|[⁺⁻]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+))?\s*%?")
# 给对方的一行有哪些列（规格第 6 节）：键、名字
COLUMNS = [
    ("id", "证据编号"), ("subject", "对象"), ("sample_label", "样品名"), ("level", "层级"), ("measure", "指标或事实项"),
    ("value", "数值"), ("value_std", "标准单位下的值"), ("range", "范围或误差"), ("summary", "转述"), ("conditions", "条件"),
    ("evidence_type", "证据类型"), ("obtained_from", "取得方式"), ("flags", "标注"),
    ("source_id", "来源编号"), ("source_type", "来源类别"), ("jurisdiction", "法域"), ("source", "来源"), ("locator", "出处位置"),
    ("obtained_at", "取得日期"), ("last_verified_at", "最近核验日期"), ("verification_status", "核验状态"), ("dispute_note", "分歧"),
    ("scope_note", "适用范围与限制"), ("groups", "所在可比组和档别"), ("questions", "对应的问题"),
]
APPENDIX_COLUMNS = ["id", "subject", "level", "measure", "value", "conditions", "evidence_type", "source", "locator",
                    "verification_status", "groups"]


class ExportError(Exception):
    pass


# ---------------------------------------------------------------- 这份报告用到了什么

def report_of(ds, rid):
    r = A.report(ds, rid)
    if not isinstance(r, dict):
        raise ExportError(f"报告登记里没有 {rid}")
    if not A.exists(ds, "topics", r.get("topic_id")):
        raise ExportError(f"{rid} 的题目 {r.get('topic_id')} 不在数据里")
    return r


def _ids(r, field):
    return [x for x in r.get(field) or [] if isinstance(x, str)] if isinstance(r.get(field), list) else []


def cited(ds, r):
    """这份报告引用到的证据。evidence：全部，照编号排；compared：其中进了对比图表、或者作了描述依据的（要专业已复核）；
    notes：登记里要补的地方。"""
    notes = []
    cmp_ids, compared = _ids(r, "cmp_ids"), set()

    def members(cid):
        c = A.comparison(ds, cid)
        return [m["evidence_id"] for m in (c.get("members") or [] if isinstance(c, dict) else [])
                if isinstance(m, dict) and m.get("role") != "excluded" and isinstance(m.get("evidence_id"), str)]

    for cid in cmp_ids:
        compared |= set(members(cid))
    for aid in _ids(r, "asm_ids"):
        a = A.assessment(ds, aid)
        for x in (a.get("basis") or [] if isinstance(a, dict) else []):
            if A.exists(ds, "evidence", x):
                compared.add(x)
            elif A.exists(ds, "comparisons", x) and x not in cmp_ids:
                notes.append(f"描述 {aid} 的依据里有可比组 {x}，报告登记的 cmp_ids 里没有列它；它的成员这里照样算作引用到的")
                compared |= set(members(x))
    every = sorted(set(_ids(r, "evidence_ids")) | compared, key=ev_sort_key)
    return {"evidence": every, "compared": compared, "notes": notes}


def exportable(e, src):
    """这条证据能不能出现在给对方的文件里（V-63）：返回不能的原因，能就是空的。"""
    if e.get("verification_status") == "void":
        return "已作废"
    if e.get("visibility") != "external":
        return "可见范围不是“可对外”"
    if (src or {}).get("external_use") == "link_only":
        return "来源只能给题录和链接"
    return ""


def meets_threshold(e):
    """对外门槛（D-33）：至少人工已核；存疑的要曾经人工核对过并写明分歧。"""
    st = e.get("verification_status")
    return st in V.VERIFIED or (st == "disputed" and V.is_human(e.get("verified_by")) and bool(e.get("dispute_note")))


# ---------------------------------------------------------------- 给对方的一行

def external_row(r, ds, names):
    """一条证据给对方的那一行。只从去掉内部字段之后的记录里取（V-64）。"""
    e = V.strip_internal(r["e"])
    src = A.source(ds, r["source_id"])
    src = src if isinstance(src, dict) else {}
    _, key, measure, _ = names.measure(e)
    kind = e.get("content_kind")
    value = ""
    if kind == "category":
        value = names.value(key, e.get("category_value"))
    elif kind == "numeric" and e.get("value_reported") not in (None, ""):
        q = e.get("value_qualifier")
        sign = QUALIFIER_SIGN.get(q) if isinstance(q, str) else ""
        sign = names.enum("value_qualifier", q) if sign is None else sign
        value = with_unit((sign + " " if sign else "") + s(e.get("value_reported")), names.unit(e.get("unit_reported")))
    std = ""
    if e.get("value_std") is not None and measure.get("unit_std") and e.get("unit_reported") != measure.get("unit_std"):
        std = with_unit(fmt_num(e["value_std"]), names.unit(measure.get("unit_std")))
    spread = []
    if e.get("range_low") is not None or e.get("range_high") is not None:
        spread.append(f"范围 {fmt_num(e.get('range_low'))}–{fmt_num(e.get('range_high'))}")
    if e.get("uncertainty") is not None:
        label = names.enum("uncertainty_kind", e.get("uncertainty_kind"))
        spread.append(f"± {fmt_num(e['uncertainty'])}" + (f"（{label}）" if label else ""))
    if e.get("n") is not None:
        spread.append(f"n = {fmt_num(e['n'])}")
    fr = e.get("figure_read") if isinstance(e.get("figure_read"), dict) else {}
    flags = [names.flag(k) for k in V.display_flags(e, src)]
    if fr.get("reading_error") is not None:
        flags = [f"{x}（读数误差 ± {fmt_num(fr['reading_error'])}）" if x == names.flag("figure_read") else x for x in flags]
    idents = src.get("identifiers") if isinstance(src.get("identifiers"), dict) else {}
    link = B.doi_url(idents.get("doi")) or B.safe_url(src.get("url")) or ""
    source = "；".join(x for x in (s(src.get("title")), s(src.get("creators")), s(src.get("container")), s(src.get("published")),
                                  s(src.get("version_label")), link) if x)
    # 档别是人定的：只列专业复核过、可以对外的组，AI 预归的不出去（V-43、V-61）
    groups = ["{}（{}）".format(g["id"], "，".join(x for x in (g["tier_label"], g["role_label"]) if x)) for g in r["groups"]
              if (A.comparison(ds, g["id"]) or {}).get("status") == "expert_reviewed"
              and (A.comparison(ds, g["id"]) or {}).get("visibility") == "external"]
    row = {
        "id": r["id"], "subject": r["subject"], "sample_label": r["sample"], "level": r["level_label"], "measure": r["measure"],
        "value": value, "value_std": std, "range": "；".join(spread), "summary": s(e.get("summary")),
        "conditions": "；".join(f"{c['name']} {c['text']}" for c in r["conditions"]),
        "evidence_type": r["type_label"], "obtained_from": r["obtained_from_label"], "flags": "；".join(flags),
        "source_id": r["source_id"], "source_type": r["source_type_label"], "jurisdiction": names.enum("jurisdiction", src.get("jurisdiction")),
        "source": source, "locator": r["locator"], "obtained_at": s(e.get("obtained_at")),
        "last_verified_at": s(e.get("expert_reviewed_at") or e.get("verified_at")), "verification_status": r["status_label"],
        "dispute_note": s(e.get("dispute_note")) if e.get("verification_status") == "disputed" else "",
        "scope_note": s(e.get("scope_note")), "groups": "；".join(groups),
        "questions": "、".join(s(q) for q in e.get("questions") or []) if isinstance(e.get("questions"), list) else "",
    }
    return {k: row[k] for k, _ in COLUMNS}


def markdown_table(rows, columns):
    """一张 Markdown 表。格子里的竖线和换行换掉，不让它把表拆开。"""
    def cell(x):
        return re.sub(r"\s*\n\s*", " ", s(x)).replace("|", "｜") or "—"

    names = dict(COLUMNS)
    lines = ["| " + " | ".join(names[k] for k in columns) + " |", "|" + "|".join(" --- " for _ in columns) + "|"]
    for row in rows:
        merged = dict(row)
        merged["subject"] = row["subject"] + (f"（{row['sample_label']}）" if row["sample_label"] else "")
        merged["value"] = "；".join(x for x in (row["value"] or row["summary"], f"标准单位下 {row['value_std']}" if row["value_std"] else "", row["range"]) if x)
        merged["evidence_type"] = "；".join(x for x in (row["evidence_type"], row["flags"]) if x)
        lines.append("| " + " | ".join(cell(merged[k]) for k in columns) + " |")
    return "\n".join(lines) + "\n"


def csv_text(rows):
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow([name for _, name in COLUMNS])
    for row in rows:
        w.writerow([B.csv_cell(row[k]) for k, _ in COLUMNS])
    return "﻿" + out.getvalue()


# ---------------------------------------------------------------- 正文里的编号和数

def expand_ranges(text, ds):
    """“EV-000001-001 至 EV-000001-004”这种写法：把中间的编号补出来（同一个来源的才认）。"""
    def fill(m):
        if m.group(1) != m.group(3):
            return m.group(0)
        a, b = int(m.group(2)), int(m.group(4))
        ids = [f"EV-{m.group(1)}-{n:03d}" for n in range(min(a, b), max(a, b) + 1)]
        return "、".join(x for x in ids if A.exists(ds, "evidence", x) or x in (ids[0], ids[-1]))
    return EV_RANGE.sub(fill, text)


def ids_in(text):
    """正文里出现的编号：{类别: [编号]}，照头一次出现的次序。"""
    found = {}
    for kind, pattern in ID_RE.items():
        seen = []
        for x in re.findall(r"(?<![A-Za-z0-9-])" + pattern + r"(?![0-9])", text):
            if x not in seen:
                seen.append(x)
        found[kind] = seen
    return found


def compare_ids(ds, r, found):
    """正文里的编号和登记对一遍：返回 (问题, 提示)。"""
    problems, hints = [], []
    use = cited(ds, r)
    listed = {"EV": set(use["evidence"]), "CMP": set(_ids(r, "cmp_ids")), "ASM": set(_ids(r, "asm_ids")), "REL": set(_ids(r, "rel_ids"))}
    for kind, ids in found.items():
        for x in ids:
            if not A.exists(ds, COLL[kind], x):
                problems.append(f"正文里的 {x} 数据里没有")
            elif x not in listed[kind]:
                problems.append(f"正文引用了 {x}，报告登记里没有列（用 cite --write 照正文改登记）")
        own = set(_ids(r, FIELD[kind]))
        for x in sorted(own - set(ids), key=ev_sort_key if kind == "EV" else None):
            hints.append(f"登记里列了 {x}，正文里没有出现")
    return problems, hints


def _decimals(token):
    m = re.search(r"\.(\d+)", token)
    return len(m.group(1)) if m else 0


def allowed_numbers(ds, lk, ids):
    """这句话引的证据里有哪些数：数值、标准单位下的值、范围、误差、条件；与同文基准之比；同一指标的两两之差。"""
    out, by_indicator = [], {}
    for eid in ids:
        e = A.evidence(ds, eid)
        if not isinstance(e, dict):
            continue
        measure = lk.measure_of(e)[1] or {}
        vals = [V.parse_number(e.get("value_reported")), e.get("value_std"), e.get("range_low"), e.get("range_high"), e.get("uncertainty"), e.get("n")]
        for c in (e.get("conditions") or {}).values() if isinstance(e.get("conditions"), dict) else []:
            if isinstance(c, dict):
                vals += [c.get("value"), c.get("low"), c.get("high")]
                vals += [V.parse_number(x) for x in re.findall(r"[-−]?\d+(?:\.\d+)?", s(c.get("reported")))]
        if isinstance(e.get("figure_read"), dict):
            vals.append(e["figure_read"].get("reading_error"))
        ratio = derive.baseline_ratio(e, ds, lk) if e.get("baseline_ref") else None
        if ratio and ratio["ratio"] is not None:
            vals.append(ratio["ratio"])
        out += [float(v) for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
        own = derive.comparable_value(e, measure) if e.get("content_kind") == "numeric" else None
        if own is not None:
            by_indicator.setdefault((e.get("indicator") or e.get("fact"), measure.get("unit_std") or e.get("unit_reported")), []).append(own)
    for vals in by_indicator.values():
        out += [abs(a - b) for i, a in enumerate(vals) for b in vals[i + 1:]]
    return out


def number_hints(text, ds):
    """把对不上的数列出来。返回 (提示, 查了几个数, 没查的小整数几个, 没带编号的句子里的数几个)。"""
    lk = A.lookups(ds)
    hints, checked, small, loose = [], 0, 0, 0
    units = []
    for line in text.splitlines():
        units += [line] if line.lstrip().startswith("|") else re.split(r"[。；;！？!?]", line)
    for unit in units:
        found = ids_in(unit)
        ids = list(found["EV"])
        for cid in found["CMP"]:
            c = A.comparison(ds, cid)
            ids += [m.get("evidence_id") for m in (c.get("members") or [] if isinstance(c, dict) else []) if isinstance(m, dict)]
        for aid in found["ASM"]:
            a = A.assessment(ds, aid)
            for x in (a.get("basis") or [] if isinstance(a, dict) else []):
                c = A.comparison(ds, x)
                ids += [m.get("evidence_id") for m in c.get("members") or [] if isinstance(m, dict)] if isinstance(c, dict) else [x]
        bare = DATE.sub(" ", ANY_ID.sub(" ", unit))
        tokens = [t.strip() for t in NUMBER.findall(bare)]
        if not ids:
            loose += len(tokens)
            continue
        allowed = None
        for token in tokens:
            plain = token.rstrip("%").strip().lstrip("-−")     # 只比大小，不看正负：正文里的短横多半是连接号
            value = V.parse_number(plain)
            if value is None:
                continue
            whole = "." not in plain and "×" not in plain and "x" not in plain.lower() and not token.endswith("%")
            if whole and (value < 100 or 1900 <= value <= 2100):   # 一百以内的整数多半是条数、种数；1900 到 2100 的多半是年份
                small += 1
                continue
            checked += 1
            allowed = allowed_numbers(ds, lk, ids) if allowed is None else allowed
            d = _decimals(plain)
            if not any(round(abs(a), d) == round(value, d) or (a and abs(abs(a) - value) <= 1e-9 * abs(a)) for a in allowed):
                where = "、".join(dict.fromkeys(x for x in ids if isinstance(x, str)))
                hints.append(f"“{token}”在所引证据（{where}）的数值、条件、比值和差值里没有找到：{' '.join(unit.split())[:120]}")
    return hints, checked, small, loose


# ---------------------------------------------------------------- 发出前检查

def check(ds, schema, rid, text=None, version=None):
    """发出前检查。返回 {"problems": [...], "hints": [...], "notes": [...]}；problems 空着才算通过。"""
    r = report_of(ds, rid)
    out = {"problems": [], "hints": [], "notes": []}
    before = set(V.validate(ds, schema))
    for it in sorted(before, key=lambda x: (x.rule, s(x.record), x.message))[:20]:
        out["problems"].append(f"{it.rule}　{s(it.record)}：{it.message}")
    if len(before) > 20:
        out["problems"].append(f"数据本身另有 {len(before) - 20} 处没通过校验，见 python3 tools/validate.py")
    status = r.get("status")
    try:
        r["status"] = "issued"     # 只在内存里当它已经发出，查完就改回去
        after = set(V.validate(ds, schema))
    finally:
        if status is None:
            r.pop("status", None)
        else:
            r["status"] = status
    for it in sorted(after - before, key=lambda x: (x.rule, s(x.record), x.message)):
        out["problems"].append(f"{it.rule}　{s(it.record)}：{it.message}")
    use = cited(ds, r)
    out["notes"] += use["notes"]
    if not use["evidence"] and not _ids(r, "rel_ids"):
        out["notes"].append("报告登记里还没有列引用到的证据（evidence_ids、cmp_ids、asm_ids）")
    if version and r.get("data_version") and r["data_version"] != version:
        out["notes"].append(f"报告登记的数据版本是 {r['data_version']}，现在的数据是 {version}")
    if text is not None:
        text = expand_ranges(text, ds)
        problems, hints = compare_ids(ds, r, ids_in(text))
        out["problems"] += problems
        out["hints"] += hints
        numbers, checked, small, loose = number_hints(text, ds)
        out["hints"] += numbers
        out["notes"].append(f"数值：带编号的句子里查了 {checked} 个数，对不上的 {len(numbers)} 个；另有 {small} 个整数没有查"
                            f"（一百以内的多半是条数、种数，1900 到 2100 的多半是年份），{loose} 个数所在的句子没有带编号、没法查")
    return out


def check_text(rid, result):
    lines = [f"{rid} 发出前检查：" + ("没有查出问题" if not result["problems"] else f"查出 {len(result['problems'])} 处问题")]
    lines += [f"问题　{x}" for x in result["problems"]]
    lines += [f"请人看　{x}" for x in result["hints"]]
    lines += [f"说明　{x}" for x in result["notes"]]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 导出

def chart_files(ds, m, r):
    """报告用的对标图：只出专业复核过的组，图里只放专业复核过的成员（D-103）。返回 ({文件名: 内容}, 说明)。"""
    names, topic_id = m["names"], m["topic_id"]
    topic = A.topic(ds, topic_id) or {}
    lk, by_id = A.lookups(ds), {row["id"]: row for row in m["rows"]}
    d = A.dictionary(ds, topic_id) or {}
    rules = {x.get("key"): x for x in d.get("rules") or [] if isinstance(x, dict)}
    questions = {q.get("key"): q.get("text") for q in topic.get("questions") or [] if isinstance(q, dict)}
    files, notes = {}, []
    for cid in _ids(r, "cmp_ids"):
        c = A.comparison(ds, cid)
        if not isinstance(c, dict):
            continue
        if c.get("status") != "expert_reviewed":
            notes.append(f"{cid} 还没有专业复核，没有出图")
            continue
        keep, left = [], []
        for mem in c.get("members") or []:
            e = A.evidence(ds, mem.get("evidence_id")) if isinstance(mem, dict) else None
            if not isinstance(e, dict) or mem.get("role") == "excluded":
                continue
            ok = e.get("verification_status") == "expert_reviewed" and not exportable(e, A.source(ds, e.get("source_id")))
            (keep if ok else left).append(mem)
        g = compare_view.group_model(dict(c, members=keep), by_id, ds, lk, names, rules, questions, B.stamp(m))
        if not g["chart"]:
            notes.append(f"{cid} 画不出图" + (f"：{g['skipped'][0][1]}" if g["skipped"] else ""))
            continue
        svg = re.sub(r"<a\b[^>]*>|</a>", "", s(g["chart"]))   # 看板里点了能跳到证据的链接，单独的图里用不上
        files[f"charts/{cid}.svg"] = '<?xml version="1.0" encoding="UTF-8"?>\n' + svg
        notes.append(f"charts/{cid}.svg　{g['caption']}｜图中的数都经过专业复核"
                     + (f"｜没有放进图的成员 {len(left)} 条（还没有专业复核，或不可对外）：{'、'.join(x['evidence_id'] for x in left)}" if left else ""))
    return files, notes


def build_export(ds, schema, labels, rid, version, text=None, with_csv=False):
    """导出的全部内容：{文件名: 文字}，和检查的结果。不写盘。"""
    r = report_of(ds, rid)
    m = B.build_model(ds, schema, labels, r["topic_id"], version)
    names = m["names"]
    result = check(ds, schema, rid, text, version)
    use = cited(ds, r)
    by_id = {row["id"]: row for row in m["rows"]}
    appendix, held = [], []
    for eid in use["evidence"]:
        row = by_id.get(eid)
        if not row or row["error"]:
            held.append((eid, "数据里没有这一条，或者这一条显示不出来"))
            continue
        why = exportable(row["e"], A.source(ds, row["source_id"])) or ("" if meets_threshold(row["e"]) else "没到对外门槛（至少人工已核）")
        if not why and eid in use["compared"] and row["status"] != "expert_reviewed":
            why = "进了对比或作了描述的依据，还没有专业复核"
        if why:
            held.append((eid, why))
        else:
            appendix.append(external_row(row, ds, names))
    everything, left = [], {}
    for row in m["rows"]:
        why = "显示不出来" if row["error"] else exportable(row["e"], A.source(ds, row["source_id"]))
        if why:
            left[why] = left.get(why, 0) + 1
        else:
            everything.append(external_row(row, ds, names))
    head = {"report": rid, "title": s(r.get("title")), "topic": {"id": m["topic_id"], "title": m["title"]},
            "cutoff_date": m["cutoff"], "data_version": version,
            "note": "只留内部的字段（原文片段、内部备注、风险档、机器核对结果、操作人）已经去掉。还没有人工核对的证据照实带着核验状态。",
            "columns": [{"key": k, "name": n} for k, n in COLUMNS]}
    files = {
        "appendix-evidence.json": store.dumps(dict(head, scope="正文引用到、达到对外门槛的证据", evidence=appendix)),
        "appendix-evidence.md": (f"附录　证据表\n\n报告 {rid}｜{B.stamp(m)}｜正文引用到的证据 {len(appendix)} 条。"
                                 f"全部证据见随报告给的数据文件 evidence-data.json。\n\n" + markdown_table(appendix, APPENDIX_COLUMNS)),
        "evidence-data.json": store.dumps(dict(head, scope="这个题目可以对外的全部证据", evidence=everything)),
    }
    if with_csv:
        files["evidence-data.csv"] = csv_text(everything)
    charts, chart_notes = chart_files(ds, m, r)
    files.update(charts)
    summary = [f"附录证据表 {len(appendix)} 条（appendix-evidence.md、appendix-evidence.json）",
               f"全部证据的数据文件 {len(everything)} 条（evidence-data.json" + ("、evidence-data.csv）" if with_csv else "）")]
    summary += [f"没有进数据文件的 {n} 条：{why}" for why, n in sorted(left.items())]
    summary += [f"引用到、没有进附录的 {eid}：{why}" for eid, why in held]
    summary += chart_notes
    summary.append(f"报告登记里要写：data_version = {version}；evidence_file = reports/{rid}/evidence-data.json")
    files["check.txt"] = check_text(rid, result) + "\n" + "\n".join(f"导出　{x}" for x in summary) + "\n"
    return files, result, summary


# ---------------------------------------------------------------- 命令行

def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError as exc:
        raise ExportError(f"读不了正文文件 {path}：{exc}")


def cmd_cite(args, ds, schema):
    r = report_of(ds, args.report)
    found = ids_in(expand_ranges(_read(args.text), ds))
    changed = False
    base = ("evidence_file", "file", "skill_version", "dictionary_version", "data_version", "status")
    after = {"EV": base, "REL": ("evidence_ids",) + base, "CMP": ("rel_ids", "evidence_ids") + base,
             "ASM": ("cmp_ids", "rel_ids", "evidence_ids") + base}     # 四个清单在登记里的次序照模板：证据、关系、可比组、描述
    for kind in ("EV", "REL", "CMP", "ASM"):
        have, want = _ids(r, FIELD[kind]), found[kind]
        missing = [x for x in want if not A.exists(ds, COLL[kind], x)]
        want = sorted((x for x in want if x not in missing), key=ev_sort_key if kind == "EV" else None)
        add, drop = [x for x in want if x not in have], [x for x in have if x not in want]
        print(f"{FIELD[kind]}：正文里 {len(want)} 个" + (f"，要加 {'、'.join(add)}" if add else "") + (f"，要去掉 {'、'.join(drop)}" if drop else "")
              + ("，和登记一样" if not add and not drop else ""))
        for x in missing:
            print(f"  正文里的 {x} 数据里没有，不写进登记")
        if (add or drop) and args.write:
            if want:
                store.put_after(r, FIELD[kind], want, after[kind])
            else:
                r.pop(FIELD[kind], None)
            changed = True
    if not args.write:
        return 0
    if not changed:
        print("登记不用改")
        return 0
    if r.get("status") != "draft":
        raise ExportError(f"{args.report} 不是草稿，登记不由脚本改")
    if A.problems(ds):
        raise ExportError("数据里有读不了的文件或重复的编号，先修好再写")
    issues = V.validate(ds, schema)
    if issues:
        raise ExportError("改完之后校验不过，没有写：" + "；".join(f"{i.rule} {s(i.record)} {i.message}" for i in issues[:5]))
    store.save_topic(ds, r["topic_id"], "reports")
    print(f"写回了 {args.report} 的登记")
    return 0


def cmd_check(args, ds, schema):
    result = check(ds, schema, args.report, _read(args.text) if args.text else None, args.version or B.data_version(args.data))
    sys.stdout.write(check_text(args.report, result))
    return 1 if result["problems"] else 0


def cmd_export(args, ds, schema):
    version = args.version or B.data_version(args.data) or "没有版本号（不在 git 仓库里）"
    files, result, summary = build_export(ds, schema, B.load_labels(args.data), args.report, version,
                                          _read(args.text) if args.text else None, args.csv)
    out = args.out or os.path.join(V.REPO, "reports", args.report)
    for name in sorted(files):
        path = os.path.join(out, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        B.write_text(path, files[name])
    print(f"写到 {out}：" + "、".join(sorted(files)))
    for x in summary:
        print(x)
    sys.stdout.write(check_text(args.report, result))
    return 1 if result["problems"] else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="报告这一侧的导出和发出前检查")
    ap.add_argument("--data", default=V.DEFAULT_DATA, help="数据目录，默认是仓库里的 data/")
    ap.add_argument("--version", help="数据版本；不写就用 git 的提交号")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("cite", help="从正文收集引用到的编号，和报告登记对一遍")
    p.add_argument("report", metavar="RPT-编号")
    p.add_argument("--text", required=True, help="报告正文（Markdown 或纯文字）")
    p.add_argument("--write", action="store_true", help="把登记里的四个清单照正文改好（只改草稿）")
    p = sub.add_parser("check", help="发出前检查")
    p.add_argument("report", metavar="RPT-编号")
    p.add_argument("--text", help="报告正文；给了就再查编号和数值")
    p = sub.add_parser("export", help="写出附录证据表、全部证据的数据文件、对标图和检查结果")
    p.add_argument("report", metavar="RPT-编号")
    p.add_argument("--out", help="写到哪个目录，默认是仓库的 reports/报告编号/")
    p.add_argument("--csv", action="store_true", help="数据文件另出一份表格文件")
    p.add_argument("--text", help="报告正文；给了就把编号和数值的检查也写进 check.txt")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.data):
        print(f"找不到数据目录：{args.data}", file=sys.stderr)
        return 2
    ds, schema = A.load(args.data), V.load_schema()
    try:
        return {"cite": cmd_cite, "check": cmd_check, "export": cmd_export}[args.cmd](args, ds, schema)
    except ExportError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
