#!/usr/bin/env python3
"""从 data/ 生成对内看板：一个只读的静态网页，加一份证据表的表格文件。

用法：
    python3 tools/build_dashboard.py                    读仓库里的 data/，写到 site/
    python3 tools/build_dashboard.py --data tools/tests/example --out /tmp/site --version 示例

做法（设计方案 4.4、4.5，D-30）：
- 不建数据库和服务。读 data/ 里的数据文件，写出 site/index.html 和 site/evidence-internal.csv。
- 网页是一个文件，样式和脚本都写在里面，打开时不向任何地方发请求。
  五个页面是这个文件里的五块，用网址里 # 后面的名字切换：#overview、#evidence、#compare、#gaps、#non-academic；
  # 后面写一条证据的编号（#EV-000001-001）就直接跳到那条证据并展开。
- 页面只读。要改数据就改数据文件，再重新生成。
- 同一个数据版本（提交号）生成的文件逐字节相同：不写生成时间，所有清单都排好序。
- 题目、指标、条件、取值的名字都从题目卡、指标字典和 labels.json 取，这里不写死任何一个指标（D-03）。
- 来源里抄来的文字（题名、原文片段等）写进页面之前一律转义；网址只认 http 和 https。

五页都做了：总览（overview_view.py）、证据表（这个文件）、对标视图（compare_view.py）、
数据概览与缺口（gaps_view.py）、非学术来源（nonacademic_view.py）。哪一页的数据坏到生成不了，别的页面照样出，原因写在页面顶上。
表格文件含原文片段、风险档这些只留内部的字段，是内部用的；给对方的证据表由 tools/report_export.py 出。
"""
import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import access as A  # noqa: E402
import compare_view  # noqa: E402
import gaps_view  # noqa: E402
import nonacademic_view  # noqa: E402
import overview_view  # noqa: E402
import validate as V  # noqa: E402
from display import (MARKS, MARK_UNKNOWN, NONE, NOT_FILLED, QUALIFIER_SIGN, TIER_HANDLING, Names, as_text, cls,  # noqa: E402
                     doi_url, ev_sort_key, fmt_num, mark, safe_url, s, tok, with_unit)
from htmlgen import Raw, el  # noqa: E402

ASSETS = os.path.join(HERE, "dashboard")
DEFAULT_OUT = os.path.join(V.REPO, "site")
PAGE_NAME = "index.html"
CSV_NAME = "evidence-internal.csv"

# 浏览器按这一条拦住页面的一切对外请求（设计方案 4.4 第 15 项）：除了写在页面里的样式和脚本，什么都不许加载、不许连
CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"

# 五个页面（设计方案 4.2）：网址里的名字、页面编号、名称、回答什么问题
VIEWS = [
    ("overview", "K1", "总览", "这个题目做到什么程度，哪里有问题。"),
    ("evidence", "K2", "证据表", "每条数据从哪来、条件是什么、核过没有。"),
    ("compare", "K3", "对标视图", "同层级、同条件下谁和谁能比。"),
    ("gaps", "K5", "数据概览与缺口", "每组数据说了什么，缺什么。"),
    ("non-academic", "K9", "非学术来源", "专利、政策法规和标准、产业和市场的数字、科研资助，同一页各占一块。"),
]
# 证据表以外的四页各由一个脚本整理和写出：页面的名字 → (整理好的数据放在哪个键下面, 脚本)
PAGES = {"overview": ("overview", overview_view), "compare": ("compare", compare_view),
         "gaps": ("gaps", gaps_view), "non-academic": ("nonacademic", nonacademic_view)}


# ---------------------------------------------------------------- 反查

class Refs:
    """反查：一条证据在哪些可比组里、被哪些数据概览引用、有过哪些变化记录；一个来源有没有更正声明。"""

    def __init__(self, ds, topic_id):
        self.groups, self.asm_direct, self.asm_via, self.changes, self.corrected_by = {}, {}, {}, {}, {}
        members_of = {}
        for cid in A.comparison_ids(ds, topic_id):
            c = A.comparison(ds, cid)
            members_of[cid] = []
            for m in c.get("members") or []:
                if isinstance(m, dict) and isinstance(m.get("evidence_id"), str):
                    self.groups.setdefault(m["evidence_id"], []).append((c, m))
                    members_of[cid].append(m["evidence_id"])
        for aid in A.assessment_ids(ds, topic_id):
            a = A.assessment(ds, aid)
            basis = [b for b in a.get("basis") or [] if isinstance(b, str)]
            for b in basis:
                if b in members_of:
                    for eid in members_of[b]:
                        if eid not in basis and (aid, b) not in self.asm_via.get(eid, []):
                            self.asm_via.setdefault(eid, []).append((aid, b))
                elif aid not in self.asm_direct.get(b, []):
                    self.asm_direct.setdefault(b, []).append(aid)
        for c in A.changes(ds):
            if isinstance(c, dict) and isinstance(c.get("target_id"), str):
                self.changes.setdefault(c["target_id"], []).append(c)
        for sid in A.source_ids(ds):
            src = A.source(ds, sid)
            if isinstance(src, dict) and isinstance(src.get("corrects"), str):
                self.corrected_by.setdefault(src["corrects"], []).append(sid)


# ---------------------------------------------------------------- 一条证据要显示的内容

def blank_row(eid):
    return {
        "id": eid, "e": {}, "error": "",
        "subject_id": "", "subject": "", "subject_flag": False, "sample": "",
        "level": "", "level_label": "",
        "measure_kind": None, "measure_key": "", "measure": "", "measure_flag": False,
        "value": "", "value_flag": False, "value_notes": [],
        "conditions": [],
        "type": "", "type_label": "", "flags": [],
        "status": "", "status_label": "",
        "groups": [],
        "risk": {"tier": "", "label": "", "reasons": [], "note": "", "set_by": "", "set_at": ""},
        "visibility": "", "visibility_label": "", "client_code": "",
        "source_id": "", "source_type": "", "source_type_label": "", "source_title": "", "source_rows": [],
        "locator": "", "obtained_from_label": "",
        "snippet": "", "cond_snippet": "", "cond_locator": "", "figure_read": [],
        "history": [], "asm_direct": [], "asm_via": [], "extra": [],
        "f": {k: NONE for k in ("level", "status", "type", "srctype", "vis", "risk", "subject", "measure", "source")},
        "tiers": [NONE],
    }


def locator_text(loc, names):
    if not isinstance(loc, dict):
        return s(loc)
    if loc.get("text"):
        return s(loc["text"])
    return "，".join(f"{names.field('locator', k)} {s(loc[k])}" for k in ("page", "table", "figure", "section", "item")
                    if loc.get(k))


def condition_items(e, measure, names):
    """测试条件，按指标字典里条件的次序排。原文没写的照实显示“未报告”，必填的没有填也标出来。"""
    conds = e.get("conditions") if isinstance(e.get("conditions"), dict) else {}
    keys = list(conds)
    keys += [k for k in measure.get("required_conditions") or [] if isinstance(k, str) and k not in conds]
    items = []
    for key in sorted(keys, key=lambda k: (names.cond_order.get(k, 10 ** 6), s(k))):
        item = {"key": s(key), "name": names.condition(key), "text": "", "state": "reported", "parsed": ""}
        if key not in conds:
            item.update(text=NOT_FILLED, state="absent")
        else:
            v = conds[key]
            if isinstance(v, dict):
                item["text"] = s(v.get("reported"))
                if isinstance(v.get("low"), (int, float)) or isinstance(v.get("high"), (int, float)):
                    span = f"{fmt_num(v.get('low'))}–{fmt_num(v.get('high'))}"
                    item["parsed"] = with_unit(span, names.unit(v.get("unit")))
                elif isinstance(v.get("value"), (int, float)) and not isinstance(v.get("value"), bool):
                    item["parsed"] = with_unit(fmt_num(v["value"]), names.unit(v.get("unit")))
                elif isinstance(v.get("value"), str):
                    item["parsed"] = names.value(key, v["value"])
            elif v in ("not_reported", "not_applicable"):
                item.update(text=names.enum("condition_missing", v), state=v)
            else:
                item["text"] = as_text(v)
        items.append(item)
    return items


def value_parts(e, key, measure, names):
    """数值一栏：返回 (主要的一行, 下面的小字)。数值照原文写法，不改；标准单位下的值另起一行。"""
    kind, notes = e.get("content_kind"), []
    if kind == "category":
        main = names.value(key, e.get("category_value"))
    elif kind == "statement":
        main = s(e.get("summary"))
    else:
        q = e.get("value_qualifier")
        sign = QUALIFIER_SIGN.get(q) if isinstance(q, str) else ""
        if sign is None:
            sign = names.enum("value_qualifier", q)
        reported = s(e.get("value_reported"))
        main = with_unit((sign + " " if sign else "") + reported, names.unit(e.get("unit_reported"))) if reported else ""
        std_unit = measure.get("unit_std")
        if e.get("value_std") is not None and std_unit and e.get("unit_reported") != std_unit:
            notes.append("标准单位下 " + with_unit(fmt_num(e["value_std"]), names.unit(std_unit)))
        if e.get("range_low") is not None or e.get("range_high") is not None:
            notes.append(f"范围 {fmt_num(e.get('range_low'))}–{fmt_num(e.get('range_high'))}")
        if e.get("uncertainty") is not None:
            kind_label = names.enum("uncertainty_kind", e.get("uncertainty_kind"))
            notes.append(f"± {fmt_num(e['uncertainty'])}" + (f"（{kind_label}）" if kind_label else ""))
        if e.get("n") is not None:
            notes.append(f"n = {fmt_num(e['n'])}")
        fr = e.get("figure_read") if isinstance(e.get("figure_read"), dict) else {}
        if fr.get("reading_error") is not None:
            notes.append(f"{names.field('evidence', 'figure_read', 'reading_error')} ± {fmt_num(fr['reading_error'])}")
    if kind != "statement" and e.get("summary"):
        notes.append(s(e["summary"]))
    return main, notes


def history(e, eid, names, refs):
    """核验历史：录入、机器核对、标风险档、复读、人工核对、专业复核、变化记录，按日期排。"""
    events = []

    def add(date, order, text):
        events.append((s(date), order, text))

    if e.get("created_at") or e.get("created_by"):
        text = "录入"
        if e.get("entry_method"):
            text += f"（{names.enum('entry_method', e['entry_method'])}）"
        if e.get("created_by"):
            text += f"，录入人 {s(e['created_by'])}"
        if e.get("double_extraction"):
            text += f"；{names.field('evidence', 'double_extraction')}：{names.enum('double_extraction', e['double_extraction'])}"
        add(e.get("created_at"), 0, text)
    mc = e.get("machine_check")
    if isinstance(mc, dict):
        checks = [f"{names.field('evidence', 'machine_check', k)} {names.enum('check_result', mc.get(k))}"
                  for k in ("identifier", "snippet", "value_unit") if k in mc]
        add(mc.get("at"), 1, "机器核对：" + "；".join(checks))
    risk = e.get("risk")
    if isinstance(risk, dict):
        reasons = "；".join(names.enum("risk_reason", r) for r in risk.get("reasons") or [])
        text = f"标{names.field('evidence', 'risk')}：{names.enum('risk_tier', risk.get('tier'))}"
        text += f"（{reasons}）" if reasons else ""
        text += f"，由 {s(risk['set_by'])} 标" if risk.get("set_by") else ""
        add(risk.get("set_at"), 2, text)
    fr = e.get("figure_read")
    if isinstance(fr, dict) and (fr.get("reread_at") or fr.get("reread_by")):
        text = "复读图上读数"
        text += f"：{fmt_num(fr['reread_value'])}" if fr.get("reread_value") is not None else ""
        text += f"，复读人 {s(fr['reread_by'])}" if fr.get("reread_by") else ""
        add(fr.get("reread_at"), 3, text)
    if e.get("verified_at") or e.get("verified_by"):
        add(e.get("verified_at"), 4, f"{names.enum('verification_status', 'human_verified')}，核对人 {s(e.get('verified_by'))}")
    if e.get("expert_reviewed_at") or e.get("expert_reviewed_by"):
        add(e.get("expert_reviewed_at"), 5,
            f"{names.enum('verification_status', 'expert_reviewed')}，复核人 {s(e.get('expert_reviewed_by'))}")
    for c in refs.changes.get(eid, []):
        text = f"{names.enum('change_kind', c.get('kind'))}（{s(c.get('id'))}）"
        if c.get("field"):
            text += f"：{names.field('evidence', s(c['field']))} 由“{as_text(c.get('before'))}”改为“{as_text(c.get('after'))}”"
        for label, value in (("原因", c.get("reason")),
                             ("错误类型", names.enum("error_type", c.get("error_type"))),
                             ("发现", names.enum("detected_by", c.get("detected_by"))),
                             ("记录人", c.get("recorded_by"))):
            if value:
                text += f"；{label}：{s(value)}"
        add(c.get("date"), 6, text)
    dated = sorted((x for x in events if x[0]), key=lambda x: (x[0], x[1]))
    out = [(d, t) for d, _, t in dated] + [("", t) for d, _, t in events if not d]
    if e.get("dispute_note"):
        out.append(("", f"{names.enum('verification_status', 'disputed')}：{s(e['dispute_note'])}"))
    if e.get("void_reason"):
        out.append(("", f"{names.enum('verification_status', 'void')}：{s(e['void_reason'])}"))
    return out


def source_rows(src, sid, names, refs):
    """来源一块里的各行：(名字, 内容, 链接或 None, 要不要标出来)。"""
    rows = []

    def add(label, text, url=None, flag=False):
        if text not in (None, ""):
            rows.append((label, s(text), url, flag))

    def f(key):
        return names.field("source", key)

    if not isinstance(src, dict):
        add(f("id"), f"{sid}（来源库里没有这个编号）", flag=True)
        return rows
    add(f("id"), "｜".join(x for x in (sid, names.enum("source_type", src.get("source_type"))) if x))
    for key in ("title", "creators", "container", "published", "version_label"):
        add(f(key), src.get(key))
    add(f("jurisdiction"), names.enum("jurisdiction", src.get("jurisdiction")))
    idents = src.get("identifiers") if isinstance(src.get("identifiers"), dict) else {}
    for k in sorted(idents):
        add("DOI" if k == "doi" else s(k), idents[k], doi_url(idents[k]) if k == "doi" else None)
    add(f("url"), src.get("url"), safe_url(src.get("url")))
    add(f("archive_url"), src.get("archive_url"), safe_url(src.get("archive_url")))
    got = [s(src.get("accessed_at")), names.enum("access_route", src.get("access_route")),
           names.enum("access_scope", src.get("access_scope")), names.enum("fetched_by", src.get("fetched_by"))]
    add(f("accessed_at"), "｜".join(x for x in got if x))
    add(f("license_class"), "｜".join(x for x in (names.enum("license_class", src.get("license_class")),
                                                 s(src.get("license"))) if x))
    add(f("external_use"), names.enum("external_use", src.get("external_use")))
    paid = src.get("paid")
    if isinstance(paid, dict) and not paid.get("purchased"):
        add(f("paid"), names.flag("not_purchased"))
    status = src.get("status")
    if status:
        checked = f"，{f('status_checked_at')} {s(src['status_checked_at'])}" if src.get("status_checked_at") else ""
        add(f("status"), names.enum("source_status", status) + checked, flag=status != "active")
    if refs.corrected_by.get(sid):
        add(names.enum("source_type", "erratum"), "、".join(refs.corrected_by[sid]), flag=True)
    add(f("parent_id"), src.get("parent_id"))
    add(f("corrects"), src.get("corrects"))
    if isinstance(src.get("version_of"), list):
        add(f("version_of"), "、".join(s(x) for x in src["version_of"]))
    add(f("watch"), src.get("watch"))
    return rows


def evidence_row(e, ds, names, refs):
    eid = s(e.get("id"))
    row = blank_row(eid)
    row["e"] = e

    ent = A.entity(ds, e["subject_id"]) if isinstance(e.get("subject_id"), str) else None
    row["subject_id"] = s(e.get("subject_id"))
    if isinstance(ent, dict) and ent.get("name"):
        row["subject"] = s(ent["name"])
    elif row["subject_id"]:
        row["subject"], row["subject_flag"] = f"{row['subject_id']}（实体库里没有这个编号）", True
    else:
        row["subject"], row["subject_flag"] = NOT_FILLED, True
    row["sample"] = s(e.get("sample_label"))

    row["level"], row["level_label"] = s(e.get("level")), names.enum("level", e.get("level")) or NOT_FILLED
    kind, key, measure, name = names.measure(e)
    row["measure_kind"], row["measure_key"] = kind, key
    if not kind:
        row["measure"], row["measure_flag"] = NOT_FILLED, True
    elif not measure:
        row["measure"], row["measure_flag"] = f"{key}（指标字典里没有）", True
    else:
        row["measure"] = name

    row["value"], row["value_notes"] = value_parts(e, key, measure, names)
    if not row["value"]:
        row["value"], row["value_flag"] = NOT_FILLED, True
    row["conditions"] = condition_items(e, measure, names)

    src = A.source(ds, e["source_id"]) if isinstance(e.get("source_id"), str) else None
    row["source_id"] = s(e.get("source_id"))
    if isinstance(src, dict):
        row["source_type"] = s(src.get("source_type"))
        row["source_type_label"] = names.enum("source_type", src.get("source_type"))
        row["source_title"] = s(src.get("title"))
    row["source_rows"] = source_rows(src, row["source_id"], names, refs)

    row["type"], row["type_label"] = s(e.get("evidence_type")), names.enum("evidence_type", e.get("evidence_type")) or NOT_FILLED
    row["flags"] = [names.flag(k) for k in V.display_flags(e, src if isinstance(src, dict) else {}) if k != "company_claim"]
    row["status"] = s(e.get("verification_status"))
    row["status_label"] = names.enum("verification_status", e.get("verification_status")) or NOT_FILLED

    for c, m in refs.groups.get(eid, []):
        row["groups"].append({
            "id": s(c.get("id")), "title": s(c.get("title")),
            "tier": s(c.get("tier")), "tier_label": names.enum("tier", c.get("tier")) or NOT_FILLED,
            "role": s(m.get("role")), "role_label": names.enum("member_role", m.get("role")),
            "status_label": names.enum("cmp_status", c.get("status")),
            "tier_reason": s(c.get("tier_reason")), "note": s(m.get("note")),
        })
    row["tiers"] = sorted({tok(g["tier"]) for g in row["groups"]}) or [NONE]

    risk = e.get("risk") if isinstance(e.get("risk"), dict) else {}
    row["risk"] = {
        "tier": s(risk.get("tier")), "label": names.enum("risk_tier", risk.get("tier")),
        "reasons": [names.enum("risk_reason", r) for r in risk.get("reasons") or []],
        "note": s(risk.get("note")), "set_by": s(risk.get("set_by")), "set_at": s(risk.get("set_at")),
    }
    row["visibility"], row["visibility_label"] = s(e.get("visibility")), names.enum("visibility", e.get("visibility")) or NOT_FILLED
    row["client_code"] = s(e.get("client_code"))

    row["locator"] = locator_text(e.get("locator"), names)
    row["obtained_from_label"] = names.enum("obtained_from", e.get("obtained_from"))
    row["snippet"], row["cond_snippet"] = s(e.get("snippet")), s(e.get("conditions_snippet"))
    row["cond_locator"] = locator_text(e.get("conditions_locator"), names) if e.get("conditions_locator") else ""
    fr = e.get("figure_read")
    if isinstance(fr, dict):
        for k in ("method", "read_by", "source_data_checked", "reread_by", "reread_at", "reread_value", "reading_error"):
            if fr.get(k) is not None:
                text = names.enum("source_data_checked", fr[k]) if k == "source_data_checked" else fmt_num(fr[k])
                row["figure_read"].append((names.field("evidence", "figure_read", k), text))

    row["history"] = history(e, eid, names, refs)
    row["asm_direct"] = list(refs.asm_direct.get(eid, []))
    row["asm_via"] = list(refs.asm_via.get(eid, []))

    def extra(field, text=None, refs_=None):
        if refs_:
            row["extra"].append((names.field("evidence", field), "evidence", [s(x) for x in refs_]))
        elif text not in (None, ""):
            row["extra"].append((names.field("evidence", field), "text", s(text)))

    if isinstance(e.get("questions"), list):
        extra("questions", "、".join(s(q) for q in e["questions"]))
    extra("series_label", e.get("series_label"))
    for field in ("baseline_ref", "control_ref", "superseded_by", "duplicate_of"):
        extra(field, refs_=[e[field]] if e.get(field) else None)
    extra("independent_validation", names.enum("independent_validation", e.get("independent_validation")))
    for field in ("validated_by", "conflicts_with"):
        extra(field, refs_=e.get(field) if isinstance(e.get(field), list) else None)
    extra("scope_note", e.get("scope_note"))
    extra("internal_note", e.get("internal_note"))
    vis = row["visibility_label"] + (f"（{names.field('evidence', 'client_code')} {row['client_code']}）" if row["client_code"] else "")
    extra("visibility", vis)
    extra("obtained_at", e.get("obtained_at"))
    extra("record_version", e.get("record_version"))

    row["f"] = {
        "level": tok(row["level"]), "status": tok(row["status"]), "type": tok(row["type"]),
        "srctype": tok(row["source_type"]), "vis": tok(row["visibility"]), "risk": tok(row["risk"]["tier"]),
        "subject": tok(row["subject_id"]), "measure": tok(f"{kind}:{key}") if kind else NONE,
        "source": tok(row["source_id"]),
    }
    return row


# ---------------------------------------------------------------- 整页要用的数据

def filter_options(rows, key, order, label_of):
    """一个筛选项有哪些选项：[(值, 显示名, 条数)]，按 order 里的次序排，order 里没有的排在后面，没有值的最后。"""
    counts = {}
    for r in rows:
        for code in (r["tiers"] if key == "tier" else [r["f"][key]]):
            counts[code] = counts.get(code, 0) + 1
    rank = {code: i for i, code in enumerate(order)}
    codes = sorted(counts, key=lambda c: (c == NONE, rank.get(c, len(rank)), c))
    return [(c, label_of(c), counts[c]) for c in codes]


def build_model(ds, schema, labels, topic_id, version, lang="zh"):
    topic = A.topic(ds, topic_id)
    if topic is None:
        raise KeyError(topic_id)
    names = Names(labels, A.dictionary(ds, topic_id), schema, lang)
    refs = Refs(ds, topic_id)
    evs = sorted((A.evidence(ds, eid) for eid in A.evidence_ids(ds, topic_id)), key=lambda e: ev_sort_key(e.get("id")))
    ids = {s(e.get("id")) for e in evs}
    rows, errors = [], []
    for e in evs:
        try:
            rows.append(evidence_row(e, ds, names, refs))
        except Exception as exc:  # 一条记录坏到显示不出来，也不让整页生成不了：照样占一行，问题写在页面顶上
            row = blank_row(s(e.get("id")))
            row["error"] = f"{type(exc).__name__}: {exc}"
            row["e"] = e
            rows.append(row)
            errors.append((row["id"], row["error"]))
    try:
        issues = sorted(set(V.validate(ds, schema)), key=lambda x: (x.rule, s(x.record), x.message))
    except Exception as exc:  # 校验脚本自己出了错，也照实写在页面顶上
        issues = [V.Issue("V-00", "tools/validate.py", f"校验脚本出错：{type(exc).__name__}: {exc}")]

    def enum_label(group, none):
        return lambda c: none if c == NONE else names.enum(group, c)

    def subject_label(c):
        ent = A.entity(ds, c)
        return s(ent.get("name")) if isinstance(ent, dict) and ent.get("name") else (NOT_FILLED if c == NONE else c)

    def measure_label(c):
        kind, _, key = c.partition(":")
        table = names.indicators if kind == "indicator" else names.facts
        return NOT_FILLED if c == NONE else names._name(table.get(key), key)

    def source_label(c):
        src = A.source(ds, c)
        title = s(src.get("title")) if isinstance(src, dict) else ""
        return NOT_FILLED if c == NONE else (f"{c}　{title}" if title else c)

    measure_rank = [f"{kind}:{key}" for (kind, key), _ in sorted(names.measure_order.items(), key=lambda x: x[1])]
    filters = {
        "level": filter_options(rows, "level", names.enum_order("level"), enum_label("level", NOT_FILLED)),
        "status": filter_options(rows, "status", names.enum_order("verification_status"),
                                 enum_label("verification_status", NOT_FILLED)),
        "srctype": filter_options(rows, "srctype", names.enum_order("source_type"), enum_label("source_type", NOT_FILLED)),
        "risk": filter_options(rows, "risk", ["high", "medium", "low"], enum_label("risk_tier", "还没标")),
        "type": filter_options(rows, "type", names.enum_order("evidence_type"), enum_label("evidence_type", NOT_FILLED)),
        "tier": filter_options(rows, "tier", names.enum_order("tier"), enum_label("tier", "未归组")),
        "vis": filter_options(rows, "vis", names.enum_order("visibility"), enum_label("visibility", NOT_FILLED)),
        "subject": filter_options(rows, "subject", [], subject_label),
        "measure": filter_options(rows, "measure", measure_rank, measure_label),
        "source": filter_options(rows, "source", [], source_label),
    }
    m = {
        "topic_id": topic_id, "title": s(topic.get("title")) or topic_id, "cutoff": s(topic.get("cutoff_date")),
        "version": version, "notice": s(A.note(ds)),
        "names": names, "rows": rows, "ids": ids, "filters": filters, "issues": issues, "errors": errors,
        "source_count": len({r["source_id"] for r in rows if r["source_id"]}),
    }
    titles = {name: title for name, _, title, _ in VIEWS}
    for name in ("compare", "overview", "gaps", "non-academic"):   # 对标视图先算：别的页面要知道有哪些可比组可以跳过去
        key, module = PAGES[name]
        try:
            m[key] = compare_view.build(ds, topic_id, names, rows, stamp(m)) if name == "compare" else module.build(m, ds, topic_id)
        except Exception as exc:  # 哪一页万一生成不了，别的页面照样出；问题写在页面顶上
            m[key] = None
            errors.append((titles[name], f"{type(exc).__name__}: {exc}"))
    return m


# ---------------------------------------------------------------- 页面各块

def sprite():
    symbols = [Raw(f'<symbol id="m-{k}" viewBox="0 0 12 12">{v}</symbol>\n') for k, v in MARKS.items()]
    symbols.append(Raw(f'<symbol id="m-unknown" viewBox="0 0 12 12">{MARK_UNKNOWN}</symbol>\n'))
    return el("svg", {"class": "sprite", "aria-hidden": "true", "focusable": "false"}, symbols)


def stamp(m):
    return f"截至 {m['cutoff'] or '还没有定'}｜数据版本 {m['version']}"


def ev_refs(id_list, ids):
    """一串证据编号：这一页里有的做成跳转。"""
    out = []
    for i, eid in enumerate(id_list):
        out.append("、" if i else "")
        out.append(el("a", {"href": f"#{eid}"}, eid) if eid in ids else eid)
    return out


def kv(pairs):
    return el("dl", {"class": "kv"}, [(el("dt", None, k), el("dd", None, v)) for k, v in pairs])


def block(name, *content, **attrs):
    return el("div", dict({"class": "block"}, **attrs), el("div", {"class": "block-name"}, name), content)


def render_banners(m):
    out = []
    if m["notice"]:
        out.append(el("div", {"class": "banner", "id": "notice"}, m["notice"]))
    problems = [f"{i.rule}　{s(i.record)}：{i.message}" for i in m["issues"]]
    problems += [f"{eid}：显示不出来（{err}）" for eid, err in m["errors"]]
    if problems:
        shown = problems[:50]
        more = el("li", None, f"其余 {len(problems) - len(shown)} 处见 python3 tools/validate.py 的输出") if len(problems) > len(shown) else None
        out.append(el(
            "div", {"class": "banner", "id": "problems", "role": "status"},
            el("details", None,
               el("summary", None, f"这份数据有 {len(problems)} 处没通过校验。页面照样生成了，没通过的地方可能显示不全。点开看是哪几处"),
               el("ul", None, [el("li", None, p) for p in shown], more))))
    return out


def render_nav():
    links = [el("a", {"href": f"#{name}", "data-view": name}, title) for name, _, title, _ in VIEWS]
    return el("nav", {"class": "pages", "aria-label": "页面"}, links)


def chip_group(key, label, options, total):
    buttons = [el("button", {"type": "button", "class": "chip", "data-filter": key, "data-value": "", "aria-pressed": "true"},
                  "全部", el("span", {"class": "n"}, total))]
    for code, text, n in options:
        buttons.append(el("button", {"type": "button", "class": "chip", "data-filter": key, "data-value": code,
                                     "aria-pressed": "false"}, text, el("span", {"class": "n"}, n)))
    return el("fieldset", {"class": "filter"}, el("legend", {"class": "filter-name"}, label),
              el("div", {"class": "chips"}, buttons))


def picker(key, label, options):
    opts = [el("option", {"value": ""}, "全部")]
    opts += [el("option", {"value": code}, f"{text}（{n}）") for code, text, n in options]
    return el("label", {"class": "picker"}, label, el("select", {"data-filter": key}, opts))


def render_filters(m):
    f, total = m["filters"], len(m["rows"])
    return el(
        "section", {"class": "card filters needs-js", "aria-label": "筛选"},
        chip_group("level", "层级", f["level"], total),
        chip_group("status", "核验状态", f["status"], total),
        chip_group("srctype", "来源类别", f["srctype"], total),
        chip_group("risk", "风险档", f["risk"], total),
        el("div", {"class": "pickers"},
           picker("type", "证据类型", f["type"]),
           picker("tier", "可比档", f["tier"]),
           picker("vis", "可见范围", f["vis"]),
           picker("subject", "对象", f["subject"]),
           picker("measure", "指标或事实项", f["measure"]),
           picker("source", "来源", f["source"]),
           el("label", {"class": "picker"}, "查找",
              el("input", {"type": "search", "data-filter": "q", "autocomplete": "off",
                           "placeholder": "编号、对象、数值、原文片段里的字"}))))


def render_toolbar(m):
    total = len(m["rows"])
    return el(
        "div", {"class": "toolbar"},
        el("div", {"class": "count needs-js", "role": "status"},
           "显示 ", el("span", {"class": "strong", "id": "ev-shown"}, total),
           f" 条，共 {total} 条。点编号看原文片段、出处、来源和核验历史。"),
        el("div", {"class": "toolbar-buttons"},
           el("button", {"type": "button", "class": "btn needs-js", "id": "ev-clear", "hidden": True}, "清除筛选"),
           el("button", {"type": "button", "class": "btn needs-js", "id": "ev-expand", "data-open": "全部展开",
                         "data-close": "全部收起"}, "全部展开"),
           el("button", {"type": "button", "class": "btn needs-js", "id": "ev-copy",
                         "data-done": "已复制，可以直接粘贴到表格软件里。",
                         "data-failed": "浏览器没让自动复制。请在下面的框里全选，再复制。"}, "复制当前显示的行"),
           el("a", {"class": "btn", "id": "ev-download", "href": CSV_NAME, "download": CSV_NAME},
              f"下载表格文件（全部 {total} 条，含只留内部的字段）")),
        el("div", {"class": "note needs-js", "id": "ev-copy-note", "role": "status"}),
        el("textarea", {"class": "copy-box", "id": "ev-copy-box", "hidden": True, "readonly": True,
                        "aria-label": "当前显示的行，制表符分隔"}))


COLUMNS = [("c-id", "编号"), ("c-subject", "对象"), ("c-level", "层级"), ("c-measure", "指标或事实项"), ("c-value", "数值"),
           ("c-cond", "关键条件"), ("c-type", "证据类型"), ("c-status", "核验状态"), ("c-group", "可比档和所在的组"),
           ("c-risk", "风险档")]


def sub(text):
    """主文字下面的一行小字。前面留一个空格：复制、查找、读屏时，两段文字不会粘在一起。"""
    return [" ", el("span", {"class": "sub"}, text)]


def flagged(text, flag):
    return el("span", {"class": "missing"}, text) if flag else text


def render_conditions(items):
    out = []
    for i, c in enumerate(items):
        out.append("；" if i else "")
        text = f"{c['name']} {c['text']}"
        out.append(flagged(text, c["state"] != "reported"))
    return out


def render_groups(groups):
    if not groups:
        return "未归组"
    out = []
    for g in groups:
        role = f"，{g['role_label']}" if g["role"] not in ("", "member") else ""
        out.append(" " if out else "")
        out.append(el("span", {"class": "group"}, el("span", {"class": "strong"}, g["tier_label"]), sub(f"{g['id']}{role}")))
    return out


def render_detail(r, m):
    names, ids = m["names"], m["ids"]
    left, right = [], []

    if r["snippet"]:
        left.append(block(f"{names.field('evidence', 'snippet')}（只在内部看板显示）",
                          el("blockquote", {"class": "snippet", "data-copy": names.field("evidence", "snippet")}, r["snippet"])))
    else:
        left.append(block(names.field("evidence", "snippet"),
                          el("div", {"data-copy": names.field("evidence", "snippet")},
                             "这条没有原文片段。" + ("图上读数不留片段，读图的记录在下面。" if r["figure_read"] else ""))))
    if r["figure_read"]:
        left.append(block(names.field("evidence", "figure_read"), kv(r["figure_read"])))
    where = "｜".join(x for x in (r["source_id"], r["locator"],
                                 f"{names.field('evidence', 'obtained_from')}：{r['obtained_from_label']}" if r["obtained_from_label"] else "") if x)
    left.append(block("出处", el("div", {"data-copy": "出处"}, where or NOT_FILLED)))
    conds = [(c["name"], [flagged(c["text"], c["state"] != "reported"),
                          sub(f"解析为 {c['parsed']}") if c["parsed"] else None])
             for c in r["conditions"]]
    if conds:
        left.append(block(names.field("evidence", "conditions"), kv(conds)))
    if r["cond_snippet"] or r["cond_locator"]:
        left.append(block(f"{names.field('evidence', 'conditions_locator')}和{names.field('evidence', 'conditions_snippet')}",
                          el("div", None, r["cond_locator"]),
                          el("blockquote", {"class": "snippet"}, r["cond_snippet"]) if r["cond_snippet"] else None))
    src_pairs = []
    for label, text, url, flag in r["source_rows"]:
        shown = el("a", {"href": url, "target": "_blank", "rel": "noopener noreferrer", "referrerpolicy": "no-referrer"},
                   text) if url else text
        src_pairs.append((label, el("span", {"class": "flag"}, shown) if flag else shown))
    left.append(block("来源", kv(src_pairs) if src_pairs else NOT_FILLED))

    steps = [el("li", None, [el("span", {"class": "date"}, d), " "] if d else None, t) for d, t in r["history"]]
    right.append(block("核验历史", el("ol", {"class": "history"}, steps) if steps else "还没有记录"))
    risk = r["risk"]
    if risk["tier"]:
        line = risk["label"] + "：" + ("；".join(risk["reasons"]) if risk["reasons"] else "没有标出理由")
        line += f"。{risk['note']}" if risk["note"] else ""
        right.append(block(f"{names.field('evidence', 'risk')}和理由", el("div", None, line)))
    else:
        right.append(block(f"{names.field('evidence', 'risk')}和理由", el("div", None, "还没标。人工核对之前要标好。")))
    if r["groups"]:
        items = []
        linked = (m.get("compare") or {}).get("group_ids") or ()
        for g in r["groups"]:
            head = "｜".join(x for x in (g["tier_label"], g["role_label"], g["status_label"]) if x)
            gid = el("a", {"href": f"#{g['id']}"}, g["id"]) if g["id"] in linked else g["id"]   # 点了去对标视图里这一组
            items.append(el("li", None, el("span", {"class": "strong"}, gid, "｜" + head if head else None),
                            sub("　".join(x for x in (g["title"], g["tier_reason"], g["note"]) if x))))
        right.append(block("所在可比组", el("ul", {"class": "plain"}, items)))
    else:
        right.append(block("所在可比组", el("div", None, "未归组")))
    cited = [f"{a}" for a in r["asm_direct"]] + [f"{a}（经可比组 {c}）" for a, c in r["asm_via"]]
    right.append(block("被这些数据概览引用", el("div", None, "、".join(cited) if cited else "还没有被引用")))
    if r["extra"]:
        pairs = [(label, ev_refs(value, ids) if kind == "evidence" else value) for label, kind, value in r["extra"]]
        right.append(block("其余字段", kv(pairs)))
    return el("div", {"class": "detail"}, el("div", {"class": "detail-col"}, left), el("div", {"class": "detail-col"}, right))


def render_row(r, m):
    def td(i, *content):
        return el("td", {"class": COLUMNS[i][0], "data-label": COLUMNS[i][1]}, el("div", {"class": "c"}, content))

    detail_id = f"d-{r['id']}"
    risk = r["risk"]
    cells = [
        td(0, el("button", {"type": "button", "class": "ev-toggle", "aria-expanded": "true", "aria-controls": detail_id}, r["id"])),
        td(1, el("span", {"class": "strong"}, flagged(r["subject"], r["subject_flag"])),
           sub(r["sample"]) if r["sample"] else None),
        td(2, r["level_label"]),
        td(3, flagged(r["measure"], r["measure_flag"])),
        td(4, flagged(r["value"], r["value_flag"]), [sub(n) for n in r["value_notes"]]),
        td(5, render_conditions(r["conditions"])),
        td(6, el("span", {"class": "type"}, mark(r["type"]), r["type_label"]), [sub(x) for x in r["flags"]]),
        td(7, el("span", {"class": f"status s-{cls(r['status'])}"}, r["status_label"])),
        td(8, render_groups(r["groups"])),
        td(9, el("span", {"class": f"risk r-{cls(risk['tier'] or 'none')}"}, risk["label"] or "还没标")),
    ]
    if r["error"]:
        detail = el("div", {"class": "detail"}, el("div", {"class": "flag"}, f"这条证据显示不出来：{r['error']}"))
    else:
        detail = render_detail(r, m)
    f = r["f"]
    return el(
        "tbody", {"class": "ev", "id": r["id"], "data-level": f["level"], "data-status": f["status"], "data-type": f["type"],
                  "data-srctype": f["srctype"], "data-tier": " ".join(r["tiers"]), "data-vis": f["vis"],
                  "data-risk": f["risk"], "data-subject": f["subject"], "data-measure": f["measure"],
                  "data-source": f["source"]},
        el("tr", {"class": "ev-main"}, cells),
        el("tr", {"class": "ev-detail", "id": detail_id}, el("td", {"colspan": len(COLUMNS)}, detail)))


def render_evidence_view(m, name, title, question):
    total = len(m["rows"])
    head = el("div", {"class": "view-head"}, el("h2", None, title),
              el("div", {"class": "note"}, f"{question}｜{total} 条证据，来自 {m['source_count']} 个来源"))
    if not total:
        body = [el("section", {"class": "card"}, head,
                   el("p", {"class": "empty", "id": "ev-none"},
                      "这个题目还没有证据。来源和证据登记进数据文件之后，重新生成，就会出现在这里。"))]
    else:
        table = el("table", {"class": "ev-table"},
                   el("thead", None, el("tr", None, [el("th", {"scope": "col", "class": c}, label) for c, label in COLUMNS])),
                   [render_row(r, m) for r in m["rows"]])
        body = [el("section", {"class": "card"}, head, render_toolbar(m)),
                render_filters(m),
                el("section", {"class": "card table-card"}, table,
                   el("p", {"class": "empty", "id": "ev-empty", "hidden": True}, "没有符合筛选条件的证据。"))]
    return el("section", {"class": "view", "id": name, "aria-label": title}, body)


def render_failed_view(name, title):
    return el("section", {"class": "view", "id": name, "aria-label": title},
              el("section", {"class": "card"}, el("div", {"class": "view-head"}, el("h2", None, title)),
                 el("p", {"class": "flag"}, "这一页生成不了，原因列在页面顶上。")))


def render_legend(names):
    def col(title, *content):
        return el("div", {"class": "legend-col"}, el("h3", None, title), content)

    types = [el("div", {"class": "legend-item"}, mark(code), names.enum("evidence_type", code))
             for code in names.enum_order("evidence_type")]
    statuses = [el("div", {"class": "legend-item"}, el("span", {"class": f"status s-{cls(code)}"}, names.enum("verification_status", code)))
                for code in names.enum_order("verification_status")]
    tiers = [el("div", None, f"{names.enum('tier', code)}" + (f"：{TIER_HANDLING[code]}" if code in TIER_HANDLING else ""))
             for code in names.enum_order("tier")]
    by_tier = {}
    for reason, tier in V.RISK_REASON_TIER.items():
        by_tier.setdefault(tier, []).append(names.enum("risk_reason", reason))
    risks = []
    for code in ("high", "medium", "low"):
        text = "；".join(by_tier[code]) if by_tier.get(code) else "以上都没有"
        risks.append(el("div", {"class": "legend-item"},
                        el("span", {"class": f"risk r-{code}"}, names.enum("risk_tier", code)), " ", text))
    return el(
        "section", {"class": "card legend", "id": "legend", "aria-label": "图例"},
        col("证据类型", types, el("div", {"class": "note"}, "是不同的类型，不分高低。")),
        col("核验状态", statuses),
        col("可比档", tiers, el("div", {"class": "note"}, "没有进任何可比组的，显示“未归组”。")),
        col("风险档", risks, el("div", {"class": "note"}, "人工核对之前标好，给做人工核对的人看。")))


def render_page(m, css, js):
    for name, text in (("style.css", css), ("app.js", js)):
        if re.search(r"</\s*(style|script)", text, re.I):
            raise ValueError(f"{name} 里不能出现 </style 或 </script")
    views = []
    for name, code, title, question in VIEWS:
        key, module = PAGES.get(name, (None, None))
        if name == "evidence":
            views.append(render_evidence_view(m, name, title, question))
        elif not m.get(key):
            views.append(render_failed_view(name, title))
        elif name == "compare":
            views.append(compare_view.render(m["compare"], m["names"], title, question))
        else:
            try:
                views.append(module.render(m[key], m, title, question))
            except Exception as exc:   # 写网页这一步出了错也一样：这一页说明生成不了，别的照出
                m["errors"].append((title, f"{type(exc).__name__}: {exc}"))
                views.append(render_failed_view(name, title))
    head = el(
        "head", None,
        el("meta", {"charset": "utf-8"}),
        el("meta", {"http-equiv": "Content-Security-Policy", "content": CSP}),
        el("meta", {"name": "viewport", "content": "width=device-width, initial-scale=1"}),
        el("meta", {"name": "referrer", "content": "no-referrer"}),
        el("meta", {"name": "robots", "content": "noindex, nofollow"}),
        el("title", None, f"{m['title']}｜对内看板"),
        el("style", None, Raw("\n" + css)),
        el("script", None, Raw("document.documentElement.className = 'js';")))
    body = el(
        "body", None,
        sprite(),
        el("div", {"class": "page"},
           el("header", {"class": "top"},
              el("div", {"class": "top-title"}, el("div", {"class": "eyebrow"}, "Intelligent Tank｜对内看板"),
                 el("h1", None, m["title"])),
              el("div", {"class": "meta", "id": "stamp"}, stamp(m))),
           render_banners(m),
           render_nav(),
           el("main", None, views),
           render_legend(m["names"]),
           el("footer", {"class": "foot"},
              f"只读。页面打开时不向任何地方发送数据；要改数据就改仓库里的数据文件，再重新生成。｜{stamp(m)}")),
        el("script", None, Raw("\n" + js)))
    return "<!DOCTYPE html>\n" + el("html", {"lang": "zh-CN", "class": "no-js"}, head, body)


# ---------------------------------------------------------------- 表格文件

def csv_cell(x):
    """表格软件会把 = + - @ 开头的格子当公式算。不是单纯的数字就在前面加一个撇号，让它当文字。"""
    text = s(x)
    if re.match(r"^[=+\-@\t\r]", text) and not re.match(r"^[+-]?\d+(\.\d+)?([eE][+-]?\d+)?%?$", text):
        return "'" + text
    return text


def evidence_csv(m):
    """证据表的表格文件（内部用）：一条证据一行，含原文片段、风险档等只留内部的字段。
    UTF-8 带 BOM，表格软件直接打开不乱码。每行末尾带截至日期和数据版本，单独传这个文件时也查得到是哪一版。"""
    names = m["names"]

    def f(key):
        return names.field("evidence", key)

    def raw(key):
        return lambda r: r["e"].get(key)

    def num(key):
        return lambda r: fmt_num(r["e"].get(key)) if r["e"].get(key) is not None else ""

    def enum(group, key):
        return lambda r: names.enum(group, r["e"].get(key))

    def machine(r):
        mc = r["e"].get("machine_check")
        if not isinstance(mc, dict):
            return ""
        parts = [f"{names.field('evidence', 'machine_check', k)} {names.enum('check_result', mc.get(k))}"
                 for k in ("identifier", "snippet", "value_unit") if k in mc]
        return "；".join(parts + [s(mc.get("at"))])

    def std_unit(r):
        _, _, measure, _ = names.measure(r["e"])
        return names.unit(measure.get("unit_std"))

    def category(r):
        return names.value(r["measure_key"], r["e"].get("category_value"))

    columns = [
        (f("id"), lambda r: r["id"]),
        ("对象编号", lambda r: r["subject_id"]),
        ("对象", lambda r: r["subject"]),
        (f("sample_label"), lambda r: r["sample"]),
        (f("level"), lambda r: r["level_label"]),
        ("指标或事实项", lambda r: r["measure"]),
        (f("content_kind"), enum("content_kind", "content_kind")),
        (f("value_qualifier"), enum("value_qualifier", "value_qualifier")),
        (f("value_reported"), raw("value_reported")),
        (f("unit_reported"), lambda r: names.unit(r["e"].get("unit_reported"))),
        (f("value_std"), num("value_std")),
        ("标准单位", std_unit),
        (f("range_low"), num("range_low")),
        (f("range_high"), num("range_high")),
        (f("uncertainty"), num("uncertainty")),
        (f("uncertainty_kind"), enum("uncertainty_kind", "uncertainty_kind")),
        (f("n"), num("n")),
        (f("category_value"), category),
        (f("summary"), raw("summary")),
        (f("conditions"), lambda r: "；".join(f"{c['name']}：{c['text']}" for c in r["conditions"])),
        (f("evidence_type"), lambda r: r["type_label"]),
        ("标注", lambda r: "；".join(r["flags"])),
        (f("obtained_from"), lambda r: r["obtained_from_label"]),
        ("来源编号", lambda r: r["source_id"]),
        (names.field("source", "source_type"), lambda r: r["source_type_label"]),
        (names.field("source", "title"), lambda r: r["source_title"]),
        (f("locator"), lambda r: r["locator"]),
        (f("snippet"), lambda r: r["snippet"]),
        (f("verification_status"), lambda r: r["status_label"]),
        (f("risk"), lambda r: r["risk"]["label"]),
        ("风险理由", lambda r: "；".join(r["risk"]["reasons"])),
        (f("machine_check"), machine),
        (f("double_extraction"), enum("double_extraction", "double_extraction")),
        (f("verified_by"), raw("verified_by")),
        (f("verified_at"), raw("verified_at")),
        (f("expert_reviewed_by"), raw("expert_reviewed_by")),
        (f("expert_reviewed_at"), raw("expert_reviewed_at")),
        ("所在可比组和档别", lambda r: "；".join(
            f"{g['id']}（{'，'.join(x for x in (g['tier_label'], g['role_label']) if x)}）" for g in r["groups"])),
        ("被数据概览引用", lambda r: "；".join(r["asm_direct"] + [f"{a}（经 {c}）" for a, c in r["asm_via"]])),
        (f("visibility"), lambda r: r["visibility_label"]),
        (f("questions"), lambda r: "；".join(s(q) for q in r["e"].get("questions") or [])
            if isinstance(r["e"].get("questions"), list) else ""),
        (f("scope_note"), raw("scope_note")),
        (f("internal_note"), raw("internal_note")),
        (f("obtained_at"), raw("obtained_at")),
        (f("created_by"), raw("created_by")),
        (f("created_at"), raw("created_at")),
        ("截至日期", lambda r: m["cutoff"]),
        ("数据版本", lambda r: m["version"]),
    ]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([name for name, _ in columns])
    for r in m["rows"]:
        cells = []
        for _, get in columns:
            try:
                cells.append(csv_cell(get(r)))
            except Exception:  # 坏到取不出来的格子留空，这一条的问题已经写在页面顶上
                cells.append("")
        writer.writerow(cells)
    return "\ufeff" + out.getvalue()


# ---------------------------------------------------------------- 数据版本

def _git(args, cwd):
    try:
        r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def data_version(data_dir):
    """数据版本就是提交号（规格 1.7）。数据或脚本有没提交的改动时照实加注；不在 git 仓库里返回 None。"""
    top = _git(["rev-parse", "--show-toplevel"], data_dir)
    sha = _git(["rev-parse", "--short=7", "HEAD"], data_dir) if top else None
    if not sha:
        return None
    paths = [os.path.realpath(data_dir)]
    try:
        if os.path.commonpath([os.path.realpath(HERE), os.path.realpath(top)]) == os.path.realpath(top):
            paths.append(os.path.realpath(HERE))
    except ValueError:
        pass
    dirty = _git(["status", "--porcelain", "--"] + paths, top)
    return sha + ("＋没提交的改动" if dirty else "")


# ---------------------------------------------------------------- 入口

def load_labels(data_dir, path=None):
    for p in (path, os.path.join(data_dir, "labels.json"), os.path.join(V.DEFAULT_DATA, "labels.json")):
        if p and os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)
    return {}


def read_asset(name):
    with open(os.path.join(ASSETS, name), encoding="utf-8") as fh:
        return fh.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def build(data_dir, out_dir, topic_id=None, version=None, labels_path=None, strict=False, log=print):
    """生成看板。返回退出码：0 成功；1 是 strict 下数据有问题；2 是生成不了。"""
    if not os.path.isdir(data_dir):
        log(f"找不到数据目录：{data_dir}")
        return 2
    ds = A.load(data_dir)
    topics = A.topic_ids(ds)
    if topic_id is None and len(topics) == 1:
        topic_id = topics[0]
    if topic_id not in topics:
        which = "、".join(topics) or "一个题目也没有读到"
        log(f"要用 --topic 指定题目。数据里有：{which}" if topic_id is None else f"数据里没有题目 {topic_id}。有：{which}")
        for it in A.problems(ds):
            log(f"{it.rule}  {it.record}: {it.message}")
        return 2
    if version is None:
        version = data_version(data_dir)
        if version is None:
            version = "没有版本号（不在 git 仓库里）"
            log("提醒：数据目录不在 git 仓库里，页面上的数据版本写不出提交号。可以用 --version 指定。")
    m = build_model(ds, V.load_schema(), load_labels(data_dir, labels_path), topic_id, version)
    page = render_page(m, read_asset("style.css"), read_asset("app.js"))
    table = evidence_csv(m)
    os.makedirs(out_dir, exist_ok=True)
    write_text(os.path.join(out_dir, PAGE_NAME), page)
    write_text(os.path.join(out_dir, CSV_NAME), table)
    log(f"题目 {topic_id}　{m['title']}")
    log(f"证据 {len(m['rows'])} 条，来源 {m['source_count']} 个｜{stamp(m)}")
    log(f"写出 {os.path.join(out_dir, PAGE_NAME)}（{len(page.encode('utf-8')) // 1024 + 1} KB）和 {os.path.join(out_dir, CSV_NAME)}")
    bad = len(m["issues"]) + len(m["errors"])
    log("数据校验：全部通过" if not bad else f"数据校验：有 {bad} 处没通过，列在页面顶上；细节见 python3 tools/validate.py")
    return 1 if (strict and bad) else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="从 data/ 生成对内看板（只读的静态网页）和证据表的表格文件")
    ap.add_argument("--data", default=V.DEFAULT_DATA, help="数据目录，默认是仓库里的 data/")
    ap.add_argument("--out", default=DEFAULT_OUT, help="写到哪个目录，默认是仓库里的 site/（不入库）")
    ap.add_argument("--topic", metavar="TOP-编号", help="生成哪个题目的看板；数据里只有一个题目时不用写")
    ap.add_argument("--version", help="页面上写的数据版本；不写就用 git 的提交号")
    ap.add_argument("--labels", help="显示名文件；不写就用数据目录里的 labels.json，没有再用仓库 data/ 里的")
    ap.add_argument("--strict", action="store_true", help="数据没通过校验、或有证据显示不出来时，退出码为 1（文件照样写出）")
    args = ap.parse_args(argv)
    return build(args.data, args.out, args.topic, args.version, args.labels, args.strict)


if __name__ == "__main__":
    sys.exit(main())
