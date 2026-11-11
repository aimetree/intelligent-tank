# 空白模板

由 `tools/make_templates.py` 从 `data/schema/` 生成，不要手工改；schema 改了之后重跑一次。

- 尖括号里是占位。写着“必填：”的是录入时就要有的字段；用竖线隔开的是可选的取值。
- 数字填的是 0、真假值填的是 false，只是占个位置。用不到的可选字段整项删掉，不要留空值。
- 带条件的必填项（例如数值型证据要有数值和单位）不在下表里，见字段规格第 3 节和第 5 节。
- 模板不是合法的记录，`tools/validate.py` 不读这个目录。

| 模板 | 对象 | 实际放在 `data/` 下的哪里 | 录入时就必填的字段 |
|---|---|---|---|
| `topic.json` | 题目卡 | `public/topics/TOP-编号/topic.json` | `id`、`title`、`direction`、`status`、`questions`、`scope_in`、`scope_out`、`levels`、`evidence_source_types`、`report_languages` |
| `dictionary.json` | 指标字典 | `public/topics/TOP-编号/dictionary.json` | `topic_id`、`version`、`status`、`conditions`、`indicators`、`rules` |
| `source_file.json` | 来源文件（来源登记加它的证据） | `public/sources/SRC-编号.json` | 来源：`id`、`source_type`、`title`、`creators`、`published`、`url`、`accessed_at`、`version_label`、`language`、`access_route`、`access_scope`、`license`、`license_class`、`terms`、`reading_mode`、`copy_kept`、`external_use`、`handling`、`use`、`topics`、`status`、`status_checked_at`、`registered_by`、`registered_at`<br>证据：`id`、`topic_id`、`record_version`、`created_by`、`created_at`、`subject_id`、`level`、`content_kind`、`evidence_type`、`source_id`、`locator`、`obtained_from`、`entry_method`、`double_extraction`、`obtained_at`、`verification_status`、`visibility` |
| `entity.json` | 实体 | `public/entities.json（数组里的一项）` | `id`、`entity_type`、`name`、`identity_status`、`visibility` |
| `relation.json` | 关系 | `public/relations.json（数组里的一项）` | `id`、`subject`、`relation_type`、`object`、`basis`、`is_key`、`verification_status`、`visibility` |
| `comparison.json` | 可比组 | `public/topics/TOP-编号/comparisons.json（数组里的一项）` | `id`、`topic_id`、`title`、`level`、`indicators`、`tier`、`tier_reason`、`normalization`、`members`、`status`、`visibility` |
| `assessment.json` | 判断（可选） | `public/topics/TOP-编号/assessments.json（数组里的一项）` | `id`、`topic_id`、`layer`、`statement`、`basis`、`status`、`drafted_by`、`visibility` |
| `report.json` | 报告登记 | `public/topics/TOP-编号/reports.json（数组里的一项）` | `id`、`topic_id`、`title`、`language`、`version`、`status` |
| `change.json` | 变化记录 | `changes.jsonl（一行一条）` | `id`、`date`、`kind`、`target_id`、`reason`、`impact`、`recorded_by` |
| `worklog.json` | 工作记录 | `worklog.jsonl（一行一条）` | `id`、`date`、`topic_id`、`arm`、`step`、`actor_kind`、`actor`、`summary` |
