#!/usr/bin/env python3
"""复核单：专业复核用的单子（规格 3.13；方案 5.1 第 8 步、5.6；D-80）。

一个可比组一张。脚本列出要复核人逐条看的条目、为什么要看、参考判断；其余成员成批确认，随机抽几条给复核人看。
不在可比组里的条目（非学术来源的证据、跨组的描述）另开一张。复核单只留内部。

脚本做四件事：起草；给人看；变成对话里的点选题；把复核人的回答写回数据。
回答不由脚本和 AI 代答：写回时复核人必须是人（V-43、V-48），回答是复核人在对话里点的、说的。

用法
  python3 tools/review_sheet.py draft                         哪些可比组该起草，起草出来是什么样（只看不写）
  python3 tools/review_sheet.py draft --write                 起草并写进题目的 reviews.json
  python3 tools/review_sheet.py draft --comparison CMP-000002 --write
  python3 tools/review_sheet.py draft --targets EV-000005-001 ASM-000002 --write
                                                              不在可比组里的条目另开一张
  python3 tools/review_sheet.py add RVW-000002 --target EV-000007-002 --reason baseline_anomaly \\
                                    --why "……" --suggestion "……"
                                                              脚本看不出来、要靠判断的条目，由起草的人加
  python3 tools/review_sheet.py list                          现在有哪些复核单，各到了哪一步
  python3 tools/review_sheet.py show RVW-000002               给人看的一份
  python3 tools/review_sheet.py questions RVW-000002          对话里出点选题用的一份（JSON）
  python3 tools/review_sheet.py questions RVW-000002 --send   交给复核人：成员都人工核对过才交得出去，状态改成“已交复核人”
  python3 tools/review_sheet.py apply RVW-000002 --answers 回答.json
                                                              把复核人的回答写回数据

回答文件的样子（questions 的输出里有一份空的）：
  {"reviewer": "kai", "date": "2026-11-20", "minutes": 12,
   "items": {"CMP-000002": {"decision": "confirm"},
             "EV-000003-001": {"decision": "modify", "note": "改成什么", "change_ids": ["CHG-000002"]}},
   "batch": {"decision": "confirm"}}
minutes 是复核人看这张单子实际用的分钟数（工作记录要实记）；当时没记就写 minutes_note 说明。
决定是“改”的：先照复核人说的改数据、记变化记录，再连同变化记录的编号（change_ids）一起写回（V-48：改了的要有变化记录）。
一时改不了的，决定先留 pending，把复核人的话记在 note 里。

全部定了之后，脚本把单子标成已复核，并把结果带到数据上：可比组标专业已复核（档别还没有人定的，定档人记复核人）；
单子里人工已核的证据标专业已复核；数据概览的陈述标已复核；工作记录加一条。写之前先在内存里把校验跑一遍，
多出任何一条校验问题，就一个字也不写。

退出码  0 做完了；1 有做不了的（没准备好、回答不合规矩、写回之后校验不过）；2 用法或环境不对。
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import access as A  # noqa: E402
import build_dashboard as B  # noqa: E402
import ids as I  # noqa: E402
import store  # noqa: E402
import validate as V  # noqa: E402
from compare_view import object_of  # noqa: E402
from display import NOT_FILLED, Names, ev_sort_key, s  # noqa: E402

# 成批确认的条目里随机抽几条给复核人看：至少 3 条，或者一成，取多的。方案 5.6 只说“随机抽的几条”，数是这里的默认做法
SAMPLE_MIN, SAMPLE_SHARE = 3, 0.1
# 对话里的点选工具一次最多四道题，每题上方的短标题不超过 12 个字
ROUND_SIZE, HEADER_MAX = 4, 12
OPEN = ("draft", "sent")
DECISIONS = ("confirm", "modify", "pending")
# 参考判断照方案 5.6 的表写；“存疑”“陈述”两种表里没有，是这里补的
SUGGEST = {
    "missing_condition": "建议留在本组并注明缺哪项，或者降到“参考性资料”",
    "reference": "这一条在组里已经只作参考；建议维持",
    "conflict": "建议都保留并标“存疑”，写明分歧",
    "outlier": "建议标“存疑”，或者核对单位",
    "claim_without_conditions": "建议不进可比组，只列在参考里",
    "disputed": "建议保留“存疑”；要用就写明分歧",
    "overview": "陈述和依据对得上就同意；要改写，写明改成什么",
}


class ReviewError(Exception):
    """做不了的事：没准备好、回答不合规矩、写回之后校验不过。"""


# ---------------------------------------------------------------- 每条记录怎么称呼

class Ctx:
    """显示名和每条证据的写法。和看板用同一套（build_dashboard.evidence_row），单子上写的和看板上看到的对得上。"""

    def __init__(self, ds, schema, labels):
        self.ds, self.schema, self.labels, self.lk = ds, schema, labels, A.lookups(ds)
        self._names, self._refs, self._rows = {}, {}, {}

    def names(self, topic_id):
        if topic_id not in self._names:
            self._names[topic_id] = Names(self.labels, A.dictionary(self.ds, topic_id), self.schema, "zh")
        return self._names[topic_id]

    def row(self, eid):
        """一条证据在看板上怎么写。证据库里没有、或者坏到写不出来的，给 None。"""
        if eid not in self._rows:
            e, row = A.evidence(self.ds, eid), None
            if isinstance(e, dict):
                tid = e.get("topic_id")
                if tid not in self._refs:
                    self._refs[tid] = B.Refs(self.ds, tid)
                try:
                    row = B.evidence_row(e, self.ds, self.names(tid), self._refs[tid])
                except Exception:
                    row = None
            self._rows[eid] = row
        return self._rows[eid]


def describe(ctx, eid):
    """一条证据是什么：对象、指标和数值；条件；出处（题名、作者、刊名、日期、位置，D-129）。"""
    row = ctx.row(eid)
    if not row:
        return {"what": f"{eid}（证据库里没有这一条，或者显示不出来）", "conditions": "", "where": ""}
    obj = object_of(row)
    src = A.source(ctx.ds, row["source_id"])
    src = src if isinstance(src, dict) else {}
    about = "，".join(s(src.get(k)) for k in ("creators", "container", "published") if src.get(k))
    title = f"《{row['source_title']}》" if row["source_title"] else row["source_id"]
    return {
        "what": f"{obj['label']}（{obj['sub']}），{row['measure']} {row['value']}",
        "conditions": "；".join(f"{c['name']} {c['text']}" for c in row["conditions"]),
        "where": "，".join(x for x in (title + (f"（{about}）" if about else ""), row["locator"]) if x),
    }


def sentence(text):
    """一句话：末尾不管原来有没有句号，都只留一个。"""
    text = s(text).strip()
    return (text[:-1] if text.endswith("。") else text) + "。" if text else ""


def why_text(names, it):
    """为什么要看：理由的名字加具体说明。理由是“其他”的只写具体说明。"""
    label = "" if it.get("reason") == "other" else (names.enum("review_reason", it.get("reason")) or s(it.get("reason")))
    return (f"{label}。" if label else "") + sentence(it.get("why"))


def targets_of(sheet):
    """一张单子看到的条目：逐条的加成批的。"""
    out = [it.get("target_id") for it in sheet.get("items") or [] if isinstance(it, dict)]
    batch = sheet.get("batch") if isinstance(sheet.get("batch"), dict) else {}
    return [x for x in out + list(batch.get("evidence_ids") or []) if isinstance(x, str)]


def evidence_targets(sheet):
    return [x for x in targets_of(sheet) if x.startswith("EV-")]


# ---------------------------------------------------------------- 起草

def sample_ids(seed, ids):
    """从成批确认的条目里抽几条。抽哪几条由单子的编号定：同一张单子每次抽到的一样，不靠随机数发生器。"""
    k = min(len(ids), max(SAMPLE_MIN, math.ceil(len(ids) * SAMPLE_SHARE)))
    ranked = sorted(ids, key=lambda i: hashlib.sha256(f"{seed}|{i}".encode("utf-8")).hexdigest())
    picked = set(ranked[:k])
    return [i for i in ids if i in picked]


def evidence_reasons(ctx, e, role="", note=""):
    """脚本从数据里看得出来的、要复核人逐条看的理由。返回 [(理由, 具体说明, 参考判断)]，主要的在前。

    看得出来的四种：来源之间矛盾（conflicts_with）；数值离群（核对时标在风险理由里的）；条件缺失或含糊
    （必填的条件没报告，或者写了但解析不出数值）；企业声明没有条件。另加已经标了存疑的。
    基准膜的数值异常、定义不一致、分类拿不准、层级或对象可能归错，这四种要靠判断，由起草的人用 add 加。
    """
    row = ctx.row(e.get("id"))
    if not row:
        return []
    names = ctx.names(e.get("topic_id"))
    found = []
    others = [x for x in e.get("conflicts_with") or [] if isinstance(x, str)]
    if others:
        said = "；".join(f"{x} 是 {(ctx.row(x) or {}).get('value') or '（显示不出来）'}" for x in others)
        found.append(("conflict", f"和别的来源的数不一样：这一条是 {row['value']}，{said}", SUGGEST["conflict"]))
    if e.get("verification_status") == "disputed":
        why = f"核对时已经标了存疑：{s(e.get('dispute_note')) or '没有写说明'}"
        found.append(("conflict" if others else "other", why, SUGGEST["disputed"]))
    risk = e.get("risk") if isinstance(e.get("risk"), dict) else {}
    if "outlier" in (risk.get("reasons") or []):
        found.append(("outlier", "核对时标了数值离群" + (f"：{s(risk['note'])}" if risk.get("note") else ""), SUGGEST["outlier"]))
    measure = ctx.lk.measure_of(e)[1] or {}
    shown = {c["key"]: c for c in row["conditions"]}
    missing, vague = [], []
    for key in [k for k in measure.get("required_conditions") or [] if isinstance(k, str)]:
        c = shown.get(key)
        kind = (names.conditions.get(key) or {}).get("value_kind")
        if c is None or c["state"] in ("absent", "not_reported"):
            missing.append(names.condition(key))
        elif c["state"] == "reported" and kind in ("numeric", "numeric_range") and not c["parsed"]:
            vague.append(f"{names.condition(key)}写的是“{c['text']}”，解析不出数值")
    if missing or vague:
        said = "；".join(([f"原文没有报告：{'、'.join(missing)}"] if missing else []) + vague)
        if e.get("evidence_type") == "company_claim":
            found.append(("claim_without_conditions", f"企业声明，{said}", SUGGEST["claim_without_conditions"]))
        elif role == "reference":
            found.append(("missing_condition", said, SUGGEST["reference"] + (f"（{note}）" if note else "")))
        else:
            found.append(("missing_condition", said, SUGGEST["missing_condition"]))
    return found


def evidence_item(ctx, e, role="", note=""):
    """一条证据要不要逐条看。要看的返回单子上的一项，不用的返回 None。"""
    found = evidence_reasons(ctx, e, role, note)
    if not found:
        return None
    reason, why, suggestion = found[0]
    if len(found) > 1:
        why += "。另外：" + "；".join(w for _, w, _ in found[1:])
    return {"target_id": e["id"], "reason": reason, "why": why, "suggestion": suggestion, "decision": "pending"}


def group_item(ctx, c):
    """这一组的档别。档别要由人来定（V-43），所以每张单子里都有这一项。"""
    names = ctx.names(c.get("topic_id"))
    tier = names.enum("tier", c.get("tier")) or NOT_FILLED
    if c.get("tier") == "direct" and c.get("missing_conditions"):
        lost = "、".join(names.condition(k) for k in c["missing_conditions"] if isinstance(k, str))
        basis = f"认为是同一套条件的依据：{s(c['same_setup_note'])}" if c.get("same_setup_note") else "没有写认为是同一套条件的依据"
        reason, why = "tier_ambiguous", f"预归为{tier}，但原文没有写{lost}。{basis}"
    elif c.get("status") == "decided":
        reason, why = "other", f"{s(c.get('decided_by'))} {s(c.get('decided_at'))} 定为{tier}，还没有专业复核"
    else:
        reason, why = "other", "这一组的档别是 AI 预归的，要由人来定"
    suggestion = f"定为{tier}。理由：{s(c.get('tier_reason')) or NOT_FILLED}" + (f"。缺：{s(c['missing'])}" if c.get("missing") else "")
    return {"target_id": c["id"], "reason": reason, "why": why, "suggestion": suggestion, "decision": "pending"}


def overview_item(a):
    basis = "、".join(x for x in a.get("basis") or [] if isinstance(x, str))
    why = f"“{s(a.get('statement'))}”（依据：{basis or NOT_FILLED}）"
    if a.get("unknowns"):
        why += f"；还不能判断的：{s(a['unknowns'])}"
    return {"target_id": a["id"], "reason": "overview", "why": why, "suggestion": SUGGEST["overview"], "decision": "pending"}


def _sheet(rid, topic_id, cid, title, by, date, items, batch):
    sheet = {"id": rid, "topic_id": topic_id}
    if cid:
        sheet["comparison_id"] = cid
    sheet.update(title=title, status="draft", created_by=by, created_at=date, items=items)
    if batch:
        sheet["batch"] = {"evidence_ids": batch, "sampled": sample_ids(rid, batch), "decision": "pending"}
    return sheet


def _in_sheets(ds, keep=lambda r: True):
    """已经在某张单子里的条目。"""
    seen = set()
    for r in (A.review(ds, rid) for rid in A.review_ids(ds)):
        if isinstance(r, dict) and keep(r):
            seen |= set(targets_of(r))
    return seen


def draft_group(ctx, c, rid, by, date):
    """给一个可比组起草复核单。返回 (单子, "")；不用起草的返回 (None, 原因)。

    这一组已经有复核完的单子时，只把还没看过的列进新的一张（后来加的成员、后来写的数据概览陈述）。
    """
    ds, cid = ctx.ds, c["id"]
    sheets = [A.review(ds, rid) for rid in A.review_ids(ds, cid)]
    unfinished = [r["id"] for r in sheets if r.get("status") in OPEN]
    if unfinished:
        return None, f"已经有一张还没复核完的复核单 {'、'.join(unfinished)}"
    seen = set()
    for r in sheets:
        seen |= set(targets_of(r))
    members = [m for m in c.get("members") or []
               if isinstance(m, dict) and isinstance(m.get("evidence_id"), str) and m.get("role") != "excluded"]
    todo = [m for m in members if m["evidence_id"] not in seen and isinstance(A.evidence(ds, m["evidence_id"]), dict)]
    taken = _in_sheets(ds)
    statements = [a for aid, a in ((x, A.assessment(ds, x)) for x in A.assessment_ids(ds, c.get("topic_id")))
                  if a.get("status") == "draft"
                  and cid in (a.get("basis") or []) and aid not in taken]
    need_group = c.get("status") != "expert_reviewed" and cid not in seen
    if not (todo or statements or need_group):
        return None, "成员都在复核完的复核单里了"
    items, batch = ([group_item(ctx, c)] if need_group else []), []
    for m in todo:
        item = evidence_item(ctx, A.evidence(ds, m["evidence_id"]), s(m.get("role")), s(m.get("note")))
        if item:
            items.append(item)
        else:
            batch.append(m["evidence_id"])
    items += [overview_item(a) for a in statements]
    title = f"{cid} 的复核单" + ("（补）" if sheets else "")
    return _sheet(rid, c.get("topic_id"), cid, title, by, date, items, batch), ""


def draft_loose(ctx, targets, rid, by, date):
    """不在可比组里的条目另开一张（规格 3.13）：非学术来源的证据、跨组的描述。"""
    ds = ctx.ds
    if not targets:
        raise ReviewError("要给出条目的编号（证据或数据概览的陈述）")
    if len(set(targets)) != len(targets):
        raise ReviewError("条目有重复")
    topics, items, batch = set(), [], []
    for t in targets:
        rec = A.evidence(ds, t) if t.startswith("EV-") else A.assessment(ds, t) if t.startswith("ASM-") else None
        if not isinstance(rec, dict):
            raise ReviewError(f"{t}：不是证据库里的证据，也不是数据概览里的陈述")
        topics.add(rec.get("topic_id"))
        if t.startswith("ASM-"):
            items.append(overview_item(rec))
        elif rec.get("verification_status") == "void":
            raise ReviewError(f"{t} 已作废，不用复核")
        else:
            item = evidence_item(ctx, rec)
            if item:
                items.append(item)
            else:
                batch.append(t)
    if len(topics) != 1:
        raise ReviewError("这些条目不在同一个题目里，一张复核单只管一个题目")
    return _sheet(rid, topics.pop(), None, f"不在可比组里的条目的复核单（{len(targets)} 条）", by, date, items, batch)


def add_item(ctx, sheet, target, reason, why, suggestion):
    """起草的人加一条要逐条看的。原来在成批确认里的，挪出来。"""
    ds = ctx.ds
    if sheet.get("status") == "closed":
        raise ReviewError(f"{sheet['id']} 已经复核完了，不能再加；要补看就另起一张")
    reasons = ctx.schema["$defs"]["enum_review_reason"]["enum"]
    if reason not in reasons:
        raise ReviewError(f"理由 {reason!r} 不认识，应为：{'、'.join(reasons)}")
    if not (why and why.strip() and suggestion and suggestion.strip()):
        raise ReviewError("要写具体说明（--why）和参考判断（--suggestion）")
    if any(isinstance(it, dict) and it.get("target_id") == target for it in sheet.get("items") or []):
        raise ReviewError(f"{target} 已经是这张单子里要逐条看的一项")
    cid = sheet.get("comparison_id")
    c = A.comparison(ds, cid) if cid else None
    if target.startswith("EV-"):
        if not isinstance(A.evidence(ds, target), dict):
            raise ReviewError(f"证据库里没有 {target}")
        if c and target not in [m.get("evidence_id") for m in c.get("members") or [] if isinstance(m, dict)]:
            raise ReviewError(f"{target} 不是 {cid} 的成员")
    elif target.startswith("ASM-"):
        if not isinstance(A.assessment(ds, target), dict):
            raise ReviewError(f"数据概览里没有 {target}")
    elif not (cid and target == cid):
        raise ReviewError(f"{target}：只能加这张单子的可比组、组里的证据，或者数据概览的陈述")
    batch = sheet.get("batch") if isinstance(sheet.get("batch"), dict) else None
    if batch and target in (batch.get("evidence_ids") or []):
        batch["evidence_ids"] = [x for x in batch["evidence_ids"] if x != target]
        if batch["evidence_ids"]:
            batch["sampled"] = sample_ids(sheet["id"], batch["evidence_ids"])
        else:
            del sheet["batch"]
    sheet.setdefault("items", []).append(
        {"target_id": target, "reason": reason, "why": why.strip(), "suggestion": suggestion.strip(), "decision": "pending"})


def not_ready(ds, sheet):
    """交给复核人之前要齐的：单子里的证据都人工核对过（规格第 4 节：人工已核之后才做专业复核）。
    返回还不行的 [(证据编号, 现在的状态)]。存疑的只要曾经人工核对过就行。"""
    out = []
    for eid in evidence_targets(sheet):
        e = A.evidence(ds, eid)
        st = e.get("verification_status") if isinstance(e, dict) else None
        ok = st in V.VERIFIED or (st == "disputed" and V.is_human(e.get("verified_by")))
        if not ok:
            out.append((eid, st))
    return out


# ---------------------------------------------------------------- 给人看

def _head(ctx, sheet):
    """这一组是什么（方案 5.6 复核单的第一部分）。"""
    ds, cid = ctx.ds, sheet.get("comparison_id")
    c = A.comparison(ds, cid) if cid else None
    names = ctx.names(sheet.get("topic_id"))
    if not isinstance(c, dict):
        return [f"不在可比组里的条目，共 {len(targets_of(sheet))} 条"] if not cid else [f"{cid}（可比组里没有这个编号）"]
    members = [m for m in c.get("members") or [] if isinstance(m, dict)]
    count = {r: sum(1 for m in members if m.get("role") == r) for r in ("member", "baseline", "reference", "excluded")}
    lines = [
        f"名称：{s(c.get('title'))}",
        f"层级和指标：{names.enum('level', c.get('level')) or NOT_FILLED}｜"
        + "、".join(names._name(names.indicators.get(k), k) for k in c.get("indicators") or [] if isinstance(k, str)),
        "成员：" + "，".join(f"{names.enum('member_role', r)} {count[r]}" for r in count if count[r] or r == "member"),
        f"档别：{names.enum('tier', c.get('tier')) or NOT_FILLED}（{names.enum('cmp_status', c.get('status')) or NOT_FILLED}）",
        f"定档理由：{s(c.get('tier_reason')) or NOT_FILLED}",
        f"归一化方法：{names.enum('normalization', c.get('normalization') or 'none')}",
    ]
    if c.get("missing"):
        lines.append(f"缺什么：{s(c['missing'])}")
    if c.get("missing_conditions"):
        lines.append("原文没写的条件：" + "、".join(names.condition(k) for k in c["missing_conditions"] if isinstance(k, str)))
    for m in members:
        if m.get("role") == "excluded":
            lines.append(f"排除的成员：{s(m.get('evidence_id'))}" + (f"（{s(m['note'])}）" if m.get("note") else ""))
    return lines


def baseline_context(ctx, sheet):
    """同一个基准膜、同一个指标在各来源里的数。基准膜的数值是不是异常要靠判断，脚本只把数摆出来，不下结论。"""
    ds = ctx.ds
    c = A.comparison(ds, sheet.get("comparison_id")) if sheet.get("comparison_id") else None
    if not isinstance(c, dict):
        return []
    wanted, mine = [], set(evidence_targets(sheet))
    for m in c.get("members") or []:
        e = A.evidence(ds, m.get("evidence_id")) \
            if isinstance(m, dict) and m.get("role") == "baseline" and m.get("evidence_id") in mine else None
        if isinstance(e, dict) and (e.get("subject_id"), e.get("indicator")) not in wanted:
            wanted.append((e.get("subject_id"), e.get("indicator")))
    lines = []
    for subject, indicator in wanted:
        same = [e for e in (A.evidence(ds, x) for x in sorted(A.evidence_ids(ds, c.get("topic_id")), key=ev_sort_key))
                if e.get("subject_id") == subject
                and e.get("indicator") == indicator and e.get("verification_status") != "void"]
        if len({e.get("source_id") for e in same}) < 2:
            continue
        for e in same:
            d = describe(ctx, e["id"])
            lines.append(f"{e['id']}　{d['what']}　{d['conditions']}")
    return lines


def _item_lines(ctx, sheet, it, names):
    target = s(it.get("target_id"))
    lines = []
    if target.startswith("EV-"):
        d = describe(ctx, target)
        lines.append(f"{target}　{d['what']}")
        if d["conditions"]:
            lines.append(f"条件：{d['conditions']}")
        if d["where"]:
            lines.append(f"出处：{d['where']}")
    elif target.startswith("ASM-"):
        lines.append(f"{target}（数据概览的陈述）")
    else:
        lines.append(f"{target}（这一组的档别）")
    lines.append(f"为什么要看：{why_text(names, it)}")
    lines.append(f"参考判断：{sentence(it.get('suggestion'))}")
    decided = names.enum("review_decision", it.get("decision")) or s(it.get("decision"))
    extra = "".join([f"；复核人的话：{s(it['note'])}" if it.get("note") else "",
                     f"；变化记录：{'、'.join(it['change_ids'])}" if it.get("change_ids") else ""])
    lines.append(f"决定：{decided}{extra}")
    return lines


def render_text(ctx, sheet):
    """给人看的一份：这一组是什么；要逐条看的；不用逐条看的；基准膜在各来源里的数。"""
    ds, names = ctx.ds, ctx.names(sheet.get("topic_id"))
    state = names.enum("review_status", sheet.get("status")) or s(sheet.get("status"))
    who = f"复核人 {s(sheet.get('reviewer'))}，{s(sheet.get('reviewed_at'))}" if sheet.get("reviewer") else "还没有复核"
    out = [f"# {sheet['id']}　{s(sheet.get('title'))}",
           f"{state}｜起草 {s(sheet.get('created_by'))}，{s(sheet.get('created_at'))}｜{who}"]
    if sheet.get("comparison_id"):
        out.append(f"看板里的位置：对标视图 #{sheet['comparison_id']}")
    waiting = not_ready(ds, sheet) if sheet.get("status") != "closed" else []
    if waiting:
        out.append("还不能交给复核人，这几条没有人工核对过："
                   + "、".join(f"{eid}（{names.enum('verification_status', st) or '证据库里没有'}）" for eid, st in waiting))
    out += ["", "## 这一组是什么"] + [f"- {x}" for x in _head(ctx, sheet)]
    items = [it for it in sheet.get("items") or [] if isinstance(it, dict)]
    out += ["", f"## 要逐条看的（{len(items)} 条）"]
    for n, it in enumerate(items, 1):
        lines = _item_lines(ctx, sheet, it, names)
        out += [f"{n}. {lines[0]}"] + [f"   {x}" for x in lines[1:]]
    batch = sheet.get("batch") if isinstance(sheet.get("batch"), dict) else None
    if batch:
        ids, sampled = list(batch.get("evidence_ids") or []), list(batch.get("sampled") or [])
        out += ["", f"## 不用逐条看的（{len(ids)} 条，默认成批确认）"]
        if len(sampled) < len(ids):
            out.append(f"随机抽了 {len(sampled)} 条：")
        for eid in sampled:
            d = describe(ctx, eid)
            out.append(f"- {eid}　{d['what']}" + (f"　{d['conditions']}" if d["conditions"] else ""))
        rest = [x for x in ids if x not in sampled]
        if rest:
            out.append("其余：" + "、".join(rest))
        out.append(f"决定：{names.enum('review_decision', batch.get('decision')) or s(batch.get('decision'))}")
    context = baseline_context(ctx, sheet)
    if context:
        out += ["", "## 同一个基准膜在各来源里的数", "基准膜的数值是不是异常，由起草的人和复核人判断；这里只把数摆出来。"]
        out += [f"- {x}" for x in context]
    if sheet.get("notes"):
        out += ["", f"备注：{s(sheet['notes'])}"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- 对话里的点选题

def _options(confirm_label, confirm_text, modify_text):
    return [{"label": confirm_label, "description": confirm_text, "decision": "confirm"},
            {"label": "要改", "description": modify_text, "decision": "modify"},
            {"label": "先不定", "description": "这一项留着，单子先不算复核完。", "decision": "pending"}]


def question_pack(ctx, sheet):
    """把单子变成对话里出点选题用的一份（D-27：题目自带背景，选项里第一个是参考判断）。

    一轮最多四题。每题的 key 是条目的编号（成批确认的那一题是 batch），回答照 key 填进 answers。
    """
    ds, names = ctx.ds, ctx.names(sheet.get("topic_id"))
    items = [it for it in sheet.get("items") or [] if isinstance(it, dict)]
    batch = sheet.get("batch") if isinstance(sheet.get("batch"), dict) else None
    total = len(items) + (1 if batch else 0)
    place = f"{sheet['comparison_id']}“{s((A.comparison(ds, sheet['comparison_id']) or {}).get('title'))}”" \
        if sheet.get("comparison_id") else "不在可比组里的条目"
    questions = []
    for n, it in enumerate(items, 1):
        target = s(it.get("target_id"))
        if target.startswith("EV-"):
            d = describe(ctx, target)
            text = f"{place}里的一条证据 {target}：" + sentence(d["what"])
            text += sentence("条件：" + d["conditions"]) if d["conditions"] else ""
            text += sentence("出处：" + d["where"]) if d["where"] else ""
            label = "同意参考判断"
        elif target.startswith("ASM-"):
            text, label = f"{place}的数据概览里的一句陈述（{target}）。", "同意这句陈述"
        else:
            c = A.comparison(ds, target) or {}
            text = f"可比组 {place}的档别。" + sentence("；".join(_head(ctx, sheet)[1:5]))
            label = f"同意，{names.enum('tier', c.get('tier')) or '照预归的档'}"
        text += f"为什么要你看：{why_text(names, it)}参考判断：{sentence(it.get('suggestion'))}"
        questions.append({"key": target, "header": f"条目 {n}/{total}"[:HEADER_MAX], "question": text, "multiSelect": False,
                          "options": _options(label, s(it.get("suggestion")), "选这一项后，接着说改成什么。")})
    if batch:
        ids, sampled = list(batch.get("evidence_ids") or []), list(batch.get("sampled") or [])
        shown = "；".join(f"{eid}：{describe(ctx, eid)['what']}" for eid in sampled)
        picked = f"随机抽了 {len(sampled)} 条给你看" if len(sampled) < len(ids) else "都列在这里"
        text = (f"{place}里其余 {len(ids)} 条证据，脚本没有看出要逐条看的理由，照约定成批确认。"
                f"{picked}：{shown}。这 {len(ids)} 条成批确认吗？")
        questions.append({"key": "batch", "header": f"成批 {total}/{total}"[:HEADER_MAX], "question": text, "multiSelect": False,
                          "options": [{"label": "成批确认", "description": f"这 {len(ids)} 条都算看过。", "decision": "confirm"},
                                      {"label": "有的要逐条看", "description": "选这一项后，接着说是哪几条、为什么；起草的人把它们挪到逐条看的里面再问。",
                                       "decision": "pending"},
                                      {"label": "先不定", "description": "这一项留着，单子先不算复核完。", "decision": "pending"}]})
    answers = {"reviewer": "", "date": "", "minutes": None, "minutes_note": "",
               "items": {q["key"]: {"decision": "pending", "note": ""} for q in questions if q["key"] != "batch"}}
    if batch:
        answers["batch"] = {"decision": "pending"}
    waiting = not_ready(ds, sheet) if sheet.get("status") != "closed" else []
    return {
        "sheet": sheet["id"], "title": s(sheet.get("title")), "comparison_id": sheet.get("comparison_id"),
        "status": s(sheet.get("status")),
        "not_ready": [{"evidence_id": eid, "status": st} for eid, st in waiting],
        "intro": _head(ctx, sheet),
        "rounds": [questions[i:i + ROUND_SIZE] for i in range(0, len(questions), ROUND_SIZE)],
        "answers": answers,
        "how": ["照 rounds 的次序一轮一轮出题，一轮最多四题；出题之前先把 intro 和 show 的那一份给复核人看。",
                "复核人选“要改”的，接着问改成什么，记在 note 里；照他说的改数据、记变化记录，再把变化记录的编号填进 change_ids。",
                "复核人自己写的话记在 note 里。回答照 answers 的样子存成文件，交给 apply。reviewer 写复核人的代号，必须是人。",
                "minutes 写复核人看这张单子实际用的分钟数：出题前后各看一次时间。当时没记就写 minutes_note 说明，不估算、不补记。"],
    }


# ---------------------------------------------------------------- 把回答写回数据

def _check_answers(ds, sheet, answers):
    if not isinstance(answers, dict):
        raise ReviewError("回答文件应是一个对象：reviewer、date、minutes、items、batch")
    unknown = sorted(set(answers) - {"reviewer", "date", "minutes", "minutes_note", "items", "batch", "notes"})
    if unknown:
        raise ReviewError(f"回答文件里有不认识的字段：{'、'.join(unknown)}")
    reviewer, date = answers.get("reviewer"), answers.get("date") or store.today()
    if not (V.is_human(reviewer) and re.match(r"^[a-z][a-z0-9-]*$", reviewer)):
        raise ReviewError(f"复核人必须是人（写代号，如 kai、expert-01），现在是 {reviewer!r}。AI 和脚本不能代答")
    if not (isinstance(date, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", date)):
        raise ReviewError(f"日期要写成 2026-11-20 这样，现在是 {date!r}")
    minutes, note = answers.get("minutes"), answers.get("minutes_note")
    timed = isinstance(minutes, (int, float)) and not isinstance(minutes, bool) and minutes >= 0
    if minutes is not None and not timed:
        raise ReviewError(f"minutes 要是不小于 0 的数，现在是 {minutes!r}")
    if not timed and not (isinstance(note, str) and note.strip()):
        raise ReviewError("工作记录要实记复核人用的分钟数（minutes）；当时没记就写 minutes_note 说明")
    known = {it.get("target_id"): it for it in sheet.get("items") or [] if isinstance(it, dict)}
    given = answers.get("items") or {}
    if not isinstance(given, dict):
        raise ReviewError("items 应是 条目编号 → {decision, note, change_ids}")
    changes = {c.get("id") for c in A.changes(ds) if isinstance(c, dict)}
    for target, a in given.items():
        if target not in known:
            raise ReviewError(f"{target} 不是 {sheet['id']} 里要逐条看的条目")
        if not isinstance(a, dict) or set(a) - {"decision", "note", "change_ids"}:
            raise ReviewError(f"{target} 的回答应是 {{decision, note, change_ids}}")
        if a.get("decision") not in DECISIONS:
            raise ReviewError(f"{target} 的决定要是 confirm、modify、pending 之一，现在是 {a.get('decision')!r}")
        said = a.get("note")
        if said is not None and not isinstance(said, str):
            raise ReviewError(f"{target} 的 note 要是一句话")
        linked = a.get("change_ids") or []
        if not isinstance(linked, list) or [x for x in linked if x not in changes]:
            raise ReviewError(f"{target} 的 change_ids 里有变化记录里没有的编号：{linked!r}")
        if a["decision"] == "modify":
            if not (said and said.strip()) and not known[target].get("note"):
                raise ReviewError(f"{target} 决定是改，要在 note 里写改成什么")
            if not linked:
                raise ReviewError(f"{target} 决定是改：先照复核人说的改数据、记变化记录，再把变化记录的编号填进 change_ids 一起写回；"
                                  "一时改不了的，决定先留 pending，把复核人的话记在 note 里")
        elif linked:
            raise ReviewError(f"{target} 的决定不是改，不用写 change_ids")
    b = answers.get("batch")
    if b is not None:
        if not isinstance(sheet.get("batch"), dict):
            raise ReviewError(f"{sheet['id']} 没有成批确认的条目")
        if not isinstance(b, dict) or set(b) - {"decision"} or b.get("decision") not in ("confirm", "pending"):
            raise ReviewError("成批确认的回答只能是 confirm 或 pending；有哪几条不同意，用 add 把它们挪到逐条看的里面再问")
    if answers.get("notes") is not None and not (isinstance(answers["notes"], str) and answers["notes"].strip()):
        raise ReviewError("notes 要是一句话")
    return reviewer, date, (minutes if timed else None), (note.strip() if not timed else None)


def apply_answers(ds, schema, sheet_id, answers):
    """把复核人的回答写进内存里的数据。返回 (说明, 要写回的文件, 工作记录)。不合规矩的抛 ReviewError，数据不要再用。

    要写回的文件：{"reviews": 题目, "comparisons": 题目或 None, "assessments": 题目或 None, "sources": [来源编号]}。
    """
    if A.problems(ds):
        raise ReviewError("数据里有读不了的文件或重复的编号，先修好再写回：" + "；".join(f"{p.record} {p.message}" for p in A.problems(ds)))
    sheet = A.review(ds, sheet_id)
    if not isinstance(sheet, dict):
        raise ReviewError(f"没有这张复核单：{sheet_id}")
    if sheet.get("status") == "closed":
        raise ReviewError(f"{sheet_id} 已经复核完了，不能再改；要补看就另起一张")
    if sheet.get("status") != "sent":
        raise ReviewError(f"{sheet_id} 还没有交给复核人：先用 questions --send 交出去")
    waiting = not_ready(ds, sheet)
    if waiting:
        raise ReviewError("这几条证据还没有人工核对过，不能做专业复核：" + "、".join(eid for eid, _ in waiting))
    reviewer, date, minutes, minutes_note = _check_answers(ds, sheet, answers)
    before = set(V.validate(ds, schema))
    said = []
    given = [a for a in (answers.get("items") or {}).values()]
    # 工作记录里记这一次的：这次同意了几条、改了几条、单子里还剩几条没定、带到了几条证据上
    counts = {"confirmed": sum(1 for a in given if a["decision"] == "confirm"),
              "modified": sum(1 for a in given if a["decision"] == "modify"), "left_pending": 0, "evidence_reviewed": 0}

    for it in sheet.get("items") or []:
        a = (answers.get("items") or {}).get(it.get("target_id")) if isinstance(it, dict) else None
        if not a:
            continue
        it["decision"] = a["decision"]
        if a.get("change_ids"):
            store.put_after(it, "change_ids", list(a["change_ids"]), ["decision"])
        if a.get("note") and a["note"].strip():
            store.put_after(it, "note", a["note"].strip(), ["change_ids", "decision"])
    if answers.get("batch"):
        sheet["batch"]["decision"] = answers["batch"]["decision"]
    if answers.get("notes"):
        sheet["notes"] = answers["notes"].strip()

    items = [it for it in sheet.get("items") or [] if isinstance(it, dict)]
    batch = sheet.get("batch") if isinstance(sheet.get("batch"), dict) else None
    agreed = sum(1 for it in items if it.get("decision") == "confirm")
    changed = sum(1 for it in items if it.get("decision") == "modify")
    counts["left_pending"] = sum(1 for it in items if it.get("decision") == "pending")
    done = not counts["left_pending"] and (not batch or batch.get("decision") == "confirm")
    touched = {"reviews": sheet.get("topic_id"), "comparisons": None, "assessments": None, "sources": []}

    if done:
        sheet["status"] = "closed"
        store.put_after(sheet, "reviewer", reviewer, ["created_at"])
        store.put_after(sheet, "reviewed_at", date, ["reviewer"])
        said.append(f"{sheet_id} 复核完了：同意 {agreed} 条，改 {changed} 条"
                    + (f"，成批确认 {len(batch.get('evidence_ids') or [])} 条" if batch else ""))
        c = A.comparison(ds, sheet.get("comparison_id")) if sheet.get("comparison_id") else None
        if isinstance(c, dict):
            # 这张单子加上以前复核完的单子，把成员都看到了，这一组才算专业已复核（V-48）
            seen = set(targets_of(sheet))
            for r in (A.review(ds, rid) for rid in A.review_ids(ds, c["id"])):
                if r.get("status") == "closed":
                    seen |= set(targets_of(r))
            left = [m.get("evidence_id") for m in c.get("members") or []
                    if isinstance(m, dict) and m.get("role") != "excluded" and m.get("evidence_id") not in seen]
            own = next((it for it in items if it.get("target_id") == c["id"]), None)
            if own and (c.get("status") == "draft" or own.get("decision") == "modify"):
                store.put_after(c, "decided_by", reviewer, ["status"])
                store.put_after(c, "decided_at", date, ["decided_by"])
            if left:
                said.append(f"{c['id']} 还有成员不在复核完的单子里：{'、'.join(left)}；这一组先不标专业已复核")
                if c.get("status") == "draft" and own:
                    c["status"] = "decided"
            elif c.get("status") != "expert_reviewed":
                c["status"] = "expert_reviewed"
                store.put_after(c, "expert_reviewed_by", reviewer, ["decided_at", "decided_by", "status"])
                store.put_after(c, "expert_reviewed_at", date, ["expert_reviewed_by"])
                said.append(f"{c['id']} 标成专业已复核")
            touched["comparisons"] = c.get("topic_id")
        for eid in evidence_targets(sheet):
            e = A.evidence(ds, eid)
            if e.get("verification_status") == "human_verified":
                e["verification_status"] = "expert_reviewed"
                store.put_after(e, "expert_reviewed_by", reviewer, ["verified_at", "verified_by", "verification_status"])
                store.put_after(e, "expert_reviewed_at", date, ["expert_reviewed_by"])
                counts["evidence_reviewed"] += 1
                if e.get("source_id") not in touched["sources"]:
                    touched["sources"].append(e.get("source_id"))
        if counts["evidence_reviewed"]:
            said.append(f"{counts['evidence_reviewed']} 条证据标成专业已复核")
        for it in items:
            a = A.assessment(ds, it.get("target_id")) if s(it.get("target_id")).startswith("ASM-") else None
            if isinstance(a, dict) and a.get("status") == "draft":
                a["status"] = "reviewed"
                store.put_after(a, "reviewed_by", reviewer, ["drafted_by", "status"])
                store.put_after(a, "reviewed_at", date, ["reviewed_by"])
                touched["assessments"] = a.get("topic_id")
                said.append(f"{a['id']} 标成已复核")
    else:
        waits = ([f"{counts['left_pending']} 条还没有定"] if counts["left_pending"] else []) \
            + (["成批确认的那一项还没有定"] if batch and batch.get("decision") != "confirm" else [])
        said.append(f"{sheet_id} 记下了回答，还没有复核完：" + "；".join(waits))

    log = {"id": I.next_ids(ds, "LOG")[0], "date": date, "topic_id": sheet.get("topic_id"), "arm": "C", "step": "expert_review",
           "actor_kind": "human", "actor": reviewer,
           "summary": f"看 {sheet_id}" + (f"（{sheet['comparison_id']}）" if sheet.get("comparison_id") else "")
                      + ("，复核完" if done else "，还没有复核完")}
    if minutes is not None:
        log["minutes"] = minutes
    else:
        log["minutes_note"] = minutes_note
    log.update(refs=[sheet_id], counts=counts)
    store.stage_log(ds, log)
    said.append(f"工作记录加了一条 {log['id']}")

    worse = sorted(set(V.validate(ds, schema)) - before, key=lambda x: (x.rule, s(x.record), x.message))
    if worse:
        raise ReviewError("照这份回答写回之后校验不过，什么也没有写：\n"
                          + "\n".join(f"  {x.rule}　{x.record}　{x.message}" for x in worse))
    return said, touched, log


def save_applied(ds, touched, log):
    for coll in ("reviews", "comparisons", "assessments"):
        if touched.get(coll):
            store.save_topic(ds, touched[coll], coll)
    store.save_sources(ds, [x for x in touched["sources"] if store.has_file(ds, x)])
    store.append_worklog(ds, log)


# ---------------------------------------------------------------- 命令行

def _load(args):
    if not os.path.isdir(args.data):
        print(f"找不到数据目录：{args.data}", file=sys.stderr)
        return None
    ds, schema = A.load(args.data), V.load_schema()
    return ds, schema, Ctx(ds, schema, B.load_labels(args.data))


def _sheet_of(ds, rid):
    sheet = A.review(ds, rid)
    if not isinstance(sheet, dict):
        raise ReviewError(f"没有这张复核单：{rid}")
    return sheet


def _guard_write(ds):
    if A.problems(ds):
        raise ReviewError("数据里有读不了的文件或重复的编号，先修好再写：" + "；".join(f"{p.record} {p.message}" for p in A.problems(ds)))


def cmd_draft(args, ds, schema, ctx):
    date = args.date or store.today()
    if not (V.is_human(args.by) or args.by in V.NOT_HUMAN) or not re.match(r"^[a-z][a-z0-9-]*$", args.by):
        raise ReviewError(f"起草人写代号，如 claude、yu，现在是 {args.by!r}")
    made, skipped = [], []

    def keep(sheet):
        # 起草好的先放进内存里的数据：下一张起草时看得到它，编号也接着往下排
        store.stage(ds, "reviews", sheet)
        made.append(sheet)

    if args.targets:
        keep(draft_loose(ctx, args.targets, I.next_ids(ds, "RVW")[0], args.by, date))
    else:
        for cid in args.comparison or A.comparison_ids(ds):
            c = A.comparison(ds, cid)
            if not isinstance(c, dict):
                raise ReviewError(f"没有这个可比组：{cid}")
            sheet, why = draft_group(ctx, c, I.next_ids(ds, "RVW")[0], args.by, date)
            if sheet:
                keep(sheet)
            else:
                skipped.append((cid, why))
    for cid, why in skipped:
        print(f"{cid}：不用起草，{why}")
    if not made:
        print("没有要起草的复核单")
        return 0
    if args.write:
        _guard_write(ds)
    for sheet in made:
        print(render_text(ctx, sheet))
    if not args.write:
        print(f"起草了 {len(made)} 张，没有写进数据（加 --write 才写）")
        return 0
    for tid in sorted({sheet["topic_id"] for sheet in made}):
        store.save_topic(ds, tid, "reviews", [sheet["id"] for sheet in made if sheet["topic_id"] == tid])
    print(f"起草了 {len(made)} 张，写进了 reviews.json：{'、'.join(sheet['id'] for sheet in made)}")
    return 0


def cmd_add(args, ds, schema, ctx):
    sheet = _sheet_of(ds, args.sheet)
    _guard_write(ds)
    add_item(ctx, sheet, args.target, args.reason, args.why, args.suggestion)
    store.save_topic(ds, sheet["topic_id"], "reviews")
    print(f"{args.sheet} 加了一条要逐条看的：{args.target}")
    return 0


def summary_line(ctx, sheet):
    """一张单子到了哪一步：一行。"""
    names = ctx.names(sheet.get("topic_id"))
    items = [it for it in sheet.get("items") or [] if isinstance(it, dict)]
    open_items = sum(1 for it in items if it.get("decision") == "pending")
    batch = sheet.get("batch") if isinstance(sheet.get("batch"), dict) else None
    parts = [f"逐条看 {len(items)} 条" + (f"（未定 {open_items}）" if open_items else "")]
    if batch:
        decided = names.enum("review_decision", batch.get("decision")) or s(batch.get("decision"))
        parts.append(f"成批确认 {len(batch.get('evidence_ids') or [])} 条（{decided}）")
    waiting = not_ready(ctx.ds, sheet) if sheet.get("status") != "closed" else []
    if waiting:
        parts.append(f"{len(waiting)} 条还没有人工核对")
    who = f"，{s(sheet.get('reviewer'))} {s(sheet.get('reviewed_at'))}" if sheet.get("reviewer") else ""
    state = names.enum("review_status", sheet.get("status")) or s(sheet.get("status"))
    return f"{sheet['id']}　{s(sheet.get('comparison_id')) or '不在可比组里的条目'}　{state}{who}：" + "，".join(parts)


def cmd_list(args, ds, schema, ctx):
    sheets = [r for r in (A.review(ds, rid) for rid in A.review_ids(ds)) if isinstance(r, dict)]
    for sheet in sheets:
        print(summary_line(ctx, sheet))
    without = [cid for cid in A.comparison_ids(ds) if isinstance(A.comparison(ds, cid), dict)
               and not any(r.get("comparison_id") == cid for r in sheets)]
    if without:
        print("还没有复核单的可比组：" + "、".join(without))
    if not sheets and not without:
        print("没有复核单，也没有可比组")
    return 0


def cmd_show(args, ds, schema, ctx):
    print(render_text(ctx, _sheet_of(ds, args.sheet)), end="")
    return 0


def cmd_questions(args, ds, schema, ctx):
    sheet = _sheet_of(ds, args.sheet)
    if args.send:
        if sheet.get("status") == "closed":
            raise ReviewError(f"{args.sheet} 已经复核完了")
        waiting = not_ready(ds, sheet)
        if waiting:
            names = ctx.names(sheet.get("topic_id"))
            raise ReviewError("还不能交给复核人，这几条证据没有人工核对过：" + "、".join(
                f"{eid}（{names.enum('verification_status', st) or '证据库里没有'}）" for eid, st in waiting))
        if sheet.get("status") == "draft":
            _guard_write(ds)
            sheet["status"] = "sent"
            store.save_topic(ds, sheet["topic_id"], "reviews")
            print(f"{args.sheet} 交给复核人了，状态改成已交复核人", file=sys.stderr)
    text = store.dumps(question_pack(ctx, sheet))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"点选题写到了 {args.out}", file=sys.stderr)
    else:
        print(text, end="")
    return 0


def cmd_apply(args, ds, schema, ctx):
    try:
        with open(args.answers, encoding="utf-8") as f:
            answers = json.load(f)
    except (OSError, ValueError) as exc:
        print(f"读不了回答文件 {args.answers}：{exc}", file=sys.stderr)
        return 2
    said, touched, log = apply_answers(ds, schema, args.sheet, answers)
    save_applied(ds, touched, log)
    print("\n".join(said))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="复核单：起草、给人看、出点选题、把回答写回数据")
    ap.add_argument("--data", default=V.DEFAULT_DATA, help="数据目录，默认是仓库里的 data/")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("draft", help="起草")
    p.add_argument("--comparison", nargs="+", metavar="CMP-编号", help="只起草这几个可比组的；不写就是全部")
    p.add_argument("--targets", nargs="+", metavar="编号", help="不在可比组里的条目另开一张：证据或数据概览陈述的编号")
    p.add_argument("--by", default="claude", help="起草人的代号，默认 claude")
    p.add_argument("--date", help="起草日期，默认今天")
    p.add_argument("--write", action="store_true", help="写进数据；不加只看")
    p.set_defaults(run=cmd_draft)
    p = sub.add_parser("add", help="加一条要逐条看的")
    p.add_argument("sheet", metavar="RVW-编号")
    p.add_argument("--target", required=True, help="证据、可比组或数据概览陈述的编号")
    p.add_argument("--reason", required=True, help="理由的代码，如 baseline_anomaly")
    p.add_argument("--why", required=True, help="具体说明")
    p.add_argument("--suggestion", required=True, help="参考判断")
    p.set_defaults(run=cmd_add)
    p = sub.add_parser("list", help="现在有哪些复核单，各到了哪一步")
    p.set_defaults(run=cmd_list)
    p = sub.add_parser("show", help="给人看的一份")
    p.add_argument("sheet", metavar="RVW-编号")
    p.set_defaults(run=cmd_show)
    p = sub.add_parser("questions", help="对话里出点选题用的一份")
    p.add_argument("sheet", metavar="RVW-编号")
    p.add_argument("--send", action="store_true", help="交给复核人：状态改成已交复核人")
    p.add_argument("--out", metavar="文件", help="写到文件；不写就打在屏幕上")
    p.set_defaults(run=cmd_questions)
    p = sub.add_parser("apply", help="把复核人的回答写回数据")
    p.add_argument("sheet", metavar="RVW-编号")
    p.add_argument("--answers", required=True, metavar="文件", help="回答文件")
    p.set_defaults(run=cmd_apply)
    args = ap.parse_args(argv)
    if args.command == "draft" and args.comparison and args.targets:
        ap.error("--comparison 和 --targets 只能用一个")
    loaded = _load(args)
    if not loaded:
        return 2
    try:
        return args.run(args, *loaded)
    except ReviewError as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
