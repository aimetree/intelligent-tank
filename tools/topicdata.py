"""总览、数据概览与缺口、非学术来源三页和报告侧的导出共用的整理：
这个题目登记了哪些来源；有哪些膜，每张膜名下有哪些证据；指标怎么并成列；一张膜的一项指标核到了哪一步。

只数、只摆，不评价（D-60）。指标、条件、分类都从题目卡和指标字典里读，这里不写死任何一个键（D-03）。
"""
import access as A
from display import NOT_FILLED, s

# 核验这条路上的四步，核得越深数越大。存疑、作废不在这条路上，单独算
STATUS_DEPTH = {"pending": 1, "machine_checked": 2, "human_verified": 3, "expert_reviewed": 4}
DEPTH_STATUS = {v: k for k, v in STATUS_DEPTH.items()}
# 非学术来源页的四块各管哪几类来源（设计方案 4.2 的 K9，D-111）
BLOCKS = [
    ("patent", "专利", ("patent",), "件"),
    ("policy", "政策法规和标准", ("policy", "standard"), "项"),
    ("market", "产业和市场的数字", ("consultancy_report", "government_report", "institution_report", "funder_report"), "份"),
    ("grant", "科研资助", ("grant_record",), "条"),
]
BLOCK_TYPES = {t for _, _, types, _ in BLOCKS for t in types}


def topic_entry(src, topic_id):
    """来源在这个题目下的那一项（纳入还是排除、怎么找到的、核心指标找过的结果）。"""
    if not isinstance(src, dict) or not isinstance(src.get("topics"), list):
        return None
    for t in src["topics"]:
        if isinstance(t, dict) and t.get("topic_id") == topic_id:
            return t
    return None


def topic_sources(ds, topic_id):
    """登记在这个题目下的来源：[(编号, 来源, 这个题目下的那一项)]，照编号排。"""
    out = []
    for sid in A.source_ids(ds):
        src = A.source(ds, sid)
        entry = topic_entry(src, topic_id)
        if entry is not None:
            out.append((sid, src, entry))
    return out


def included(sources):
    return [x for x in sources if x[2].get("decision") == "included"]


def counted(items, order=()):
    """数一数：[(值, 几个)]，照 order 里的次序，order 里没有的排在后面。"""
    counts = {}
    for x in items:
        counts[x] = counts.get(x, 0) + 1
    rank = {code: i for i, code in enumerate(order)}
    return [(k, counts[k]) for k in sorted(counts, key=lambda k: (rank.get(k, len(rank)), s(k)))]


def is_product(ent):
    return isinstance(ent, dict) and ent.get("entity_type") == "product"


def entity_name(ds, eid):
    ent = A.entity(ds, eid) if isinstance(eid, str) else None
    return s(ent.get("name")) if isinstance(ent, dict) and ent.get("name") else s(eid)


def facet_values(ds, topic, names, sample, entity):
    """这张膜的分类，照题目卡里分类维度的次序：[(维度名, 取值的显示名)]。
    记在膜上的维度取样品登记（商业膜取产品实体），记在材料族上的取它所属的材料族。"""
    entity = entity if isinstance(entity, dict) else {}
    family = entity if entity.get("entity_type") == "material_class" else A.entity(ds, entity.get("class_id"))
    own = (entity.get("facets") if is_product(entity) else (sample or {}).get("facets")) or {}
    out = []
    for f in topic.get("facets") or []:
        if not isinstance(f, dict) or not isinstance(f.get("key"), str):
            continue
        where = ((family or {}).get("facets") or {}) if f.get("applies_to") == "material_class" else own
        v = where.get(f["key"]) if isinstance(where, dict) else None
        if isinstance(v, str) and v:
            out.append((s(f.get("name")) or f["key"], names.value(f["key"], v)))
    return out


def membranes(ds, topic_id, names, rows):
    """这个题目里的每一张膜，和它名下的证据。
    实验室样品照样品登记：一个来源里的一个样品名算一张，各篇各算各的；补充材料里的数算在所属论文的样品上。
    商业膜按产品实体算：几篇论文都拿它作基准、规格书里也有它，是同一张。
    没有样品名、对象又不是产品的证据（专利权利要求、政策条款、报告里的数）不是哪一张膜的，不在这里。
    次序：先实验室样品，照来源编号和登记的次序；再商业膜，照实体编号。行的次序就是录入的次序，不排名。"""
    topic = A.topic(ds, topic_id) or {}
    lk = A.lookups(ds)
    labs, products = [], {}

    def product(ent):
        key = f"entity|{ent.get('id')}"
        if key not in products:
            products[key] = {"key": key, "kind": "product", "label": s(ent.get("name")) or s(ent.get("id")),
                             "source_id": "", "sample": "", "subject_id": s(ent.get("id")), "roles": [], "used_by": [],
                             "facets": facet_values(ds, topic, names, None, ent), "core_check": {}, "rows": []}
        return products[key]

    by_key = {}
    for sid, src, entry in topic_sources(ds, topic_id):
        if entry.get("decision") == "excluded":
            continue
        for sm in A.samples(ds, sid) or []:
            if not isinstance(sm, dict) or not isinstance(sm.get("label"), str):
                continue
            ent = A.entity(ds, sm.get("subject_id")) if isinstance(sm.get("subject_id"), str) else None
            if is_product(ent):
                p = product(ent)
                if sm.get("role") and sm["role"] not in p["roles"]:
                    p["roles"].append(sm["role"])
                if sid not in p["used_by"]:
                    p["used_by"].append(sid)
                by_key[(sid, sm["label"])] = p
                continue
            mem = {"key": f"{sid}|{sm['label']}", "kind": "lab", "label": sm["label"], "source_id": sid, "sample": sm["label"],
                   "subject_id": s(sm.get("subject_id")), "roles": [sm["role"]] if sm.get("role") else [], "used_by": [sid],
                   "facets": facet_values(ds, topic, names, sm, ent),
                   "core_check": entry.get("core_check") if isinstance(entry.get("core_check"), dict) else {}, "rows": []}
            labs.append(mem)
            by_key[(sid, sm["label"])] = mem

    for r in rows:
        if r["error"]:
            continue
        sid, label = r["source_id"], r["sample"]
        owner = sid if A.samples(ds, sid) is not None else (s((A.source(ds, sid) or {}).get("parent_id")) or sid)
        ent = A.entity(ds, r["subject_id"])
        mem = by_key.get((owner, label)) if label else None
        if mem is None and label and lk.register_of(sid).get(label) is None and not is_product(ent):
            # 证据写了样品名，样品登记里却没有：照实列一张，校验（V-19）会另外报出来
            mem = {"key": f"{owner}|{label}", "kind": "lab", "label": label, "source_id": owner, "sample": label,
                   "subject_id": r["subject_id"], "roles": [], "used_by": [owner], "facets": facet_values(ds, topic, names, None, ent),
                   "core_check": {}, "rows": []}
            labs.append(mem)
            by_key[(owner, label)] = mem
        if mem is None and is_product(ent):
            mem = product(ent)
        if mem is not None:
            mem["rows"].append(r)
    return labs + [products[k] for k in sorted(products)]


def indicator_groups(names):
    """指标并成列：指标清单上同一个编号（IN-xx）的几个键算一列，比如三项效率（规格 9.1 第 22 项）。
    由别的指标算出来的（entry 是 derived）和用实体、关系表达的（relations）没有自己的证据，不单列。
    返回 [{no, keys, label, level, core}]，照指标字典的次序。"""
    groups, by_no = [], {}
    for key, ind in names.indicators.items():
        if ind.get("entry", "evidence") != "evidence":
            continue
        no = ind.get("list_no") if isinstance(ind.get("list_no"), str) and ind.get("list_no") else key
        g = by_no.get(no)
        if g is None:
            g = by_no[no] = {"no": no, "keys": [], "names": [], "level": s(ind.get("level")), "core": False}
            groups.append(g)
        g["keys"].append(key)
        g["names"].append(names._name(ind, key))
        g["core"] = g["core"] or ind.get("grade") == "core"
    for g in groups:
        g["label"] = "／".join(g["names"])
    return groups


def skipped_indicators(names):
    """没有单列的指标：[(名字, 为什么)]。"""
    why = {"derived": "由别的指标的证据算出来", "relations": "用实体和关系表达"}
    return [(names._name(ind, key), why.get(ind.get("entry"), s(ind.get("entry"))))
            for key, ind in names.indicators.items() if ind.get("entry", "evidence") != "evidence"]


def cell(mem, group):
    """一张膜的一列指标现在是什么情况。
    state：有证据的，是这一项里核得最深的那一条的核验状态；只有存疑的是 disputed。
    没有证据的：这张膜所在的来源逐项找过核心指标、写的是原文没有报告，是 not_reported；写的是不适用，是 not_applicable；
    别的（没找过，或者这篇里别的样品有、这张没有）是 none。
    rows：这一格的证据，不含作废的；disputed：核得最深的那条之外，另有几条存疑。"""
    evs = [r for r in mem["rows"] if r["measure_kind"] == "indicator" and r["measure_key"] in group["keys"] and r["status"] != "void"]
    if evs:
        depth = max(STATUS_DEPTH.get(r["status"], 0) for r in evs)
        disputed = sum(1 for r in evs if r["status"] == "disputed")
        if depth:
            best = next(r for r in evs if STATUS_DEPTH.get(r["status"], 0) == depth)
            return {"state": DEPTH_STATUS[depth], "disputed": disputed, "rows": evs, "best": best}
        return {"state": "disputed" if disputed else "unknown", "disputed": 0, "rows": evs, "best": evs[0]}
    found = [mem["core_check"].get(k) for k in group["keys"] if k in mem["core_check"]]
    if found and "found" not in found:
        return {"state": "not_reported" if "not_reported" in found else "not_applicable", "disputed": 0, "rows": [], "best": None}
    return {"state": "none", "disputed": 0, "rows": [], "best": None}


def facet_text(mem):
    return "｜".join(v for _, v in mem["facets"]) or NOT_FILLED
