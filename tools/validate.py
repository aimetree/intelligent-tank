#!/usr/bin/env python3
"""校验 data/ 是否符合《数据结构_字段规格》v0.1（docs/03_技术与开发/数据结构_字段规格_v0.1.md）。

用法
  python3 tools/validate.py                         校验仓库里的 data/
  python3 tools/validate.py --data tools/tests/example
  python3 tools/validate.py --external CMP-000001   假设这些可比组要对外，多查对外门槛（V-61 至 V-63）

做两件事
  1. 结构：每条记录的字段名、类型、枚举和录入时就必填的字段，对照 data/schema/ 里的定义。
  2. 规则：规格第 5 节的 V-xx，包括带条件的必填项和跨记录的检查。

退出码  0 通过；1 有问题；2 用法或环境不对。
依赖    jsonschema（pip install -r tools/requirements.txt）。
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
from collections import namedtuple

Issue = namedtuple("Issue", "rule record message")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA = os.path.join(REPO, "data")
DEFAULT_SCHEMA = os.path.join(REPO, "data", "schema", "intelligent-tank.schema.json")

ID_PATTERNS = {
    "TOP": r"^TOP-\d{6}$", "SRC": r"^SRC-\d{6}$", "ENT": r"^ENT-\d{6}$", "EV": r"^EV-\d{6}-\d{3,}$",
    "REL": r"^REL-\d{6}$", "CMP": r"^CMP-\d{6}$", "ASM": r"^ASM-\d{6}$", "CHG": r"^CHG-\d{6}$",
    "LOG": r"^LOG-\d{6}$", "RPT": r"^RPT-\d{6}$",
}
NOT_HUMAN = {"claude", "script"}
VERIFIED = ("human_verified", "expert_reviewed")
# 只留内部、不导出给对方的字段（规格第 6 节，V-64）。生成报告附录的脚本用 strip_internal()。
INTERNAL_ONLY = {
    "snippet", "conditions_snippet", "internal_note", "machine_check", "created_by", "verified_by",
    "expert_reviewed_by", "entry_method", "double_extraction",
}


def is_human(actor):
    return isinstance(actor, str) and actor != "" and actor not in NOT_HUMAN


def strip_internal(evidence):
    """对外导出一条证据之前调用：去掉只留内部的字段。"""
    row = {k: v for k, v in evidence.items() if k not in INTERNAL_ONLY}
    if isinstance(row.get("figure_read"), dict):
        row["figure_read"] = {k: v for k, v in row["figure_read"].items() if k in ("reading_error", "source_data_checked")}
    return row


# ---------------------------------------------------------------- 读入

def _read_json(path, problems, rel):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        problems.append(Issue("V-00", rel, f"读不了这个文件：{exc}"))
        return None


def _read_jsonl(path, problems, rel):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError as exc:
                problems.append(Issue("V-00", f"{rel} 第 {n} 行", f"不是合法的 JSON：{exc}"))
    return rows


def load_dataset(data_dir):
    """把 data/ 读成一个字典。读不了的文件、重复的编号记在 ds["problems"] 里。"""
    problems = []
    ds = {"dir": data_dir, "problems": problems, "meta": None, "sources": {}, "evidence": {}, "entities": {},
          "relations": {}, "topics": {}, "dictionaries": {}, "comparisons": {}, "assessments": {}, "reports": {},
          "changes": [], "worklog": []}

    def put(coll, rec, where):
        rid = rec.get("id") if isinstance(rec, dict) else None
        if not isinstance(rid, str):
            problems.append(Issue("V-00", where, "有一条记录没有 id，或者不是一个对象"))
            return
        if rid in ds[coll]:
            problems.append(Issue("V-01", rid, f"编号重复（{where}）"))
            return
        ds[coll][rid] = rec

    meta_path = os.path.join(data_dir, "meta.json")
    if os.path.exists(meta_path):
        ds["meta"] = _read_json(meta_path, problems, "meta.json")
    else:
        problems.append(Issue("V-00", "meta.json", "缺 meta.json"))

    pub = os.path.join(data_dir, "public")
    for path in sorted(glob.glob(os.path.join(pub, "sources", "*.json"))):
        rel = os.path.relpath(path, data_dir)
        doc = _read_json(path, problems, rel)
        if not isinstance(doc, dict) or not isinstance(doc.get("source"), dict):
            if doc is not None:
                problems.append(Issue("V-00", rel, "来源文件应是 {source, evidence} 的结构"))
            continue
        src = doc["source"]
        put("sources", src, rel)
        if src.get("id") != os.path.splitext(os.path.basename(path))[0]:
            problems.append(Issue("V-01", rel, "文件名与来源编号不一致"))
        for ev in doc.get("evidence") or []:
            put("evidence", ev, rel)
            if isinstance(ev, dict) and ev.get("source_id") != src.get("id"):
                problems.append(Issue("V-20", str(ev.get("id")), f"放在 {rel} 里，但 source_id 不是这个来源"))

    for coll, name in (("entities", "entities.json"), ("relations", "relations.json")):
        path = os.path.join(pub, name)
        if os.path.exists(path):
            for rec in _read_json(path, problems, f"public/{name}") or []:
                put(coll, rec, f"public/{name}")

    for tdir in sorted(glob.glob(os.path.join(pub, "topics", "*", ""))):
        rel = os.path.relpath(tdir, data_dir)
        tpath = os.path.join(tdir, "topic.json")
        if not os.path.exists(tpath):
            problems.append(Issue("V-00", rel, "题目目录里缺 topic.json"))
            continue
        topic = _read_json(tpath, problems, rel + "/topic.json")
        if not isinstance(topic, dict):
            continue
        put("topics", topic, rel + "/topic.json")
        tid = topic.get("id")
        if tid != os.path.basename(os.path.normpath(tdir)):
            problems.append(Issue("V-01", rel, "目录名与题目编号不一致"))
        dpath = os.path.join(tdir, "dictionary.json")
        if os.path.exists(dpath):
            dic = _read_json(dpath, problems, rel + "/dictionary.json")
            if isinstance(dic, dict):
                ds["dictionaries"][tid] = dic
        for coll, name in (("comparisons", "comparisons.json"), ("assessments", "assessments.json"), ("reports", "reports.json")):
            path = os.path.join(tdir, name)
            if os.path.exists(path):
                for rec in _read_json(path, problems, f"{rel}/{name}") or []:
                    put(coll, rec, f"{rel}/{name}")

    ds["changes"] = _read_jsonl(os.path.join(data_dir, "changes.jsonl"), problems, "changes.jsonl")
    ds["worklog"] = _read_jsonl(os.path.join(data_dir, "worklog.jsonl"), problems, "worklog.jsonl")
    return ds


def load_schema(path=DEFAULT_SCHEMA):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- 结构

def _structure_message(err):
    path = "/".join(str(p) for p in err.absolute_path) or "（整条记录）"
    kw = err.validator
    if kw == "required":
        missing = [k for k in err.validator_value if not isinstance(err.instance, dict) or k not in err.instance]
        return f"{path} 缺必填字段：{'、'.join(missing)}"
    if kw == "additionalProperties":
        extra = sorted(set(err.instance) - set(err.schema.get("properties", {})))
        extra = [k for k in extra if not k.endswith("_en")]
        return f"{path} 有规格里没有的字段：{'、'.join(extra)}"
    if kw == "enum":
        return f"{path} 的取值 {err.instance!r} 不在枚举里"
    if kw == "type":
        return f"{path} 的类型不对（现在是 {type(err.instance).__name__}，应为 {err.validator_value}）"
    if kw == "pattern":
        return f"{path} 的写法不对：{err.instance!r}"
    if kw in ("oneOf", "anyOf"):
        return f"{path} 的写法不对：{json.dumps(err.instance, ensure_ascii=False)[:80]}"
    if kw in ("minItems", "minLength"):
        return f"{path} 不能为空"
    return f"{path}：{err.message}"


def _structure_rule(err, kind):
    kw = err.validator
    last = str(err.absolute_path[-1]) if err.absolute_path else ""
    if kw == "enum":
        return "V-03"
    if kw == "required" and kind in ("source", "evidence"):
        return "V-10" if kind == "source" else "V-20"
    if kw in ("pattern", "anyOf") and (last == "id" or last.endswith(("_id", "_ids", "_ref", "_of", "_by", "_into")) or last in ("subject", "object")):
        return "V-01"
    return "V-00"


def check_structure(ds, schema):
    """对照 schema 查每条记录的字段名、类型、枚举、必填。"""
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        raise SystemExit("缺 jsonschema：pip install -r tools/requirements.txt")
    cache = {}

    def validator(name):
        if name not in cache:
            cache[name] = Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": f"#/$defs/{name}"})
        return cache[name]

    issues = []

    def run(name, rec, label):
        for err in sorted(validator(name).iter_errors(rec), key=lambda e: list(map(str, e.absolute_path))):
            issues.append(Issue(_structure_rule(err, name), label, _structure_message(err)))

    if ds["meta"] is not None:
        run("meta", ds["meta"], "meta.json")
    for coll, name in (("sources", "source"), ("evidence", "evidence"), ("entities", "entity"), ("relations", "relation"),
                       ("topics", "topic"), ("comparisons", "comparison"), ("assessments", "assessment"), ("reports", "report")):
        for rid, rec in ds[coll].items():
            run(name, rec, rid)
    for tid, dic in ds["dictionaries"].items():
        run("dictionary", dic, f"{tid} 的指标字典")
    for rec in ds["changes"]:
        run("change", rec, str(rec.get("id", "changes.jsonl")) if isinstance(rec, dict) else "changes.jsonl")
    for rec in ds["worklog"]:
        run("worklog", rec, str(rec.get("id", "worklog.jsonl")) if isinstance(rec, dict) else "worklog.jsonl")
    return issues


# ---------------------------------------------------------------- 规则

def check_rules(ds, external=()):
    """规格第 5 节的规则。external：假设要对外的可比组编号。"""
    issues = []
    src, ev, ent, rel = ds["sources"], ds["evidence"], ds["entities"], ds["relations"]
    top, dic, cmp_, asm, rpt = ds["topics"], ds["dictionaries"], ds["comparisons"], ds["assessments"], ds["reports"]
    known = {"SRC": src, "EV": ev, "ENT": ent, "REL": rel, "TOP": top, "CMP": cmp_, "ASM": asm, "RPT": rpt}

    def E(rule, rid, msg):
        issues.append(Issue(rule, str(rid), msg))

    def ref(rid, target, kinds, what):
        """V-01 / V-02：target 的写法属于 kinds 之一，并且那条记录存在。"""
        if target is None:
            return None
        kind = next((k for k in kinds if isinstance(target, str) and re.match(ID_PATTERNS[k], target)), None)
        if kind is None:
            E("V-01", rid, f"{what} 的编号 {target!r} 写法不对，应为 {'、'.join(kinds)}")
            return None
        if target not in known[kind]:
            E("V-02", rid, f"{what} 指向的 {target} 不存在")
            return None
        return known[kind][target]

    def guarded(rid, fn):
        try:
            fn()
        except Exception as exc:  # 结构问题已经单独报了；这里保证一条坏记录不让整个检查停下
            E("V-00", rid, f"记录的结构有问题，后面的规则没法查（{type(exc).__name__}: {exc}）")

    def indicator_of(e):
        d = dic.get(e.get("topic_id")) or {}
        return next((x for x in d.get("indicators", []) if x.get("key") == e.get("indicator")), None)

    def unreported(e):
        ind = indicator_of(e) or {}
        cond = e.get("conditions") or {}
        return [k for k in ind.get("required_conditions", []) if cond.get(k) == "not_reported"]

    def reread_done(e):
        fr = e.get("figure_read") or {}
        return bool(fr.get("reread_by")) and fr.get("reading_error") is not None

    for coll, kind in (("sources", "SRC"), ("evidence", "EV"), ("entities", "ENT"), ("relations", "REL"), ("topics", "TOP"),
                       ("comparisons", "CMP"), ("assessments", "ASM"), ("reports", "RPT")):
        for rid, rec in ds[coll].items():
            if not re.match(ID_PATTERNS[kind], rid):
                E("V-01", rid, "编号的写法不对")
            if rec.get("visibility") == "client" or rec.get("client_code"):
                if coll != "topics":
                    E("V-05", rid, "公共区里不放客户专属的记录")

    # ---- 题目卡与指标字典（V-07）
    def topic_rules(tid, t):
        if t.get("status") == "active" and not (is_human(t.get("confirmed_by")) and t.get("confirmed_at")):
            E("V-07", tid, "进行中的题目要有确认人和日期")
        keys = [q.get("key") for q in t.get("questions", [])]
        if len(keys) != len(set(keys)):
            E("V-07", tid, "问题编号有重复")
        if tid not in dic:
            E("V-07", tid, "缺指标字典 dictionary.json")
    for tid, t in top.items():
        guarded(tid, lambda: topic_rules(tid, t))

    def dictionary_rules(tid, d):
        label = f"{tid} 的指标字典"
        if d.get("topic_id") != tid:
            E("V-02", label, "topic_id 与所在的题目目录不一致")
        cond_keys = [c.get("key") for c in d.get("conditions", [])]
        ind_keys = [i.get("key") for i in d.get("indicators", [])]
        rule_keys = [r.get("key") for r in d.get("rules", [])]
        for name, keys in (("条件项", cond_keys), ("指标", ind_keys), ("可比规则", rule_keys)):
            dup = sorted({k for k in keys if keys.count(k) > 1})
            if dup:
                E("V-07", label, f"{name}的键有重复：{'、'.join(dup)}")
        for i in d.get("indicators", []):
            for k in i.get("required_conditions", []) + i.get("optional_conditions", []):
                if k not in cond_keys:
                    E("V-07", label, f"指标 {i.get('key')} 用到的条件 {k} 不在条件项里")
            if i.get("value_kind") == "category" and not i.get("allowed_values"):
                E("V-07", label, f"分类型指标 {i.get('key')} 要列出允许的取值")
        for r in d.get("rules", []):
            for k in r.get("applies_to", []):
                if k not in ind_keys:
                    E("V-07", label, f"可比规则 {r.get('key')} 适用的指标 {k} 不在指标里")
    for tid, d in dic.items():
        guarded(tid, lambda: dictionary_rules(tid, d))

    # ---- 来源（关口 1）
    def source_rules(sid, s):
        ids = s.get("identifiers") or {}
        resolved = (s.get("id_check") or {}).get("result") == "pass"
        if not ((ids.get("doi") or ids.get("patent_number") or s.get("url")) and resolved) and s.get("use") != "lead":
            E("V-11", sid, "没有通过解析的标识（DOI、专利号或网址），只能作线索")
        t = s.get("terms") or {}
        if (t.get("no_ai") or t.get("no_scraping")) and s.get("reading_mode") != "human_only":
            E("V-12", sid, "条款有禁止自动抓取或用于 AI 的，阅读方式应为 human_only")
        if s.get("access_route") == "public_abstract" and s.get("access_scope") != "abstract_only":
            E("V-13", sid, "取得途径是公开摘要，读到的范围应为 abstract_only")
        if s.get("access_route") == "metadata" and s.get("access_scope") != "metadata_only":
            E("V-13", sid, "只有题录，读到的范围应为 metadata_only")
        if s.get("source_type") == "supplement" and not s.get("parent_id"):
            E("V-10", sid, "补充材料要填 parent_id，指向论文")
        if s.get("copy_kept") == "snapshot" and not (s.get("snapshot_ref") or s.get("archive_url")):
            E("V-10", sid, "留了快照要填 snapshot_ref 或 archive_url")
        for tu in s.get("topics", []):
            t_ = ref(sid, tu.get("topic_id"), ["TOP"], "topics.topic_id")
            if tu.get("decision") == "excluded" and not tu.get("exclusion_reason"):
                E("V-10", sid, "排除的来源要写排除原因")
            if t_ and s.get("use") == "evidence" and tu.get("decision") == "included" \
                    and s.get("source_type") not in t_.get("evidence_source_types", []):
                E("V-14", sid, f"来源类别 {s.get('source_type')} 不在题目卡允许作证据的类别里")
        ref(sid, s.get("parent_id"), ["SRC"], "parent_id")
        ref(sid, s.get("version_of"), ["SRC"], "version_of")
        ref(sid, s.get("publisher_id"), ["ENT"], "publisher_id")
    for sid, s in src.items():
        guarded(sid, lambda: source_rules(sid, s))

    # ---- 实体（V-06）
    def entity_rules(eid, e):
        if e.get("entity_type") == "organization" and not e.get("org_kind"):
            E("V-06", eid, "机构要填 org_kind")
        if e.get("entity_type") == "sample" and not e.get("defined_in"):
            E("V-06", eid, "样品要填 defined_in，指向首次描述它的来源")
        if e.get("identity_status") == "confirmed" and not (is_human(e.get("confirmed_by")) and e.get("confirmed_at")):
            E("V-06", eid, "人工确认的实体要有确认人和日期")
        if e.get("merged_into") == eid:
            E("V-06", eid, "不能并入自己")
        ref(eid, e.get("class_id"), ["ENT"], "class_id")
        ref(eid, e.get("merged_into"), ["ENT"], "merged_into")
        ref(eid, e.get("defined_in"), ["SRC"], "defined_in")
    for eid, e in ent.items():
        guarded(eid, lambda: entity_rules(eid, e))

    # ---- 证据（关口 2）
    def status_rules(rid, r):
        st = r.get("verification_status")
        if st in VERIFIED and not (is_human(r.get("verified_by")) and r.get("verified_at")):
            E("V-27", rid, "人工已核及以上要有核验人（必须是人）和日期")
        if st == "expert_reviewed" and not (is_human(r.get("expert_reviewed_by")) and r.get("expert_reviewed_at")):
            E("V-27", rid, "专业已复核要有复核人和日期")

    def evidence_rules(i, e):
        ref(i, e.get("topic_id"), ["TOP"], "topic_id")
        ref(i, e.get("subject_id"), ["ENT"], "subject_id")
        s = ref(i, e.get("source_id"), ["SRC"], "source_id") or {}
        for f in ("duplicate_of", "superseded_by"):
            ref(i, e.get(f), ["EV"], f)
        for f in ("conflicts_with", "validated_by"):
            for x in e.get(f, []):
                ref(i, x, ["EV"], f)
        if e.get("source_id") and i.split("-")[1:2] != e["source_id"].split("-")[1:2]:
            E("V-20", i, "编号里的来源序号与 source_id 不一致")
        kind, ind = e.get("content_kind"), indicator_of(e)
        if kind in ("numeric", "category") and not ind:
            E("V-21", i, f"指标 {e.get('indicator')!r} 不在指标字典里")
        if ind:
            if e.get("level") != ind.get("level"):
                E("V-21", i, f"层级 {e.get('level')} 与指标的层级 {ind.get('level')} 不一致")
            cond = e.get("conditions") or {}
            for k in ind.get("required_conditions", []):
                if k not in cond:
                    E("V-22", i, f"缺必填条件 {k}（原文没写应填 not_reported）")
            allowed = {c.get("key") for c in (dic.get(e.get("topic_id")) or {}).get("conditions", [])}
            for k in cond:
                if k not in allowed:
                    E("V-22", i, f"条件 {k} 不在指标字典的条件项里")
        if kind == "numeric":
            if not e.get("value_reported") or not e.get("unit_reported"):
                E("V-23", i, "数值型要有 value_reported 和 unit_reported")
            elif ind:
                factor = next((u.get("factor") for u in ind.get("units_accepted", []) if u.get("unit") == e["unit_reported"]), None)
                if factor is None:
                    E("V-23", i, f"单位 {e['unit_reported']} 不在指标允许的单位里")
                elif e.get("value_std") is None:
                    E("V-23", i, "缺 value_std（由脚本按换算系数算）")
                else:
                    try:
                        want = float(e["value_reported"]) * factor
                    except ValueError:
                        want = None  # 原文写法不是纯数字（如 1.2×10⁻⁶），只要求有 value_std
                    if want is not None and abs(want - e["value_std"]) > 1e-9 * max(1.0, abs(want)):
                        E("V-23", i, f"value_std 与换算结果不一致（应为 {want:g}）")
        if kind == "category":
            if not e.get("category_value"):
                E("V-23", i, "分类型要有 category_value")
            elif ind and e["category_value"] not in ind.get("allowed_values", []):
                E("V-23", i, f"分类值 {e['category_value']!r} 不在指标允许的取值里")
        if kind == "statement" and not e.get("summary"):
            E("V-23", i, "陈述型要有 summary")
        if e.get("obtained_from") == "figure_read":
            if not e.get("figure_read"):
                E("V-24", i, "图上读数要有 figure_read 记录")
        elif not e.get("snippet"):
            E("V-24", i, "缺原文片段 snippet")
        if s and (s.get("access_scope") == "abstract_only") != (e.get("obtained_from") == "abstract_only"):
            E("V-25", i, "“仅摘要”的标记与来源读到的范围不一致")
        loc = e.get("locator") or {}
        if not any(loc.get(k) for k in ("page", "table", "figure", "section", "item")):
            E("V-26", i, "出处位置至少写到页、表、图、节、项之一")
        st, mc = e.get("verification_status"), e.get("machine_check") or {}
        if st in ("machine_checked",) + VERIFIED:
            need = ["identifier"] if e.get("obtained_from") == "figure_read" else ["identifier", "snippet", "value_unit"]
            if any(mc.get(k) != "pass" for k in need):
                E("V-27", i, "机器核对没有全部通过，状态不能到机器已核及以上")
        status_rules(i, e)
        if st == "disputed" and not e.get("dispute_note"):
            E("V-27", i, "存疑要写 dispute_note")
        if st == "void" and not e.get("void_reason"):
            E("V-27", i, "作废要写 void_reason")
        if s and s.get("use") != "evidence":
            E("V-28", i, "它的来源的用途不是 evidence")
        if s and s.get("status") == "retracted" and st not in ("void", "disputed"):
            E("V-28", i, "来源已撤稿，证据应作废或存疑")
        base = ref(i, e.get("baseline_ref"), ["EV"], "baseline_ref")
        if base and (base.get("source_id") != e.get("source_id") or base.get("indicator") != e.get("indicator")):
            E("V-29", i, "基准应是同一来源、同一指标的证据")
    for i, e in ev.items():
        guarded(i, lambda: evidence_rules(i, e))

    # ---- 关系
    def relation_rules(rid, r):
        ref(rid, r.get("subject"), ["ENT", "SRC"], "subject")
        ref(rid, r.get("object"), ["ENT", "SRC"], "object")
        ref(rid, r.get("source_id"), ["SRC"], "source_id")
        for x in r.get("evidence_ids", []):
            ref(rid, x, ["EV"], "evidence_ids")
        basis = str(r.get("basis", ""))
        if basis == "sourced" and not (r.get("source_id") and (r.get("locator") or {}).get("text") and r.get("summary")):
            E("V-30", rid, "有出处的关系要写来源、出处位置和转述")
        if basis.startswith("inferred"):
            if not r.get("inference_note"):
                E("V-30", rid, "推断的关系要写推断的依据")
            if r.get("verification_status") in ("machine_checked",) + VERIFIED:
                E("V-30", rid, "推断的关系不能标成已核；找到出处后先把 basis 改成 sourced")
        status_rules(rid, r)
    for rid, r in rel.items():
        guarded(rid, lambda: relation_rules(rid, r))

    # ---- 可比组（关口 3）
    def comparison_rules(cid, c):
        ref(cid, c.get("topic_id"), ["TOP"], "topic_id")
        d = dic.get(c.get("topic_id")) or {}
        ind_keys = {x.get("key") for x in d.get("indicators", [])}
        for k in c.get("indicators", []):
            if d and k not in ind_keys:
                E("V-40", cid, f"指标 {k} 不在指标字典里")
        if c.get("rule") and d and c["rule"] not in {x.get("key") for x in d.get("rules", [])}:
            E("V-40", cid, f"可比规则 {c['rule']} 不在指标字典里")
        if c.get("tier") == "insufficient" and not c.get("missing"):
            E("V-40", cid, "数据不足要写明缺什么")
        seen = set()
        for m in c.get("members", []):
            e = ref(cid, m.get("evidence_id"), ["EV"], "members.evidence_id")
            if m.get("evidence_id") in seen:
                E("V-40", cid, f"{m.get('evidence_id')} 在成员里出现了两次")
            seen.add(m.get("evidence_id"))
            if m.get("role") == "excluded" and not m.get("note"):
                E("V-40", cid, f"{m.get('evidence_id')} 被排除，要写原因")
            if not e:
                continue
            if e.get("level") != c.get("level"):
                E("V-40", cid, f"{e['id']} 的层级与可比组不一致")
            if e.get("indicator") not in c.get("indicators", []):
                E("V-40", cid, f"{e['id']} 的指标不在这一组的指标里")
            if m.get("role") in ("member", "baseline") and c.get("tier") == "direct":
                if unreported(e):
                    E("V-41", cid, f"{e['id']} 有未报告的必填条件（{'、'.join(unreported(e))}），不能进直接可比")
                if e.get("obtained_from") == "abstract_only":
                    E("V-41", cid, f"{e['id']} 仅摘要，不能进直接可比")
            if m.get("role") == "member" and c.get("normalization") == "ratio_to_baseline" and not e.get("baseline_ref"):
                E("V-42", cid, f"{e['id']} 没有 baseline_ref，算不了与基准之比")
            if m.get("role") != "excluded" and e.get("verification_status") == "void":
                E("V-44", cid, f"{e['id']} 已作废，不能留在组里")
        if c.get("normalization") in ("ratio_to_baseline", "other") and c.get("tier") == "direct":
            E("V-42", cid, "做了归一化的组不能定为直接可比")
        if c.get("normalization") == "other" and not c.get("normalization_note"):
            E("V-42", cid, "归一化方法是 other 时要写说明")
        if c.get("status") in ("decided", "expert_reviewed") and not (is_human(c.get("decided_by")) and c.get("decided_at")):
            E("V-43", cid, "定档要由人来定，并写日期")
        if c.get("status") == "expert_reviewed" and not (is_human(c.get("expert_reviewed_by")) and c.get("expert_reviewed_at")):
            E("V-43", cid, "专业已复核要有复核人和日期")
    for cid, c in cmp_.items():
        guarded(cid, lambda: comparison_rules(cid, c))

    # ---- 判断（关口 4，可选）
    def assessment_rules(aid, a):
        ref(aid, a.get("topic_id"), ["TOP"], "topic_id")
        for x in a.get("basis", []):
            ref(aid, x, ["EV", "CMP", "REL"], "basis")
        if not a.get("basis"):
            E("V-50", aid, "缺依据清单")
        if a.get("status") == "reviewed" and not (is_human(a.get("reviewed_by")) and a.get("reviewed_at")):
            E("V-50", aid, "已复核要有复核人（必须是人）和日期")
        if a.get("layer") == "judgment" and not (a.get("conditions") and a.get("unknowns")):
            E("V-50", aid, "judgment 要写成立条件和不能判断的部分")
    for aid, a in asm.items():
        guarded(aid, lambda: assessment_rules(aid, a))

    # ---- 对外（关口 5）
    def external_evidence(i, e, for_comparison):
        s = src.get(e.get("source_id")) or {}
        st = e.get("verification_status")
        if for_comparison:
            if st != "expert_reviewed":
                E("V-61", i, "进对比图表或作判断依据的证据要专业已复核")
        elif not (st in VERIFIED or (st == "disputed" and is_human(e.get("verified_by")) and e.get("dispute_note"))):
            E("V-60", i, "报告引用的证据至少要人工已核；存疑的要曾经人工核对过并写明分歧")
        if e.get("obtained_from") == "figure_read" and not reread_done(e):
            E("V-62", i, "图上读数要有人复读，并写读数误差")
        if e.get("visibility") != "external" or s.get("external_use") == "link_only":
            E("V-63", i, "不可对外：可见范围不是 external，或来源只能给题录和链接")

    def external_comparison(cid):
        c = cmp_.get(cid)
        if not c:
            E("V-02", cid, "这个可比组不存在")
            return
        if c.get("status") != "expert_reviewed":
            E("V-61", cid, "对外用的可比组要专业已复核")
        for m in c.get("members", []):
            if m.get("role") != "excluded" and m.get("evidence_id") in ev:
                external_evidence(m["evidence_id"], ev[m["evidence_id"]], True)

    for cid in external:
        guarded(cid, lambda: external_comparison(cid))

    def report_rules(rid, r):
        ref(rid, r.get("topic_id"), ["TOP"], "topic_id")
        ref(rid, r.get("supersedes"), ["RPT"], "supersedes")
        cited = {f: [ref(rid, x, [k], f) for x in r.get(f, [])] for f, k in
                 (("evidence_ids", "EV"), ("rel_ids", "REL"), ("cmp_ids", "CMP"), ("asm_ids", "ASM"))}
        if r.get("status") != "issued":
            return
        if not (r.get("data_version") and r.get("issued_at")):
            E("V-60", rid, "已发出的报告要记数据版本和发出日期")
        in_cmp = set()
        for c in filter(None, cited["cmp_ids"]):
            external_comparison(c["id"])
            in_cmp |= {m.get("evidence_id") for m in c.get("members", []) if m.get("role") != "excluded"}
        for a in filter(None, cited["asm_ids"]):
            if a.get("status") != "reviewed":
                E("V-61", a["id"], "报告引用的判断要已复核")
            for x in a.get("basis", []):
                if x in ev and x not in in_cmp:
                    in_cmp.add(x)
                    external_evidence(x, ev[x], True)
        for e in filter(None, cited["evidence_ids"]):
            if e["id"] not in in_cmp:
                external_evidence(e["id"], e, False)
        for x in filter(None, cited["rel_ids"]):
            if not str(x.get("basis", "")).startswith("inferred") and x.get("verification_status") not in VERIFIED:
                E("V-65", x["id"], "报告引用的关系要人工已核（推断的关系要用就标明是推断）")
            if x.get("visibility") != "external":
                E("V-63", x["id"], "不可对外：可见范围不是 external")
    for rid, r in rpt.items():
        guarded(rid, lambda: report_rules(rid, r))

    # ---- 两个日志
    seen = set()
    def log_id(rec, kind, name):
        rid = rec.get("id")
        if not isinstance(rid, str) or not re.match(ID_PATTERNS[kind], rid):
            E("V-01", rid or name, "编号的写法不对")
        elif rid in seen:
            E("V-01", rid, "编号重复")
        seen.add(rid)
        return str(rid or name)

    def change_rules(c):
        cid = log_id(c, "CHG", "changes.jsonl")
        ref(cid, c.get("target_id"), ["EV", "SRC", "ENT", "REL", "CMP", "ASM", "TOP"], "target_id")
        ref(cid, c.get("topic_id"), ["TOP"], "topic_id")
        ref(cid, c.get("trigger_source"), ["SRC"], "trigger_source")
        for f, k in (("cmp", "CMP"), ("asm", "ASM"), ("rpt", "RPT")):
            for x in (c.get("affected") or {}).get(f, []):
                ref(cid, x, [k], f"affected.{f}")
        if c.get("kind") == "correction" and not c.get("error_type"):
            E("V-70", cid, "核验更正要写错误类型 error_type")
        if c.get("field") and not ("before" in c and "after" in c):
            E("V-70", cid, "改了字段值的要写 before 和 after")
    for c in ds["changes"]:
        guarded("changes.jsonl", lambda: change_rules(c))

    def worklog_rules(w):
        wid = log_id(w, "LOG", "worklog.jsonl")
        ref(wid, w.get("topic_id"), ["TOP"], "topic_id")
        if w.get("actor_kind") == "ai" and not w.get("ai"):
            E("V-71", wid, "AI 做的工作要填 ai（模型和模板版本）")
        if w.get("actor_kind") == "human":
            if not is_human(w.get("actor")):
                E("V-71", wid, "actor_kind 是 human，但操作人不是人")
            if w.get("minutes") is None and not w.get("minutes_note"):
                E("V-71", wid, "人做的工作要有实记的分钟数；当时没记就写 minutes_note 说明")
        if w.get("step") == "search" and not w.get("search"):
            E("V-71", wid, "检索要填 search（查了哪里、怎么查、命中多少）")
    for w in ds["worklog"]:
        guarded("worklog.jsonl", lambda: worklog_rules(w))

    return issues


def check_append_only(data_dir):
    """V-72：两个日志只在末尾加。和 git 里上一次提交的内容比，已有的行不能变。不在 git 里就跳过。"""
    issues = []
    try:
        top = subprocess.run(["git", "-C", data_dir, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    except OSError:
        return issues
    if top.returncode != 0:
        return issues
    root = top.stdout.strip()
    for name in ("changes.jsonl", "worklog.jsonl"):
        path = os.path.join(data_dir, name)
        rel = os.path.relpath(os.path.realpath(path), os.path.realpath(root)).replace(os.sep, "/")
        old = subprocess.run(["git", "-C", root, "show", f"HEAD:{rel}"], capture_output=True)
        if old.returncode != 0:
            continue  # 上一次提交里还没有这个文件
        new = open(path, "rb").read() if os.path.exists(path) else b""
        if not new.startswith(old.stdout):
            issues.append(Issue("V-72", name, "已经提交过的行被改动或删除了；这个日志只能在末尾加"))
    return issues


def validate(ds, schema, external=()):
    """结构加规则。不含 V-72（它要看 git，用 check_append_only）。"""
    return list(ds["problems"]) + check_structure(ds, schema) + check_rules(ds, external)


def main(argv=None):
    ap = argparse.ArgumentParser(description="校验 data/ 是否符合字段规格 v0.1")
    ap.add_argument("--data", default=DEFAULT_DATA, help="数据目录，默认是仓库里的 data/")
    ap.add_argument("--schema", default=DEFAULT_SCHEMA, help="schema 文件")
    ap.add_argument("--external", nargs="*", default=[], metavar="CMP-编号", help="假设这些可比组要对外，多查对外门槛")
    ap.add_argument("--no-git", action="store_true", help="不查 V-72（日志只追加）")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.data):
        print(f"找不到数据目录：{args.data}", file=sys.stderr)
        return 2
    schema = load_schema(args.schema)
    ds = load_dataset(args.data)
    issues = validate(ds, schema, args.external)
    if not args.no_git:
        issues += check_append_only(args.data)
    spec = (ds["meta"] or {}).get("spec_version")
    counts = "、".join(f"{name} {len(ds[key])}" for name, key in (
        ("题目", "topics"), ("来源", "sources"), ("证据", "evidence"), ("实体", "entities"), ("关系", "relations"),
        ("可比组", "comparisons"), ("判断", "assessments"), ("报告", "reports"), ("变化记录", "changes"), ("工作记录", "worklog")))
    print(f"规格版本 {spec}｜{counts}")
    if not issues:
        print("全部通过")
        return 0
    for it in sorted(set(issues), key=lambda x: (x.rule, x.record, x.message)):
        print(f"{it.rule}  {it.record}: {it.message}")
    print(f"共 {len(set(issues))} 处问题")
    return 1


if __name__ == "__main__":
    sys.exit(main())
