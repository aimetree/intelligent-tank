"""看板和报告怎么显示：显示名、数的写法、单位、网址，和证据类型的记号。看板的各个脚本共用。

显示名从哪里来：枚举、单位、取值取自 labels.json；指标、事实项、条件取自指标字典；字段名取自 schema 的 title。
这里不写死任何一个指标（D-03）。
"""
import json
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from check_identifiers import clean_doi  # noqa: E402
from htmlgen import el  # noqa: E402

# 证据类型的记号（设计方案 6.1：证据类型用形状表示）。12×12 的画框里各画一个实心的形状
MARKS = {
    "experimental": '<circle cx="6" cy="6" r="5"/>',
    "company_claim": '<rect x="1.5" y="1.5" width="9" height="9"/>',
    "model_simulation": '<polygon points="6,1 11.2,10.6 0.8,10.6"/>',
    "verified_fact": '<polygon points="6,0.4 11.6,6 6,11.6 0.4,6"/>',
    "third_party_analysis": '<polygon points="4.4,1 7.6,1 7.6,4.4 11,4.4 11,7.6 7.6,7.6 7.6,11 4.4,11 4.4,7.6 1,7.6 1,4.4 4.4,4.4"/>',
    "expert_judgment": '<polygon points="6,0.4 10.9,3.2 10.9,8.8 6,11.6 1.1,8.8 1.1,3.2"/>',
}
MARK_UNKNOWN = '<rect x="1" y="4.8" width="10" height="2.4"/>'

# 四档可比性各自怎么处理（设计方案 2.5 的表，D-49）。和题目无关
TIER_HANDLING = {
    "direct": "可以定量比较",
    "conditional": "并排时列出其余条件的差异",
    "reference": "分开呈现，不排名",
    "insufficient": "写明缺什么",
}

QUALIFIER_SIGN = {"eq": "", "lt": "<", "le": "≤", "gt": ">", "ge": "≥", "approx": "约"}
NOT_FILLED = "（没有填）"
NONE = "-"   # 筛选里“这一项没有值”用的记号。不能和真的代码撞：层级里就有一个代码叫 none（不分层）
SUPERSCRIPT = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")


def mark(code):
    """页面里证据类型的记号：引用页面开头那一组形状（build_dashboard.sprite）。"""
    ref = code if code in MARKS else "unknown"
    return el("svg", {"class": "mark", "viewBox": "0 0 12 12", "aria-hidden": "true", "focusable": "false"},
              el("use", {"href": f"#m-{ref}"}))


def s(x):
    return "" if x is None else str(x)


def cls(code):
    """把代码变成能放进 class 的写法。"""
    return re.sub(r"[^A-Za-z0-9_-]", "", s(code)) or "x"


def tok(code):
    """筛选用的值：不能带空白（页面脚本按空白分开多个值）；没有值就是 NONE。"""
    return re.sub(r"\s+", "_", s(code).strip()) or NONE


def fmt_num(x):
    """脚本算出来的数怎么写：整数不带小数点，最多六位有效数字，很大很小的写成 a×10ⁿ。"""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return s(x)
    if x != x or x in (float("inf"), float("-inf")):
        return s(x)
    if float(x).is_integer() and abs(x) < 1e15:
        return str(int(x))
    text = format(x, ".6g")
    if "e" in text:
        mantissa, exponent = text.split("e")
        return f"{mantissa}×10{str(int(exponent)).translate(SUPERSCRIPT)}"
    return text


def with_unit(text, unit):
    if not unit:
        return text
    return text + ("" if unit.startswith("%") else " ") + unit


def axis_label(name, unit):
    """坐标轴上怎么写：名字，逗号，单位；没有单位只写名字。"""
    return f"{name}，{unit}" if unit else name


def safe_url(u):
    """只认 http 和 https 的网址；别的（比如 javascript:）不做成链接。"""
    return u if isinstance(u, str) and re.match(r"^https?://[^\s<>\"'`]+$", u) else None


def doi_url(doi):
    if not isinstance(doi, str):
        return None
    d = clean_doi(doi)
    return "https://doi.org/" + urllib.parse.quote(d, safe="/") if re.match(r"^10\.\d{4,9}/\S+$", d) else None


def ev_sort_key(eid):
    m = re.match(r"^EV-(\d+)-(\d+)$", s(eid))
    return (0, int(m.group(1)), int(m.group(2)), "") if m else (1, 0, 0, s(eid))


def as_text(v):
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


# ---------------------------------------------------------------- 显示名

class Names:
    """显示名。枚举、单位、取值取自 labels.json；指标、事实项、条件取自指标字典；字段名取自 schema 的 title。
    找不到显示名的，原样显示代码，不猜。"""

    def __init__(self, labels, dictionary, schema, lang="zh"):
        self.l, self.lang = labels or {}, lang
        d = dictionary if isinstance(dictionary, dict) else {}

        def table(key):
            return {x.get("key"): x for x in d.get(key) or [] if isinstance(x, dict) and isinstance(x.get("key"), str)}

        self.indicators, self.facts, self.conditions = table("indicators"), table("facts"), table("conditions")
        self.cond_order = {k: i for i, k in enumerate(self.conditions)}
        self.measure_order = {("indicator", k): i for i, k in enumerate(self.indicators)}
        self.measure_order.update({("fact", k): len(self.indicators) + i for i, k in enumerate(self.facts)})
        self.defs = (schema or {}).get("$defs") or {}

    def _pick(self, v, fallback):
        if isinstance(v, dict):
            return v.get(self.lang) or v.get("zh") or fallback
        return v if isinstance(v, str) else fallback

    def _from(self, section, group, code):
        if code is None or code == "":
            return ""
        if not isinstance(code, str):
            return as_text(code)
        return self._pick(((self.l.get(section) or {}).get(group) or {}).get(code), code)

    def enum(self, group, code):
        return self._from("enums", group, code)

    def value(self, group, code):
        return self._from("values", group, code)

    def enum_order(self, group):
        return list((self.l.get("enums") or {}).get(group) or {})

    def unit(self, code):
        if not isinstance(code, str) or not code:
            return ""
        return self._pick((self.l.get("units") or {}).get(code), code)

    def flag(self, key):
        return self._pick((self.l.get("flags") or {}).get(key), key)

    def field(self, obj, key, sub=None):
        prop = ((self.defs.get(obj) or {}).get("properties") or {}).get(key) or {}
        if sub is not None:
            prop = (prop.get("properties") or {}).get(sub) or {}
            return prop.get("title") or sub
        return prop.get("title") or key

    def _name(self, d, key):
        return (d or {}).get("name_" + self.lang) or (d or {}).get("name_zh") or key

    def measure(self, e):
        """证据用的指标或事实项：返回 (类别, 键, 定义, 名字)。指标字典里没有的，定义是空的。"""
        for kind, table in (("indicator", self.indicators), ("fact", self.facts)):
            key = e.get(kind)
            if isinstance(key, str) and key:
                return kind, key, table.get(key) or {}, self._name(table.get(key), key)
        return None, "", {}, ""

    def condition(self, key):
        return self._name(self.conditions.get(key), key)
