"""总览（K1）：这个题目做到什么程度，哪里有问题（设计方案 4.2；样张第一页）。

- 五个数：来源、膜、证据、可比组、存疑。
- 核到哪一步：各核验状态各有几条。
- 覆盖图：行是膜，列是核心指标（指标清单上同一个编号的并成一列）。格里是这一项里核得最深的那一条的核验状态；
  逐项找过、原文没有报告的写“未”；空着的就是缺口（设计方案 4.4 第 7 项、6.1）。
- 最近的变化、来源是怎么读的、工时与成本：首版只显示累计数，明细页（变化记录、质量与成本、来源与许可）后做（D-31）。
只数、只摆，不评价（D-60）。
"""
import access as A
import topicdata as T
from display import NOT_FILLED, as_text, cls, fmt_num, s
from htmlgen import el

STATUS_ORDER = ("expert_reviewed", "human_verified", "machine_checked", "pending", "disputed", "void")
# 覆盖图格子里的字：核验状态的头一个字。图例里写全称
CELL_TEXT = {"expert_reviewed": "复", "human_verified": "人", "machine_checked": "机", "pending": "待", "disputed": "疑",
             "unknown": "？", "not_reported": "未", "not_applicable": "不适用", "none": "—"}
RECENT = 8


def _join(pairs):
    return "，".join(f"{label} {n}" for label, n in pairs)


def tiles(m, ds, topic_id, sources, membranes):
    names, rows = m["names"], m["rows"]
    live = [r for r in rows if r["status"] != "void"]
    inc = T.included(sources)
    by_type = T.counted([s(src.get("source_type")) for _, src, _ in inc], names.enum_order("source_type"))
    labs = sum(1 for x in membranes if x["kind"] == "lab")
    ev_types = T.counted([r["type"] for r in live], names.enum_order("evidence_type"))
    groups = [A.comparison(ds, cid) for cid in A.comparison_ids(ds, topic_id)]
    tiers = T.counted([s(c.get("tier")) for c in groups], names.enum_order("tier"))
    disputed = [r for r in live if r["status"] == "disputed"]
    void = len(rows) - len(live)
    out = [
        {"key": "sources", "label": "来源", "n": len(inc),
         "sub": (_join((names.enum("source_type", k) or NOT_FILLED, n) for k, n in by_type) + f"；其中 {m['source_count']} 个录了证据")
         if inc else "还没有纳入的来源"},
        {"key": "membranes", "label": "膜", "n": len(membranes),
         "sub": f"实验室样品 {labs}，商业产品 {len(membranes) - labs}" if membranes else "样品登记里还没有膜"},
        {"key": "evidence", "label": "证据", "n": len(live),
         "sub": (_join((names.enum("evidence_type", k) or NOT_FILLED, n) for k, n in ev_types) or "还没有证据")
         + (f"；另有{names.enum('verification_status', 'void')} {void} 条，不算在内" if void else "")},
        {"key": "groups", "label": "可比组", "n": len(groups),
         "sub": _join((names.enum("tier", k) or NOT_FILLED, n) for k, n in tiers) or "还没有归组"},
        {"key": "disputed", "label": names.enum("verification_status", "disputed"), "n": len(disputed), "warn": bool(disputed),
         "sub": "", "ids": [r["id"] for r in disputed],
         "note": s(disputed[0]["e"].get("dispute_note")) if len(disputed) == 1 else ""},
    ]
    return out


def status_parts(m):
    counts = dict(T.counted([r["status"] for r in m["rows"]]))
    names = m["names"]
    parts = [(code, names.enum("verification_status", code), counts.pop(code, 0)) for code in STATUS_ORDER]
    parts += [(code, names.enum("verification_status", code) or NOT_FILLED, n) for code, n in sorted(counts.items())]
    return [p for p in parts if p[2] or p[0] not in ("void",)]


def coverage(m, membranes):
    names = m["names"]
    cols = [g for g in T.indicator_groups(names) if g["core"]]
    rows, with_data, not_reported = [], 0, 0
    for mem in membranes:
        cells = []
        for g in cols:
            c = T.cell(mem, g)
            with_data += 1 if c["rows"] else 0
            not_reported += 1 if c["state"] == "not_reported" else 0
            cells.append(c)
        rows.append({"mem": mem, "cells": cells})
    return {"cols": cols, "rows": rows, "total": len(cols) * len(rows), "with_data": with_data, "not_reported": not_reported,
            "skipped": T.skipped_indicators(names)}


def recent(m, ds, topic_id, sources):
    """最近的事，新的在前：登记了几个来源、几条证据；人工核对、专业复核各过了几条；变化记录。"""
    names, ids = m["names"], m["ids"]
    events = []

    def tally(dates):
        counts = {}
        for d in dates:
            if isinstance(d, str) and d:
                counts[d] = counts.get(d, 0) + 1
        return counts

    reg = tally(src.get("registered_at") for _, src, _ in sources)
    made = tally(r["e"].get("created_at") for r in m["rows"])
    for d in sorted(set(reg) | set(made)):
        what = "、".join(x for x in (f"{reg[d]} 个来源" if reg.get(d) else "", f"{made[d]} 条证据" if made.get(d) else "") if x)
        events.append((d, 0, [f"新登记 {what}。"]))
    for key, order, label in (("verified_at", 1, "人工核对"), ("expert_reviewed_at", 2, "专业复核")):
        for d, n in sorted(tally(r["e"].get(key) for r in m["rows"]).items()):
            events.append((d, order, [f"{label}过了 {n} 条。"]))
    for i, c in enumerate(A.changes(ds)):
        if not isinstance(c, dict) or not isinstance(c.get("date"), str):
            continue
        target = s(c.get("target_id"))
        if c.get("topic_id") != topic_id and not (c.get("topic_id") is None and target in ids):
            continue
        text = [el("a", {"href": f"#{target}"}, target) if target in ids else target, "：", s(c.get("reason")) or NOT_FILLED]
        if c.get("field"):
            text.append(f"；由“{as_text(c.get('before'))}”改为“{as_text(c.get('after'))}”")
        tags = [names.enum("change_kind", c.get("kind")),
                f"错误类型：{names.enum('error_type', c.get('error_type'))}" if c.get("error_type") else ""]
        text.append("（" + "，".join(x for x in tags + [s(c.get("id"))] if x) + "）")
        events.append((c["date"], 3 + i, text))
    events.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return events[:RECENT], max(0, len(events) - RECENT)


def reading(m, sources):
    """来源是怎么读的：读到哪里、谁取来的，各有几个。没买的付费来源、排除的、还没定的另列。"""
    names = m["names"]
    inc = T.included(sources)
    order = [(a, b) for a in names.enum_order("access_scope") for b in names.enum_order("fetched_by")]
    keys = [(s(src.get("access_scope")), s(src.get("fetched_by")), src.get("reading_mode") == "human_only") for _, src, _ in inc]
    rows = []
    for (scope, by, human), n in T.counted(keys, [(a, b, h) for a, b in order for h in (False, True)]):
        label = "｜".join(x for x in (names.enum("access_scope", scope) or NOT_FILLED, names.enum("fetched_by", by) or NOT_FILLED,
                                     names.enum("reading_mode", "human_only") if human else "") if x)
        rows.append((label, n, False))
    unpaid = sum(1 for _, src, _ in inc if isinstance(src.get("paid"), dict) and not src["paid"].get("purchased"))
    if unpaid:
        rows.append((names.flag("not_purchased"), unpaid, True))
    for code, label in (("excluded", "登记了、排除的"), ("pending", "登记了、还没定纳入不纳入的")):
        n = sum(1 for _, _, entry in sources if entry.get("decision") == code)
        if n:
            rows.append((label, n, True))
    return rows


def effort(m, ds, topic_id):
    """工时与成本的累计数：人做的按步骤加分钟数；AI 的加费用。没记的照实说没记，不估。"""
    names = m["names"]
    logs = [w for w in A.worklog(ds) if isinstance(w, dict) and w.get("topic_id") == topic_id]
    minutes, unrecorded, cost, ai_runs, ai_unpriced = {}, 0, {}, 0, 0
    for w in logs:
        if w.get("actor_kind") == "human":
            mins = w.get("minutes")
            if isinstance(mins, (int, float)) and not isinstance(mins, bool):
                key = s(w.get("step"))
                minutes[key] = minutes.get(key, 0) + mins
            else:
                unrecorded += 1
        elif w.get("actor_kind") == "ai":
            ai_runs += 1
            ai = w.get("ai") if isinstance(w.get("ai"), dict) else {}
            if isinstance(ai.get("cost"), (int, float)) and not isinstance(ai.get("cost"), bool):
                cur = s(ai.get("currency")) or "（没有写币种）"
                cost[cur] = cost.get(cur, 0) + ai["cost"]
            else:
                ai_unpriced += 1
    rank = {code: i for i, code in enumerate(names.enum_order("step"))}
    rows = [(names.enum("step", k) or NOT_FILLED, f"{fmt_num(round(v, 2))} 分钟")
            for k, v in sorted(minutes.items(), key=lambda x: (rank.get(x[0], len(rank)), x[0]))]
    rows += [("AI 调用的费用", f"{fmt_num(round(v, 2))} {cur}") for cur, v in sorted(cost.items())]
    notes = []
    if unrecorded:
        notes.append(f"另有 {unrecorded} 条人做的工作当时没有记分钟数。")
    if ai_runs:
        notes.append(f"AI 的工作记了 {ai_runs} 条" + (f"，其中 {ai_unpriced} 条没有记费用。" if ai_unpriced else "。"))
    return rows, notes


def build(m, ds, topic_id):
    sources = T.topic_sources(ds, topic_id)
    mems = T.membranes(ds, topic_id, m["names"], m["rows"])
    events, older = recent(m, ds, topic_id, sources)
    rows, notes = effort(m, ds, topic_id)
    return {"tiles": tiles(m, ds, topic_id, sources, mems), "status": status_parts(m), "coverage": coverage(m, mems),
            "recent": events, "older": older, "reading": reading(m, sources), "effort": rows, "effort_notes": notes,
            "total": len(m["rows"]), "source_count": m["source_count"]}


# ---------------------------------------------------------------- 写成网页

def render_tiles(items, ids):
    out = []
    for t in items:
        sub = [t["sub"]]
        if t["key"] == "disputed":
            if not t["n"]:
                sub = ["没有"]
            elif t["note"]:
                sub = [el("a", {"href": f"#{t['ids'][0]}"}, t["ids"][0]), "：", t["note"]]
            else:
                sub = [[("、" if i else ""), el("a", {"href": f"#{x}"}, x) if x in ids else x] for i, x in enumerate(t["ids"])]
        out.append(el("div", {"class": "tile" + (" warn" if t.get("warn") else ""), "data-tile": t["key"]},
                      el("div", {"class": "tile-name"}, t["label"]), el("div", {"class": "tile-n"}, t["n"]),
                      el("div", {"class": "tile-sub"}, sub)))
    return el("div", {"class": "tiles"}, out)


def render_status(parts, total):
    segs, x = [], 0.0
    for code, label, n in parts:
        if not n or not total:
            continue
        w = 1000.0 * n / total
        segs.append(el("rect", {"class": f"seg seg-{cls(code)}", "x": fmt_num(round(x, 2)), "y": "0", "width": fmt_num(round(w, 2)),
                                "height": "18"}, el("title", None, f"{label} {n} 条")))
        x += w
    summary = "，".join(f"{label} {n} 条" for _, label, n in parts)
    bar = el("svg", {"class": "statusbar", "viewBox": "0 0 1000 18", "preserveAspectRatio": "none", "role": "img",
                     "aria-label": f"各核验状态的条数：{summary}"}, segs) if segs else None
    legend = [el("span", {"class": "status-count", "data-status": code},
                 el("span", {"class": f"status s-{cls(code)}"}, label), " ", el("span", {"class": "strong"}, n))
              for code, label, n in parts]
    return el("section", {"class": "card", "id": "overview-status", "aria-label": "核到哪一步"},
              el("h2", None, "核到哪一步"), bar, el("div", {"class": "status-counts"}, legend),
              el("p", {"class": "note"}, "报告只用“人工已核”以上的；用于对比的和数据概览要到“专业已复核”。看板显示全部，含待核的。"))


def cov_cell(c):
    """覆盖图的一格：字是核验状态的头一个字，点了去这一项里核得最深的那条证据。"""
    text = CELL_TEXT.get(c["state"], "？") + ("·疑" if c["disputed"] else "")
    box = el("span", {"class": f"cov cov-{cls(c['state'])}" + (" cov-also-disputed" if c["disputed"] else "")}, text)
    if not c["best"]:
        return el("td", {"data-state": c["state"]}, box)
    ids = "、".join(r["id"] for r in c["rows"])
    more = [" ", el("span", {"class": "sub"}, f"{len(c['rows'])} 条")] if len(c["rows"]) > 1 else None
    return el("td", {"data-state": c["state"], "data-n": len(c["rows"])},
              el("a", {"class": "cov-link", "href": f"#{c['best']['id']}", "title": ids}, box), more)


def render_coverage(cov, names):
    head = el("div", {"class": "view-head"}, el("h2", None, "覆盖图：哪种膜的哪项指标有数据"),
              el("div", {"class": "note", "id": "coverage-count"},
                 f"{cov['total']} 格里 {cov['with_data']} 格有数据，{cov['not_reported']} 格是找过、原文没有报告"))
    if not cov["rows"] or not cov["cols"]:
        why = "指标字典里还没有核心指标。" if not cov["cols"] else "样品登记里还没有膜。来源登记了样品、录了证据之后，重新生成，就会出现在这里。"
        return el("section", {"class": "card", "id": "coverage"}, head, el("p", {"class": "empty"}, why))
    ths = [el("th", {"scope": "col"}, "膜")] + [
        el("th", {"scope": "col"}, g["label"], " ", el("span", {"class": "sub"}, names.enum("level", g["level"]) or NOT_FILLED))
        for g in cov["cols"]]
    body = []
    for r in cov["rows"]:
        mem = r["mem"]
        where = mem["source_id"] if mem["kind"] == "lab" else "商业产品"
        body.append(el("tr", {"data-membrane": mem["key"]},
                       el("th", {"scope": "row"}, mem["label"], " ", el("span", {"class": "sub"}, f"{T.facet_text(mem)}｜{where}")),
                       [cov_cell(c) for c in r["cells"]]))
    table = el("div", {"class": "table-wrap"}, el("table", {"class": "cmp-table cov-table"},
               el("thead", None, el("tr", None, ths)), el("tbody", None, body)))
    legend = [el("span", {"class": "legend-item"}, el("span", {"class": f"cov cov-{code}"}, CELL_TEXT[code]), text)
              for code, text in (("expert_reviewed", names.enum("verification_status", "expert_reviewed")),
                                 ("human_verified", names.enum("verification_status", "human_verified")),
                                 ("machine_checked", names.enum("verification_status", "machine_checked")),
                                 ("pending", names.enum("verification_status", "pending")),
                                 ("disputed", "只有" + names.enum("verification_status", "disputed") + "的"),
                                 ("not_reported", "找过，原文没有报告"), ("not_applicable", "找过，不适用"), ("none", "还没有数据"))]
    legend.insert(5, el("span", {"class": "legend-item"}, el("span", {"class": "cov cov-expert_reviewed cov-also-disputed"}, "复·疑"),
                        "另有一条" + names.enum("verification_status", "disputed")))
    skipped = "；".join(f"{name}（{why}）" for name, why in cov["skipped"])
    return el("section", {"class": "card", "id": "coverage", "aria-label": "覆盖图"}, head, table,
              el("div", {"class": "cov-legend"}, legend),
              el("p", {"class": "note"}, "每格显示这一项里核得最深的那条，点了去那条证据；别的几条到",
                 el("a", {"href": "#evidence"}, "证据表"), "里查。行的次序是录入的次序，不是排名。只列核心指标；",
                 f"没有单列的：{skipped}。" if skipped else "", "专利、政策法规和标准、产业和市场的数字、科研资助不在这张图里，见",
                 el("a", {"href": "#non-academic"}, "非学术来源"), "。"))


def rows_card(card_id, title, rows, notes=(), empty=""):
    lines = [el("div", {"class": "line" + (" muted" if len(r) > 2 and r[2] else "")},
                el("span", None, r[0]), " ", el("span", {"class": "strong"}, r[1])) for r in rows]
    return el("section", {"class": "card third", "id": card_id, "aria-label": title}, el("h2", None, title),
              el("div", {"class": "lines"}, lines) if lines else el("p", {"class": "empty"}, empty),
              [el("p", {"class": "note"}, n) for n in notes])


def render(model, m, title, question):
    names = m["names"]
    head = el("section", {"class": "card"},
              el("div", {"class": "view-head"}, el("h2", None, title),
                 el("div", {"class": "note"}, f"{question}｜{model['total']} 条证据，来自 {model['source_count']} 个来源")),
              render_tiles(model["tiles"], m["ids"]))
    events = [el("li", None, el("span", {"class": "date"}, d), " ", text) for d, _, text in model["recent"]]
    older = [f"更早的还有 {model['older']} 条，在各条证据的核验历史和 data/changes.jsonl 里。"] if model["older"] else []
    changes = el("section", {"class": "card third", "id": "overview-recent", "aria-label": "最近的变化"}, el("h2", None, "最近的变化"),
                 el("ol", {"class": "history"}, events) if events else el("p", {"class": "empty"}, "还没有记录。"),
                 [el("p", {"class": "note"}, x) for x in older])
    return el("section", {"class": "view", "id": "overview", "aria-label": title},
              head, render_status(model["status"], model["total"]), render_coverage(model["coverage"], names),
              el("div", {"class": "thirds"}, changes,
                 rows_card("overview-reading", "来源是怎么读的", model["reading"], empty="还没有纳入的来源。"),
                 rows_card("overview-effort", "工时与成本", model["effort"],
                           list(model["effort_notes"]) + ["首版只显示累计数，明细页以后再做。"], "工作记录里还没有记工时。")))
