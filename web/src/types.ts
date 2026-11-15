/* 数据文件的样子。views.json 由 tools/site_views.py 写出，各页的内容由看板的 Python 函数算好（Yu 2026-11-15 定“甲”）。
   这里的名字和 Python 那边一一对应，改了那边要跟着改这里。 */

/** 已经写好的 HTML 片段，在 views.json 里拆成了节点：{t: 标签, a: 属性, c: 子节点}，文字节点是字符串 */
export interface HtmlNode {
  t: string;
  a?: Record<string, string>;
  c?: Array<HtmlNode | string>;
}
export interface Html {
  $html: Array<HtmlNode | string>;
}
/** 页面上的一段：文字、HTML 片段，或者它们排成的一串（Python 里 el() 的 children） */
export type Content = string | number | null | undefined | false | Html | Content[];

/** 键是“谁和谁”的字典 */
export interface Pairs<T> {
  $pairs: Array<[string[], T]>;
}

export interface Meta {
  format: number;
  audience: string;
  data_version: string | null;
  spec_version: string;
  counts: Record<string, number>;
  problems: string[];
  files: string[];
}

export interface Cond {
  key: string;
  name: string;
  text: string;
  state: string;
  parsed: string;
}

export interface RowGroup {
  id: string;
  title: string;
  tier: string;
  tier_label: string;
  role: string;
  role_label: string;
  status_label: string;
  tier_reason: string;
  note: string;
}

/** 证据表的一行：build_dashboard.evidence_row 算出来的 */
export interface Row {
  id: string;
  error: string;
  subject_id: string;
  subject: string;
  subject_flag: boolean;
  sample: string;
  level: string;
  level_label: string;
  measure_kind: string | null;
  measure_key: string;
  measure: string;
  measure_flag: boolean;
  value: string;
  value_flag: boolean;
  value_notes: string[];
  conditions: Cond[];
  type: string;
  type_label: string;
  flags: string[];
  status: string;
  status_label: string;
  groups: RowGroup[];
  risk: { tier: string; label: string; reasons: string[]; note: string; set_by: string; set_at: string };
  visibility: string;
  visibility_label: string;
  client_code: string;
  source_id: string;
  source_type: string;
  source_type_label: string;
  source_title: string;
  source_rows: Array<[string, string, string | null, boolean]>;
  locator: string;
  obtained_from_label: string;
  snippet: string;
  cond_snippet: string;
  cond_locator: string;
  figure_read: Array<[string, string]>;
  history: Array<[string, string]>;
  asm_direct: string[];
  asm_via: Array<[string, string]>;
  extra: Array<[string, 'text' | 'evidence', string | string[]]>;
  f: Record<string, string>;
  tiers: string[];
  /** 新前端用：出图用的数（标准单位下）、标准单位、数值在原文片段里的位置 */
  x: { num: number | null; unit: string; mark: [number, number] | null };
}

export type FilterOption = [string, string, number];

// ---------------------------------------------------------------- 对标视图（compare_view.build）

export interface Obj {
  key: string;
  label: string;
  sub: string;
}
export interface Member {
  id: string;
  row: Row | null;
  role: string;
  role_label: string;
  note: string;
  value: number | null;
  err: [number, number] | null;
  ratio: { ratio: number | null; value: number; base_value: number; base_id: string; why: string } | null;
  indicator: string;
  unit: string;
  obj: Obj;
}
export interface Column {
  key: string;
  name: string;
  is_key: boolean;
  cells: Record<string, Cond>;
}
export interface Target {
  id: string;
  href: string;
  what: string;
}
export interface ReviewItem {
  target: Target;
  reason: string;
  why: string;
  suggestion: string;
  decision: string;
  decision_label: string;
  note: string;
  changes: string[];
}
export interface Review {
  id: string;
  title: string;
  status: string;
  status_label: string;
  created: string;
  reviewed: string;
  items: ReviewItem[];
  batch: { ids: Target[]; sampled: string[]; decision: string; decision_label: string } | null;
  notes: string;
}
export interface Group {
  id: string;
  title: string;
  level: string;
  level_label: string;
  tier: string;
  tier_label: string;
  status_label: string;
  rule: string;
  rule_statement: string;
  normalization: string;
  normalization_label: string;
  question: string;
  question_text: string;
  indicators: string[];
  members: Member[];
  notes: Array<[string, string]>;
  columns: Column[];
  same: Array<[string, string, string]>;
  skipped: Array<[string, string]>;
  caption: string;
  reviews: Review[];
}
export interface MatrixCell {
  tier: string;
  label: string;
  groups: string[];
}
export interface SeriesPoint {
  x: number;
  y: number;
  type: string;
  solid: boolean;
  role: string;
  href: string;
  dashed: boolean;
  title: string;
  evidence: string;
  y_err: [number, number] | null;
  label?: string;
}
export interface SeriesLine {
  label: string;
  points: SeriesPoint[];
}
export interface Level {
  code: string;
  label: string;
  groups: Group[];
  matrix: { objects: Obj[]; cells: Pairs<MatrixCell> };
  series: Array<{ title: string; caption: string; x_label: string; y_label: string; lines: SeriesLine[] }>;
  derived: Array<{
    indicator: string;
    source_id: string;
    object: string;
    series: string;
    condition: string;
    value: string;
    tested: number;
    picked: Array<[string, string, string]>;
  }>;
}
export interface CompareModel {
  levels: Level[];
  group_ids: string[];
  group_count: number;
}

// ---------------------------------------------------------------- 总览（overview_view.build）

export interface Membrane {
  key: string;
  kind: string;
  label: string;
  source_id: string;
  sample: string;
  subject_id: string;
  roles: string[];
  used_by: string[];
  facets: Array<[string, string]>;
  core_check: Record<string, string>;
  rows: Row[];
}
export interface IndicatorGroup {
  no: string;
  keys: string[];
  names: string[];
  label: string;
  level: string;
  core: boolean;
}
export interface CovCell {
  state: string;
  disputed: number;
  rows: Row[];
  best: Row | null;
}
export interface Tile {
  key: string;
  label: string;
  n: number;
  sub: string;
  warn?: boolean;
  ids?: string[];
  note?: string;
}
export interface OverviewModel {
  tiles: Tile[];
  status: Array<[string, string, number]>;
  coverage: {
    cols: IndicatorGroup[];
    rows: Array<{ mem: Membrane; cells: CovCell[] }>;
    total: number;
    with_data: number;
    not_reported: number;
    skipped: Array<[string, string]>;
  };
  recent: Array<[string, number, Content]>;
  older: number;
  reading: Array<[string, number, boolean]>;
  effort: Array<[string, string]>;
  effort_notes: string[];
  total: number;
  source_count: number;
}

// ---------------------------------------------------------------- 数据概览与缺口（gaps_view.build）

export interface Entry {
  id: string;
  value: string;
  flag: boolean;
  notes: string[];
  status: string;
  status_label: string;
}
export interface Statement {
  id: string;
  statement: string;
  status: string;
  status_label: string;
  question: string;
  basis: Array<{ id: string; href: string; note: string }>;
  not_ready: string[];
  extra: Array<[string, string]>;
  who: string;
}
export interface Gap {
  key: string;
  text: string;
  ids: string[];
}
export interface GapsModel {
  table: {
    cols: IndicatorGroup[];
    rows: Array<{ mem: Membrane; cells: Array<{ state: string; entries: Entry[] }> }>;
    empty_core: string[];
  };
  statements: Statement[];
  count: string;
  searches: Array<{
    id: string;
    date: string;
    where: string;
    query: string;
    hits: number | null;
    screened: number | null;
    included: number | null;
  }>;
  funnel: Array<[string, number, string]>;
  excluded: Array<[string, string]>;
  missing: Array<{
    level: string;
    level_label: string;
    sources: number;
    items: Array<{ key: string; name: string; n: number; ids: string[] }>;
  }>;
  gaps: Gap[];
  reviews: Review[];
}

// ---------------------------------------------------------------- 非学术来源（nonacademic_view.build）

export interface EvLine {
  id: string;
  measure: string;
  value: string;
  conds: string;
  flags: string[];
  type_label: string;
  status: string;
  status_label: string;
  sample: string;
  locator: string;
}
export interface Relation {
  id: string;
  what: string;
  from: string;
  how: string;
  inferred: boolean;
  status_label: string;
  status: string;
}
export interface DocCard {
  id: string;
  kind: string;
  head: string;
  chip: string;
  pairs: Array<[string, string]>;
  evidence: EvLine[];
  relations: Relation[];
  verified: string;
  needs_verify: boolean;
}
export interface Block {
  key: string;
  title: string;
  unit: string;
  n: number;
  sub: string;
  cards: DocCard[];
  evidence: string[];
}
export interface MarketItem {
  id: string;
  source: string;
  source_id: string;
  value: string;
  number: number | null;
  unit: string;
  basis: string;
  locator: string;
  type_label: string;
  flags: string[];
  status: string;
  status_label: string;
}
export interface NonAcademicModel {
  blocks: Block[];
  matrix: Array<{ type: string; cells: number[] }>;
  cols: string[];
  by_status: Array<[string, number]>;
  evidence_total: number;
  checks: Array<[string, string]>;
  stale: string[];
  events: Array<{ date: string; what: string; where: string; expected: boolean; source: string }>;
  market: Array<{ key: string; name: string; items: MarketItem[]; scale: number | null }>;
  market_waiting: string[];
  papers: number;
  papers_funded: number;
  relations: Relation[];
  gaps: Gap[];
  source_ids: string[];
  reviews: Review[];
}

// ---------------------------------------------------------------- 整站

export interface TopicView {
  topic_id: string;
  title: string;
  cutoff: string;
  version: string;
  stamp: string;
  notice: string;
  source_count: number;
  rows: Row[];
  filters: Record<string, FilterOption[]>;
  issues: Array<[string, string, string]>;
  compare: CompareModel | null;
  overview: OverviewModel | null;
  gaps: GapsModel | null;
  nonacademic: NonAcademicModel | null;
  errors: Array<[string, string]>;
  csv: string;
}

export interface Legend {
  types: Array<{ code: string; label: string }>;
  statuses: Array<{ code: string; cls: string; label: string }>;
  tiers: Array<{ code: string; text: string }>;
  risks: Array<{ code: string; label: string; text: string }>;
}

export interface Views {
  format: number;
  fields: Record<string, Record<string, string>>;
  legend: Legend;
  sprite: Html;
  views: Array<{ key: string; code: string; title: string; question: string }>;
  topics: TopicView[];
}

export type Labels = Record<string, Record<string, unknown>>;

/** 前端读进来的全部数据 */
export interface SiteData {
  meta: Meta;
  labels: Labels;
  views: Views;
}
