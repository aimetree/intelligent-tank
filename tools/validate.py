#!/usr/bin/env python3
"""校验 data/ 是否符合《数据结构_字段规格》（docs/03_技术与开发/，现在是哪一版见 data/schema/ 里 schema 的 $id）。

用法
  python3 tools/validate.py                         校验仓库里的 data/
  python3 tools/validate.py --data tools/tests/example
  python3 tools/validate.py --external CMP-000001   假设这些可比组要对外，多查对外门槛（V-61 至 V-63）
  python3 tools/validate.py --base <提交>            V-72（日志只追加）和这次提交比，GitHub Actions 上用

做三件事
  1. 版本：数据的规格版本（meta.json 的 spec_version）和 schema 的版本是不是同一个。不是的话先跑 tools/migrate.py。
  2. 结构：每条记录的字段名、类型、枚举和录入时就必填的字段，对照 data/schema/ 里的定义。
  3. 规则：规格第 5 节的 V-xx，包括带条件的必填项和跨记录的检查。

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
    "LOG": r"^LOG-\d{6}$", "RPT": r"^RPT-\d{6}$", "RVW": r"^RVW-\d{6}$",
}
NOT_HUMAN = {"claude", "script"}
VERIFIED = ("human_verified", "expert_reviewed")
# 只留内部、不导出给对方的字段（规格第 6 节，V-64）。生成报告附录和证据数据文件的脚本用 strip_internal()。
INTERNAL_ONLY = {
    "snippet", "conditions_snippet", "internal_note", "machine_check", "created_by", "verified_by",
    "expert_reviewed_by", "entry_method", "double_extraction", "risk",
}

# 来源类别的分组（规格 3.3）
CORE_CHECK_TYPES = {"paper", "preprint", "thesis"}                  # 读了全文要逐项写核心指标（V-17）
NON_ACADEMIC = {"patent", "policy", "standard", "consultancy_report", "government_report",
                "funder_report", "grant_record", "institution_report"}   # 证据要写对应的问题（V-33）
JURISDICTION_REQUIRED = {"patent", "policy", "standard", "government_report", "funder_report", "grant_record"}
COMPANY_TYPES = {"datasheet", "company_web", "filing"}               # 证据标企业声明（V-32）
VERIFY_RECORD_TYPES = {"patent", "policy", "standard", "grant_record"}  # 登记内容要人工核对（V-60）
COMPARABLE_LEVELS = {"material", "component", "system"}              # 只有这三层建可比组（V-40）

# 风险档（方案 5.6，D-80）：每个理由对应的最低档
RISK_REASON_TIER = {
    "figure_read": "high", "extraction_mismatch": "high", "machine_check_failed": "high", "outlier": "high",
    "unit_converted": "medium", "conditions_elsewhere": "medium", "multiple_samples_or_tables": "medium",
    "from_supplement": "medium", "qualified_value": "medium",
}
TIER_RANK = {"low": 0, "medium": 1, "high": 2}


_PLAIN = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
_GROUPED = re.compile(r"^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$")
_POWER = re.compile(r"^([+-]?\d+(?:\.\d+)?)\s*[×xX*·]\s*10\s*(?:\^\s*\(?\s*([+-]?\d+)\s*\)?|([⁺⁻]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+)|([+-]\d+))$")
_DASHES = str.maketrans({"−": "-", "–": "-", "‒": "-", "﹣": "-", "－": "-", "\u00a0": " ", "\u2009": " ", "\u202f": " "})
_SUPER = str.maketrans("⁺⁻⁰¹²³⁴⁵⁶⁷⁸⁹", "+-0123456789")


def parse_number(text):
    """原文数值的写法 → 数。认三种：普通的数（85.6、1.2e-6）；带千分位逗号的（3,200）；
    a×10ⁿ（1.2×10⁻⁶、1.2 x 10^-6、1.2×10-6）。指数要看得出是指数：上标、^ 或带正负号；
    “2×103”这种看不出来的，以及范围、带单位、小数逗号等别的写法，返回 None，不猜。
    换算 value_std（tools/derive.py）和校验（V-23）用的是这同一个函数。"""
    if not isinstance(text, str):
        return None
    t = text.strip().translate(_DASHES).strip()
    if _PLAIN.match(t):
        return float(t)
    if _GROUPED.match(t):
        return float(t.replace(",", ""))
    m = _POWER.match(t)
    if m:
        exponent = m.group(2) or (m.group(3) or "").translate(_SUPER) or m.group(4)
        return float(f"{m.group(1)}e{int(exponent)}")
    return None


def is_human(actor):
    return isinstance(actor, str) and actor != "" and actor not in NOT_HUMAN


def strip_internal(evidence):
    """对外导出一条证据之前调用：去掉只留内部的字段。"""
    row = {k: v for k, v in evidence.items() if k not in INTERNAL_ONLY}
    if isinstance(row.get("figure_read"), dict):
        row["figure_read"] = {k: v for k, v in row["figure_read"].items() if k in ("reading_error", "source_data_checked")}
    return row


def display_flags(evidence, source):
    """对外证据表里这条要显示的标注，返回 labels.json 里 flags 的键（规格第 6 节）。"""
    source = source or {}
    st = source.get("source_type")
    flags = []
    if st == "preprint":
        flags.append("preprint")
    if st == "thesis":
        flags.append("thesis")
    if st == "patent" and evidence.get("evidence_type") == "experimental":
        flags.append("patent_example")
    if evidence.get("evidence_type") == "company_claim":
        flags.append("company_claim")
    if evidence.get("obtained_from") == "figure_read":
        flags.append("figure_read")
    if evidence.get("obtained_from") == "abstract_only":
        flags.append("abstract_only")
    paid = source.get("paid") or {}
    if paid and not paid.get("purchased"):
        flags.append("not_purchased")
    return flags


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
    ds = {"dir": data_dir, "problems": problems, "meta": None, "sources": {}, "samples": {}, "evidence": {},
          "entities": {}, "relations": {}, "topics": {}, "dictionaries": {}, "comparisons": {}, "assessments": {},
          "reports": {}, "reviews": {}, "changes": [], "worklog": [],
          "files": {},        # 来源编号 → (文件路径, 整个文件)。改了来源或证据之后写回文件用（tools/store.py）
          "topic_files": {}}  # (题目编号, 类别) → (文件路径, 这个文件里读进来的编号，照文件里的次序)。写回可比组、描述、复核单用

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
                problems.append(Issue("V-00", rel, "来源文件应是 {source, samples, evidence} 的结构"))
            continue
        src = doc["source"]
        put("sources", src, rel)
        if isinstance(src.get("id"), str) and ds["sources"].get(src["id"]) is src:
            ds["files"][src["id"]] = (path, doc)
        if src.get("id") != os.path.splitext(os.path.basename(path))[0]:
            problems.append(Issue("V-01", rel, "文件名与来源编号不一致"))
        if "samples" in doc:
            ds["samples"][src.get("id")] = [x for x in (doc.get("samples") or [])]
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
        for coll, name in (("comparisons", "comparisons.json"), ("assessments", "assessments.json"),
                           ("reports", "reports.json"), ("reviews", "reviews.json")):
            path = os.path.join(tdir, name)
            if os.path.exists(path):
                loaded = []
                for rec in _read_json(path, problems, f"{rel}/{name}") or []:
                    put(coll, rec, f"{rel}/{name}")
                    if isinstance(rec, dict) and isinstance(rec.get("id"), str) and ds[coll].get(rec["id"]) is rec:
                        loaded.append(rec["id"])
                ds["topic_files"][(tid, coll)] = (path, loaded)

    ds["changes"] = _read_jsonl(os.path.join(data_dir, "changes.jsonl"), problems, "changes.jsonl")
    ds["worklog"] = _read_jsonl(os.path.join(data_dir, "worklog.jsonl"), problems, "worklog.jsonl")
    return ds


def load_schema(path=DEFAULT_SCHEMA):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def spec_version_of(schema):
    """schema 是规格的哪一版：$id 末尾的那个号（urn:intelligent-tank:schema:0.3 就是 0.3）。脚本要的就是这一版的数据。"""
    return str(schema.get("$id") or "").rsplit(":", 1)[-1]


def version_key(version):
    """版本号拆成一串数，好比大小：0.10 比 0.9 新。认不出来的写法返回 None。"""
    if not isinstance(version, str) or not re.match(r"^\d+(\.\d+)*$", version):
        return None
    return tuple(int(x) for x in version.split("."))


def check_version(ds, schema):
    """数据的规格版本要和 schema 的版本一样（规格 1.7）。不一样时别的检查报出来的多半是版本的事，所以单独先说清楚。"""
    meta = ds["meta"]
    have = meta.get("spec_version") if isinstance(meta, dict) else None
    want = spec_version_of(schema)
    if not isinstance(have, str) or have == want:
        return []      # 没有 meta.json、没写版本号，另有问题会报（V-00）
    a, b = version_key(have), version_key(want)
    if a is None or b is None:
        how = "这个版本号认不出来"
    elif a < b:
        how = "数据是旧版的，先跑 python3 tools/migrate.py 把它升上来"
    else:
        how = "数据比脚本新，先把脚本更新到和数据一样的版本"
    return [Issue("V-00", "meta.json", f"数据的规格版本是 {have}，脚本要的是 {want}：{how}")]


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
    if kw == "required" and kind in ("source", "evidence", "sample"):
        return {"source": "V-10", "evidence": "V-20", "sample": "V-19"}[kind]
    if kw in ("pattern", "anyOf") and (last == "id" or last.endswith(("_id", "_ids", "_ref", "_of", "_by", "_into"))
                                       or last in ("subject", "object", "corrects")):
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
                       ("topics", "topic"), ("comparisons", "comparison"), ("assessments", "assessment"),
                       ("reports", "report"), ("reviews", "review")):
        for rid, rec in ds[coll].items():
            run(name, rec, rid)
    for sid, reg in ds["samples"].items():
        for x in reg:
            run("sample", x, f"{sid} 的样品登记")
    for tid, dic in ds["dictionaries"].items():
        run("dictionary", dic, f"{tid} 的指标字典")
    for rec in ds["changes"]:
        run("change", rec, str(rec.get("id", "changes.jsonl")) if isinstance(rec, dict) else "changes.jsonl")
    for rec in ds["worklog"]:
        run("worklog", rec, str(rec.get("id", "worklog.jsonl")) if isinstance(rec, dict) else "worklog.jsonl")
    return issues


# ---------------------------------------------------------------- 规则

def unit_entry(measure, unit):
    """指标或事实项的 units_accepted 里这个单位的那一项；不在里面返回 None。"""
    return next((u for u in (measure or {}).get("units_accepted", []) if u.get("unit") == unit), None)


def unit_factor(measure, unit):
    """换算到标准单位的系数；单位不在允许的单位里，或这个单位照原文记、不换算的，返回 None。"""
    return (unit_entry(measure, unit) or {}).get("factor")


class Lookups:
    """跨记录的查找。check_rules 用它；别的脚本（如 machine_check.py 预填风险档）也用它，
    这样脚本推出来的和校验查的是同一套。"""

    def __init__(self, ds):
        self.src, self.ev, self.dic, self.samples = ds["sources"], ds["evidence"], ds["dictionaries"], ds["samples"]
        self.by_source = {}
        for e in self.ev.values():
            if isinstance(e, dict):
                self.by_source.setdefault(e.get("source_id"), []).append(e)

    def measure_of(self, e):
        """证据用的指标或事实项：返回 (类别, 定义)。"""
        d = self.dic.get(e.get("topic_id")) or {}
        if e.get("indicator"):
            return "indicator", next((x for x in d.get("indicators", []) if x.get("key") == e["indicator"]), None)
        if e.get("fact"):
            return "fact", next((x for x in d.get("facts", []) if x.get("key") == e["fact"]), None)
        return None, None

    def register_of(self, sid):
        """来源的样品登记，按样品名索引；补充材料没有自己的登记时用所属论文的。"""
        reg = self.samples.get(sid)
        if reg is None:
            parent = (self.src.get(sid) or {}).get("parent_id")
            reg = self.samples.get(parent) if parent else None
        return {x.get("label"): x for x in (reg or []) if isinstance(x, dict)}

    def several(self, sid):
        """同一来源里有多个样品或多张表（风险理由 multiple_samples_or_tables）。"""
        rows = self.by_source.get(sid, [])
        labels = {e.get("sample_label") for e in rows if e.get("sample_label")}
        tables = {(e.get("locator") or {}).get("table") for e in rows if (e.get("locator") or {}).get("table")}
        return len(self.register_of(sid)) > 1 or len(labels) > 1 or len(tables) > 1

    def derive_risk(self, e):
        """按字段推得出的风险理由（方案 5.6）。数值离群的门槛试做时定，这里不推。"""
        s = self.src.get(e.get("source_id")) or {}
        reasons = set()
        if e.get("obtained_from") == "figure_read":
            reasons.add("figure_read")
        if e.get("double_extraction") == "resolved":
            reasons.add("extraction_mismatch")
        if "fail" in [v for k, v in (e.get("machine_check") or {}).items() if k != "at"]:
            reasons.add("machine_check_failed")
        m = self.measure_of(e)[1] or {}
        if e.get("content_kind") == "numeric" and e.get("unit_reported") and m.get("unit_std") \
                and e["unit_reported"] != m["unit_std"] and unit_factor(m, e["unit_reported"]) is not None:
            reasons.add("unit_converted")
        if e.get("conditions_locator"):
            reasons.add("conditions_elsewhere")
        if self.several(e.get("source_id")):
            reasons.add("multiple_samples_or_tables")
        if s.get("source_type") == "supplement":
            reasons.add("from_supplement")
        if e.get("value_qualifier") not in (None, "eq"):
            reasons.add("qualified_value")
        return reasons


def risk_floor(reasons):
    """这些理由对应的最低风险档（方案 5.6）；一个理由都没有就是低档。"""
    rank = max([TIER_RANK[RISK_REASON_TIER[x]] for x in reasons if x in RISK_REASON_TIER] or [0])
    return next(k for k, v in TIER_RANK.items() if v == rank)


def machine_check_ok(e):
    """机器核对是否全部通过（V-27）。图上读数只看标识；数值型三项都要通过；
    分类型、陈述型没有数值可核，value_unit 写不适用（na）也算通过，写未通过不行。"""
    mc = e.get("machine_check") or {}
    if mc.get("identifier") != "pass":
        return False
    if e.get("obtained_from") == "figure_read":
        return True
    if mc.get("snippet") != "pass":
        return False
    if e.get("content_kind") == "numeric":
        return mc.get("value_unit") == "pass"
    return mc.get("value_unit") in ("pass", "na")


def check_rules(ds, external=()):
    """规格第 5 节的规则。external：假设要对外的可比组编号。"""
    issues = []
    src, ev, ent, rel = ds["sources"], ds["evidence"], ds["entities"], ds["relations"]
    top, dic, cmp_, asm, rpt, rvw = (ds["topics"], ds["dictionaries"], ds["comparisons"], ds["assessments"],
                                     ds["reports"], ds["reviews"])
    samples = ds["samples"]
    chg = {c.get("id"): c for c in ds["changes"] if isinstance(c, dict) and isinstance(c.get("id"), str)}
    known = {"SRC": src, "EV": ev, "ENT": ent, "REL": rel, "TOP": top, "CMP": cmp_, "ASM": asm, "RPT": rpt,
             "RVW": rvw, "CHG": chg}

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

    # ---- 共用的查找
    lk = Lookups(ds)
    measure_of, register_of, several, derive_risk, by_source = (lk.measure_of, lk.register_of, lk.several,
                                                                lk.derive_risk, lk.by_source)

    def unreported(e):
        m = measure_of(e)[1] or {}
        cond = e.get("conditions") or {}
        return [k for k in m.get("required_conditions", []) if cond.get(k) == "not_reported"]

    def reread_done(e):
        fr = e.get("figure_read") or {}
        return bool(fr.get("reread_by")) and fr.get("reading_error") is not None

    def work_of(sid):
        """同一篇工作：补充材料算在它所属的论文上。"""
        s = src.get(sid) or {}
        return s.get("parent_id") if s.get("source_type") == "supplement" and s.get("parent_id") else sid

    def sample_of(e):
        return register_of(e.get("source_id")).get(e.get("sample_label"))

    def included_in(s, tid=None):
        return [tu for tu in s.get("topics", []) if tu.get("decision") == "included" and (tid is None or tu.get("topic_id") == tid)]

    for coll, kind in (("sources", "SRC"), ("evidence", "EV"), ("entities", "ENT"), ("relations", "REL"), ("topics", "TOP"),
                       ("comparisons", "CMP"), ("assessments", "ASM"), ("reports", "RPT"), ("reviews", "RVW")):
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
        facets = {f.get("key"): f for f in t.get("facets") or []}
        if len(facets) != len(t.get("facets") or []):
            E("V-07", tid, "分类维度的键有重复")
        for k, f in facets.items():
            for ck, vals in (f.get("only_when") or {}).items():
                if ck not in facets:
                    E("V-07", tid, f"分类维度 {k} 的 only_when 用到的 {ck} 没有定义")
                elif facets[ck].get("values") and set(vals) - set(facets[ck]["values"]):
                    E("V-07", tid, f"分类维度 {k} 的 only_when 里有 {ck} 不允许的取值")
    for tid, t in top.items():
        guarded(tid, lambda: topic_rules(tid, t))

    def dictionary_rules(tid, d):
        label = f"{tid} 的指标字典"
        if d.get("topic_id") != tid:
            E("V-02", label, "topic_id 与所在的题目目录不一致")
        cond_keys = [c.get("key") for c in d.get("conditions", [])]
        ind_keys = [i.get("key") for i in d.get("indicators", [])]
        fact_keys = [f.get("key") for f in d.get("facts", [])]
        rule_keys = [r.get("key") for r in d.get("rules", [])]
        for name, keys in (("条件项", cond_keys), ("指标", ind_keys), ("事实项", fact_keys), ("可比规则", rule_keys)):
            dup = sorted({k for k in keys if keys.count(k) > 1})
            if dup:
                E("V-07", label, f"{name}的键有重复：{'、'.join(dup)}")
        both = sorted(set(ind_keys) & set(fact_keys))
        if both:
            E("V-07", label, f"这些键既是指标又是事实项：{'、'.join(both)}")
        level_conditions = d.get("level_conditions") or {}
        for lv, keys in level_conditions.items():
            for k in keys:
                if k not in cond_keys:
                    E("V-07", label, f"{lv} 层统一必填的条件 {k} 不在条件项里")
        for kind_name, items in (("指标", d.get("indicators", [])), ("事实项", d.get("facts", []))):
            for i in items:
                for k in i.get("required_conditions", []) + i.get("optional_conditions", []):
                    if k not in cond_keys:
                        E("V-07", label, f"{kind_name} {i.get('key')} 用到的条件 {k} 不在条件项里")
                if i.get("value_kind") == "category" and not i.get("allowed_values"):
                    E("V-07", label, f"分类型{kind_name} {i.get('key')} 要列出允许的取值")
                units = i.get("units_accepted", [])
                std = i.get("unit_std")
                if std is None and any("factor" in u for u in units):
                    E("V-07", label, f"{kind_name} {i.get('key')} 有要换算的单位，要写标准单位 unit_std")
                if std is not None and (unit_entry(i, std) or {}).get("factor") != 1:
                    E("V-07", label, f"{kind_name} {i.get('key')} 的标准单位 {std} 要列在允许的单位里，系数为 1")
        ind_by_key = {i.get("key"): i for i in d.get("indicators", [])}
        cond_by_key = {c.get("key"): c for c in d.get("conditions", [])}
        for i in d.get("indicators", []):
            # 由脚本派生的指标（如 IN-16）：要写明从哪些指标的证据里、按哪个条件取最大的那一条
            src = i.get("derived_from")
            if i.get("entry") == "derived" and not src:
                E("V-07", label, f"指标 {i.get('key')} 由脚本派生，要写从哪里派生 derived_from")
            if src and i.get("entry") != "derived":
                E("V-07", label, f"指标 {i.get('key')} 写了 derived_from，entry 要是 derived")
            if src:
                cond = cond_by_key.get(src.get("condition"))
                if cond is None:
                    E("V-07", label, f"指标 {i.get('key')} 的 derived_from 按条件 {src.get('condition')} 挑，这个条件不在条件项里")
                elif cond.get("value_kind") != "numeric":
                    E("V-07", label, f"指标 {i.get('key')} 的 derived_from 按条件 {src.get('condition')} 取最大的，这个条件要是数值型")
                elif i.get("unit_std") != cond.get("unit_std"):
                    E("V-07", label, f"指标 {i.get('key')} 的标准单位要和条件 {src.get('condition')} 的一样（{cond.get('unit_std')}）")
                for k in src.get("indicators", []):
                    base = ind_by_key.get(k)
                    if base is None:
                        E("V-07", label, f"指标 {i.get('key')} 的 derived_from 里的 {k} 不在指标里")
                    elif base.get("entry", "evidence") != "evidence" or base.get("level") != i.get("level"):
                        E("V-07", label, f"指标 {i.get('key')} 的 derived_from 里的 {k} 要是同一层、照常录入的指标")
                    elif src.get("condition") not in base.get("required_conditions", []) + base.get("optional_conditions", []):
                        E("V-07", label, f"指标 {k} 没有条件 {src.get('condition')}，指标 {i.get('key')} 没法按它挑")
            lacking = [k for k in level_conditions.get(i.get("level"), []) if k not in i.get("required_conditions", [])]
            if lacking and i.get("entry", "evidence") == "evidence":
                E("V-07", label, f"指标 {i.get('key')} 是 {i.get('level')} 层，必须同时记录 {'、'.join(lacking)}（D-72）")
        for f in d.get("facts", []):
            if f.get("question") and tid in top and f["question"] not in {q.get("key") for q in top[tid].get("questions", [])}:
                E("V-07", label, f"事实项 {f.get('key')} 对应的问题 {f['question']} 不在题目卡里")
        ind_level = {i.get("key"): i.get("level") for i in d.get("indicators", [])}
        for r in d.get("rules", []):
            for k in r.get("applies_to", []):
                if k not in ind_keys:
                    E("V-07", label, f"可比规则 {r.get('key')} 适用的指标 {k} 不在指标里")
                elif r.get("level") and ind_level[k] != r["level"]:
                    E("V-07", label, f"可比规则 {r.get('key')} 写的层级是 {r['level']}，适用的指标 {k} 在 {ind_level[k]} 层")
            for k in r.get("key_conditions", []):
                if k not in cond_keys:
                    E("V-07", label, f"可比规则 {r.get('key')} 的关键条件 {k} 不在条件项里")
    for tid, d in dic.items():
        guarded(tid, lambda: dictionary_rules(tid, d))

    # ---- 分类维度（V-08）
    facet_defs = {tid: {f.get("key"): f for f in (t.get("facets") or []) if isinstance(f, dict)} for tid, t in top.items()}

    def facet_values(owner, facets, defs_list, scope, where):
        for k, v in (facets or {}).items():
            cands = [fd[k] for fd in defs_list if k in fd]
            if not cands:
                E("V-08", owner, f"{where}的分类维度 {k} 没有在题目卡里定义")
                continue
            if scope and all(c.get("applies_to") != scope for c in cands):
                E("V-08", owner, f"{where}的分类维度 {k} 不记在这一类上")
            allowed = set().union(*[set(c.get("values") or []) for c in cands])
            if allowed and v not in allowed:
                E("V-08", owner, f"{where}的 {k} 取值 {v!r} 不在题目卡允许的取值里")

    def facet_required(owner, facets, fdefs, scopes, where):
        facets = facets or {}
        for k, f in fdefs.items():
            if f.get("applies_to") not in scopes:
                continue
            cond = f.get("only_when")
            if cond:
                applies = all(facets.get(ck) in vals for ck, vals in cond.items())
                when = "；".join(f"{ck} 为 {'、'.join(vals)}" for ck, vals in cond.items())
                if applies and k not in facets:
                    E("V-08", owner, f"{where}缺分类维度 {k}（{when} 时必填）")
                if not applies and k in facets:
                    E("V-08", owner, f"{where}的分类维度 {k} 只在 {when} 时填")
            elif f.get("required") and k not in facets:
                E("V-08", owner, f"{where}缺必填的分类维度 {k}")

    def facet_rules():
        all_defs = list(facet_defs.values())
        for eid, e in ent.items():
            scope = {"material_class": "material_class", "product": "membrane", "sample": "membrane"}.get(e.get("entity_type"))
            facet_values(eid, e.get("facets"), all_defs, scope, "实体")
        for tid, fdefs in facet_defs.items():
            products, classes = set(), set()
            for sid, s in src.items():
                tus = included_in(s, tid)
                if not tus:
                    continue
                for tu in tus:
                    if tu.get("facets") is not None:
                        facet_values(sid, tu.get("facets"), [fdefs], None, "只登记的类别里")
                if s.get("access_scope") == "metadata_only":
                    facet_required(sid, tus[0].get("facets"), fdefs, ("membrane", "material_class"), "只登记的来源")
                for x in samples.get(sid, []):
                    subj = ent.get(x.get("subject_id")) or {}
                    where = f"样品 {x.get('label')} "
                    if subj.get("entity_type") == "product":
                        products.add(x.get("subject_id"))
                        if x.get("facets"):
                            E("V-08", sid, f"{where}是商业膜，分类记在产品实体上，样品登记里不写 facets")
                        continue
                    if subj.get("entity_type") == "material_class":
                        classes.add(x.get("subject_id"))
                    facet_values(sid, x.get("facets"), [fdefs], "membrane", where)
                    facet_required(sid, x.get("facets"), fdefs, ("membrane",), where)
            for e in ev.values():
                if e.get("topic_id") == tid and (ent.get(e.get("subject_id")) or {}).get("entity_type") == "product" \
                        and e.get("indicator"):
                    products.add(e.get("subject_id"))
            for c in cmp_.values():
                if c.get("topic_id") == tid and c.get("baseline_subject_id") in ent \
                        and ent[c["baseline_subject_id"]].get("entity_type") == "product":
                    products.add(c["baseline_subject_id"])
            for pid in sorted(products):
                p = ent[pid]
                facet_required(pid, p.get("facets"), fdefs, ("membrane",), "产品")
                if p.get("class_id") in ent:
                    classes.add(p["class_id"])
            for cid_ in sorted(classes):
                facet_required(cid_, ent[cid_].get("facets"), fdefs, ("material_class",), "材料族")
    guarded("分类维度", facet_rules)

    # ---- 来源（关口 1）
    def source_rules(sid, s):
        ids = s.get("identifiers") or {}
        st = s.get("source_type")
        d = s.get("doc") or {}
        resolved = (s.get("id_check") or {}).get("result") == "pass"
        if not ((ids.get("doi") or ids.get("patent_number") or s.get("url")) and resolved) and s.get("use") != "lead":
            E("V-11", sid, "没有通过解析的标识（DOI、专利号或网址），只能作线索")
        how = (s.get("id_check") or {}).get("method")
        if how == "member" and s.get("fetched_by") not in ("member_download", "member_lookup"):
            E("V-11", sid, "id_check 写的是成员取得时确认（member），但这个来源不是成员下载或代查的")
        if how == "doi_registry" and not ids.get("doi"):
            E("V-11", sid, "id_check 写的是在 DOI 注册处查到（doi_registry），但来源没有登记 DOI")
        # V-10
        if st == "supplement" and not s.get("parent_id"):
            E("V-10", sid, "补充材料要填 parent_id，指向论文")
        if s.get("copy_kept") == "snapshot" and not (s.get("snapshot_ref") or s.get("archive_url")):
            E("V-10", sid, "留了快照要填 snapshot_ref 或 archive_url")
        if s.get("copy_kept") == "project_files" and s.get("fetched_by") not in ("member_download", "member_lookup"):
            E("V-10", sid, "放在 Project 文件区的是成员下载的文件，fetched_by 应为 member_download 或 member_lookup（D-107）")
        # V-12
        t = s.get("terms") or {}
        fb = s.get("fetched_by")
        if t.get("no_scraping") and fb == "ai_tool":
            E("V-12", sid, "条款禁止自动抓取，不能由读取工具直接读；由成员下载（D-56 第三条、D-89）")
        if t.get("no_ai") and s.get("reading_mode") == "ai_assisted" and fb not in ("member_download", "member_lookup"):
            E("V-12", sid, "条款禁止用于 AI：现阶段只有成员下载后才可以交给 AI 读（D-89），否则阅读方式应为 human_only")
        # V-13
        route, scope = s.get("access_route"), s.get("access_scope")
        if route == "public_abstract" and scope != "abstract_only":
            E("V-13", sid, "取得途径是公开摘要，读到的范围应为 abstract_only")
        if route == "metadata" and scope != "metadata_only":
            E("V-13", sid, "只有题录，读到的范围应为 metadata_only")
        paid = s.get("paid")
        if paid:
            if paid.get("purchased"):
                if route != "purchased":
                    E("V-13", sid, "买了的付费来源，取得途径应为 purchased")
            else:
                if route == "purchased" or scope == "full":
                    E("V-13", sid, "没买的付费来源只能用公开部分（D-56 第二条、D-98）")
                if not paid.get("assessment"):
                    E("V-13", sid, "没买的付费来源要写评估单在哪里 paid.assessment（D-98）")
        elif route == "purchased":
            E("V-13", sid, "取得途径是 purchased，要填 paid")
        if scope == "metadata_only" and by_source.get(sid):
            E("V-13", sid, "只到题录的来源不出证据（D-68）")
        for tu in s.get("topics", []):
            t_ = ref(sid, tu.get("topic_id"), ["TOP"], "topics.topic_id")
            if tu.get("decision") == "excluded" and not tu.get("exclusion_reason"):
                E("V-10", sid, "排除的来源要写排除原因")
            if t_ and s.get("use") == "evidence" and tu.get("decision") == "included" \
                    and st not in t_.get("evidence_source_types", []):
                E("V-14", sid, f"来源类别 {st} 不在题目卡允许作证据的类别里")
        ref(sid, s.get("parent_id"), ["SRC"], "parent_id")
        ref(sid, s.get("publisher_id"), ["ENT"], "publisher_id")
        # V-15：各类来源要多记的
        included = bool(included_in(s))
        if st in JURISDICTION_REQUIRED and not s.get("jurisdiction"):
            E("V-15", sid, "这类来源要写法域 jurisdiction（D-96）")
        if st == "patent":
            if not d.get("kind"):
                E("V-15", sid, "专利要写文献类型 doc.kind")
            if not (ids.get("patent_number") or d.get("application_number")):
                E("V-15", sid, "专利要有公开号（identifiers.patent_number）或申请号（doc.application_number）")
            if included and not d.get("status"):
                E("V-15", sid, "纳入的专利要记法律状态 doc.status：照数据库原样写，带在哪里查的和日期")
            if (d.get("status") or {}).get("stage"):
                E("V-15", sid, "专利的法律状态只照数据库原样写（stated），不填 stage（方案 3.8 第 6 条）")
        if st in ("policy", "standard"):
            if not d.get("issuer"):
                E("V-15", sid, "政策法规和标准要写发布机关或归口单位 doc.issuer")
            if included and not (d.get("status") or {}).get("stage"):
                E("V-15", sid, "纳入的政策法规和标准要记状态 doc.status，含进程 stage")
            if st == "standard" and not (ids.get("standard_number") or d.get("doc_number")):
                E("V-15", sid, "标准要有标准号（identifiers.standard_number 或 doc.doc_number）")
        if st == "grant_record":
            for k in ("funder", "project_number"):
                if not d.get(k):
                    E("V-15", sid, f"资助记录要写 doc.{k}")
        if d.get("amount") is not None and not d.get("currency"):
            E("V-15", sid, "写了金额要写币种 doc.currency")
        if st == "thesis" and not s.get("parts"):
            E("V-15", sid, "学位论文要写取用的部分 parts（按章取舍）")
        # V-16：版本与更正
        for x in s.get("version_of") or []:
            if x == sid:
                E("V-16", sid, "version_of 不能指向自己")
                continue
            o = ref(sid, x, ["SRC"], "version_of")
            if o and sid not in (o.get("version_of") or []):
                E("V-16", sid, f"和 {x} 要互相指向（{x} 的 version_of 里没有 {sid}）")
        if st == "erratum":
            if not s.get("corrects"):
                E("V-16", sid, "更正声明要写 corrects，指向被更正的来源")
            else:
                o = ref(sid, s["corrects"], ["SRC"], "corrects")
                if o and o.get("status") != "corrected":
                    E("V-16", sid, f"{s['corrects']} 被更正了，它的 status 应为 corrected")
        elif s.get("corrects"):
            E("V-16", sid, "只有更正声明填 corrects")
        if s.get("status") == "corrected" and not any(o.get("corrects") == sid for o in src.values()):
            E("V-16", sid, "标了已更正，要登记一条更正声明（source_type erratum）指向它")
        # V-17：核心指标逐项找过
        for tu in s.get("topics", []):
            d_ = dic.get(tu.get("topic_id")) or {}
            core = [i.get("key") for i in d_.get("indicators", [])
                    if i.get("grade") == "core" and i.get("entry", "evidence") == "evidence"]
            cc = tu.get("core_check")
            need = tu.get("decision") == "included" and st in CORE_CHECK_TYPES and scope in ("full", "partial") \
                and s.get("use") == "evidence"
            if need and cc is None:
                E("V-17", sid, "读了全文的论文要逐项写核心指标找过的结果 core_check（D-67）")
            if cc is None:
                continue
            for k in core:
                if need and k not in cc:
                    E("V-17", sid, f"core_check 缺核心指标 {k}")
            have = {e.get("indicator") for x in [sid] + [o for o, so in src.items() if so.get("parent_id") == sid]
                    for e in by_source.get(x, []) if e.get("topic_id") == tu.get("topic_id")
                    and e.get("verification_status") != "void"}
            for k, v in cc.items():
                if k not in core:
                    E("V-17", sid, f"core_check 里的 {k} 不是这个题目的核心指标")
                elif v == "found" and k not in have:
                    E("V-17", sid, f"core_check 写了找到 {k}，但这个来源里没有这项指标的证据")
                elif v != "found" and k in have:
                    E("V-17", sid, f"这个来源里有 {k} 的证据，core_check 不能写 {v}")
    for sid, s in src.items():
        guarded(sid, lambda: source_rules(sid, s))

    # ---- 样品登记（V-19）
    def register_rules(sid, reg):
        labels = [x.get("label") for x in reg]
        dup = sorted({k for k in labels if labels.count(k) > 1})
        if dup:
            E("V-19", sid, f"样品登记里样品名重复：{'、'.join(dup)}")
        for x in reg:
            where = f"样品 {x.get('label')}"
            subj = ref(sid, x.get("subject_id"), ["ENT"], f"{where} 的 subject_id")
            role, bf = x.get("role"), x.get("baseline_form")
            if role == "baseline" and not bf:
                E("V-19", sid, f"{where} 是同文基准，要写 baseline_form（原样、预处理过、重铸、没写）")
            if role != "baseline" and bf:
                E("V-19", sid, f"{where} 不是同文基准，不填 baseline_form")
            if subj and role == "baseline":
                if bf == "recast" and subj.get("entity_type") != "material_class":
                    E("V-19", sid, f"{where} 是重铸的基准膜，subject_id 指向全氟磺酸的材料族，不指向产品")
                if bf in ("as_received", "pretreated") and subj.get("entity_type") != "product":
                    E("V-19", sid, f"{where} 是商业基准膜，subject_id 指向产品实体（型号）")
    for sid, reg in samples.items():
        guarded(sid, lambda: register_rules(sid, reg))

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
        subject = ref(i, e.get("subject_id"), ["ENT"], "subject_id") or {}
        s = ref(i, e.get("source_id"), ["SRC"], "source_id") or {}
        for f in ("duplicate_of", "superseded_by"):
            ref(i, e.get(f), ["EV"], f)
        for f in ("conflicts_with", "validated_by"):
            for x in e.get(f, []):
                ref(i, x, ["EV"], f)
        if e.get("source_id") and i.split("-")[1:2] != e["source_id"].split("-")[1:2]:
            E("V-20", i, "编号里的来源序号与 source_id 不一致")
        # V-19：样品登记
        reg = register_of(e.get("source_id"))
        smp = reg.get(e.get("sample_label"))
        lab = subject.get("entity_type") == "material_class" and e.get("indicator")
        if e.get("sample_label") and reg and not smp:
            E("V-19", i, f"样品名 {e['sample_label']!r} 不在来源的样品登记里")
        elif lab and not e.get("sample_label"):
            E("V-19", i, "实验室样品的证据要写 sample_label（D-81）")
        elif lab and not reg:
            E("V-19", i, "实验室样品要在来源的样品登记 samples 里登记（D-81）")
        if smp and smp.get("subject_id") and smp["subject_id"] != e.get("subject_id"):
            E("V-19", i, "subject_id 与样品登记里这个样品的不一致")
        if len(reg) > 1 and not e.get("sample_label"):
            E("V-19", i, "来源里不止一个样品，要写 sample_label")
        # V-21 至 V-23：指标或事实项
        kind = e.get("content_kind")
        mk, m = measure_of(e)
        if e.get("indicator") and e.get("fact"):
            E("V-21", i, "indicator 和 fact 只能填一个")
        if e.get("indicator") and not m and mk == "indicator":
            E("V-21", i, f"指标 {e.get('indicator')!r} 不在指标字典里")
        if e.get("fact") and not m and mk == "fact":
            E("V-21", i, f"事实项 {e.get('fact')!r} 不在指标字典里")
        if kind in ("numeric", "category") and not (e.get("indicator") or e.get("fact")):
            E("V-21", i, "数值型、分类型要有指标字典里的 indicator 或 fact")
        if m:
            if mk == "indicator" and m.get("entry", "evidence") != "evidence":
                E("V-21", i, f"指标 {m.get('key')} 不录入（{m.get('entry')}），不能有证据")
            if e.get("level") != m.get("level"):
                E("V-21", i, f"层级 {e.get('level')} 与{'指标' if mk == 'indicator' else '事实项'}的层级 {m.get('level')} 不一致")
            cond = e.get("conditions") or {}
            for k in m.get("required_conditions", []):
                if k not in cond:
                    E("V-22", i, f"缺必填条件 {k}（原文没写应填 not_reported）")
        if e.get("conditions"):
            allowed = {c.get("key") for c in (dic.get(e.get("topic_id")) or {}).get("conditions", [])}
            for k in e["conditions"]:
                if k not in allowed:
                    E("V-22", i, f"条件 {k} 不在指标字典的条件项里")
        if kind == "numeric":
            if not e.get("value_reported") or not e.get("unit_reported"):
                E("V-23", i, "数值型要有 value_reported 和 unit_reported")
            elif m:
                entry = unit_entry(m, e["unit_reported"])
                factor = (entry or {}).get("factor")
                if entry is None:
                    E("V-23", i, f"单位 {e['unit_reported']} 不在允许的单位里")
                elif factor is None:
                    if e.get("value_std") is not None:
                        E("V-23", i, f"单位 {e['unit_reported']} 照原文记、不换算，不填 value_std")
                elif e.get("value_std") is None:
                    E("V-23", i, "缺 value_std（由脚本按换算系数算）")
                else:
                    number = parse_number(e["value_reported"])
                    want = None if number is None else number * factor  # 认不出的写法（如范围）只要求有 value_std
                    if want is not None and abs(want - e["value_std"]) > 1e-9 * max(1.0, abs(want)):
                        E("V-23", i, f"value_std 与换算结果不一致（应为 {want:g}）")
        if kind == "category":
            if not e.get("category_value"):
                E("V-23", i, "分类型要有 category_value")
            elif m and e["category_value"] not in m.get("allowed_values", []):
                E("V-23", i, f"分类值 {e['category_value']!r} 不在允许的取值里")
        if kind == "statement" and not e.get("summary"):
            E("V-23", i, "陈述型要有 summary")
        # V-24 至 V-28
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
        st = e.get("verification_status")
        if st in ("machine_checked",) + VERIFIED and not machine_check_ok(e):
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
        # V-29：同文基准与同文对照
        for fld, role in (("baseline_ref", "baseline"), ("control_ref", "control")):
            tgt = ref(i, e.get(fld), ["EV"], fld)
            if not tgt:
                continue
            if work_of(tgt.get("source_id")) != work_of(e.get("source_id")) or tgt.get("indicator") != e.get("indicator"):
                E("V-29", i, f"{fld} 应指向同一来源、同一指标的证据")
            treg = register_of(tgt.get("source_id"))
            ts = treg.get(tgt.get("sample_label"))
            if treg and (not ts or ts.get("role") != role):
                E("V-29", i, f"{fld} 指向的样品在登记里不是 {role}（D-71：同文对照不算基准）")
        # V-31：风险档
        r = e.get("risk")
        if st in VERIFIED and not r:
            E("V-31", i, "人工核对之前要标好风险档 risk（D-80）")
        if r:
            missing = derive_risk(e) - set(r.get("reasons") or [])
            if missing:
                E("V-31", i, f"风险理由漏了按字段推得出的：{'、'.join(sorted(missing))}")
            need = max([TIER_RANK[RISK_REASON_TIER[x]] for x in r.get("reasons") or [] if x in RISK_REASON_TIER] or [0])
            if TIER_RANK.get(r.get("tier"), 0) < need:
                E("V-31", i, "风险档不能低于理由对应的档（方案 5.6）")
            if "other" in (r.get("reasons") or []) and not r.get("note"):
                E("V-31", i, "风险理由里有 other 要写 note")
        # V-32：企业来源
        if s.get("source_type") in COMPANY_TYPES and e.get("evidence_type") != "company_claim":
            E("V-32", i, "厂商规格书、企业网页、上市申报材料里的证据标为企业声明（D-64）")
        # V-33：对应的问题
        qs = e.get("questions") or []
        qkeys = {q.get("key") for q in (top.get(e.get("topic_id")) or {}).get("questions", [])}
        for q in qs:
            if q not in qkeys:
                E("V-33", i, f"问题 {q} 不在题目卡里")
        if s.get("source_type") in NON_ACADEMIC and not qs:
            E("V-33", i, "非学术来源的证据要写对应题目卡的哪个问题 questions（D-94）")
        if mk == "fact" and m and m.get("question") and qs and m["question"] not in qs:
            E("V-33", i, f"事实项 {m.get('key')} 对应 {m['question']}，questions 里要有它")
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
        rules = {x.get("key"): x for x in d.get("rules", [])}
        if c.get("level") not in COMPARABLE_LEVELS:
            E("V-40", cid, "可比组只建在材料、器件、系统三层；产品与供应、合规不参与对标（D-10、D-67）")
        for k in c.get("indicators", []):
            if d and k not in ind_keys:
                E("V-40", cid, f"指标 {k} 不在指标字典里")
        if c.get("rule") and d and c["rule"] not in rules:
            E("V-40", cid, f"可比规则 {c['rule']} 不在指标字典里")
        elif c.get("rule") in rules:
            r = rules[c["rule"]]
            if not r.get("tier_if_met"):
                E("V-40", cid, f"可比规则 {c['rule']} 是约束性的规则（没有满足时的可比档），不能作为可比组的依据")
            for k in c.get("indicators", []):
                if k in ind_keys and k not in r.get("applies_to", []):
                    E("V-40", cid, f"指标 {k} 不在可比规则 {c['rule']} 适用的指标里")
        if c.get("tier") == "insufficient" and not c.get("missing"):
            E("V-40", cid, "数据不足要写明缺什么")
        seen, rows = set(), []
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
            if e.get("fact") or not e.get("indicator") or e.get("content_kind") == "statement":
                E("V-40", cid, f"{e['id']} 不是指标上的数值或分类，不能进可比组（R9）")
            elif e.get("indicator") not in c.get("indicators", []):
                E("V-40", cid, f"{e['id']} 的指标不在这一组的指标里")
            if m.get("role") == "member" and c.get("normalization") == "ratio_to_baseline" and not e.get("baseline_ref"):
                E("V-42", cid, f"{e['id']} 没有 baseline_ref，算不了与基准之比")
            if m.get("role") != "excluded" and e.get("verification_status") == "void":
                E("V-44", cid, f"{e['id']} 已作废，不能留在组里")
            if m.get("role") in ("member", "baseline"):
                rows.append((m, e))
        # V-41、V-45：直接可比
        if c.get("tier") == "direct":
            miss = set(c.get("missing_conditions") or [])
            all_unrep = set()
            for m, e in rows:
                if e.get("obtained_from") == "abstract_only":
                    E("V-41", cid, f"{e['id']} 仅摘要，不能进直接可比")
                u = set(unreported(e))
                all_unrep |= u
                if u - miss:
                    E("V-41", cid, f"{e['id']} 有未报告的必填条件（{'、'.join(sorted(u - miss))}），组上要写明缺这几项（missing_conditions）")
            if miss and not c.get("same_setup_note"):
                E("V-41", cid, "直接可比的组写了缺的条件，要写同一套条件的依据 same_setup_note（D-64 第三条）")
            if miss - all_unrep:
                E("V-41", cid, f"missing_conditions 里的 {'、'.join(sorted(miss - all_unrep))} 成员里没有未报告的")
            if len({work_of(e.get("source_id")) for _, e in rows}) > 1:
                E("V-45", cid, "直接可比的组里成员来自不同来源；跨来源一律不算直接可比（D-71）")
            series = {e.get("series_label") for _, e in rows}
            if rows and (None in series or len(series) > 1):
                E("V-45", cid, "直接可比的组里成员要是同一批测试（同一个 series_label）（D-64 第三条、D-71）")
        # V-42、V-46：与基准之比
        if c.get("normalization") in ("ratio_to_baseline", "other") and c.get("tier") == "direct":
            E("V-42", cid, "做了归一化的组不能定为直接可比")
        if c.get("normalization") == "other" and not c.get("normalization_note"):
            E("V-42", cid, "归一化方法是 other 时要写说明")
        if c.get("normalization") == "ratio_to_baseline":
            bs, bc = c.get("baseline_subject_id"), c.get("baseline_class")
            if not (bs and bc):
                E("V-46", cid, "用与基准之比的组要写基准膜 baseline_subject_id 和形态 baseline_class（D-71）")
            ref(cid, bs, ["ENT"], "baseline_subject_id")
            for m, e in rows:
                target = ev.get(e.get("baseline_ref")) if m.get("role") == "member" else e
                if not target:
                    continue
                if bs and target.get("subject_id") != bs:
                    E("V-46", cid, f"{e['id']} 的基准膜是 {target.get('subject_id')}，不是这一组的 {bs}；不同型号的比值不并排（D-71）")
                ts = sample_of(target)
                if bc and ts and (ts.get("baseline_form") == "recast") != (bc == "recast"):
                    E("V-46", cid, f"{e['id']} 的基准膜形态与这一组不一致：重铸的单列（D-71）")
        # V-47：关键条件
        kc = (rules.get(c.get("rule")) or {}).get("key_conditions") or []
        if kc and c.get("tier") in ("direct", "conditional"):
            vals = {}
            for _, e in rows:
                cond = e.get("conditions") or {}
                for k in kc:
                    v = cond.get(k)
                    if not isinstance(v, dict) or ("value" not in v and "low" not in v):
                        E("V-47", cid, f"{e['id']} 的关键条件 {k} 没有解析出的值；未报告的应归参考性资料（R4）")
                        continue
                    vals.setdefault(k, set()).add((json.dumps(v.get("value")), v.get("low"), v.get("high"), v.get("unit")))
            for k, got in vals.items():
                if len(got) > 1:
                    E("V-47", cid, f"组里成员的关键条件 {k} 不相同（R3）")
            env = c.get("condition_envelope") or {}
            for k in kc:
                v = env.get(k)
                if isinstance(v, dict) and len(vals.get(k, set())) == 1 \
                        and (json.dumps(v.get("value")), v.get("low"), v.get("high"), v.get("unit")) not in vals[k]:
                    E("V-47", cid, f"condition_envelope 里的 {k} 与成员不一致")
        if c.get("status") in ("decided", "expert_reviewed") and not (is_human(c.get("decided_by")) and c.get("decided_at")):
            E("V-43", cid, "定档要由人来定，并写日期")
        if c.get("status") == "expert_reviewed" and not (is_human(c.get("expert_reviewed_by")) and c.get("expert_reviewed_at")):
            E("V-43", cid, "专业已复核要有复核人和日期")
    for cid, c in cmp_.items():
        guarded(cid, lambda: comparison_rules(cid, c))

    # ---- 复核单（V-48）
    covered_ev, covered_cmp, covered_asm = {}, {}, set()

    def review_rules(rid, r):
        ref(rid, r.get("topic_id"), ["TOP"], "topic_id")
        c = ref(rid, r.get("comparison_id"), ["CMP"], "comparison_id")
        if c and c.get("topic_id") != r.get("topic_id"):
            E("V-48", rid, "复核单和它的可比组不在同一个题目里")
        closed = r.get("status") == "closed"
        if closed and not (is_human(r.get("reviewer")) and r.get("reviewed_at")):
            E("V-48", rid, "已复核的复核单要有复核人（必须是人）和日期")
        for it in r.get("items", []):
            t = ref(rid, it.get("target_id"), ["EV", "CMP", "ASM"], "items.target_id")
            for x in it.get("change_ids", []):
                ref(rid, x, ["CHG"], "items.change_ids")
            if it.get("decision") == "modify" and not it.get("change_ids"):
                E("V-48", rid, f"{it.get('target_id')} 改了，要写对应的变化记录 change_ids（方案 5.3）")
            if closed and it.get("decision") == "pending":
                E("V-48", rid, f"已复核的复核单里 {it.get('target_id')} 还没有定")
            if closed and t:
                tid_ = it.get("target_id")
                if tid_.startswith("EV-"):
                    covered_ev.setdefault(tid_, set()).add(r.get("reviewer"))
                elif tid_.startswith("ASM-"):
                    covered_asm.add(tid_)
        b = r.get("batch") or {}
        for x in b.get("evidence_ids", []) + b.get("sampled", []):
            ref(rid, x, ["EV"], "batch")
        if set(b.get("sampled", [])) - set(b.get("evidence_ids", [])):
            E("V-48", rid, "抽出来给复核人看的条目要在成批确认的条目里")
        if closed and b and b.get("decision") == "pending":
            E("V-48", rid, "已复核的复核单里成批确认的部分还没有定")
        if closed:
            for x in b.get("evidence_ids", []):
                covered_ev.setdefault(x, set()).add(r.get("reviewer"))
            if c:
                covered_cmp.setdefault(c["id"], []).append(r)
    for rid, r in rvw.items():
        guarded(rid, lambda: review_rules(rid, r))

    def review_coverage():
        for cid, c in cmp_.items():
            if c.get("status") != "expert_reviewed":
                continue
            sheets = covered_cmp.get(cid, [])
            if not sheets:
                E("V-48", cid, "专业已复核的可比组要有一张已复核的复核单（D-80）")
                continue
            seen = set()
            for r in sheets:
                seen |= {it.get("target_id") for it in r.get("items", [])}
                seen |= set((r.get("batch") or {}).get("evidence_ids", []))
            missing = [m.get("evidence_id") for m in c.get("members", []) if m.get("role") != "excluded" and m.get("evidence_id") not in seen]
            if missing:
                E("V-48", cid, f"复核单没有覆盖这些成员：{'、'.join(missing)}")
        for i, e in ev.items():
            if e.get("verification_status") != "expert_reviewed":
                continue
            who = covered_ev.get(i)
            if not who:
                E("V-48", i, "专业已复核的证据要在一张已复核的复核单里（逐条或成批）（D-80）")
            elif e.get("expert_reviewed_by") not in who:
                E("V-48", i, "专业复核人与复核单上的复核人不一致")
        for aid, a in asm.items():
            if a.get("status") == "reviewed" and aid not in covered_asm:
                E("V-48", aid, "已复核的描述要在一张已复核的复核单里（D-61、D-80）")
    guarded("复核单", review_coverage)

    # ---- 判断（关口 4，可选；现阶段只用描述）
    def assessment_rules(aid, a):
        ref(aid, a.get("topic_id"), ["TOP"], "topic_id")
        for x in a.get("basis", []):
            ref(aid, x, ["EV", "CMP", "REL"], "basis")
        if not a.get("basis"):
            E("V-50", aid, "缺依据清单")
        if a.get("status") == "reviewed" and not (is_human(a.get("reviewed_by")) and a.get("reviewed_at")):
            E("V-50", aid, "已复核要有复核人（必须是人）和日期")
        if a.get("layer") == "judgment":
            if not (a.get("conditions") and a.get("unknowns")):
                E("V-50", aid, "judgment 要写成立条件和不能判断的部分")
            E("V-51", aid, "现阶段只做到整理和描述，judgment 这一层不用（D-60、D-61）")
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
        t = ref(rid, r.get("topic_id"), ["TOP"], "topic_id") or {}
        ref(rid, r.get("supersedes"), ["RPT"], "supersedes")
        ref(rid, r.get("other_language"), ["RPT"], "other_language")
        cited = {f: [ref(rid, x, [k], f) for x in r.get(f, [])] for f, k in
                 (("evidence_ids", "EV"), ("rel_ids", "REL"), ("cmp_ids", "CMP"), ("asm_ids", "ASM"))}
        if r.get("status") != "issued":
            return
        if not (r.get("data_version") and r.get("issued_at")):
            E("V-60", rid, "已发出的报告要记数据版本和发出日期")
        if not r.get("evidence_file"):
            E("V-60", rid, "已发出的报告要随附全部证据的数据文件 evidence_file（D-102）")
        if t and not t.get("cutoff_date"):
            E("V-60", rid, "出报告时题目卡要写截至日期 cutoff_date")
        in_cmp = set()
        for c in filter(None, cited["cmp_ids"]):
            external_comparison(c["id"])
            in_cmp |= {m.get("evidence_id") for m in c.get("members", []) if m.get("role") != "excluded"}
        for a in filter(None, cited["asm_ids"]):
            if a.get("status") != "reviewed":
                E("V-61", a["id"], "报告引用的描述要已复核")
            for x in a.get("basis", []):
                if x in ev and x not in in_cmp:
                    in_cmp.add(x)
                    external_evidence(x, ev[x], True)
        for e in filter(None, cited["evidence_ids"]):
            if e["id"] not in in_cmp:
                external_evidence(e["id"], e, False)
        used = {ev[x].get("source_id") for x in in_cmp | {e["id"] for e in filter(None, cited["evidence_ids"])} if x in ev}
        for sid in sorted(filter(None, used)):
            s = src.get(sid) or {}
            if s.get("source_type") in VERIFY_RECORD_TYPES and not (is_human(s.get("record_verified_by")) and s.get("record_verified_at")):
                E("V-60", sid, "报告用到的专利、政策法规、标准、资助记录，登记内容（doc）要人工核对过（D-95）")
            status = (s.get("doc") or {}).get("status") or {}
            if status and t.get("cutoff_date") and status.get("checked_at", "") < t["cutoff_date"]:
                E("V-66", sid, "出报告前要再查一次状态：查的日期早于题目的截至日期（方案 3.8 第 5 条）")
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


def check_append_only(data_dir, base="HEAD"):
    """V-72：两个日志只在末尾加。和 git 里 base 那次提交的内容比，已有的行不能变。不在 git 里就跳过。

    提交之前在本机跑，和 HEAD 比就够了；在 GitHub Actions 上工作区就是 HEAD，要给 --base 指定推送之前的那次提交。
    """
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
        old = subprocess.run(["git", "-C", root, "show", f"{base}:{rel}"], capture_output=True)
        if old.returncode != 0:
            continue  # 那次提交里还没有这个文件
        new = open(path, "rb").read() if os.path.exists(path) else b""
        if not new.startswith(old.stdout):
            issues.append(Issue("V-72", name, "已经提交过的行被改动或删除了；这个日志只能在末尾加"))
    return issues


def validate(ds, schema, external=()):
    """版本、结构加规则。不含 V-72（它要看 git，用 check_append_only）。"""
    return list(ds["problems"]) + check_version(ds, schema) + check_structure(ds, schema) + check_rules(ds, external)


def main(argv=None):
    ap = argparse.ArgumentParser(description="校验 data/ 是否符合字段规格")
    ap.add_argument("--data", default=DEFAULT_DATA, help="数据目录，默认是仓库里的 data/")
    ap.add_argument("--schema", default=DEFAULT_SCHEMA, help="schema 文件")
    ap.add_argument("--external", nargs="*", default=[], metavar="CMP-编号", help="假设这些可比组要对外，多查对外门槛")
    ap.add_argument("--no-git", action="store_true", help="不查 V-72（日志只追加）")
    ap.add_argument("--base", default="HEAD", metavar="提交", help="V-72 和哪次提交比，默认 HEAD（提交之前在本机跑）")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.data):
        print(f"找不到数据目录：{args.data}", file=sys.stderr)
        return 2
    schema = load_schema(args.schema)
    ds = load_dataset(args.data)
    issues = validate(ds, schema, args.external)
    if not args.no_git:
        issues += check_append_only(args.data, args.base)
    spec = (ds["meta"] or {}).get("spec_version")
    counts = "、".join(f"{name} {len(ds[key])}" for name, key in (
        ("题目", "topics"), ("来源", "sources"), ("证据", "evidence"), ("实体", "entities"), ("关系", "relations"),
        ("可比组", "comparisons"), ("判断", "assessments"), ("复核单", "reviews"), ("报告", "reports"),
        ("变化记录", "changes"), ("工作记录", "worklog")))
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
