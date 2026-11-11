# data/　证据库的数据文件

字段、枚举和规则的说明在《数据结构_字段规格》v0.1（`docs/03_技术与开发/数据结构_字段规格_v0.1.md`，正本在 Project 里）。这个目录是它的机器可读版本，加上空的目录骨架。

现在还没有数据。题目卡和指标字典要等《阶段 1 样品验证方案》（清单 T-04）定了再建。

目录、文件格式和分文件方式是按规格第 9.1 节的默认做法建的（JSON；一个来源一个文件），由 Yu 定，可以改。改格式只动读写，不动字段和规则。

## 目录

| 路径 | 是什么 | 对应 schema 里的定义 |
|---|---|---|
| `meta.json` | 规格版本 | `meta` |
| `labels.json` | 枚举值、对外证据表的列名的中英文显示名；单位的显示写法（先放了几个，随指标字典补） | 不校验结构；测试会查枚举有没有漏 |
| `schema/intelligent-tank.schema.json` | 字段的机器可读定义，JSON Schema 2020-12。每类对象是 `$defs` 里的一项，字段的中文名在 `title` 里 | |
| `templates/` | 空白模板，由 schema 生成，见里面的 `README.md` | |
| `changes.jsonl` | 变化记录，一行一条，只在末尾加 | `change` |
| `worklog.jsonl` | 工作记录，一行一条，只在末尾加 | `worklog` |
| `public/sources/SRC-编号.json` | 一个来源一个文件：来源登记，加从它取出的全部证据 | `source_file` |
| `public/entities.json` | 实体，数组 | `entity` |
| `public/relations.json` | 关系，数组 | `relation` |
| `public/topics/TOP-编号/topic.json` | 题目卡 | `topic` |
| `public/topics/TOP-编号/dictionary.json` | 指标字典：指标、条件项、可比规则 | `dictionary` |
| `public/topics/TOP-编号/comparisons.json` | 可比组，数组 | `comparison` |
| `public/topics/TOP-编号/assessments.json` | 判断，数组。整类可选，可以不建 | `assessment` |
| `public/topics/TOP-编号/reports.json` | 报告登记，数组 | `report` |
| `clients/客户代号/` | 客户专属区。现在没有客户，没有建 | |

## 怎么用

1. 装依赖：`pip install -r tools/requirements.txt`（只有 jsonschema）。
2. 录入：从 `templates/` 里复制对应的模板，填好，用不到的可选字段整项删掉，不留空值。
3. 编号取现有最大号加一，一经分配不复用。记录不删除：证据作废改状态，实体合并填 `merged_into`。
4. 每次提交之前跑：`python3 tools/validate.py`。有问题时退出码是 1，每行是“规则编号、记录编号、哪里不对”。
5. 改了 schema 之后：`python3 tools/make_templates.py` 重新生成模板，再跑 `python3 tools/tests/test_validate.py`。

## 校验脚本查什么

- **结构**　字段名、类型、枚举、录入时就必填的字段，对照 schema。拼错的字段名、空值都会报（V-00、V-01、V-03、V-10、V-20）。
- **规则**　规格第 5 节的 V-xx：带条件的必填项、引用是否存在、层级与条件、核验状态、可比组、对外门槛等。
- **对外门槛**　报告登记里状态是 `issued` 的报告会自动查。想提前看某几个可比组能不能对外：`python3 tools/validate.py --external CMP-000001`。
- **日志只追加**（V-72）　和上一次提交比，`changes.jsonl`、`worklog.jsonl` 里已有的行不能变。
- **导出**（V-64）　生成对外证据表时调用 `validate.strip_internal()`，去掉只留内部的字段。

`tools/tests/example/` 是一组虚构的示例数据，测试用，不是证据。测试的做法是逐处把它改错，看对应的规则有没有报出来。

## 不进仓库的东西

受版权限制的全文、付费库内容、对方的保密资料不进仓库。逐字的原文片段只留在证据的 `snippet` 里供内部核对，不对外。
