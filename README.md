# Intelligent Tank

产业科技智库与专业情报服务（业务A）的版本存档与代码仓库。

## 以哪里为准

| 内容 | 正本在哪里 | 本仓库的角色 |
|---|---|---|
| 计划类文档（主页、决策、问题、清单、路线图、基线分析） | claude.ai 上的 Project “Intelligent Tank” | `docs/` 是带版本历史的快照，单向同步，不在这里直接改 |
| 代码、数据、证据表 | 本仓库 | 正本；Project 里只放说明与结论 |
| 原始文件（交接包、Word 原件） | 本仓库 `archive/` | 正本；Project 里是文字转录 |

## 目录

| 路径 | 内容 |
|---|---|
| `docs/00_项目管理/` | 项目主页、决策记录、待决问题、路线图草案、想法与补充清单、协作流程 |
| `docs/01_业务与产品/` | 项目基线（交接资料分析）、全盘判断记录 |
| `docs/02_研究与验证/` | 学术样品的题目收窄方案、文献量初数、指标清单、样品验证方案和它的三份补充；以后放证据表、对照测试 |
| `docs/03_技术与开发/` | 设计方案（对内 dashboard 与对外报告）；数据结构的字段规格（v0.1、v0.2）；示范案例库；报告写法 skill |
| `docs/90_资料归档/` | 交接资料的 Markdown 转录 |
| `archive/Intelligence_Handoff_2026-11-09/` | 交接包原件（含 5 个 Word 文件，其中两份历史稿内容相同） |
| `data/` | 证据库的数据文件。现在有字段的机器可读定义（`schema/`，规格 v0.2）、空白模板（`templates/`）、显示名表，和学术样品的题目卡、指标字典（草稿，待 Yu 验收）；还没有来源和证据。说明见 `data/README.md` |
| `tools/` | 脚本：`validate.py` 校验 `data/`，`make_templates.py` 由 schema 生成模板；登记与机器核对用的 `ids.py`（分配编号）、`compare_extractions.py`（两遍抽取的比对）、`check_identifiers.py`（标识能否解析，要联网）、`machine_check.py`（机器核对和风险档预填）；`derive.py` 算派生值（标准单位下的值、与同文基准之比、派生指标）；`build_dashboard.py` 从 `data/` 生成对内看板（只读的静态网页，样式和页面脚本在 `dashboard/`；对标视图在 `compare_view.py`，图在 `charts.py`，都是脚本直接写 SVG，不用图表库）；`tests/` 是测试和一组虚构的示例数据。怎么配合见 `data/README.md` |
| `.github/workflows/` | GitHub Actions：`checks.yml` 跑校验和测试，生成看板并在 `main` 上存成可下载的附件；`identifiers.yml` 跑要联网的标识解析 |

每次提交 `data/` 之前跑一遍 `python3 tools/validate.py`（依赖见 `tools/requirements.txt`）。推上去之后 GitHub Actions 会再跑一遍校验和测试。

看板：`python3 tools/build_dashboard.py` 生成到 `site/`（不入库），用浏览器打开 `site/index.html`。不想自己生成的，到 GitHub Actions 最新一次“校验与测试”运行的 Artifacts 里下载，或者让 Claude 在对话里发布成网页。说明见 `data/README.md` 的“生成看板”。

后续目录随阶段建立：产品代码。

## 同步规则

1. 计划类文档只在 Project 里修改。
2. 某次对话改了文档，就在结束时向本仓库提交一次；没有改动不提交。
3. 提交前先拉取 `main` 的最新版本；管理类文档整份导出，归档资料只在新增时导出，仓库里缺的文档一并补上。
4. 文档快照直接提交到 `main`，不走分支和合并请求。
5. 受版权限制的材料（论文全文、付费数据库内容）和客户的保密资料不入库。

先读 `docs/00_项目管理/00_项目主页.md`。新加入的成员先读 `docs/00_项目管理/05_协作流程.md`。
