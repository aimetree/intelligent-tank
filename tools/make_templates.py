#!/usr/bin/env python3
"""由 schema 生成空白模板：data/templates/*.json 和 data/templates/README.md。

schema 改了之后重跑一次：python3 tools/make_templates.py
模板里尖括号是占位，写着“必填：”的是录入时就要有的字段；数字、真假值没法做标记，
哪些必填看 README.md 里的表。模板不是合法的记录，校验脚本不读这个目录。
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = os.path.join(REPO, "data", "schema", "intelligent-tank.schema.json")
OUT = os.path.join(REPO, "data", "templates")

# (schema 里的定义, 中文名, 模板文件, 实际放在哪)
OBJECTS = [
    ("topic", "题目卡", "topic.json", "public/topics/TOP-编号/topic.json"),
    ("dictionary", "指标字典", "dictionary.json", "public/topics/TOP-编号/dictionary.json"),
    ("source_file", "来源文件（来源登记、样品登记和它的证据）", "source_file.json", "public/sources/SRC-编号.json"),
    ("entity", "实体", "entity.json", "public/entities.json（数组里的一项）"),
    ("relation", "关系", "relation.json", "public/relations.json（数组里的一项）"),
    ("comparison", "可比组", "comparison.json", "public/topics/TOP-编号/comparisons.json（数组里的一项）"),
    ("assessment", "判断（可选）", "assessment.json", "public/topics/TOP-编号/assessments.json（数组里的一项）"),
    ("review", "复核单", "review.json", "public/topics/TOP-编号/reviews.json（数组里的一项）"),
    ("report", "报告登记", "report.json", "public/topics/TOP-编号/reports.json（数组里的一项）"),
    ("change", "变化记录", "change.json", "changes.jsonl（一行一条）"),
    ("worklog", "工作记录", "worklog.json", "worklog.jsonl（一行一条）"),
]
SAMPLE_ID = {"EV": "EV-000000-000"}


def placeholder(node, defs, required=False):
    mark = "必填：" if required else ""
    title = node.get("title", "")
    ref = node.get("$ref", "").rsplit("/", 1)[-1]
    if ref.startswith("id_"):
        kind = ref[3:]
        return f"<{mark}{SAMPLE_ID.get(kind, kind + '-000000')}>"
    if ref.startswith("enum_"):
        return f"<{mark}{'｜'.join(defs[ref]['enum'])}>"
    if ref == "date":
        return f"<{mark}YYYY-MM-DD>"
    if ref == "date_partial":
        return f"<{mark}YYYY-MM-DD，可以只到年或月>"
    if ref == "key":
        return f"<{mark}{title or '键名'}，英文小写加下划线>"
    if ref == "actor":
        return f"<{mark}kai｜yu｜claude｜script｜expert-01>"
    if ref:
        return placeholder({**defs[ref], **{k: v for k, v in node.items() if k != "$ref"}}, defs, required)
    if "enum" in node:
        return f"<{mark}{'｜'.join(node['enum'])}>"
    if "anyOf" in node:
        return placeholder({**node["anyOf"][0], "title": title}, defs, required)
    if "oneOf" in node:
        return placeholder(node["oneOf"][-1], defs, required)
    kind = node.get("type")
    if kind == "string":
        return f"<{mark}{title}>"
    if kind in ("number", "integer") or isinstance(kind, list):
        return 0
    if kind == "boolean":
        return False
    if kind == "array":
        return [placeholder(node["items"], defs, required)]
    if kind == "object":
        if "properties" in node:
            req = set(node.get("required", []))
            return {k: placeholder(v, defs, k in req) for k, v in node["properties"].items()}
        return {"<键>": placeholder(node.get("additionalProperties", {}), defs)}
    return f"<{mark}{title or '任意'}>"


def build(schema):
    """返回 {文件名: 内容}。"""
    defs = schema["$defs"]
    files = {}
    rows = []
    for name, label, fname, where in OBJECTS:
        files[fname] = json.dumps(placeholder(defs[name], defs), ensure_ascii=False, indent=2) + "\n"
        if name == "source_file":
            req = ("来源：" + "、".join(f"`{k}`" for k in defs["source"]["required"])
                   + "<br>样品登记：" + "、".join(f"`{k}`" for k in defs["sample"]["required"])
                   + "<br>证据：" + "、".join(f"`{k}`" for k in defs["evidence"]["required"]))
        else:
            req = "、".join(f"`{k}`" for k in defs[name]["required"])
        rows.append(f"| `{fname}` | {label} | `{where}` | {req} |")
    files["README.md"] = "\n".join([
        "# 空白模板",
        "",
        "由 `tools/make_templates.py` 从 `data/schema/` 生成，不要手工改；schema 改了之后重跑一次。",
        "",
        "- 尖括号里是占位。写着“必填：”的是录入时就要有的字段；用竖线隔开的是可选的取值。",
        "- 数字填的是 0、真假值填的是 false，只是占个位置。用不到的可选字段整项删掉，不要留空值。",
        "- 带条件的必填项（例如数值型证据要有数值和单位）不在下表里，见字段规格第 3 节和第 5 节。",
        "- 模板不是合法的记录，`tools/validate.py` 不读这个目录。",
        "",
        "| 模板 | 对象 | 实际放在 `data/` 下的哪里 | 录入时就必填的字段 |",
        "|---|---|---|---|",
        *rows,
        "",
    ])
    return files


def main():
    with open(SCHEMA, encoding="utf-8") as f:
        schema = json.load(f)
    os.makedirs(OUT, exist_ok=True)
    for fname, text in build(schema).items():
        with open(os.path.join(OUT, fname), "w", encoding="utf-8") as f:
            f.write(text)
    print(f"写了 {len(OBJECTS)} 个模板和 README.md 到 {os.path.relpath(OUT, REPO)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
