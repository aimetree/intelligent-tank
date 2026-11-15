#!/usr/bin/env python3
"""取数：页面、导出、复核单读数据都从这里走。

为什么单独一层（《开发蓝图》v0.1 第 5 节 B1；《设计方案_补充1》3.3）：
现在证据库是 data/ 里的一组文件，validate.load_dataset() 把它读成一个字典。页面要是自己去翻这个字典，
以后把文件换成数据库，每一页都得改。所以读数据只走这里的函数：换存的地方时只改这个文件，
函数的名字、参数和返回的东西不变。

四类：
    查        有哪些题目、来源、证据、日志；一条记录是什么
    比        可比组、数据概览里的陈述、复核单
    取证据    一条证据，它的来源、它说的是谁、它的指标是怎么定义的
    看关联    关系

约定：
- ds 是 load() 返回的那个东西。用的人只把它传来传去，不去翻它里面。
- 一条记录原样返回，就是数据里的那一个对象，不复制：坏记录（不是对象的）也原样返回，由用的人判断。
  没有这个编号返回 None。
- 清单给的是编号，按编号的字面排好序，和记录在文件里怎么摆没有关系。
  带 topic_id（复核单是 comparison_id）的清单只列那一项正好等于它、而且是对象的记录；
  给 None 就是只列没有填这一项的，比如不属于任何可比组的复核单。不给这个参数才是全部。
  两份日志（变化记录、工作记录）照写入的先后。
- 这里只读。改数据走 tools/store.py；查数据对不对走 tools/validate.py。

哪些脚本要走这里：见 USERS。校验、存储、迁移这三个脚本管的就是数据文件本身；流水线里的几步
（分配编号、查标识、机器核对）也直接读数据文件，以后跟着流水线一起改。这几个不在这里。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import validate as V  # noqa: E402

# 读数据要走这里的脚本（tools/tests/test_access.py 照这张单子查它们有没有自己去翻 ds）
USERS = ("build_dashboard.py", "compare_view.py", "overview_view.py", "gaps_view.py", "nonacademic_view.py",
         "topicdata.py", "derive.py", "report_export.py", "review_sheet.py")

# 能按编号问“有没有”的几类记录（exists 用）
KINDS = ("topics", "sources", "entities", "evidence", "relations", "comparisons", "assessments", "reports", "reviews")


def load(data_dir):
    """打开一份数据。读不了的文件、重复的编号在 problems() 里。"""
    return V.load_dataset(data_dir)


ALL = object()   # 清单的筛选项不给时的默认值：不筛


def _ids(table, field=None, value=ALL):
    if value is ALL:
        return sorted(table)
    return sorted(k for k, v in table.items() if isinstance(v, dict) and v.get(field) == value)


# ---------------------------------------------------------------- 查

def problems(ds):
    """打开数据时发现的问题：读不了的文件、重复的编号。"""
    return ds["problems"]


def note(ds):
    """数据目录自己带的说明（meta.json 里的 note），没有就是 None。"""
    return (ds.get("meta") or {}).get("note")


def topic_ids(ds):
    return sorted(ds["topics"])


def topic(ds, topic_id):
    """题目卡。"""
    return ds["topics"].get(topic_id)


def dictionary(ds, topic_id):
    """这个题目的指标字典。"""
    return ds["dictionaries"].get(topic_id)


def source_ids(ds):
    return sorted(ds["sources"])


def source(ds, source_id):
    return ds["sources"].get(source_id)


def samples(ds, source_id):
    """这个来源自己的样品登记，照登记的次序；它没有登记时是 None（补充材料用所属论文的，见 lookups().register_of）。"""
    return ds["samples"].get(source_id)


def entity(ds, entity_id):
    return ds["entities"].get(entity_id)


def evidence_ids(ds, topic_id=ALL):
    return _ids(ds["evidence"], "topic_id", topic_id)


def changes(ds):
    """变化记录，照写入的先后。"""
    return ds["changes"]


def worklog(ds):
    """工作记录，照写入的先后。"""
    return ds["worklog"]


def report(ds, report_id):
    """报告登记里的一条。"""
    return ds["reports"].get(report_id)


def exists(ds, kind, record_id):
    """这一类记录里有没有这个编号。kind 是 KINDS 里的一个。"""
    if kind not in KINDS:
        raise ValueError(f"不认识的记录类别：{kind}")
    return record_id in ds[kind]


# ---------------------------------------------------------------- 比

def comparison_ids(ds, topic_id=ALL):
    return _ids(ds["comparisons"], "topic_id", topic_id)


def comparison(ds, comparison_id):
    """可比组。"""
    return ds["comparisons"].get(comparison_id)


def assessment_ids(ds, topic_id=ALL):
    return _ids(ds["assessments"], "topic_id", topic_id)


def assessment(ds, assessment_id):
    """数据概览里的一条陈述。"""
    return ds["assessments"].get(assessment_id)


def review_ids(ds, comparison_id=ALL):
    """复核单。带 comparison_id 时只列这个可比组的；给 None 是不属于任何可比组的那几张（规格 3.13）。"""
    return _ids(ds["reviews"], "comparison_id", comparison_id)


def review(ds, review_id):
    return ds["reviews"].get(review_id)


# ---------------------------------------------------------------- 取证据

def evidence(ds, evidence_id):
    return ds["evidence"].get(evidence_id)


def lookups(ds):
    """跨记录的查找，和校验用的是同一套：
    .measure_of(e)      这条证据的指标或事实项：(类别, 字典里的定义)
    .register_of(sid)   这个来源的样品登记，按样品名索引；补充材料没有自己的登记时用所属论文的
    """
    return V.Lookups(ds)


# ---------------------------------------------------------------- 看关联

def relation_ids(ds):
    return sorted(ds["relations"])


def relation(ds, relation_id):
    return ds["relations"].get(relation_id)
