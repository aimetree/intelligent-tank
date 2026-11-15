"""网页前端的“页面要显示的内容”（views.json），由 tools/export_site_data.py 写出。

Yu 2026-11-15 定（选“甲”）：五页要显示的内容照旧由看板的 Python 函数算（build_dashboard.build_model 和四个页面脚本的 build），
前端只管显示、筛选、跳转和画 SVG。算法只有一套，新前端和旧看板显示的东西不会两样。

这里只做一件事：把 build_model 算好的那一大块变成能写成 JSON 的样子，不改任何一个数或一个字。
- 证据表的每一行只在 rows 里出现一次；页面模型里别处用到同一行的，写成 {"$row": 证据编号}，前端读进来时换回那一行。
- 一行里的原始记录 e 不写（前端要原始记录读 evidence.json）。
- 页面模型里有几处是已经写好的 HTML 片段（图、最近的变化里指向证据的链接、证据类型的记号），写成 {"$html": [节点]}。
  节点是 {"t": 标签, "a": 属性, "c": [子节点]}，文字节点就是字符串。前端照白名单把它画出来，不当网页代码插进页面。
- 键是 frozenset 的字典（可比性矩阵：谁和谁）写成 {"$pairs": [[[a, b], 内容], ...]}，a、b 排好序。
- 元组写成数组，集合写成排好序的数组。别的类型一律报错，免得悄悄丢了东西。
同一份数据写出来逐字节相同。
"""
import json
import os
import sys
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import access as A  # noqa: E402
import build_dashboard as B  # noqa: E402
import derive  # noqa: E402
import textmatch  # noqa: E402
import nonacademic_view as NA  # noqa: E402
import topicdata as T  # noqa: E402
import validate as V  # noqa: E402
from display import TIER_HANDLING, Names, cls  # noqa: E402
from htmlgen import VOID, Raw  # noqa: E402

FORMAT = 2   # views.json 的写法改了、前端要跟着改的时候加一。2：每一行加了 x（出图用的数、标准单位、数值在原文片段里的位置）

# HTMLParser 把标签名和属性名都改成小写；SVG 里有几个区分大小写的，照原样改回来
SVG_CASE = {"viewbox": "viewBox", "preserveaspectratio": "preserveAspectRatio"}


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {"c": []}
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = {"t": tag, "a": {SVG_CASE.get(k, k): ("" if v is None else v) for k, v in attrs}, "c": []}
        self.stack[-1]["c"].append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.stack.pop()

    def handle_endtag(self, tag):
        # 看板的片段都是 htmlgen 写的，开和关一定配对；对不上就是哪里错了，不猜
        if len(self.stack) < 2 or self.stack[-1]["t"] != tag:
            raise ValueError(f"结束标签 </{tag}> 和开着的标签对不上")
        self.stack.pop()

    def handle_data(self, data):
        if data != "\n":   # htmlgen 在一些标签后面加的换行，只为了文件好读
            self.stack[-1]["c"].append(data)


def _clean(nodes):
    for n in nodes:
        if isinstance(n, dict):
            if n["c"]:
                _clean(n["c"])
            else:
                del n["c"]
            if not n["a"]:
                del n["a"]
    return nodes


def html_nodes(raw):
    p = _Tree()
    p.feed(raw)
    p.close()
    if len(p.stack) != 1:
        raise ValueError("HTML 片段里有没关上的标签")
    return _clean(p.root["c"])


def to_json(x, rows):
    """rows：{id(一行): 证据编号}。"""
    if isinstance(x, Raw):
        return {"$html": html_nodes(x)}
    if x is None or isinstance(x, (str, bool, int, float)):
        return x
    if isinstance(x, dict):
        if id(x) in rows:
            return {"$row": rows[id(x)]}
        if any(isinstance(k, frozenset) for k in x):
            pairs = [[sorted(k), to_json(v, rows)] for k, v in x.items()]
            return {"$pairs": sorted(pairs, key=lambda p: p[0])}
        out = {}
        for k, v in x.items():
            if not isinstance(k, str):
                raise TypeError(f"键不是字符串：{k!r}")
            out[k] = to_json(v, rows)
        return out
    if isinstance(x, (list, tuple)):
        return [to_json(v, rows) for v in x]
    if isinstance(x, (set, frozenset)):
        return [to_json(v, rows) for v in sorted(x)]
    raise TypeError(f"写不成 JSON：{type(x).__name__}")


def field_titles(schema):
    """字段的显示名（schema 的 title）：{对象: {字段: 名字, "字段.里面的字段": 名字}}。前端的 names.field 照这个取。"""
    out = {}
    for obj, d in sorted(((schema or {}).get("$defs") or {}).items()):
        props = (d or {}).get("properties") if isinstance(d, dict) else None
        if not isinstance(props, dict):
            continue
        table = {}
        for key, prop in props.items():
            if not isinstance(prop, dict):
                continue
            if prop.get("title"):
                table[key] = prop["title"]
            inner = prop.get("properties") or ((prop.get("items") or {}).get("properties") if isinstance(prop.get("items"), dict) else None) or {}
            for sub, p in inner.items():
                if isinstance(p, dict) and p.get("title"):
                    table[f"{key}.{sub}"] = p["title"]
        if table:
            out[obj] = table
    return out


def legend(labels, schema):
    """全站共用的图例：和旧看板 render_legend 一样的四栏。"""
    names = Names(labels, None, schema)
    by_tier = {}
    for reason, tier in V.RISK_REASON_TIER.items():
        by_tier.setdefault(tier, []).append(names.enum("risk_reason", reason))
    return {
        "types": [{"code": c, "label": names.enum("evidence_type", c)} for c in names.enum_order("evidence_type")],
        "statuses": [{"code": c, "cls": cls(c), "label": names.enum("verification_status", c)} for c in names.enum_order("verification_status")],
        "tiers": [{"code": c, "text": names.enum("tier", c) + (f"：{TIER_HANDLING[c]}" if c in TIER_HANDLING else "")}
                  for c in names.enum_order("tier")],
        "risks": [{"code": c, "label": names.enum("risk_tier", c), "text": "；".join(by_tier[c]) if by_tier.get(c) else "以上都没有"}
                  for c in ("high", "medium", "low")],
    }


def snippet_mark(snippet, value):
    """记录的数值在原文片段里的位置 [起, 止]，前端拿来高亮。
    用机器核对同一套找法（textmatch.find_value）。只在片段里正好出现一次、而且片段不用规范化就能对上原文的位置时给；
    别的情形（找不到、出现几次、片段里有上标全角这类排版差别）给 None，前端就不高亮，不猜。"""
    if not isinstance(snippet, str) or not isinstance(value, str) or not snippet or not value:
        return None
    ends = textmatch.find_value(value, snippet)
    if len(ends) != 1 or textmatch._prep(snippet) != snippet:
        return None
    v = textmatch._prep(value)
    start = ends[0] - len(v)
    return [start, ends[0]] if start >= 0 and snippet[start:ends[0]] == v else None


def row_extras(row, names):
    """一行在新前端里还要用的几样：出图用的数（标准单位下）、标准单位、数值在原文片段里的位置。"""
    e = row.get("e") or {}
    try:
        _, _, measure, _ = names.measure(e)
        num = derive.comparable_value(e, measure) if e.get("content_kind") == "numeric" else None
        unit = names.unit((measure or {}).get("unit_std"))
    except Exception:  # 这一行坏了：页面顶上已经写了，这里不再出数
        num, unit = None, ""
    return {"num": num, "unit": unit, "mark": snippet_mark(row.get("snippet"), e.get("value_reported"))}


# 页面模型里有几样网页前端用不着、又很占地方，导出时去掉（证据多了以后 views.json 会大好几倍）：
# 对标视图里 Python 画好的图（前端照成员和点的数自己画，颜色跟着深浅色走；报告里的图照旧由 tools/charts.py 出）；
# 非学术来源页每一块的整份来源登记和证据行（前端只用卡片、条数和编号）。
def prune(view):
    cmp = view.get("compare") or {}
    for lv in cmp.get("levels") or []:
        for g in lv.get("groups") or []:
            g.pop("chart", None)
        for s in lv.get("series") or []:
            s.pop("chart", None)
    for b in (view.get("nonacademic") or {}).get("blocks") or []:
        b.pop("rows", None)
        b.pop("sources", None)


# 新样子（A 2.0）的两页要多几样东西。都在这里由数据算好，前端只管画（Yu 2026-11-15 定“甲”）。

NOT_READY = ("pending", "machine_checked")   # 还不能进报告的核验状态（gaps_view 数“待核、机器已核”用的同一组）


def gaps_extras(view):
    """数据概览与缺口：
    每条缺口点了以后亮哪些：ev 是相关的证据（缺口里列的证据、列的来源的全部证据；“还不能进报告”那条没有列编号，按核验状态找），
    src 是缺口里列的来源（一览表里这个来源的膜整行亮）；数据概览的陈述已复核的排前面，同一状态里照编号。"""
    g = view.get("gaps")
    if not isinstance(g, dict):
        return
    rows = [r for r in view["rows"] if not r["error"] and r["status"] != "void"]
    for gap in g.get("gaps") or []:
        ids = set(gap.get("ids") or [])
        if gap.get("key") == "not_verified" and not ids:
            gap["ev"] = [r["id"] for r in rows if r["status"] in NOT_READY]
        else:
            gap["ev"] = [r["id"] for r in rows if r["id"] in ids or r["source_id"] in ids]
        gap["src"] = [x for x in gap.get("ids") or [] if x.startswith("SRC-")]
    g["statements"] = sorted(g.get("statements") or [], key=lambda a: a.get("status") != "reviewed")


def nonacademic_extras(view, names):
    """非学术来源：
    每块有哪些来源类别（法域表里亮哪几行）；法域表的每一列是不是必查的（题目按 D-96 的四个法域问，没有来源的标出来）；
    每张来源卡片挑三项放在最上面，其余照旧在“全部登记项目”里；政策法规的事项按来源分好。"""
    na = view.get("nonacademic")
    if not isinstance(na, dict):
        return
    by_label = {}
    for key, _, types, _ in T.BLOCKS:
        labels = [names.enum("source_type", t) for t in types]
        for b in na.get("blocks") or []:
            if b["key"] == key:
                b["types"] = labels
        for x in labels:
            by_label[x] = key
    for r in na.get("matrix") or []:
        r["block"] = by_label.get(r["type"], "")
    need = {names.enum("jurisdiction", j) for j in NA.MAIN_JURISDICTIONS}
    na["cols_need"] = [c in need for c in na.get("cols") or []]
    na["cols_empty"] = [not any(r["cells"][i] for r in na.get("matrix") or []) for i in range(len(na.get("cols") or []))]
    f = lambda part, key: names.field(part, key)   # noqa: E731
    pick = {
        "patent": [f("doc", "applicants"), f("source", "jurisdiction"), f("doc", "kind")],
        "policy": [f("source", "jurisdiction"), f("doc", "issued"), f("source", "published"), f("doc", "scope")],
        "market": [f("source", "jurisdiction"), f("source", "published"), "读到哪里"],
        "grant": [f("source", "jurisdiction"), f("doc", "host"), f("doc", "amount")],
    }
    for b in na.get("blocks") or []:
        for c in b.get("cards") or []:
            pairs = dict(c["pairs"])
            keys = [k for i, k in enumerate(pick.get(b["key"], [])) if k in pairs and k not in pick[b["key"]][:i]]
            c["facts"] = [[k, pairs[k]] for k in keys][:3]
            c["events"] = [e for e in na.get("events") or [] if e.get("source") == c["id"]]
            c["evidence_ids"] = [e["id"] for e in c["evidence"]]


def dumps(views):
    """views.json 不缩进：证据几百条时，缩进的写法要大两三倍。同一份数据写出来逐字节相同。"""
    return json.dumps(views, ensure_ascii=False, separators=(",", ":")) + "\n"


def topic_view(ds, schema, labels, topic_id, version):
    """一个题目五页要显示的内容。"""
    m = B.build_model(ds, schema, labels, topic_id, version)
    rows = {id(r): r["id"] for r in m["rows"]}
    out = {
        "topic_id": topic_id, "title": m["title"], "cutoff": m["cutoff"], "version": version, "stamp": B.stamp(m),
        "notice": m["notice"], "source_count": m["source_count"],
        "rows": [to_json(dict({k: v for k, v in r.items() if k != "e"}, x=row_extras(r, m["names"])), {}) for r in m["rows"]],
        "filters": to_json(m["filters"], rows),
        "issues": [[i.rule, B.s(i.record), i.message] for i in m["issues"]],
    }
    for key in ("compare", "overview", "gaps", "nonacademic"):
        out[key] = to_json(m[key], rows)
    gaps_extras(out)
    nonacademic_extras(out, m["names"])
    prune(out)
    out["errors"] = to_json(m["errors"], rows)   # 页面模型都算完才定：哪一页生成不了也记在这里
    out["csv"] = B.evidence_csv(m)
    return out


def views(ds, schema, labels, version):
    return {"format": FORMAT, "fields": field_titles(schema), "legend": legend(labels, schema), "sprite": to_json(B.sprite(), {}),
            "views": [{"key": name, "code": code, "title": title, "question": q} for name, code, title, q in B.VIEWS],
            "topics": [topic_view(ds, schema, labels, t, version) for t in A.topic_ids(ds)]}
