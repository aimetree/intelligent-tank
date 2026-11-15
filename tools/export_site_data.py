#!/usr/bin/env python3
"""把 data/ 导出成网页前端读的数据文件（《开发蓝图》方案 C 的前半：前端独立成一个工程，只读这些文件）。

前端不直接读 data/ 的目录结构，只读这里导出的几个 JSON；以后把文件换成后台接口，接口返回的就是这几个文件的样子。
文件照取数模块的四类分（tools/access.py）：
  meta.json        数据版本、规格版本、导出给谁看、各类记录的条数、校验问题
  topics.json      查：题目卡、指标字典
  sources.json     查：来源登记和样品登记
  entities.json    查：实体
  evidence.json    取证据：证据
  comparisons.json 比：可比组、描述、复核单
  relations.json   看关联：关系
  logs.json        查：变化记录、工作记录
  labels.json      页面上的中文名
  views.json       五页要显示的内容，由看板的 Python 函数算好（tools/site_views.py；Yu 2026-11-15 定“甲”）。只在给内部看的导出里有

--audience internal（默认）原样导出，含只留内部的字段（原文片段等，D-56），只能放在有登录的地方。
--audience external 去掉只留内部的字段，只留可对外、并且至少人工已核的证据，和可对外的实体、关系；复核单、工作记录不导出。
  views.json 也不导出：五页是对内看板，里面有原文片段、风险档这些只留内部的东西。对外给谁看、看哪几页还没有定。
来源登记现在原样导出（含条款要点和备注），对外之前要不要再删，等定了对外给谁看再做。
同一份数据、同一次提交导出两遍，文件逐字节相同。

用法  python3 tools/export_site_data.py --out site-data [--data DIR] [--audience internal|external] [--version 版本]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import access as A  # noqa: E402
import build_dashboard as B  # noqa: E402
import site_views  # noqa: E402
import store  # noqa: E402
import validate as V  # noqa: E402

AUDIENCES = ("internal", "external")
FORMAT = 2   # 这几个文件的写法改了、前端要跟着改的时候加一。2：加了 views.json


OUTSIDE_OK = ("human_verified", "expert_reviewed")   # 对外至少人工已核（方案 5.2，V-60）


def _visible(rec, audience):
    return audience == "internal" or rec.get("visibility") == "external"


def export(data_dir, audience="internal", version=None):
    """返回 {文件名: 内容}。不写文件。version 不给就用 git 的提交号（和看板一样）。"""
    if audience not in AUDIENCES:
        raise ValueError(f"不认识的 audience：{audience}")
    ds = A.load(data_dir)
    inside = audience == "internal"
    evidence = [A.evidence(ds, i) for i in A.evidence_ids(ds)]
    evidence = [e if inside else V.strip_internal(e) for e in evidence
                if _visible(e, audience) and (inside or e.get("verification_status") in OUTSIDE_OK)]
    sources = [{"source": A.source(ds, i), "samples": A.samples(ds, i)} for i in A.source_ids(ds)]
    if not inside:
        used = {e.get("source_id") for e in evidence}
        sources = [s for s in sources if s["source"].get("id") in used and s["source"].get("external_use") != "link_only"]
    entities = [e for e in (A.entity(ds, i) for i in A.entity_ids(ds)) if _visible(e, audience)]
    relations = [r for r in (A.relation(ds, i) for i in A.relation_ids(ds)) if _visible(r, audience)]
    comparisons = [c for c in (A.comparison(ds, i) for i in A.comparison_ids(ds)) if _visible(c, audience)]
    assessments = [a for a in (A.assessment(ds, i) for i in A.assessment_ids(ds)) if _visible(a, audience)]
    reviews = [A.review(ds, i) for i in A.review_ids(ds)] if inside else []
    topics = [{"topic": A.topic(ds, t), "dictionary": A.dictionary(ds, t)} for t in A.topic_ids(ds)]
    labels_path = os.path.join(data_dir, "labels.json")
    if not os.path.exists(labels_path):     # 测试的示例数据没有自己的 labels.json，用仓库里的那一份
        labels_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "labels.json")
    with open(labels_path, encoding="utf-8") as f:
        labels = json.load(f)
    if version is None:
        version = B.data_version(data_dir)
    meta = {
        "format": FORMAT,
        "audience": audience,
        "data_version": version,
        "spec_version": A.spec_version(ds),
        "counts": {"topics": len(topics), "sources": len(sources), "entities": len(entities), "evidence": len(evidence),
                   "relations": len(relations), "comparisons": len(comparisons), "assessments": len(assessments),
                   "reviews": len(reviews)},
        "problems": [str(p) for p in A.problems(ds)] if inside else [],
    }
    files = {
        "meta.json": meta,
        "topics.json": topics,
        "sources.json": sources,
        "entities.json": entities,
        "evidence.json": evidence,
        "comparisons.json": {"comparisons": comparisons, "assessments": assessments, "reviews": reviews},
        "relations.json": relations,
        "logs.json": {"changes": A.changes(ds) if inside else [c for c in A.changes(ds) if c.get("kind") != "correction"],
                      "worklog": A.worklog(ds) if inside else []},
        "labels.json": labels,
    }
    if inside:
        files["views.json"] = site_views.views(ds, V.load_schema(), labels,
                                               version or "没有版本号（不在 git 仓库里）")
    meta["files"] = sorted(files)
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(description="导出网页前端读的数据文件")
    ap.add_argument("--data", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--audience", choices=AUDIENCES, default="internal")
    ap.add_argument("--version", help="写进数据文件的数据版本；不写就用 git 的提交号")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.data):
        print(f"没有这个数据目录：{args.data}", file=sys.stderr)
        return 2
    files = export(args.data, args.audience, args.version)
    os.makedirs(args.out, exist_ok=True)
    for name, content in files.items():
        if name == "views.json":
            with open(os.path.join(args.out, name), "w", encoding="utf-8") as f:
                f.write(site_views.dumps(content))
        else:
            store.write_json(os.path.join(args.out, name), content)
    c = files["meta.json"]["counts"]
    print(f"写出 {len(files)} 个文件到 {args.out}（给 {args.audience} 看）：来源 {c['sources']}、证据 {c['evidence']}、"
          f"实体 {c['entities']}、可比组 {c['comparisons']}；数据版本 {files['meta.json']['data_version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
