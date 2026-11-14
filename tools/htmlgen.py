"""写 HTML 用的几个小函数。看板的各个脚本共用。

规矩只有一条：除了明确标成 Raw 的，任何字符串放进页面之前都转义。来源里抄来的文字（题名、原文片段等）因此不会被当成网页代码。
"""
import html

class Raw(str):
    """已经是 HTML 的字符串。别的字符串放进页面之前一律转义。"""


VOID = {"meta", "br", "input", "hr"}
BREAK_AFTER = {"html", "head", "body", "meta", "title", "style", "script", "header", "nav", "main", "section",
               "footer", "div", "table", "thead", "tbody", "tr", "ul", "ol", "li", "dl", "dd", "p", "h1", "h2", "h3",
               "svg", "symbol", "fieldset", "select", "option", "optgroup", "blockquote", "details", "textarea"}


def esc(x):
    return html.escape("" if x is None else str(x), quote=True)


def flat(children):
    out = []
    for c in children:
        if c is None or c is False or c == "":
            continue
        if isinstance(c, (list, tuple)):
            out.append(flat(c))
        elif isinstance(c, Raw):
            out.append(c)
        else:
            out.append(esc(c))
    return "".join(out)


def el(tag, attrs=None, *children):
    """一个 HTML 元素。属性值和文字都转义；属性值是 None 或 False 就不写这个属性，是 True 就只写属性名。"""
    parts = [tag]
    for k, v in (attrs or {}).items():
        if v is None or v is False:
            continue
        parts.append(k if v is True else f'{k}="{esc(v)}"')
    start = "<" + " ".join(parts) + ">"
    if tag in VOID:
        return Raw(start + "\n")
    return Raw(start + flat(children) + f"</{tag}>" + ("\n" if tag in BREAK_AFTER else ""))
