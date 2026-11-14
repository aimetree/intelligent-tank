# data/　证据库的数据文件

字段、枚举和规则的说明在《数据结构_字段规格》v0.2（`docs/03_技术与开发/数据结构_字段规格_v0.2.md`，正本在 Project 里）。这个目录是它的机器可读版本，加上空的目录骨架。

现在只有学术样品的题目卡和指标字典（`public/topics/TOP-000001/`，2026-11-14 照规格 v0.2 的 3.1.1、3.2.1 放进来，草稿，和规格 v0.2 一起待 Yu 验收，D-123），还没有来源和证据。试做批次（清单 T-11）从这里开始录。

目录、文件格式和分文件方式是按规格第 9.1 节的默认做法建的（JSON；一个来源一个文件），由 Yu 定，可以改。改格式只动读写，不动字段和规则。

## 目录

| 路径 | 是什么 | 对应 schema 里的定义 |
|---|---|---|
| `meta.json` | 规格版本 | `meta` |
| `labels.json` | 枚举值、对外证据表的列名、对外显示的标注（预印本、专利实施例等）、题目卡和指标字典自己定义的取值（`values`）的中英文显示名；单位的显示写法，随指标字典补 | 不校验结构；测试会查枚举有没有漏，仓库里题目卡和指标字典用到的取值和单位有没有显示名 |
| `schema/intelligent-tank.schema.json` | 字段的机器可读定义，JSON Schema 2020-12。每类对象是 `$defs` 里的一项，字段的中文名在 `title` 里 | |
| `templates/` | 空白模板，由 schema 生成，见里面的 `README.md` | |
| `changes.jsonl` | 变化记录，一行一条，只在末尾加 | `change` |
| `worklog.jsonl` | 工作记录，一行一条，只在末尾加 | `worklog` |
| `public/sources/SRC-编号.json` | 一个来源一个文件：来源登记、样品登记（来源里出现的每一张膜），加从它取出的全部证据 | `source_file`（样品登记一项是 `sample`） |
| `public/entities.json` | 实体，数组 | `entity` |
| `public/relations.json` | 关系，数组 | `relation` |
| `public/topics/TOP-编号/topic.json` | 题目卡 | `topic` |
| `public/topics/TOP-编号/dictionary.json` | 指标字典：指标、条件项、可比规则 | `dictionary` |
| `public/topics/TOP-编号/comparisons.json` | 可比组，数组 | `comparison` |
| `public/topics/TOP-编号/assessments.json` | 判断，数组。整类可选，可以不建；现阶段只用描述一层（数据概览） | `assessment` |
| `public/topics/TOP-编号/reviews.json` | 复核单，数组。专业复核用，一个可比组一张，只留内部 | `review` |
| `public/topics/TOP-编号/reports.json` | 报告登记，数组 | `report` |
| `clients/客户代号/` | 客户专属区。现在没有客户，没有建 | |

## 怎么用

1. 装依赖：`pip install -r tools/requirements.txt`（只有 jsonschema）。
2. 录入：从 `templates/` 里复制对应的模板，填好，用不到的可选字段整项删掉，不留空值。
3. 编号取现有最大号加一，一经分配不复用。记录不删除：证据作废改状态，实体合并填 `merged_into`。
4. 每次提交之前跑：`python3 tools/validate.py`。有问题时退出码是 1，每行是“规则编号、记录编号、哪里不对”。
5. 改了 schema 之后：`python3 tools/make_templates.py` 重新生成模板，再跑 `python3 tools/tests/test_validate.py` 和 `python3 tools/tests/test_step1.py`。

## 录一个来源，脚本怎么配合

登记与机器核对这一步的脚本（2026-11-14 起，样品阶段脚本第 1 步）。每个脚本的文件头里有用法。

| 步 | 做什么 | 用哪个脚本 |
|---|---|---|
| 1 | 分配来源编号，建来源文件 | `python3 tools/ids.py SRC` |
| 2 | 同一个来源独立抽两遍，各存一个文件，把两遍对起来 | `python3 tools/compare_extractions.py pass1.json pass2.json --out report.json`：一致的已经写好 `double_extraction`，可以直接登记；不一致的、只有一遍有的交给人裁定，定下来的记 `resolved` |
| 3 | 给证据分配编号，登记进来源文件 | `python3 tools/ids.py EV --source SRC-编号 --count 20` |
| 4 | 查来源的标识能不能解析（要联网） | 推到 `main` 之后 GitHub Actions 自动跑 `tools/check_identifiers.py`，把 `id_check` 提交回来；跑完先 `git pull` 再接着做 |
| 5 | 机器核对，预填风险档 | `python3 tools/machine_check.py --texts work/texts --write` |
| 6 | 校验 | `python3 tools/validate.py` |

- **来源文本**　机器核对要拿原文片段到来源文本里逐字找。抽取的时候把读到的来源文本存成 `work/texts/SRC-编号.txt`（或 `.md`）；`work/` 不入库（规格 9.1 第 6 项），两遍抽取的文件和比对报告也放在这里。没有文本的来源，它的证据没法查，留在待核。
- **标识怎么查**　有 DOI 的到 DOI 注册处查这个号存不存在，不碰出版商的网站；没有 DOI、由成员下载或代查的，成员取到了就是存在，不发请求；其余的先看网站的 robots.txt，让自动访问才打开登记的网址。条款禁止自动访问又不是成员取来的，不查，列出来等人处理。没查成的（超时、被拒、robots.txt 不让）不写进数据。专利号现在不单独查，按网址或成员确认走。
- **机器核对查什么**　来源的标识通过了解析；原文片段在来源文本里逐字找得到；数值在片段里，片段里数值后面紧跟着单位的，和记录的单位一致。只放宽排版上的差别（上标、全角、横线的写法、空白、换行、行尾断词），不改字，大小写不放宽。都过了的从待核改成机器已核；没过的留在或退回待核。人工已核及以上的证据不动。
- **风险档**　机器核对之后按字段推出风险理由预填（规格 3.6.1）；数值离群、其他这两种由人或 Claude 标，重跑时留着。
- **GitHub Actions**　`.github/workflows/checks.yml` 在数据或脚本有改动时跑校验和两组测试；`.github/workflows/identifiers.yml` 查标识，只有在 `main` 上才写回并提交，每次先自检（到注册处查一个存在的号和一个不存在的号）。

## 校验脚本查什么

- **结构**　字段名、类型、枚举、录入时就必填的字段，对照 schema。拼错的字段名、空值都会报（V-00、V-01、V-03、V-10、V-19、V-20）。
- **规则**　规格第 5 节的 V-xx：带条件的必填项、引用是否存在、分类维度、样品登记、层级与条件、核验状态、风险档、可比组、复核单、对外门槛等。
- **对外门槛**　报告登记里状态是 `issued` 的报告会自动查。想提前看某几个可比组能不能对外：`python3 tools/validate.py --external CMP-000001`。
- **日志只追加**（V-72）　和上一次提交比，`changes.jsonl`、`worklog.jsonl` 里已有的行不能变。
- **导出**（V-64）　生成对外证据表和随报告给的证据数据文件时，调用 `validate.strip_internal()` 去掉只留内部的字段，调用 `validate.display_flags()` 取要显示的标注（显示名在 `labels.json` 的 `flags`）。

`tools/tests/example_texts/` 是示例来源的文本，也是虚构的，机器核对的测试用。

`tools/tests/example/` 是一组虚构的示例数据，测试用，不是证据：11 个来源（论文、规格书、只有摘要的论文、专利、政策法规、资助记录、预印本和它的正式版、只登记题录的论文、更正声明、付费报告）、13 条证据、3 个可比组、1 张复核单。测试的做法是逐处把它改错，看对应的规则有没有报出来；另有一条测试查校验脚本里的每条规则都有改错的测试。

## 不进仓库的东西

受版权限制的全文、付费库内容、对方的保密资料不进仓库。成员下载的原文放在 Project 的文件区（D-107），也不进仓库。逐字的原文片段只留在证据的 `snippet` 里供内部核对，不对外。
