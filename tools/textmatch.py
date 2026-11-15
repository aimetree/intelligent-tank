#!/usr/bin/env python3
"""比对原文用的规范化和查找，给 machine_check.py 和 compare_extractions.py 共用。

三件事：
  find_snippet      原文片段是不是逐字在来源文本里
  find_value        记录的数值在不在片段里（不会把 85.6 认成 185.6、85.65 或 85.6×10⁻⁷ 的一部分）
  check_value_unit  数值在片段里，而且片段里数值后面紧跟着单位的，和记录的单位一致

规范化只抹掉排版上的差别（上标、全角、连字、各种横线、空白、换行），不改字，大小写也不放宽。
"""
import re
import unicodedata

MIN_SNIPPET = 6  # 去掉空白之后至少这么多个字符，再短就定位不了原文

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−﹘﹣－"), "-")
_DROP = dict.fromkeys(map(ord, "­​‌‍⁠﻿"), None)   # 软连字符、零宽字符
_QUOTES = {0x201c: '"', 0x201d: '"', 0x2018: "'", 0x2019: "'"}


def norm(text):
    """规范写法：NFKC（上标、下标、全角、连字还原成普通字符），各种横线和减号统一成 -，
    软连字符和零宽字符去掉，弯引号改直引号，空白（含换行、制表符）压成一个空格。"""
    t = unicodedata.normalize("NFKC", text or "")
    t = t.translate(_DROP).translate(_DASHES).translate(_QUOTES)
    return re.sub(r"\s+", " ", t).strip()


def squeeze(text):
    return re.sub(r"\s+", "", text)


def _unbreak(text):
    """把行尾断词接上：规范化之后原文的 “mem-␤brane” 是 “mem- brane”。"""
    return re.sub(r"(?<=\w)- (?=\w)", "", text)


def find_snippet(snippet, text):
    """片段在不在来源文本里。返回 (找到没有, 说明)。

    先只放宽空白；找不到再去掉全部空白找一次（表格的一行在抽出来的文本里常被拆成几行）；
    最后把行尾断词的连字符接上再找。
    """
    s, t = norm(snippet), norm(text)
    if len(squeeze(s)) < MIN_SNIPPET:
        return False, f"片段太短（去掉空白不到 {MIN_SNIPPET} 个字符），定位不了原文"
    if s in t:
        return True, "逐字找到"
    if squeeze(s) in squeeze(t):
        return True, "找到，只差空白"
    if squeeze(_unbreak(s)) in squeeze(_unbreak(t)):
        return True, "找到，原文在行尾断了词"
    return False, "来源文本里找不到这个片段"


def _prep(text):
    """数值比对之前：规范化，再把乘号两边的空格去掉（1.2 × 10-7 和 1.2×10-7 是一回事；x 当乘号用的也算）。

    PDF 抽出来的文本里上标成了普通的字：记录里写的 10^4 在片段里是 104，指数的负号后面还常多一个空格（10− 7）。
    所以两边都把指数前的 ^ 去掉，把 10- 7 接成 10-7。"""
    t = re.sub(r"\s*[x×]\s*(?=10)", "×", norm(text))
    t = re.sub(r"(?<=×10)\^", "", t)
    return re.sub(r"(?<=×10)-\s+(?=\d)", "-", t)


def find_value(value, snippet):
    """数值在片段里出现的位置（每处匹配结束的下标，针对 _prep(snippet)）。找不到返回空列表。"""
    v, s = _prep(str(value)), _prep(snippet)
    if not v:
        return []
    body = r"\s*".join(re.escape(p) for p in v.split(" "))
    # 前面不能紧挨着数字、小数点、千分位或拉丁字母（N212 里的 212 不是数值）；
    # 后面不能接着数字、小数、乘 10 的幂或 e 记数
    pattern = re.compile(r"(?<![0-9A-Za-z.,])" + body + r"(?![\d]|[.,]\d|×10|[eE][-+]?\d)")
    ends = []
    for m in pattern.finditer(s):
        i = m.start()
        if i > 0 and s[i - 1] == "-" and not v.startswith("-"):
            before = s[i - 2] if i > 1 else " "
            if before in " (=:,;[<>~":
                continue  # 片段里是负数，记录的是正数
            if before.isascii() and before.isalpha():
                continue  # 样品名的一部分，如 X-1 里的 1
        ends.append(m.end())
    return ends


# ---------------------------------------------------------------- 单位

_TOKEN_ALIAS = {"hr": "h", "hrs": "h", "hour": "h", "hours": "h", "mins": "min", "minute": "min", "minutes": "min",
                "day": "d", "days": "d", "yr": "year", "yrs": "year", "years": "year", "cycle": "cycles", "l": "L"}
_KEY_ALIAS = {"M": "molL-1", "moldm-3": "molL-1"}


def _token(tok, sign):
    m = re.match(r"^(.*?)(-?\d+)?$", tok)
    sym, exp = m.group(1), int(m.group(2) or 1) * sign
    sym = _TOKEN_ALIAS.get(sym, sym)
    return sym if exp == 1 else f"{sym}{exp}"


def unit_key(expr):
    """单位的规范键：不管原文写 mA/cm2、mA cm-2、mA·cm⁻² 还是 mA cm−2，得到的都是 mAcm-2。
    认不出来的写法也会得到一个键，只是和哪个单位代码都对不上。空的写法（如无量纲的 1）返回空串。"""
    t = norm(expr).strip("()[]")
    t = t.replace("Ω", "ohm").replace("μ", "u").replace("° C", "degC").replace("°C", "degC")
    t = re.sub(r"\s+per\s+", "/", t).replace("^", "")
    if t in ("", "1"):
        return ""
    num, *dens = t.split("/")

    def tokens(part):
        return [x for x in re.split(r"[\s·⋅*]+", part.strip("()")) if x]

    key = "".join([_token(x, 1) for x in tokens(num)] + [_token(x, -1) for d in dens for x in tokens(d)])
    return _KEY_ALIAS.get(key, key)


def unit_after(prepared, end, accepted):
    """prepared[end:] 开头是不是一个认得的单位。accepted 是 {规范键: 单位代码}。认得就返回单位代码。"""
    # PDF 里上标的负号后面常多出一个空格：mS cm- 1 接成 mS cm-1（只接字母后面的负号，数的范围 10 - 12 不动）
    tail = re.sub(r"(?<=[A-Za-z])-\s+(?=\d)", "-", prepared[end:end + 48])
    words = tail.lstrip().lstrip("([").split(" ")[:4]
    for n in range(len(words), 0, -1):
        key = unit_key(" ".join(words[:n]).rstrip(".,;:)]"))
        if key and key in accepted:
            return accepted[key]
    return None


def check_value_unit(value, unit, units_accepted, snippet):
    """数值、单位与片段是否一致。返回 ("pass" 或 "fail", 说明)。

    不通过只有两种：片段里找不到这个数值；数值后面紧跟着的是这个指标允许的另一个单位。
    片段里数值后面没有单位（表格的一行多半这样）不算不一致，说明里会写“单位没法核”。
    """
    ends = find_value(value, snippet)
    if not ends:
        return "fail", f"片段里找不到数值 {value}"
    accepted = {}
    for u in list(units_accepted or []) + [unit]:
        key = unit_key(u or "")
        if key:
            accepted.setdefault(key, u)
    want = unit_key(unit or "")
    prepared, others = _prep(snippet), []
    for end in ends:
        got = unit_after(prepared, end, accepted)
        if got is None:
            continue
        if unit_key(got) == want:
            return "pass", "数值在片段里，后面的单位一致"
        others.append(got)
    if others:
        return "fail", f"片段里数值后面的单位是 {others[0]}，记录写的是 {unit}"
    return "pass", "数值在片段里；片段里数值后面没有单位，单位没法核"
