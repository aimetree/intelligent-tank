"""对标视图（K3）：同层级、同条件下谁和谁能比（设计方案 4.2、4.3、6.1）。

- 层级各有各的一块，不合并；一张图只放一个可比组。
- 每个可比组：档别、依据的规则、定档的理由、缺什么；一张图；成员的表（数值、与基准之比、关键条件和各成员不一样的条件）。
- 与基准之比、派生指标是脚本现算的，不是证据，页面上标“换算值”（规格 1.5）。
- 可比性矩阵：这一层里谁和谁在同一个组里、是哪一档。
- 同一批测试里随条件变化的图：同一来源、同一批测试，同一个样品的点连起来。
- 每个可比组的复核单：专业复核时要逐条看的条目、为什么要看、参考判断、复核人的决定（规格 3.13，D-80）。
  单子由 tools/review_sheet.py 起草和写回，这里只照数据显示。
这里只整理和并排：成员照数据文件里的次序排，不按数值排名，不求平均，不下结论（D-60，设计方案 6.1 第 5 条）。
"""
import charts
import derive
import validate as V
from display import NOT_FILLED, axis_label, cls, fmt_num, mark, s, with_unit
from htmlgen import el

TIER_RANK = {"direct": 3, "conditional": 2, "reference": 1, "insufficient": 0}
PLOT_ROLES = ("member", "baseline", "reference")
RATIO = "ratio_to_baseline"


# ---------------------------------------------------------------- 算出要显示的内容

def object_of(row):
    """图和表里怎么称呼一个对象：实验室样品用原文里的样品名（各篇论文各算各的），产品用实体名。"""
    if row["sample"]:
        return {"key": f"{row['source_id']}|{row['sample']}", "label": row["sample"], "sub": f"{row['subject']}｜{row['source_id']}"}
    return {"key": f"entity|{row['subject_id']}", "label": row["subject"], "sub": row["source_id"]}


def error_range(e, value, factor):
    """原文给的范围或误差，换到标准单位下：返回 (下限, 上限) 或 None。图上读数的读数误差也算。"""
    if value is None or factor is None:
        return None
    lo, hi = e.get("range_low"), e.get("range_high")
    if charts.is_number(lo) and charts.is_number(hi):
        return (lo * factor, hi * factor)
    u = e.get("uncertainty")
    if not charts.is_number(u) and isinstance(e.get("figure_read"), dict):
        u = e["figure_read"].get("reading_error")
    return (value - u * factor, value + u * factor) if charts.is_number(u) and u > 0 else None


def member_model(m, group, by_id, ds, lk, names):
    eid = s(m.get("evidence_id"))
    row = by_id.get(eid)
    out = {"id": eid, "row": row, "role": s(m.get("role")), "role_label": names.enum("member_role", m.get("role")),
           "note": s(m.get("note")), "value": None, "err": None, "ratio": None, "indicator": "", "unit": "",
           "obj": {"key": eid, "label": eid, "sub": "证据库里没有这一条"}}
    if row and row["error"]:
        out["row"], out["obj"]["sub"] = None, "这一条显示不出来，原因在页面顶上"
    if not out["row"]:
        return out
    e = row["e"]
    measure = lk.measure_of(e)[1] or {}
    out["obj"], out["indicator"] = object_of(row), s(e.get("indicator"))
    out["unit"] = names.unit(measure.get("unit_std"))
    if e.get("content_kind") == "numeric":
        out["value"] = derive.comparable_value(e, measure)
        out["err"] = error_range(e, out["value"], V.unit_factor(measure, e.get("unit_reported")))
    if out["role"] != "baseline" and (group["normalization"] == RATIO or e.get("baseline_ref")):
        out["ratio"] = derive.baseline_ratio(e, ds, lk)
        if out["ratio"]["ratio"] is not None:
            out["ratio"]["ratio"] = round(out["ratio"]["ratio"], 4)   # 比值写到小数点后四位，图上和表里用同一个数
    return out


def point_of(m, names, value, href, label=None):
    """成员在图上的那个点。"""
    row = m["row"]
    e = row["e"]
    fig = e.get("obtained_from") == "figure_read"
    bits = [f"{m['obj']['label']}（{m['obj']['sub']}）", f"{row['measure']} {row['value']}", m["role_label"], row["status_label"],
            row["type_label"]] + (["图上读数"] if fig else [])
    return {"value": value, "label": label or m["obj"]["label"], "sub": m["obj"]["sub"], "type": row["type"],
            "solid": row["status"] == "expert_reviewed", "role": m["role"], "href": href, "dashed": fig,
            "title": "｜".join(b for b in bits if b), "evidence": m["id"]}


def condition_table(members, key_conditions, names):
    """成员的条件怎么并排：关键条件和各成员不一样的条件各占一栏；各成员都一样的收成一句。"""
    used = [m for m in members if m["row"] and m["role"] in PLOT_ROLES]
    cells = {}
    for m in used:
        for c in m["row"]["conditions"]:
            cells.setdefault(c["key"], {})[m["id"]] = c
    columns, same = [], []
    for key in sorted(cells, key=lambda k: (names.cond_order.get(k, 10 ** 6), k)):
        seen = {(cells[key][m["id"]]["parsed"] or cells[key][m["id"]]["text"], cells[key][m["id"]]["state"])
                if m["id"] in cells[key] else ("", "absent") for m in used}
        if key in key_conditions or len(seen) > 1:
            columns.append({"key": key, "name": names.condition(key), "is_key": key in key_conditions, "cells": cells[key]})
        else:
            text, state = next(iter(seen))
            same.append((names.condition(key), cells[key][used[0]["id"]]["text"], state))
    return columns, same


def chart_of(group, names, stamp):
    """这一组的图。返回 (图或 None, 没画进图里的 [(证据编号, 原因)], 图下的说明)。"""
    members, skipped, rows = group["members"], [], []
    indicators = group["indicators"]
    for m in members:
        if m["role"] not in PLOT_ROLES:
            skipped.append((m["id"], f"{m['role_label'] or m['role']}" + (f"：{m['note']}" if m["note"] else "")))
        elif not m["row"]:
            skipped.append((m["id"], m["obj"]["sub"]))
    usable = [m for m in members if m["role"] in PLOT_ROLES and m["row"]]
    axis = "、".join(names._name(names.indicators.get(k), k) for k in indicators)
    label = f"{group['id']}　{group['title']}"
    chart = None
    if group["normalization"] == RATIO:
        for m in usable:
            if m["role"] == "baseline":
                continue
            if m["ratio"] and m["ratio"]["ratio"] is not None:
                rows.append(dict(point_of(m, names, m["ratio"]["ratio"], f"#{group['id']}--{m['id']}")))
            else:
                skipped.append((m["id"], (m["ratio"] or {}).get("why") or "算不出与基准之比"))
        if rows:
            chart = charts.dot_chart(rows, f"{axis}：与同文基准之比（换算值）", label, ref=1.0, ref_label="基准 = 1")
    elif len(indicators) == 2:
        pairs, order = {}, []
        for m in usable:
            if m["value"] is None:
                skipped.append((m["id"], "没有标准单位下的数值"))
                continue
            slot = pairs.setdefault(m["obj"]["key"], {})
            if m["obj"]["key"] not in order:
                order.append(m["obj"]["key"])
            if m["indicator"] in slot:
                skipped.append((m["id"], "这个对象的这个指标在组里不止一条，图上只画了第一条"))
            else:
                slot[m["indicator"]] = m
        points = []
        for key in order:
            a, b = pairs[key].get(indicators[0]), pairs[key].get(indicators[1])
            if a and b:
                p = point_of(a, names, None, f"#{group['id']}--{a['id']}")
                p.update(x=a["value"], y=b["value"], x_err=a["err"], y_err=b["err"],
                         solid=p["solid"] and b["row"]["status"] == "expert_reviewed",
                         title=p["title"] + "｜" + f"{b['row']['measure']} {b['row']['value']}（{b['id']}）")
                points.append(p)
            else:
                only = a or b
                skipped.append((only["id"], f"这个对象在组里只有{only['row']['measure']}，凑不成一个点"))
        if points:
            axes = [axis_label(names._name(names.indicators.get(k), k), next((m["unit"] for m in usable if m["indicator"] == k), ""))
                    for k in indicators]
            chart = charts.xy_chart([{"points": points, "connect": False}], axes[0], axes[1], label)
            rows = points
    elif len(indicators) == 1:
        for m in usable:
            if m["value"] is None:
                skipped.append((m["id"], "没有标准单位下的数值"))
            else:
                p = point_of(m, names, m["value"], f"#{group['id']}--{m['id']}")
                p["err"] = m["err"]
                rows.append(p)
        if rows:
            chart = charts.dot_chart(rows, axis_label(axis, next((m["unit"] for m in usable if m["unit"]), "")), label)
    else:
        skipped.append((group["id"], f"这一组有 {len(indicators)} 个指标，没有画图，只列表"))
    count = {r: sum(1 for m in usable if m["role"] == r) for r in PLOT_ROLES}
    objects = len({m["obj"]["key"] for m in usable})
    caption = (f"对象数 {objects}：{names.enum('member_role', 'member')} {count['member']}，{names.enum('member_role', 'baseline')} "
               f"{count['baseline']}，{names.enum('member_role', 'reference')} {count['reference']}｜图上 {len(rows)} 个点｜"
               f"筛选：{group['level_label']}，{axis}，{group['id']}｜{stamp}")
    return chart, skipped, caption


def group_model(c, by_id, ds, lk, names, rules, questions, stamp):
    rule = rules.get(c.get("rule")) or {}
    g = {
        "id": s(c.get("id")), "title": s(c.get("title")), "level": s(c.get("level")),
        "level_label": names.enum("level", c.get("level")) or NOT_FILLED,
        "tier": s(c.get("tier")), "tier_label": names.enum("tier", c.get("tier")) or NOT_FILLED,
        "status_label": names.enum("cmp_status", c.get("status")),
        "rule": s(rule.get("name") or c.get("rule")), "rule_statement": s(rule.get("statement")),
        "normalization": s(c.get("normalization") or "none"),
        "normalization_label": names.enum("normalization", c.get("normalization") or "none"),
        "question": s(c.get("question")), "question_text": s(questions.get(c.get("question"))),
        "indicators": [k for k in c.get("indicators") or [] if isinstance(k, str)],
    }
    g["members"] = [member_model(m, g, by_id, ds, lk, names) for m in c.get("members") or [] if isinstance(m, dict)]
    notes = []

    def note(key, text):
        if text not in (None, "", []):
            notes.append((names.field("comparison", key), s(text)))

    note("tier_reason", c.get("tier_reason"))
    if isinstance(c.get("missing_conditions"), list):
        note("missing_conditions", "、".join(names.condition(k) for k in c["missing_conditions"]))
    note("same_setup_note", c.get("same_setup_note"))
    note("missing", c.get("missing") if not isinstance(c.get("missing"), list) else "；".join(s(x) for x in c["missing"]))
    if isinstance(c.get("condition_envelope"), dict):
        note("condition_envelope", "；".join(f"{names.condition(k)} {s(v.get('reported')) if isinstance(v, dict) else names.enum('condition_missing', v)}"
                                            for k, v in c["condition_envelope"].items()))
    if c.get("baseline_subject_id"):
        ent = ds["entities"].get(c["baseline_subject_id"]) if isinstance(c["baseline_subject_id"], str) else None
        name = s(ent.get("name")) if isinstance(ent, dict) and ent.get("name") else s(c["baseline_subject_id"])
        note("baseline_subject_id", "｜".join(x for x in (name, names.enum("baseline_class", c.get("baseline_class"))) if x))
    note("normalization_note", c.get("normalization_note"))
    note("notes", c.get("notes"))
    g["notes"] = notes
    g["columns"], g["same"] = condition_table(g["members"], rule.get("key_conditions") or [], names)
    g["chart"], g["skipped"], g["caption"] = chart_of(g, names, stamp)
    g["reviews"] = review_models(g, ds, by_id, names)
    return g


def review_models(g, ds, by_id, names):
    """这一组的复核单，照编号排。"""
    labels = {m["id"]: m["obj"]["label"] for m in g["members"]}

    def target(tid):
        tid = s(tid)
        if tid == g["id"]:
            return {"id": tid, "href": "", "what": "这一组的档别"}
        if tid.startswith("ASM-"):
            return {"id": tid, "href": "", "what": names.enum("review_reason", "overview")}
        row = by_id.get(tid)
        what = f"{labels.get(tid) or (row or {}).get('sample') or (row or {}).get('subject') or ''}"
        if row and not row["error"]:
            what = "　".join(x for x in (what, f"{row['measure']} {row['value']}") if x)
        return {"id": tid, "href": f"#{tid}" if row else "", "what": what or "证据库里没有这一条"}

    out = []
    for rid in sorted(ds["reviews"]):
        r = ds["reviews"][rid]
        if not isinstance(r, dict) or r.get("comparison_id") != g["id"]:
            continue
        items = []
        for it in r.get("items") or []:
            if not isinstance(it, dict):
                continue
            items.append({"target": target(it.get("target_id")),
                          "reason": names.enum("review_reason", it.get("reason")) or s(it.get("reason")),
                          "why": s(it.get("why")), "suggestion": s(it.get("suggestion")),
                          "decision": s(it.get("decision")),
                          "decision_label": names.enum("review_decision", it.get("decision")) or s(it.get("decision")) or NOT_FILLED,
                          "note": s(it.get("note")),
                          "changes": [s(x) for x in it.get("change_ids") or []] if isinstance(it.get("change_ids"), list) else []})
        b = r.get("batch") if isinstance(r.get("batch"), dict) else None
        batch = None
        if b:
            ids = [s(x) for x in b.get("evidence_ids") or []] if isinstance(b.get("evidence_ids"), list) else []
            sampled = [s(x) for x in b.get("sampled") or []] if isinstance(b.get("sampled"), list) else []
            batch = {"ids": [target(x) for x in ids], "sampled": sampled, "decision": s(b.get("decision")),
                     "decision_label": names.enum("review_decision", b.get("decision")) or s(b.get("decision")) or NOT_FILLED}
        out.append({"id": rid, "title": s(r.get("title")), "status": s(r.get("status")),
                    "status_label": names.enum("review_status", r.get("status")) or s(r.get("status")) or NOT_FILLED,
                    "created": "，".join(x for x in (s(r.get("created_by")), s(r.get("created_at"))) if x),
                    "reviewed": "，".join(x for x in (s(r.get("reviewer")), s(r.get("reviewed_at"))) if x),
                    "items": items, "batch": batch, "notes": s(r.get("notes"))})
    return out


def matrix_model(groups, names):
    """可比性矩阵：这一层里，哪两个对象在同一个组里、是哪一档。同在几个组里的取最高的一档。"""
    objects, best = {}, {}
    for g in groups:
        ms = [m for m in g["members"] if m["role"] in PLOT_ROLES and m["row"]]
        for i, a in enumerate(ms):
            objects.setdefault(a["obj"]["key"], a["obj"])
            for b in ms[i + 1:]:
                if a["obj"]["key"] == b["obj"]["key"]:
                    continue
                tier = g["tier"]
                if "reference" in (a["role"], b["role"]) and TIER_RANK.get(tier, 0) > TIER_RANK["reference"]:
                    tier = "reference"   # 只作参考的成员，和谁并排都只算参考
                pair = frozenset((a["obj"]["key"], b["obj"]["key"]))
                cur = best.get(pair)
                if cur is None or TIER_RANK.get(tier, -1) > TIER_RANK.get(cur["tier"], -1):
                    best[pair] = {"tier": tier, "label": names.enum("tier", tier), "groups": [g["id"]]}
                elif tier == cur["tier"] and g["id"] not in cur["groups"]:
                    cur["groups"].append(g["id"])
    return {"objects": list(objects.values()), "cells": best}


def series_models(level, rows, lk, names, rules, stamp):
    """同一批测试里随条件变化的图：指标按可比规则里它的关键条件中第一个数值型的来画。"""
    out = []
    for key, ind in names.indicators.items():
        if ind.get("level") != level or ind.get("value_kind") != "numeric" or ind.get("entry", "evidence") != "evidence":
            continue
        xkey = next((k for r in rules.values() if key in (r.get("applies_to") or []) for k in r.get("key_conditions") or []
                     if (names.conditions.get(k) or {}).get("value_kind") == "numeric"), None)
        if not xkey:
            continue
        batches = {}
        for row in rows:
            e = row["e"]
            if row["error"] or e.get("indicator") != key or e.get("verification_status") == "void" or not e.get("series_label"):
                continue
            cv = e["conditions"].get(xkey) if isinstance(e.get("conditions"), dict) else None
            x, y = (cv.get("value") if isinstance(cv, dict) else None), derive.comparable_value(e, ind)
            if not charts.is_number(x) or y is None:
                continue
            batches.setdefault((row["source_id"], s(e["series_label"])), []).append((x, y, row))
        for (sid, series), items in sorted(batches.items()):
            if len({x for x, _, _ in items}) < 2:
                continue
            lines, order = {}, []
            for x, y, row in items:
                obj = object_of(row)
                role = (lk.register_of(sid).get(row["sample"]) or {}).get("role")
                fig = row["e"].get("obtained_from") == "figure_read"
                bits = [f"{obj['label']}（{obj['sub']}）", f"{names.condition(xkey)} {fmt_num(x)}", f"{row['measure']} {row['value']}",
                        row["status_label"], row["type_label"]] + (["图上读数"] if fig else [])
                p = {"x": x, "y": y, "type": row["type"], "solid": row["status"] == "expert_reviewed",
                     "role": "baseline" if role == "baseline" else "member", "href": f"#{row['id']}", "dashed": fig,
                     "title": "｜".join(bits), "evidence": row["id"],
                     "y_err": error_range(row["e"], y, V.unit_factor(ind, row["e"].get("unit_reported")))}
                if obj["key"] not in lines:
                    order.append(obj["key"])
                lines.setdefault(obj["key"], {"label": obj["label"], "points": []})["points"].append(p)
            for k in order:   # 每条线只在最后一个点旁边写名字
                max(lines[k]["points"], key=lambda p: p["x"])["label"] = lines[k]["label"]
            name, xname = names._name(ind, key), names.condition(xkey)
            title = f"{name}随{xname}的变化｜{sid}｜同一批测试 {series}"
            xunit = names.unit((names.conditions.get(xkey) or {}).get("unit_std"))
            chart = charts.xy_chart([{"points": lines[k]["points"], "connect": True} for k in order],
                                    axis_label(xname, xunit), axis_label(name, names.unit(ind.get("unit_std"))), title)
            out.append({"title": title, "chart": chart,
                        "caption": f"对象数 {len(order)}｜图上 {len(items)} 个点｜同一个样品的点连成线，不同样品之间不连｜"
                                   f"筛选：{names.enum('level', level)}，{name}，{sid}｜{stamp}"})
    return out


def derived_models(level, ds, topic_id, by_id, names):
    records, _ = derive.derived_records(ds, topic_id)
    out = []
    for r in records:
        ind = names.indicators.get(r["indicator"]) or {}
        if ind.get("level") != level:
            continue
        ent = ds["entities"].get(r["subject_id"]) if isinstance(r["subject_id"], str) else None
        out.append({
            "indicator": names._name(ind, r["indicator"]), "source_id": s(r["source_id"]),
            "object": s(r["sample_label"]) or (s(ent.get("name")) if isinstance(ent, dict) else s(r["subject_id"])),
            "series": s(r["series_label"]), "condition": names.condition(r["condition"]),
            "value": with_unit(fmt_num(r["value"]), names.unit(r["unit"])), "tested": r["tested"],
            "picked": [(names._name(names.indicators.get(k), k), by_id[eid]["value"] if eid in by_id else "", eid)
                       for k, eid in r["picked"].items()],
        })
    return out


def build(ds, topic_id, names, rows, stamp):
    """对标视图要显示的全部内容。rows 是证据表页算好的各行。"""
    topic = ds["topics"].get(topic_id) or {}
    lk = V.Lookups(ds)
    by_id = {r["id"]: r for r in rows}
    d = ds["dictionaries"].get(topic_id) or {}
    rules = {r.get("key"): r for r in d.get("rules") or [] if isinstance(r, dict)}
    questions = {q.get("key"): q.get("text") for q in topic.get("questions") or [] if isinstance(q, dict)}
    groups = [group_model(ds["comparisons"][cid], by_id, ds, lk, names, rules, questions, stamp)
              for cid in sorted(ds["comparisons"])
              if isinstance(ds["comparisons"][cid], dict) and ds["comparisons"][cid].get("topic_id") == topic_id]
    wanted = [lv for lv in names.enum_order("level") if lv in V.COMPARABLE_LEVELS and lv in (topic.get("levels") or [])]
    wanted += sorted({g["level"] for g in groups} - set(wanted))   # 数据里写了别的层级的组也照样显示，校验会报
    levels = []
    for lv in wanted:
        own = [g for g in groups if g["level"] == lv]
        levels.append({"code": lv, "label": names.enum("level", lv) or NOT_FILLED, "groups": own,
                       "matrix": matrix_model(own, names), "series": series_models(lv, rows, lk, names, rules, stamp),
                       "derived": derived_models(lv, ds, topic_id, by_id, names)})
    return {"levels": levels, "group_ids": {g["id"] for g in groups}, "group_count": len(groups)}


# ---------------------------------------------------------------- 写成网页

def kv(pairs):
    return el("dl", {"class": "kv"}, [(el("dt", None, k), el("dd", None, v)) for k, v in pairs])


def flagged(text, flag):
    return el("span", {"class": "missing"}, text) if flag else text


def render_members(g, names):
    multi = len(g["indicators"]) > 1
    show_ratio = any(m["ratio"] for m in g["members"])
    head = ["证据", "对象"] + (["指标"] if multi else []) + ["角色", "数值"] + (["与基准之比（换算值）"] if show_ratio else [])
    head += [c["name"] + ("（关键条件）" if c["is_key"] else "") for c in g["columns"]] + ["证据类型", "核验状态"]
    lines = []
    for m in g["members"]:
        row = m["row"]
        if not row:
            lines.append(el("tr", {"id": f"{g['id']}--{m['id']}"}, el("td", None, flagged(m["id"], True)),
                            el("td", {"colspan": len(head) - 1}, flagged(m["obj"]["sub"], True))))
            continue
        ratio = "—（它就是基准）" if m["role"] == "baseline" else ""
        if m["ratio"]:
            r = m["ratio"]
            ratio = (f"{fmt_num(r['ratio'])}（{fmt_num(r['value'])} ÷ {fmt_num(r['base_value'])}，基准 {r['base_id']}）"
                     if r["ratio"] is not None else flagged(r["why"], True))
        cells = [el("td", None, el("a", {"href": f"#{m['id']}"}, m["id"])),
                 el("td", None, el("span", {"class": "strong"}, m["obj"]["label"]), " ", el("span", {"class": "sub"}, m["obj"]["sub"]))]
        if multi:
            cells.append(el("td", None, row["measure"]))
        cells += [el("td", None, m["role_label"] or m["role"], [" ", el("span", {"class": "sub"}, m["note"])] if m["note"] else None),
                  el("td", None, flagged(row["value"], row["value_flag"]),
                     [[" ", el("span", {"class": "sub"}, x)] for x in row["value_notes"]])]
        if show_ratio:
            cells.append(el("td", None, ratio))
        for c in g["columns"]:
            cell = c["cells"].get(m["id"])
            cells.append(el("td", None, flagged(cell["text"], cell["state"] != "reported") if cell else flagged("没有这一项", True)))
        cells += [el("td", None, el("span", {"class": "type"}, mark(row["type"]), row["type_label"]),
                     [[" ", el("span", {"class": "sub"}, x)] for x in row["flags"]]),
                  el("td", None, el("span", {"class": f"status s-{cls(row['status'])}"}, row["status_label"]))]
        lines.append(el("tr", {"id": f"{g['id']}--{m['id']}", "class": f"role-{cls(m['role'])}"}, cells))
    return el("div", {"class": "table-wrap"},
              el("table", {"class": "cmp-table"},
                 el("thead", None, el("tr", None, [el("th", {"scope": "col"}, h) for h in head])), el("tbody", None, lines)))


def render_group(g, names):
    tags = [el("span", {"class": f"tier t-{cls(g['tier'])}"}, g["tier_label"]),
            el("span", None, f"{names.field('comparison', 'status')}：{g['status_label'] or NOT_FILLED}"),
            el("span", None, f"{names.field('comparison', 'rule')}：{g['rule'] or NOT_FILLED}"),
            el("span", None, f"{names.field('comparison', 'normalization')}：{g['normalization_label']}")]
    question = f"{g['question']}　{g['question_text']}" if g["question"] else ""
    body = [el("div", {"class": "view-head"}, el("h3", None, f"{g['id']}　{g['title']}"), el("div", {"class": "note"}, question)),
            el("div", {"class": "tags"}, tags)]
    notes = list(g["notes"]) + ([("这条规则说的是", g["rule_statement"])] if g["rule_statement"] else [])
    if notes:
        body.append(kv(notes))
    if g["chart"]:
        body.append(el("figure", {"class": "figure"}, g["chart"], el("figcaption", {"class": "note"}, g["caption"])))
    else:
        body.append(el("p", {"class": "note"}, "这一组没有画图。" + g["caption"]))
    body.append(render_members(g, names))
    if g["same"]:
        body.append(el("p", {"class": "note"}, "各成员都一样的条件：",
                       [[("；" if i else ""), flagged(f"{name} {text}", state != "reported")] for i, (name, text, state) in enumerate(g["same"])]))
    if g["skipped"]:
        body.append(el("div", {"class": "block"}, el("div", {"class": "block-name"}, "没画进图里的"),
                       el("ul", {"class": "plain"}, [el("li", None, f"{eid}：{why}") for eid, why in g["skipped"]])))
    body += [render_review(r, names) for r in g["reviews"]] or [el("p", {"class": "note"}, "这一组还没有复核单。")]
    return el("section", {"class": "card group-card", "id": g["id"]}, body)


def _target(t):
    return [el("a", {"href": t["href"]}, t["id"]) if t["href"] else t["id"], " ", el("span", {"class": "sub"}, t["what"])]


def render_review(r, names):
    """一张复核单：谁起草、谁复核；要逐条看的条目和复核人的决定；成批确认的。还没定的决定标出来。"""
    def field(key):
        return names.field("review", "items", key)

    def decision(code, label):
        return flagged(label, code not in ("confirm", "modify"))

    head = [f"{names.field('review', 'status')}：{r['status_label']}", f"{names.field('review', 'created_by')}：{r['created'] or NOT_FILLED}",
            f"{names.field('review', 'reviewer')}：{r['reviewed'] or '还没有复核'}"]
    body = [el("div", {"class": "block-name"}, f"复核单 {r['id']}　{r['title']}"),
            el("div", {"class": "tags"}, [[el("span", None, x), " "] for x in head])]
    if r["items"]:
        lines = []
        for it in r["items"]:
            extra = [[" ", el("span", {"class": "sub"}, f"{field('note')}：{it['note']}")] if it["note"] else None,
                     [" ", el("span", {"class": "sub"}, f"{field('change_ids')}：{'、'.join(it['changes'])}")] if it["changes"] else None]
            lines.append(el("tr", None, el("td", None, _target(it["target"])), el("td", None, it["reason"]), el("td", None, it["why"]),
                            el("td", None, it["suggestion"]), el("td", None, decision(it["decision"], it["decision_label"]), extra)))
        head_cells = [names.field("review", "items")] + [field(k) for k in ("reason", "why", "suggestion", "decision")]
        body.append(el("div", {"class": "table-wrap"}, el("table", {"class": "cmp-table"},
                    el("thead", None, el("tr", None, [el("th", {"scope": "col"}, h) for h in head_cells])), el("tbody", None, lines))))
    if r["batch"]:
        b = r["batch"]
        ids = [[("、" if i else ""), el("a", {"href": t["href"]}, t["id"]) if t["href"] else t["id"],
                "（抽看）" if t["id"] in b["sampled"] else ""] for i, t in enumerate(b["ids"])]
        body.append(el("p", {"class": "note"}, f"{names.field('review', 'batch')} {len(b['ids'])} 条：", ids, "｜",
                       f"{names.field('review', 'batch', 'decision')}：", decision(b["decision"], b["decision_label"])))
    if r["notes"]:
        body.append(el("p", {"class": "note"}, f"{names.field('review', 'notes')}：{r['notes']}"))
    return el("div", {"class": "block review", "id": r["id"]}, body)


def render_matrix(matrix, level_label):
    objects = matrix["objects"]
    if len(objects) < 2:
        return None
    head = [el("th", None)] + [el("th", {"scope": "col"}, o["label"], " ", el("span", {"class": "sub"}, o["sub"])) for o in objects]
    lines, used = [], {}
    for a in objects:
        cells = [el("th", {"scope": "row"}, a["label"], " ", el("span", {"class": "sub"}, a["sub"]))]
        for b in objects:
            cell = matrix["cells"].get(frozenset((a["key"], b["key"]))) if a["key"] != b["key"] else None
            if a["key"] == b["key"]:
                cells.append(el("td", {"class": "self"}, "—"))
            elif cell:
                used[cell["tier"]] = cell["label"]
                cells.append(el("td", None, el("span", {"class": f"tier t-{cls(cell['tier'])}", "title": f"{cell['label']}：{'、'.join(cell['groups'])}"},
                                               cell["label"][:1]), " ", el("span", {"class": "sub"}, "、".join(cell["groups"]))))
            else:
                cells.append(el("td", None))
        lines.append(el("tr", None, cells))
    legend = [el("span", {"class": "legend-item"}, el("span", {"class": f"tier t-{cls(t)}"}, used[t][:1]), " ", used[t])
              for t in sorted(used, key=lambda t: -TIER_RANK.get(t, -1))]
    return el("section", {"class": "card"},
              el("div", {"class": "view-head"}, el("h3", None, "可比性矩阵：谁和谁在同一个组里，是哪一档"), el("div", {"class": "note"}, level_label)),
              el("div", {"class": "table-wrap"}, el("table", {"class": "cmp-table matrix"}, el("thead", None, el("tr", None, head)), el("tbody", None, lines))),
              el("div", {"class": "tags"}, legend),
              el("p", {"class": "note"}, "空着的格子：这两个对象不在同一个可比组里。同在几个组里的，显示最高的一档；只作参考的成员和谁并排都只算参考。"))


def render_derived(items):
    if not items:
        return None
    lines = []
    for d in items:
        picked = [[("；" if i else ""), f"{name} {value}（", el("a", {"href": f"#{eid}"}, eid), "）"] for i, (name, value, eid) in enumerate(d["picked"])]
        lines.append(el("tr", None, el("td", None, d["indicator"]), el("td", None, el("span", {"class": "strong"}, d["object"]), " ",
                        el("span", {"class": "sub"}, f"{d['source_id']}｜同一批测试 {d['series']}")),
                        el("td", None, f"{d['condition']} {d['value']}"), el("td", None, picked), el("td", None, f"{d['tested']} 个")))
    return el("section", {"class": "card"},
              el("div", {"class": "view-head"}, el("h3", None, "派生指标（换算值）"),
                 el("div", {"class": "note"}, "由脚本从同一批测试里取出来的，不是证据")),
              el("div", {"class": "table-wrap"}, el("table", {"class": "cmp-table"},
                 el("thead", None, el("tr", None, [el("th", {"scope": "col"}, h) for h in ("派生指标", "对象", "取到的值", "那一处的证据", "这一批测了几个值")])),
                 el("tbody", None, lines))))


def render(model, names, title, question):
    levels = model["levels"]
    tabs = [el("button", {"type": "button", "class": "chip", "data-level-tab": lv["code"], "aria-pressed": "false"},
               lv["label"], el("span", {"class": "n"}, len(lv["groups"]))) for lv in levels]
    head = el("section", {"class": "card"},
              el("div", {"class": "view-head"}, el("h2", None, title),
                 el("div", {"class": "note"}, f"{question}｜{model['group_count']} 个可比组")),
              el("div", {"class": "chips needs-js", "role": "group", "aria-label": names.field("comparison", "level")}, tabs) if tabs else None,
              el("p", {"class": "note"}, "层级各有各的图，不合并。成员照登记的次序排，不按数值排名，不求平均；不同来源、不同样品的点不连线。"
                 "图上实心的点是专业已复核的，空心的是还没复核的；基准、只作参考、图上读数，写在点旁边的字和点的提示里。"
                 "与基准之比和派生指标是脚本现算的换算值，不是证据。"))
    panels = []
    for lv in levels:
        body = [el("h3", {"class": "level-name"}, lv["label"])]
        body += [render_group(g, names) for g in lv["groups"]] or [
            el("section", {"class": "card"}, el("p", {"class": "empty"}, f"{lv['label']}这一层还没有可比组。"))]
        for sm in lv["series"]:
            body.append(el("section", {"class": "card"}, el("div", {"class": "view-head"}, el("h3", None, sm["title"])),
                           el("figure", {"class": "figure"}, sm["chart"], el("figcaption", {"class": "note"}, sm["caption"]))))
        body += [render_matrix(lv["matrix"], lv["label"]), render_derived(lv["derived"])]
        panels.append(el("section", {"class": "level", "data-level-panel": lv["code"], "aria-label": lv["label"]}, body))
    if not levels:
        panels.append(el("section", {"class": "card"}, el("p", {"class": "empty"}, "这个题目没有可以建可比组的层级。")))
    return el("section", {"class": "view", "id": "compare", "aria-label": title}, head, panels)
