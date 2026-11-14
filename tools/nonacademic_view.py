"""非学术来源（K9）：专利、政策法规和标准、产业和市场的数字、科研资助，同一页各占一块（设计方案 4.2，D-111；样张第五页）。

取自来源的文件属性（doc：著录项目和状态）和这些来源名下的证据（规格第 6 节末段）。
- 这些数不和论文数据放进同一个可比组；报告里的数按口径并排，不合并成一个数（规则 R9，D-95）。
- 专利的法律状态、政策法规和标准的状态，照查到的记录写，写明在哪里、哪天查的，不作解读；不作侵权和自由实施的判断（D-10）。
- 关系每条都带出处；推断的标明是推断（D-49）。
只整理和描述，不作评价（D-60）。对外报告第 4.2 至 4.5 节、第 5 节里的关系和第 7 节里这四块的缺口，用的是同一份数据。
"""
import gaps_view
import topicdata as T
import validate as V
from display import NOT_FILLED, cls, fmt_num, s
from htmlgen import el

MAIN_JURISDICTIONS = ("cn", "uk", "eu", "us")   # 题目按这四个法域问（D-96）；国际和其他有来源才列


def doc_of(src):
    return src.get("doc") if isinstance(src.get("doc"), dict) else {}


def status_of(src):
    st = doc_of(src).get("status")
    return st if isinstance(st, dict) else {}


def end_name(ds, x):
    """关系的一头叫什么：来源写题名和编号，实体写名字。"""
    src = ds["sources"].get(x) if isinstance(x, str) else None
    if isinstance(src, dict):
        return f"{s(src.get('title')) or NOT_FILLED}（{x}）"
    return T.entity_name(ds, x) or NOT_FILLED


def relation_model(ds, names, rel):
    basis = s(rel.get("basis"))
    where = "｜".join(x for x in (s(rel.get("source_id")), s((rel.get("locator") or {}).get("text")) if isinstance(rel.get("locator"), dict) else "") if x)
    inferred = basis.startswith("inferred")
    how = names.enum("basis", basis) or NOT_FILLED
    if inferred:
        how += f"，{s(rel['confirmed_by'])} 已确认" if V.is_human(rel.get("confirmed_by")) else "，还没有人确认"
    return {"id": s(rel.get("id")), "what": f"{end_name(ds, rel.get('subject'))} — {names.enum('relation_type', rel.get('relation_type')) or NOT_FILLED} — {end_name(ds, rel.get('object'))}",
            "from": "｜".join(x for x in (s(rel.get("summary")) or s(rel.get("inference_note")), where) if x) or NOT_FILLED,
            "how": how, "inferred": inferred,
            "status_label": names.enum("verification_status", rel.get("verification_status")) or NOT_FILLED,
            "status": s(rel.get("verification_status"))}


def ev_line(r):
    """来源卡片里的一条证据：是什么、值或转述、标注、编号、状态。"""
    conds = "；".join(f"{c['name']} {c['text']}" for c in r["conditions"])
    return {"id": r["id"], "measure": r["measure"], "value": r["value"], "conds": conds, "flags": list(r["flags"]),
            "type_label": r["type_label"], "status": r["status"], "status_label": r["status_label"], "sample": r["sample"],
            "locator": r["locator"]}


def source_card(sid, src, names, rows, rels, ds):
    d, st = doc_of(src), status_of(src)
    kind = s(src.get("source_type"))
    pairs = []

    def add(label, text):
        if text not in (None, "", []):
            pairs.append((label, "、".join(s(x) for x in text) if isinstance(text, list) else s(text)))

    def f(key):
        return names.field("doc", key)

    add(names.field("source", "source_type"), names.enum("source_type", kind))
    if kind == "patent":
        idents = src.get("identifiers") if isinstance(src.get("identifiers"), dict) else {}
        head = s(idents.get("patent_number")) or s(d.get("application_number")) or sid
        add(names.field("source", "title"), src.get("title"))
        for key in ("applicants", "inventors"):
            add(f(key), d.get(key))
        add(names.field("source", "jurisdiction"), names.enum("jurisdiction", src.get("jurisdiction")))
        add(f("kind"), names.enum("patent_kind", d.get("kind")))
        for key in ("application_number", "filed", "priority_date"):
            add(f(key), d.get(key))
        add(names.field("source", "published"), src.get("published"))
        add(f("granted"), d.get("granted"))
        members = d.get("family_members") if isinstance(d.get("family_members"), list) else []
        add(f("family_id"), "｜".join(x for x in (s(d.get("family_id")), f"同族 {len(members)} 件：{'、'.join(s(x) for x in members)}" if members else "") if x))
        add(f("classifications"), d.get("classifications"))
    else:
        head = s(src.get("title")) or sid
        for key in ("issuer", "doc_number", "funder", "programme", "project_number", "commissioned_by"):
            add(f(key), d.get(key))
        add(names.field("source", "creators"), src.get("creators") if kind in T.BLOCKS[2][2] else None)
        add(names.field("source", "jurisdiction"), names.enum("jurisdiction", src.get("jurisdiction")))
        for key in ("host", "pi"):
            add(f(key), d.get(key))
        money = s(d.get("amount_stated")) or " ".join(x for x in (fmt_num(d.get("amount")) if d.get("amount") is not None else "", s(d.get("currency"))) if x)
        add(f("amount"), money)
        span = "–".join(x for x in (s(d.get("start")), s(d.get("end"))) if x)
        add("起止", span)
        add(names.field("source", "published"), src.get("published") if not d.get("issued") else None)
        for key in ("issued", "effective", "scope", "replaces", "replaced_by", "pages"):
            add(f(key), d.get(key))
    stage = names.enum("doc_stage", st.get("stage"))
    checked = "照 " + " ".join(x for x in (s(st.get("checked_in")), s(st.get("checked_at"))) if x) + " 的记录" if st.get("checked_in") or st.get("checked_at") else ""
    add("法律状态" if kind == "patent" else "现在的状态", "｜".join(x for x in (stage, s(st.get("stated")), checked) if x))
    nxt = st.get("next_step") if isinstance(st.get("next_step"), dict) else {}
    if nxt:
        add("下一个时间点", "｜".join(x for x in (s(nxt.get("summary")), f"预计 {s(nxt['expected'])}" if nxt.get("expected") else "", s(nxt.get("locator"))) if x))
    scope = s(src.get("access_scope"))
    unpaid = isinstance(src.get("paid"), dict) and not src["paid"].get("purchased")
    if scope != "full" or unpaid:
        add("读到哪里", "｜".join(x for x in (names.enum("access_scope", scope) or NOT_FILLED, names.flag("not_purchased") if unpaid else "") if x))
    verified = V.is_human(src.get("record_verified_by")) and bool(src.get("record_verified_at"))
    needs = kind in V.VERIFY_RECORD_TYPES
    return {"id": sid, "kind": kind, "head": head, "chip": stage or s(st.get("stated")), "pairs": pairs,
            "evidence": [ev_line(r) for r in rows], "relations": rels,
            "verified": f"{s(src.get('record_verified_by'))}，{s(src.get('record_verified_at'))}" if verified else "",
            "needs_verify": needs and not verified}


def events_of(cards_sources):
    """政策法规和标准的事项，新的在前；时间表上预计的排在最前面。"""
    out = []
    for sid, src in cards_sources:
        st = status_of(src)
        title = s(src.get("title")) or sid
        for ev in st.get("events") or [] if isinstance(st.get("events"), list) else []:
            if isinstance(ev, dict):
                out.append({"date": s(ev.get("date")), "what": f"{title}：{s(ev.get('summary'))}", "where": s(ev.get("locator")), "expected": False, "source": sid})
        nxt = st.get("next_step") if isinstance(st.get("next_step"), dict) else None
        if nxt:
            out.append({"date": s(nxt.get("expected")), "what": f"{title}：{s(nxt.get('summary'))}", "where": s(nxt.get("locator")), "expected": True, "source": sid})
    out.sort(key=lambda x: (x["expected"], x["date"]), reverse=True)
    return out


def market_groups(rows, ds, names):
    """报告里的数和说法，按指标或事实项分开；同一项里各个来源的数并排，不合并。"""
    groups, order = {}, []
    for r in rows:
        key = (r["measure_kind"], r["measure_key"])
        if key not in groups:
            groups[key] = {"key": f"{key[0]}:{key[1]}", "name": r["measure"], "items": []}
            order.append(key)
        src = ds["sources"].get(r["source_id"]) or {}
        e = r["e"]
        number = V.parse_number(e.get("value_reported")) if e.get("content_kind") == "numeric" else None
        groups[key]["items"].append({
            "id": r["id"], "source": "｜".join(x for x in (s(src.get("title")) or r["source_id"], r["source_type_label"], s(src.get("published"))) if x),
            "source_id": r["source_id"], "value": r["value"], "number": number, "unit": s(e.get("unit_reported")),
            "basis": "；".join(f"{c['name']} {c['text']}" for c in r["conditions"]), "locator": r["locator"],
            "type_label": r["type_label"], "flags": list(r["flags"]), "status": r["status"], "status_label": r["status_label"]})
    out = []
    for key in order:
        g = groups[key]
        nums = [x["number"] for x in g["items"] if x["number"] is not None]
        units = {x["unit"] for x in g["items"] if x["number"] is not None}
        g["scale"] = None
        if len(nums) >= 2 and min(nums) >= 0 and len(units) == 1:   # 只有一个数的不画条；单位不一样的也不画
            g["scale"] = 100.0 if units == {"%"} and max(nums) <= 100 else (max(nums) or None)
        out.append(g)
    return out


def build(m, ds, topic_id):
    names, cutoff = m["names"], m["cutoff"]
    sources = T.topic_sources(ds, topic_id)
    mine = [(sid, src) for sid, src, _ in T.included(sources) if s(src.get("source_type")) in T.BLOCK_TYPES]
    mine_ids = {sid for sid, _ in mine}
    by_source = {}
    for r in m["rows"]:
        if r["status"] != "void" and not r["error"]:
            by_source.setdefault(r["source_id"], []).append(r)
    rels = []
    for rid in sorted(ds["relations"]):
        rel = ds["relations"][rid]
        if not isinstance(rel, dict):
            continue
        ends = [rel.get("subject"), rel.get("object")]
        family = any(isinstance(ds["entities"].get(x), dict) and ds["entities"][x].get("entity_type") == "patent_family" for x in ends if isinstance(x, str))
        if family or any(x in mine_ids for x in ends):
            rels.append((rel, relation_model(ds, names, rel)))

    def rels_of(sid):
        return [model for rel, model in rels if sid in (rel.get("subject"), rel.get("object"))]

    blocks = []
    for key, title, types, unit in T.BLOCKS:
        srcs = [(sid, src) for sid, src in mine if s(src.get("source_type")) in types]
        cards = [source_card(sid, src, names, by_source.get(sid, []), rels_of(sid), ds) for sid, src in srcs]
        rows = [r for sid, _ in srcs for r in by_source.get(sid, [])]
        if key == "patent":
            sub = "，".join(f"{names.enum('patent_kind', k) or NOT_FILLED} {n}" for k, n in T.counted([s(doc_of(src).get("kind")) for _, src in srcs], names.enum_order("patent_kind")))
        elif key == "policy":
            stages = T.counted([s(status_of(src).get("stage")) for _, src in srcs], names.enum_order("doc_stage"))
            sub = "，".join(f"{names.enum('doc_stage', k) or '状态' + NOT_FILLED} {n}" for k, n in stages)
        elif key == "market":
            sub = "，".join(f"{name} {n} 条" for name, n in T.counted([r["measure"] for r in rows]))
        else:
            papers = {rel.get("subject") for rel, _ in rels if rel.get("relation_type") == "funded_by" and rel.get("object") in {sid for sid, _ in srcs}}
            sub = f"对得上 {len(papers)} 个来源" if srcs else ""
        blocks.append({"key": key, "title": title, "unit": unit, "n": len(srcs), "sub": sub, "cards": cards,
                       "evidence": [r["id"] for r in rows], "rows": rows, "sources": srcs})
    policy = next(b for b in blocks if b["key"] == "policy")
    market = next(b for b in blocks if b["key"] == "market")
    grant = next(b for b in blocks if b["key"] == "grant")

    # 按法域：每一类来源有几个
    types = [k for k, _ in T.counted([s(src.get("source_type")) for _, src in mine], names.enum_order("source_type"))]
    used = {s(src.get("jurisdiction")) for _, src in mine}
    cols = [j for j in names.enum_order("jurisdiction") if j in MAIN_JURISDICTIONS or j in used] + (["" ] if "" in used else [])
    matrix = [{"type": names.enum("source_type", t) or NOT_FILLED,
               "cells": [sum(1 for _, src in mine if s(src.get("source_type")) == t and s(src.get("jurisdiction")) == j) for j in cols]} for t in types]

    all_rows = [r for b in blocks for r in b["rows"]]
    by_status = [(names.enum("verification_status", k) or NOT_FILLED, n) for k, n in T.counted([r["status"] for r in all_rows], names.enum_order("verification_status"))]
    checks = sorted((s(status_of(src).get("checked_at")), sid) for sid, src in mine if status_of(src).get("checked_at"))
    stale = [sid for d, sid in checks if cutoff and d < cutoff]
    core = [sid for sid, src, _ in T.included(sources) if s(src.get("source_type")) in V.CORE_CHECK_TYPES]
    funded = {rel.get("subject") for rel, _ in rels if rel.get("relation_type") == "funded_by" and rel.get("object") in {sid for sid, _ in grant["sources"]}}

    gaps = []
    for b in blocks:
        if not b["n"]:
            gaps.append({"key": f"empty_{b['key']}", "text": f"{b['title']}：这一批里还没有来源。", "ids": []})
    none = [names.enum("jurisdiction", j) for j in MAIN_JURISDICTIONS if j not in used]
    if none and mine:
        gaps.append({"key": "jurisdiction", "text": f"还没有来源的法域：{'、'.join(none)}。", "ids": []})
    for code, label in (("abstract_only", "只读到仅摘要的"), ("metadata_only", "只有题录、没有读到内容的")):
        ids = [sid for sid, src in mine if src.get("access_scope") == code]
        if ids:
            gaps.append({"key": code, "text": f"{label}：", "ids": ids})
    unpaid = [sid for sid, src in mine if isinstance(src.get("paid"), dict) and not src["paid"].get("purchased")]
    if unpaid:
        gaps.append({"key": "not_purchased", "text": "付费没有买、只用了公开部分的：", "ids": unpaid})
    unverified = [c["id"] for b in blocks for c in b["cards"] if c["needs_verify"]]
    if unverified:
        gaps.append({"key": "record_unverified", "text": "登记内容（著录项目和状态）还没有人工核对的，报告用到之前要核对：", "ids": unverified})
    if stale:
        gaps.append({"key": "stale_status", "text": f"状态是在题目的截至日期（{cutoff}）之前查的，出报告前要再查一次：", "ids": stale})
    waiting = [r["id"] for r in all_rows if r["status"] not in V.VERIFIED]
    if waiting:
        gaps.append({"key": "not_verified", "text": f"还没有人工核对、不能进报告的证据 {len(waiting)} 条：", "ids": waiting})

    return {"blocks": blocks, "matrix": matrix, "cols": [names.enum("jurisdiction", j) or NOT_FILLED for j in cols],
            "by_status": by_status, "evidence_total": len(all_rows), "checks": checks, "stale": stale,
            "events": events_of(policy["sources"]), "market": market_groups(market["rows"], ds, names),
            "market_waiting": [r["id"] for r in market["rows"] if r["status"] not in V.VERIFIED],
            "papers": len(core), "papers_funded": len([x for x in core if x in funded]),
            "relations": [model for _, model in rels], "gaps": gaps, "source_ids": mine_ids,
            "reviews": gaps_view.loose_reviews(m, ds, topic_id, lambda types: bool(types) and types <= T.BLOCK_TYPES)}


# ---------------------------------------------------------------- 写成网页

def kv(pairs):
    return el("dl", {"class": "kv"}, [(el("dt", None, k), el("dd", None, v)) for k, v in pairs])


def status_span(code, label):
    return el("span", {"class": f"status s-{cls(code)}"}, label)


def render_card(c, known):
    lines = []
    for x in c["evidence"]:
        what = "｜".join(y for y in (x["sample"], x["measure"]) if y)
        tail = "｜".join(y for y in [x["conds"], x["type_label"]] + x["flags"] + [x["locator"]] if y)
        lines.append(el("li", {"data-ev": x["id"]}, el("span", {"class": "strong"}, what, "：", x["value"]), " ",
                        el("span", {"class": "sub"}, tail + "｜" if tail else "", el("a", {"href": f"#{x['id']}"}, x["id"]), "｜", x["status_label"])))
    rel_lines = [el("li", None, r["what"], " ", el("span", {"class": "sub"}, f"{r['id']}｜{r['how']}｜{r['status_label']}")) for r in c["relations"]]
    check = el("div", {"class": "sub"}, f"登记内容人工核对：{c['verified']}") if c["verified"] else (
        el("div", {"class": "sub"}, el("span", {"class": "missing"}, "登记内容还没有人工核对")) if c["needs_verify"] else None)
    return el("div", {"class": "doc-card", "id": c["id"], "data-kind": c["kind"]},
              el("div", {"class": "doc-head"}, el("span", {"class": "strong"}, c["head"]), " ",
                 el("span", {"class": "chip-static"}, c["chip"]) if c["chip"] else None, " ", el("span", {"class": "sub"}, c["id"])),
              kv(c["pairs"]),
              el("div", {"class": "block"}, el("div", {"class": "block-name"}, "证据"),
                 el("ul", {"class": "plain"}, lines) if lines else el("div", {"class": "note"}, "这个来源还没有录证据。")),
              el("div", {"class": "block"}, el("div", {"class": "block-name"}, "对得上的"), el("ul", {"class": "plain"}, rel_lines)) if rel_lines else None,
              check)


def block_section(b, intro, *extra, note=None, known=()):
    cards = [render_card(c, known) for c in b["cards"]]
    return el("section", {"class": "card", "id": f"block-{b['key']}", "aria-label": b["title"]},
              el("div", {"class": "view-head"}, el("h2", None, b["title"])), el("p", {"class": "note"}, intro),
              el("div", {"class": "doc-cards"}, cards) if cards else el("p", {"class": "empty"}, "这一批里还没有来源。"),
              extra, el("p", {"class": "note"}, note) if note else None)


def render_market(groups, waiting, known):
    out = []
    for g in groups:
        rows = []
        for x in g["items"]:
            share = x["number"] / g["scale"] if g["scale"] and x["number"] is not None else None
            tail = "｜".join(y for y in [x["basis"], x["locator"], x["type_label"]] + x["flags"] if y)
            rows.append(el("div", {"class": "meter", "data-ev": x["id"]},
                           el("div", {"class": "line"}, el("span", None, x["source"]), " ", el("span", {"class": "strong"}, x["value"])),
                           gaps_view.bar(share) if share is not None else None,
                           el("div", {"class": "sub"}, tail + "｜" if tail else "", el("a", {"href": f"#{x['id']}"}, x["id"]), "｜", x["status_label"])))
        out.append(el("div", {"class": "block", "data-measure": g["key"]}, el("h3", None, g["name"]), el("div", {"class": "lines"}, rows)))
    if waiting:
        out.append(el("p", {"class": "banner-soft"}, f"还没有人工核对、不进报告的 {len(waiting)} 条：", gaps_view.id_links(waiting, known), "。"))
    return out


def render_events(events):
    if not events:
        return None
    items = [el("li", {"class": "event" + (" expected" if e["expected"] else ""), "data-source": e["source"]},
                el("span", {"class": "strong"}, (e["date"] or NOT_FILLED) + ("，预计" if e["expected"] else "")), " ", e["what"],
                [" ", el("span", {"class": "sub"}, e["where"])] if e["where"] else None) for e in events]
    return el("div", {"class": "block", "id": "policy-events"}, el("h3", None, "事项"), el("ol", {"class": "events"}, items),
              el("div", {"class": "note"}, "新的在前。带“预计”的是时间表上写的，还没有发生。"))


def render(model, m, title, question):
    names, known = m["names"], set(m["ids"])
    b = {x["key"]: x for x in model["blocks"]}
    tiles = [el("div", {"class": "tile", "data-tile": x["key"]}, el("div", {"class": "tile-name"}, x["title"]),
                el("div", {"class": "tile-n"}, f"{x['n']} {x['unit']}"), el("div", {"class": "tile-sub"}, x["sub"]),
                el("div", {"class": "tile-sub"}, f"证据 {len(x['evidence'])} 条") ) for x in model["blocks"]]
    status = "，".join(f"{label} {n} 条" for label, n in model["by_status"])
    checked = f"状态查的日期：{model['checks'][0][0]}" + (f" 至 {model['checks'][-1][0]}" if model["checks"][-1][0] != model["checks"][0][0] else "") + "；每次出报告前再查一次。" if model["checks"] else ""
    head = el("section", {"class": "card"},
              el("div", {"class": "view-head"}, el("h2", None, title), el("div", {"class": "note"}, question)),
              el("p", {"class": "note"}, "这些数不和论文数据放进同一个可比组；只整理和描述，不作评价。和对外报告第 4.2 至 4.5 节是同一份数据。"),
              el("div", {"class": "tiles"}, tiles),
              el("p", {"class": "note", "id": "na-status"}, f"{model['evidence_total']} 条证据：{status or '还没有'}。", checked))
    if model["matrix"]:
        rows = [el("tr", None, el("th", {"scope": "row"}, r["type"]), [el("td", None, n if n else el("span", {"class": "muted"}, "—")) for n in r["cells"]])
                for r in model["matrix"]]
        matrix = el("div", {"class": "table-wrap"}, el("table", {"class": "cmp-table matrix", "id": "jurisdictions"},
                    el("thead", None, el("tr", None, el("th", {"scope": "col"}, "类别"), [el("th", {"scope": "col"}, j) for j in model["cols"]])),
                    el("tbody", None, rows)))
    else:
        matrix = el("p", {"class": "empty"}, "这一批里还没有非学术来源。")
    juris = el("section", {"class": "card", "id": "by-jurisdiction", "aria-label": "按法域"}, el("h2", None, "按法域：每一类有几个来源"),
               el("p", {"class": "note"}, "数的是纳入的来源，不是证据。“—”是这一格还没有来源。"), matrix)
    grants_note = f"{model['papers']} 个论文类的来源里，查到资助项目记录的是 {model['papers_funded']} 个。" if model["papers"] else None
    rel_rows = [el("div", {"class": "rel", "id": r["id"], "data-inferred": "yes" if r["inferred"] else "no"},
                   el("span", {"class": "strong"}, r["id"]), " ", el("span", {"class": "rel-what"}, r["what"]), " ",
                   el("span", {"class": "sub"}, r["from"]), " ",
                   el("span", {"class": "chip-static" + (" dashed" if r["inferred"] else "")}, r["how"]), " ", status_span(r["status"], r["status_label"]))
                for r in model["relations"]]
    relations = el("section", {"class": "card", "id": "na-relations", "aria-label": "和论文、企业对得上的"}, el("h2", None, "和论文、企业对得上的"),
                   el("p", {"class": "note"}, "每条关系都有出处。“推断”是按出处推出来的，要人确认过才进报告。原文没有写、建立不了的对应，数据里不记。"),
                   el("div", {"class": "rels"}, rel_rows) if rel_rows else el("p", {"class": "empty"}, "还没有记到和这四块有关的关系。"))
    gaps = el("section", {"class": "card", "id": "na-gaps", "aria-label": "这四块缺什么"}, el("h2", None, "这四块缺什么"),
              el("div", {"class": "lines"}, [el("div", {"class": "gap", "data-gap": g["key"]}, g["text"], gaps_view.id_links(g["ids"], known | model["source_ids"]),
                                              "。" if g["ids"] else "") for g in model["gaps"]])
              if model["gaps"] else el("p", {"class": "empty"}, "数据里没有数出缺口。"),
              el("p", {"class": "note"}, "查了哪里、怎么查的，在", el("a", {"href": "#gaps"}, "数据概览与缺口"), "的“查了什么，读到多少”里。"))
    return el("section", {"class": "view", "id": "non-academic", "aria-label": title},
              head, juris,
              block_section(b["patent"], "同族算一件。法律状态照数据库的记录写，不作解读；不作侵权和自由实施的判断。",
                            note="专利实施例里的数标“专利实施例，未经同行评议”，和论文数据不进同一个可比组。", known=known),
              block_section(b["policy"], "每份文件现在的状态照发布机构的记录写，写明在哪里、哪天查的。", render_events(model["events"]), known=known),
              el("section", {"class": "card", "id": "block-market", "aria-label": b["market"]["title"]},
                 el("div", {"class": "view-head"}, el("h2", None, b["market"]["title"])),
                 el("p", {"class": "note"}, "报告里的数不进可比组，按口径并排。不同报告对同一件事给的数不一样时照实列出，不合并成一个数。条长只表示数的大小，不表示好坏；口径不同的数不能直接比。"),
                 render_market(model["market"], model["market_waiting"], known) or el("p", {"class": "empty"}, "这一批里还没有报告里的数。"),
                 el("div", {"class": "doc-cards"}, [render_card(c, known) for c in b["market"]["cards"]]) if b["market"]["cards"] else None),
              block_section(b["grant"], "按论文致谢里的项目号，到基金的项目库里查。", note=grants_note, known=known),
              relations, gaps_view.render_reviews(model["reviews"], names, "非学术来源的复核单"), gaps,
              el("p", {"class": "note"}, "对外报告第 4.2 至 4.5 节、第 5 节里的关系和第 7 节里这四块的缺口，由这一页用的同一份数据生成。原文片段和出处，到",
                 el("a", {"href": "#evidence"}, "证据表"), "里按来源类别筛。"))
