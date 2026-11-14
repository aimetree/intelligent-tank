"""数据概览与缺口（K5）：每组数据说了什么，缺什么（设计方案 4.2；样张第四页）。

- 一览表：行是膜，列是有数据的指标（指标清单上同一个编号的并成一列）。每格列出这张膜这一项的每一条证据：
  数值、关键条件、缺哪些必填条件、标注、与同文基准之比（脚本现算的换算值）、证据编号和核验状态。
  不打分、不排名；条件不同的数只是摆在一起，不比大小（D-62、D-67）。事实项不进一览表（D-124）。
- 数据概览：数据文件里的描述（ASM）逐条列出，每句后面是它依据的可比组和证据（设计方案 4.4 第 8 项）。
  陈述是人定稿的，这里只照数据显示，不由脚本写。
- 查了什么、读到多少：工作记录里的检索，和来源登记里纳入、排除、读到哪里的数。
- 必填条件，几个来源没有报告；其他缺口。
- 不属于任何可比组的复核单（规格 3.13）。
只整理和描述（D-60）。对外报告的“数据概览”“覆盖与缺口”两节用的是同一份数据。
"""
import compare_view
import derive
import topicdata as T
import validate as V
from display import NOT_FILLED, cls, fmt_num, s
from htmlgen import el

MAX_LINES = 6           # 一览表一格里最多列几条，多的写“另有几条”
COMPARABLE = V.COMPARABLE_LEVELS


def key_conditions(ds, topic_id):
    """每个指标并排时要看的关键条件：取自指标字典里各条可比规则的 key_conditions，照规则的次序。"""
    out = {}
    for rule in (ds["dictionaries"].get(topic_id) or {}).get("rules") or []:
        if not isinstance(rule, dict):
            continue
        for ind in rule.get("applies_to") or []:
            for k in rule.get("key_conditions") or []:
                if k not in out.setdefault(ind, []):
                    out[ind].append(k)
    return out


def entry(r, group, keyconds, ds, lk, names):
    """一览表格子里的一条：数值，和跟着它走的说明。"""
    e = r["e"]
    notes = []
    if len(group["keys"]) > 1:
        notes.append(r["measure"])
    conds = {c["key"]: c for c in r["conditions"]}
    notes += [conds[k]["text"] for k in keyconds.get(r["measure_key"], []) if k in conds and conds[k]["state"] == "reported"]
    missing = [c["name"] for c in r["conditions"] if c["state"] in ("not_reported", "absent")]
    if missing:
        notes.append("缺" + "、".join(missing))
    src = ds["sources"].get(r["source_id"])
    flags = [names.flag(k) for k in V.display_flags(e, src if isinstance(src, dict) else {})]
    if r["type"] not in ("experimental", "company_claim") and r["type_label"]:
        flags.insert(0, r["type_label"])
    notes += flags
    ratio = derive.baseline_ratio(e, ds, lk) if e.get("baseline_ref") else None
    if ratio and ratio["ratio"] is not None:
        notes.append(f"与同文基准之比 {fmt_num(round(ratio['ratio'], 3))}（换算值，基准 {ratio['base_id']}）")
    return {"id": r["id"], "value": r["value"], "flag": r["value_flag"], "notes": notes, "status": r["status"],
            "status_label": r["status_label"]}


def summary_table(m, ds, topic_id, mems):
    names = m["names"]
    lk = V.Lookups(ds)
    keyconds = key_conditions(ds, topic_id)
    groups = T.indicator_groups(names)
    cols = [g for g in groups if any(T.cell(mem, g)["rows"] for mem in mems)]
    empty_core = [g["label"] for g in groups if g["core"] and g not in cols]
    rows = []
    for mem in mems:
        cells = []
        for g in cols:
            c = T.cell(mem, g)
            cells.append({"state": c["state"], "entries": [entry(r, g, keyconds, ds, lk, names) for r in c["rows"]]})
        rows.append({"mem": mem, "cells": cells})
    return {"cols": cols, "rows": rows, "empty_core": empty_core}


def statements(m, ds, topic_id):
    """数据概览里的陈述，照编号排。每句的依据：可比组带档别，证据带核验状态；还没到“专业已复核”的依据单独点出来。"""
    names, by_id = m["names"], {r["id"]: r for r in m["rows"]}
    out = []
    for aid in sorted(ds["assessments"]):
        a = ds["assessments"][aid]
        if not isinstance(a, dict) or a.get("topic_id") != topic_id:
            continue
        basis, not_ready = [], []
        for x in a.get("basis") or [] if isinstance(a.get("basis"), list) else []:
            x = s(x)
            c, r, rel = ds["comparisons"].get(x), by_id.get(x), ds["relations"].get(x)
            if isinstance(c, dict):
                basis.append({"id": x, "href": f"#{x}", "note": names.enum("tier", c.get("tier")) or NOT_FILLED})
                if c.get("status") != "expert_reviewed":
                    not_ready.append(x)
            elif r:
                basis.append({"id": x, "href": f"#{x}", "note": r["status_label"]})
                if r["status"] != "expert_reviewed":
                    not_ready.append(x)
            elif isinstance(rel, dict):
                basis.append({"id": x, "href": "", "note": names.enum("relation_type", rel.get("relation_type"))})
            else:
                basis.append({"id": x, "href": "", "note": "数据里没有这个编号"})
                not_ready.append(x)
        extra = [(names.field("assessment", k), s(a[k])) for k in ("conditions", "unknowns", "assumptions", "disagreements") if a.get(k)]
        who = [f"{names.field('assessment', 'drafted_by')} {s(a.get('drafted_by')) or NOT_FILLED}"]
        if a.get("reviewed_by") or a.get("reviewed_at"):
            who.append(f"{names.field('assessment', 'reviewed_by')} {s(a.get('reviewed_by'))}，{s(a.get('reviewed_at'))}")
        out.append({"id": aid, "statement": s(a.get("statement")) or NOT_FILLED, "status": s(a.get("status")),
                    "status_label": names.enum("asm_status", a.get("status")) or NOT_FILLED, "question": s(a.get("question")),
                    "basis": basis, "not_ready": not_ready, "extra": extra, "who": "；".join(who)})
    return out


def searches(ds, topic_id):
    out = []
    for w in ds["worklog"]:
        if isinstance(w, dict) and w.get("topic_id") == topic_id and isinstance(w.get("search"), dict):
            q = w["search"]
            out.append({"id": s(w.get("id")), "date": s(w.get("date")), "where": s(q.get("where")), "query": s(q.get("query")),
                        "hits": q.get("hits"), "screened": q.get("screened"), "included": q.get("included")})
    return out


def funnel(m, sources):
    """来源登记里的数：登记了几个，纳入、排除、还没定各几个；纳入的读到哪里。"""
    names = m["names"]
    inc = T.included(sources)
    rows = [("登记的来源", len(sources), "")]
    for code, n in T.counted([s(e.get("decision")) for _, _, e in sources], names.enum_order("screening_decision")):
        ids = [sid for sid, _, e in sources if s(e.get("decision")) == code]
        rows.append((names.enum("screening_decision", code) or NOT_FILLED, n, "、".join(ids) if code != "included" else ""))
    for code, n in T.counted([s(src.get("access_scope")) for _, src, _ in inc], names.enum_order("access_scope")):
        ids = [sid for sid, src, _ in inc if s(src.get("access_scope")) == code]
        rows.append((f"纳入的里面：{names.enum('access_scope', code) or NOT_FILLED}", n, "、".join(ids) if code != "full" else ""))
    reasons = [(sid, s(e.get("exclusion_reason"))) for sid, _, e in sources if e.get("decision") == "excluded"]
    return rows, reasons


def missing_conditions(m, ds, topic_id):
    """某一层统一必填的条件，各有几个来源没有报告：只数在这一层有证据的来源。"""
    names = m["names"]
    level_conditions = (ds["dictionaries"].get(topic_id) or {}).get("level_conditions")
    out = []
    for level, keys in (level_conditions.items() if isinstance(level_conditions, dict) else []):
        rows = [r for r in m["rows"] if r["level"] == level and r["measure_kind"] == "indicator" and r["status"] != "void" and not r["error"]]
        srcs = sorted({r["source_id"] for r in rows})
        items = []
        for k in keys if isinstance(keys, list) else []:
            lacking = sorted({r["source_id"] for r in rows
                              if any(c["key"] == k and c["state"] in ("not_reported", "absent") for c in r["conditions"])})
            items.append({"key": s(k), "name": names.condition(k), "n": len(lacking), "ids": lacking})
        out.append({"level": level, "level_label": names.enum("level", level) or s(level), "sources": len(srcs), "items": items})
    return out


def other_gaps(m, ds, topic_id, sources, mems):
    """其他缺口，每条一句，都是数出来的：[(键, 文字, 有关的编号)]。没有的不写。"""
    names, rows = m["names"], [r for r in m["rows"] if r["status"] != "void"]
    inc = T.included(sources)
    out = []

    def add(key, text, ids=()):
        out.append({"key": key, "text": text, "ids": list(ids)})

    with_samples = [sid for sid, _, _ in inc if ds["samples"].get(sid)]
    no_base = [sid for sid in with_samples
               if not any(isinstance(x, dict) and x.get("role") == "baseline" for x in ds["samples"][sid])]
    if no_base:
        add("no_baseline", f"登记了样品的 {len(with_samples)} 个来源里，{len(no_base)} 个没有同文基准膜，它的数据算不了与基准之比：", no_base)
    for code in ("abstract_only", "metadata_only"):
        ids = [sid for sid, src, _ in inc if src.get("access_scope") == code]
        if ids:
            tail = "，没有从中取数：" if code == "metadata_only" else "，从中取的数都带着这个标注："
            add(code, f"{names.enum('access_scope', code)}的来源 {len(ids)} 个{tail}", ids)
    unpaid = [sid for sid, src, _ in inc if isinstance(src.get("paid"), dict) and not src["paid"].get("purchased")]
    if unpaid:
        add("not_purchased", f"付费没有买、只用了公开部分的来源 {len(unpaid)} 个：", unpaid)
    for code, n in T.counted([s(src.get("status")) for _, src, _ in inc if src.get("status") not in (None, "active")], names.enum_order("source_status")):
        add("source_status", f"{names.enum('source_status', code) or NOT_FILLED}的来源 {n} 个：", [sid for sid, src, _ in inc if s(src.get("status")) == code])
    fig = [r for r in rows if r["e"].get("obtained_from") == "figure_read"]
    if fig:
        reread = sum(1 for r in fig if isinstance(r["e"].get("figure_read"), dict) and r["e"]["figure_read"].get("reread_by"))
        add("figure_read", f"{len(rows)} 条证据里 {len(fig)} 条是图上读数，其中 {reread} 条由人复读过：", [r["id"] for r in fig])
    by_status = dict(T.counted([r["status"] for r in rows]))
    waiting = [(names.enum("verification_status", code), by_status[code]) for code in ("disputed", "pending", "machine_checked") if by_status.get(code)]
    if waiting:
        add("not_verified", "、".join(f"{label} {n} 条" for label, n in waiting) + "，还不能用在报告里。")
    for cid in sorted(ds["comparisons"]):
        c = ds["comparisons"][cid]
        if isinstance(c, dict) and c.get("topic_id") == topic_id and c.get("tier") == "insufficient":
            add("insufficient", f"{names.enum('tier', 'insufficient')}的可比组：缺 {s(c.get('missing')) or NOT_FILLED}：", [cid])
    loose = [r["id"] for r in rows if r["measure_kind"] == "indicator" and r["level"] in COMPARABLE
             and r["e"].get("content_kind") != "statement" and not r["groups"]]
    if loose:
        add("ungrouped", f"材料、器件、系统三层里，还没有进任何可比组的数值 {len(loose)} 条：", loose)
    nothing = [mem for mem in mems if not any(r["status"] != "void" for r in mem["rows"])]
    if nothing:
        add("no_evidence", f"样品登记里有、还没有任何证据的膜 {len(nothing)} 张：" + "、".join(f"{x['label']}（{x['source_id'] or '商业产品'}）" for x in nothing) + "。")
    return out


def loose_reviews(m, ds, topic_id, wanted=None):
    """不属于任何可比组的复核单（规格 3.13）。wanted 用来挑：给它一张单子里证据条目的来源类别，返回要不要。"""
    by_id = {r["id"]: r for r in m["rows"]}
    out = []
    for r in compare_view.review_models({"id": None, "members": []}, ds, by_id, m["names"]):
        raw = ds["reviews"][r["id"]]
        if raw.get("topic_id") != topic_id:
            continue
        targets = [it["target"]["id"] for it in r["items"]] + [t["id"] for t in (r["batch"] or {}).get("ids", [])]
        types = {by_id[x]["source_type"] for x in targets if x in by_id}
        if wanted is None or wanted(types):
            out.append(r)
    return out


def build(m, ds, topic_id):
    sources = T.topic_sources(ds, topic_id)
    mems = T.membranes(ds, topic_id, m["names"], m["rows"])
    rows, reasons = funnel(m, sources)
    table, said = summary_table(m, ds, topic_id, mems), statements(m, ds, topic_id)
    reviewed = sum(1 for a in said if a["status"] == "reviewed")
    count = (f"{len(mems)} 张膜，{len(table['cols'])} 项指标有数据；数据概览 {len(said)} 句，其中已复核 {reviewed} 句。")
    return {"table": table, "statements": said, "count": count,
            "searches": searches(ds, topic_id), "funnel": rows, "excluded": reasons,
            "missing": missing_conditions(m, ds, topic_id), "gaps": other_gaps(m, ds, topic_id, sources, mems),
            "reviews": loose_reviews(m, ds, topic_id, lambda types: not types or not types <= T.BLOCK_TYPES)}


# ---------------------------------------------------------------- 写成网页

def bar(share):
    """一条横条：只表示数的大小。"""
    w = max(0.0, min(1.0, share)) * 100
    return el("svg", {"class": "bar", "viewBox": "0 0 100 8", "preserveAspectRatio": "none", "aria-hidden": "true", "focusable": "false"},
              el("rect", {"class": "bar-bg", "width": "100", "height": "8"}),
              el("rect", {"class": "bar-fill", "width": fmt_num(round(w, 2)), "height": "8"}))


def id_links(id_list, known):
    return [[("、" if i else ""), el("a", {"href": f"#{x}"}, x) if x in known else x] for i, x in enumerate(id_list)]


def render_cell(c):
    if not c["entries"]:
        text = {"not_reported": "未报告", "not_applicable": "不适用"}.get(c["state"], "—")
        sub = {"not_reported": "找过，原文没有写", "not_applicable": "找过，这一项不适用"}.get(c["state"])
        return el("td", {"data-state": c["state"]}, el("span", {"class": "muted"}, text), [" ", el("span", {"class": "sub"}, sub)] if sub else None)
    lines = []
    for x in c["entries"][:MAX_LINES]:
        note = "｜".join(x["notes"])
        lines.append(el("div", {"class": "entry", "data-ev": x["id"]},
                        el("span", {"class": "strong" + (" missing" if x["flag"] else "")}, x["value"]), " ",
                        el("span", {"class": "sub"}, note + "｜" if note else "", el("a", {"href": f"#{x['id']}"}, x["id"]), "｜",
                           el("span", {"class": "flag"} if x["status"] == "disputed" else None, x["status_label"]))))
    more = len(c["entries"]) - MAX_LINES
    if more > 0:
        lines.append(el("div", {"class": "note"}, f"另有 {more} 条，在", el("a", {"href": "#evidence"}, "证据表"), "里。"))
    return el("td", {"data-state": c["state"], "data-n": len(c["entries"])}, lines)


def render_table(t, names):
    head = el("div", {"class": "view-head"}, el("h2", None, "一览表：按膜摆出各项指标上的数据"))
    intro = el("p", {"class": "note"}, "不打分，不排名，行的次序是录入的次序。条件不同的数只是摆在一起，不比大小。每条后面是证据编号和核验状态，点了去",
               el("a", {"href": "#evidence"}, "证据表"), "里看原文片段和出处。")
    if not t["rows"] or not t["cols"]:
        why = "样品登记里还没有膜。" if not t["rows"] else "这些膜还没有任何一项指标的证据。"
        return el("section", {"class": "card", "id": "summary-table"}, head, intro, el("p", {"class": "empty"}, why))
    ths = [el("th", {"scope": "col"}, "膜"), el("th", {"scope": "col"}, "类别")] + [
        el("th", {"scope": "col"}, g["label"], " ", el("span", {"class": "sub"}, names.enum("level", g["level"]) or NOT_FILLED))
        for g in t["cols"]]
    body = []
    for r in t["rows"]:
        mem = r["mem"]
        where = mem["source_id"] if mem["kind"] == "lab" else "商业产品"
        roles = "、".join(names.enum("sample_role", x) for x in mem["roles"])
        body.append(el("tr", {"data-membrane": mem["key"]},
                       el("th", {"scope": "row"}, mem["label"], " ", el("span", {"class": "sub"}, "｜".join(x for x in (where, roles) if x))),
                       el("td", None, T.facet_text(mem)), [render_cell(c) for c in r["cells"]]))
    foot = ["“—”是还没有数据；“未报告”是逐项找过、原文没有写。企业声明、图上读数、预印本、专利实施例在格子里注明；与同文基准之比是脚本现算的换算值，不是证据。"]
    if t["empty_core"]:
        foot.append(f"核心指标里一条数据都还没有的：{'、'.join(t['empty_core'])}。")
    foot.append("专利权利要求、政策条款、报告里的数这些事实项不进一览表，见")
    return el("section", {"class": "card", "id": "summary-table", "aria-label": "一览表"}, head, intro,
              el("div", {"class": "table-wrap"}, el("table", {"class": "cmp-table sum-table"},
                 el("thead", None, el("tr", None, ths)), el("tbody", None, body))),
              el("p", {"class": "note"}, foot, el("a", {"href": "#non-academic"}, "非学术来源"), "。"))


def render_statements(items, known):
    head = el("div", {"class": "view-head"}, el("h2", None, "数据概览：逐组陈述数据说了什么"))
    intro = el("p", {"class": "note"}, "只陈述数量和范围，不写评价和建议。每句后面是它依据的可比组或证据。陈述由人定稿，报告引用的要已复核，依据要专业已复核。")
    if not items:
        return el("section", {"class": "card", "id": "statements"}, head, intro, el("p", {"class": "empty"}, "这个题目还没有写数据概览。"))
    out = []
    for a in items:
        basis = [[(" " if i else ""), el("span", {"class": "basis"}, el("a", {"href": b["href"]}, b["id"]) if b["href"] else b["id"], "｜", b["note"])]
                 for i, b in enumerate(a["basis"])]
        # 每段小字前面留一个空格：复制、查找、读屏时，两段文字不会粘在一起
        extra = [[" ", el("div", {"class": "sub"}, f"{k}：{v}")] for k, v in a["extra"]]
        warn = [" ", el("div", {"class": "sub"}, el("span", {"class": "missing"}, "依据里还没有到“专业已复核”的："), id_links(a["not_ready"], known))] if a["not_ready"] else None
        out.append(el("div", {"class": "statement", "id": a["id"], "data-status": a["status"]},
                      el("div", {"class": "statement-text"}, a["statement"], extra, warn),
                      el("div", {"class": "statement-side"},
                         el("div", None, el("span", {"class": "strong"}, a["id"]), "｜", a["question"] + "｜" if a["question"] else "",
                            el("span", {"class": f"asm asm-{cls(a['status'])}"}, a["status_label"])),
                         el("div", {"class": "sub"}, basis or "没有写依据"), el("div", {"class": "sub"}, a["who"]))))
    return el("section", {"class": "card", "id": "statements", "aria-label": "数据概览"}, head, intro, el("div", {"class": "statements"}, out))


def render_search(model, known):
    lines = [el("div", {"class": "line" + (" muted" if ids else "")}, el("span", None, label, [" ", el("span", {"class": "sub"}, ids)] if ids else None),
                " ", el("span", {"class": "strong"}, n)) for label, n, ids in model["funnel"]]
    body = [el("div", {"class": "lines"}, lines)]
    if model["searches"]:
        rows = [el("tr", None, el("td", None, q["date"]), el("td", None, q["where"]), el("td", None, q["query"]),
                   [el("td", None, fmt_num(q[k]) if q[k] is not None else "—") for k in ("hits", "screened", "included")])
                for q in model["searches"]]
        body.append(el("div", {"class": "table-wrap"}, el("table", {"class": "cmp-table", "id": "search-log"},
                    el("thead", None, el("tr", None, [el("th", {"scope": "col"}, h) for h in ("日期", "查了哪里", "怎么查", "命中", "筛过", "纳入")])),
                    el("tbody", None, rows))))
    else:
        body.append(el("p", {"class": "empty"}, "工作记录里还没有检索的记录。"))
    if model["excluded"]:
        body.append(el("p", {"class": "note"}, "排除的原因：", [[("；" if i else ""), sid, " ", why or NOT_FILLED] for i, (sid, why) in enumerate(model["excluded"])]))
    return el("section", {"class": "card third", "id": "search-funnel", "aria-label": "查了什么，读到多少"}, el("h2", None, "查了什么，读到多少"), body)


def render_missing(levels):
    body = []
    for lv in levels:
        items = [el("div", {"class": "meter", "data-condition": it["key"]},
                    el("div", {"class": "line"}, el("span", None, it["name"]), " ", el("span", {"class": "strong"}, f"{it['n']} / {lv['sources']}")),
                    bar(it["n"] / lv["sources"] if lv["sources"] else 0)) for it in lv["items"]]
        body.append(el("div", {"class": "lines", "data-level": lv["level"]}, items,
                       el("p", {"class": "note"}, f"{lv['level_label']}这一层：按在这一层有证据的 {lv['sources']} 个来源算，只看这一层统一必填的 {len(lv['items'])} 项。")))
    return el("section", {"class": "card third", "id": "missing-conditions", "aria-label": "必填条件，几个来源没有报告"},
              el("h2", None, "必填条件，几个来源没有报告"),
              body or el("p", {"class": "empty"}, "指标字典里没有哪一层规定统一必填的条件。"))


def render_gaps(items, known):
    lines = [el("div", {"class": "gap", "data-gap": g["key"]}, g["text"], id_links(g["ids"], known), "。" if g["ids"] else "") for g in items]
    return el("section", {"class": "card third", "id": "other-gaps", "aria-label": "其他缺口"}, el("h2", None, "其他缺口"),
              el("div", {"class": "lines"}, lines) if lines else el("p", {"class": "empty"}, "数据里没有数出别的缺口。"))


def render_reviews(reviews, names, title="不属于任何可比组的复核单"):
    if not reviews:
        return None
    return el("section", {"class": "card", "id": "loose-reviews", "aria-label": title}, el("h2", None, title),
              [compare_view.render_review(r, names) for r in reviews])


def render(model, m, title, question):
    names = m["names"]
    known = set(m["ids"]) | set((m.get("compare") or {}).get("group_ids") or ())
    return el("section", {"class": "view", "id": "gaps", "aria-label": title},
              el("section", {"class": "card"}, el("div", {"class": "view-head"}, el("h2", None, title), el("div", {"class": "note"}, question)),
                 el("p", {"class": "note", "id": "gaps-count"}, model["count"])),
              render_table(model["table"], names), render_statements(model["statements"], known),
              render_reviews(model["reviews"], names),
              el("div", {"class": "thirds"}, render_search(model, known), render_missing(model["missing"]), render_gaps(model["gaps"], known)),
              el("p", {"class": "note"}, "对外报告里的“数据概览”和“覆盖与缺口”两节，由这一页用的同一份数据生成。"))
