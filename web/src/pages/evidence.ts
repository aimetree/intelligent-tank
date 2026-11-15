/* 证据表（K2），A 2.0：左边筛选（每项带一条小柱，条数随别的筛选变）、中间一张表（数值带一条横条）、右边一条证据的详情
   （核验进度、原文片段里把数值标出来、条件、来源、核验历史）。参考 Lens 的分面筛选和 Elicit 的“点一格看原文”。
   每一行要显示什么由 Python 算好（views.json 的 rows）；这里只摆出来、筛选、选中、复制、下载。 */
import { computed, defineComponent, h, onMounted, reactive, ref, type PropType } from 'vue';
import { el, type Kid } from '../el';
import { NOT_FILLED, NONE, fmtNum, type Names } from '../names';
import { clearFilters, setFilter, state } from '../state';
import type { FilterOption, Row, TopicView } from '../types';
import { cls, mark } from './common';

export const CSV_NAME = 'evidence-internal.csv';
const DONE = '已复制，可以直接粘贴到表格软件里。';
const FAILED = '浏览器没让自动复制。请在下面的框里全选，再复制。';

export interface Ctx {
  view: TopicView;
  names: Names;
  ids: Set<string>;
  groupIds: Set<string>;
}

// 核验这条路上的四步，核得越深数越大；存疑、作废不在这条路上
export const DEPTH: Record<string, number> = { pending: 1, machine_checked: 2, human_verified: 3, expert_reviewed: 4 };

// ---------------------------------------------------------------- 筛选

/** 一行里供查找的字，全部小写 */
export function textOf(r: Row): string {
  const parts = [r.id, r.subject, r.sample, r.measure, r.value, ...r.value_notes, ...r.conditions.map((c) => `${c.name} ${c.text}`),
    r.type_label, r.status_label, r.source_id, r.source_title, r.locator, r.snippet, r.level_label, ...r.groups.map((g) => g.id)];
  return parts.join(' ').toLowerCase();
}

function values(row: Row, key: string): string[] {
  return key === 'tier' ? row.tiers : [row.f[key] ?? NONE];
}

export function matches(row: Row, filters: Record<string, string>, query = '', skip = ''): boolean {
  for (const [key, want] of Object.entries(filters)) {
    if (key !== skip && !values(row, key).includes(want)) return false;
  }
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length) {
    const body = textOf(row);
    if (terms.some((t) => !body.includes(t))) return false;
  }
  return true;
}

// 筛选项：先摆出来的四项，其余的点“更多”再看
const MAIN_FACETS: Array<[string, string]> = [['status', '核验状态'], ['level', '层级'], ['type', '证据类型'], ['srctype', '来源类别']];
const MORE_FACETS: Array<[string, string]> = [['tier', '可比档'], ['risk', '风险档'], ['measure', '指标或事实项'], ['subject', '对象'], ['source', '来源'], ['vis', '可见范围']];
const SHOW_ITEMS = 6;
// 表里一次先画这么多行，多的点“再显示”：证据上千条时，换页、筛选、选中都不用重画上千行
export const PAGE_ROWS = 200;

function facet(v: TopicView, base: Row[], key: string, name: string, open: Record<string, boolean>) {
  const options: FilterOption[] = v.filters[key] || [];
  const total = base.length || 1;
  const now = state.filters[key] || '';
  const items = options.map(([code, label]) => {
    const n = base.filter((r) => matches(r, state.filters, state.query, key) && values(r, key).includes(code)).length;
    return { code, label, n };
  });
  const shown = open[key] ? items : items.slice(0, SHOW_ITEMS);
  return el('div', { class: 'facet', role: 'group', 'aria-label': name },
    el('div', { class: 'facet-name' }, name),
    shown.map((it) => h('button', {
      type: 'button', 'aria-pressed': now === it.code ? 'true' : 'false', 'data-filter': key, 'data-value': it.code,
      onClick: () => setFilter(key, now === it.code ? '' : it.code),
    }, [el('span', { class: 'l' }, el('span', null, it.label), el('span', { class: 'num mute' }, it.n)),
      el('span', { class: 'bar' }, h('span', { style: { width: `${Math.round((it.n / total) * 100)}%` } }))])),
    items.length > SHOW_ITEMS
      ? h('button', { type: 'button', class: 'more', onClick: () => { open[key] = !open[key]; } }, open[key] ? '收起' : `另有 ${items.length - SHOW_ITEMS} 项`)
      : null);
}

// ---------------------------------------------------------------- 一行

/** 同一个指标的数在多大的范围里：画横条用。只有一个数的不画 */
function ranges(rows: Row[]): Map<string, [number, number]> {
  const out = new Map<string, [number, number]>();
  for (const r of rows) {
    if (r.x.num === null || r.x.num === undefined || !r.measure_key) continue;
    const cur = out.get(r.measure_key);
    out.set(r.measure_key, cur ? [Math.min(cur[0], r.x.num), Math.max(cur[1], r.x.num)] : [r.x.num, r.x.num]);
  }
  for (const [k, [lo, hi]] of out) if (lo === hi) out.delete(k);
  return out;
}

function condSummary(r: Row): Kid {
  const missing = r.conditions.filter((c) => c.state !== 'reported');
  const first = r.conditions.find((c) => c.state === 'reported');
  return [first ? el('span', null, `${first.name} ${first.text}`) : null,
    missing.length ? [first ? ' · ' : '', el('span', { class: 'warnword' }, `缺${missing.map((c) => c.name).join('、')}`)] : null];
}

function groupSummary(r: Row): string {
  if (!r.groups.length) return '—';
  const top = r.groups[0].tier_label;
  return r.groups.length > 1 ? `${top} 等 ${r.groups.length} 组` : top;
}

function statusDot(code: string, label: string) {
  return el('span', { class: `dot s-${DEPTH[code] || code === 'disputed' || code === 'void' ? cls(code) : 'x'}`, title: label, role: 'img', 'aria-label': label });
}

const EvRow = defineComponent({
  props: {
    row: { type: Object as PropType<Row>, required: true },
    span: { type: Array as unknown as PropType<[number, number] | null>, default: null },
  },
  setup(props) {
    return () => {
      const r = props.row;
      const on = state.selected === r.id;
      const span = props.span;
      const num = r.x.num;
      const bar = span && num !== null
        ? el('span', { class: 'vbar', 'aria-hidden': 'true' },
          h('span', { class: r.status === 'expert_reviewed' ? 'top' : '', style: { width: `${Math.max(4, Math.round(((num - span[0]) / (span[1] - span[0])) * 100))}%` } }))
        : null;
      return h('tr', {
        class: 'ev-row', id: r.id, 'aria-selected': on ? 'true' : 'false',
        'data-status': r.f.status, 'data-level': r.f.level,
        onClick: () => { state.selected = r.id; },
      }, [
        el('td', { style: 'width: 18px; padding-left: 16px' }, statusDot(r.status, r.status_label)),
        el('td', null, h('button', { type: 'button', class: 'pick', 'aria-label': `${r.id} ${r.subject} ${r.measure}`, onClick: () => { state.selected = r.id; } },
          [r.sample || r.subject]), el('span', { class: 'id num' }, r.id)),
        el('td', null, el('span', { class: r.measure_flag ? 'warnword' : '' }, r.measure),
          el('span', { class: 'id' }, r.type_label)),
        el('td', null, el('span', { class: 'vcell' }, el('span', { class: `v num${r.value_flag ? ' warnword' : ''}` }, r.value), bar)),
        el('td', { class: 'small' }, r.error ? el('span', { class: 'warnword' }, `显示不出来：${r.error}`) : condSummary(r)),
        el('td', { class: 'small', style: 'padding-right: 16px; white-space: nowrap' }, groupSummary(r)),
      ]);
    };
  },
});

// ---------------------------------------------------------------- 右边的详情

function snippetBlock(r: Row, names: Names): Kid {
  const label = `${names.field('evidence', 'snippet')} · 只在内部看板显示`;
  if (r.snippet) {
    const m = r.x.mark;
    const body = m ? [r.snippet.slice(0, m[0]), el('mark', null, r.snippet.slice(m[0], m[1])), r.snippet.slice(m[1])] : r.snippet;
    return el('div', null, el('div', { class: 'label' }, label), el('blockquote', { class: 'quote' }, body),
      el('div', { class: 'small mute', style: 'margin-top: 6px' }, [r.source_id, r.locator, r.obtained_from_label].filter(Boolean).join(' · ')));
  }
  return el('div', null, el('div', { class: 'label' }, names.field('evidence', 'snippet')),
    el('div', { class: 'small mute' }, r.figure_read.length ? '图上读数不留片段，读图的记录在下面。' : '这条没有原文片段。'),
    r.figure_read.length ? el('dl', { class: 'kvs', style: 'margin-top: 8px' }, r.figure_read.map(([k, v]) => [el('dt', null, k), el('dd', null, v)])) : null,
    el('div', { class: 'small mute', style: 'margin-top: 6px' }, [r.source_id, r.locator, r.obtained_from_label].filter(Boolean).join(' · ')));
}

function detail(r: Row | undefined, c: Ctx): Kid {
  if (!r) return el('div', { class: 'empty-note' }, '点左边的一行，在这里看详情。');
  if (r.error) return el('div', null, el('div', { class: 'num small mute' }, r.id), el('p', { class: 'warnword' }, `这条证据显示不出来：${r.error}`));
  const { names } = c;
  const depth = DEPTH[r.status] || 0;
  const risk = r.risk;
  return [
    el('div', null,
      el('div', { class: 'num small mute' }, r.id),
      el('div', { class: `big num${r.value_flag ? ' warnword' : ''}` }, r.value),
      el('div', { class: 'small', style: 'color: var(--sub)' }, [r.sample || r.subject, r.measure].filter(Boolean).join(' · ')),
      r.value_notes.length ? el('div', { class: 'small mute' }, r.value_notes.join(' · ')) : null),
    el('div', { class: 'chips' },
      el('span', { class: `pill${r.status === 'expert_reviewed' ? ' solid' : r.status === 'disputed' ? ' amber' : r.status === 'pending' ? ' dashed' : ' accent'}` }, r.status_label),
      el('span', { class: 'pill' }, mark(r.type), r.type_label),
      el('span', { class: `pill${risk.tier === 'high' ? ' amber' : ''}` }, risk.tier ? `风险 ${risk.label}` : '风险档还没标'),
      r.flags.map((f) => el('span', { class: 'pill amber' }, f))),
    el('div', { class: 'progress', role: 'img', 'aria-label': `核到第 ${depth} 步：${r.status_label}` },
      ['录入', '机器', '人工', '专业'].map((label, i) => el('div', null,
        el('span', { class: i < depth ? (i === 3 ? 'on top' : 'on') : '' }), el('em', null, label)))),
    snippetBlock(r, names),
    r.conditions.length ? el('div', null, el('div', { class: 'label' }, names.field('evidence', 'conditions')),
      el('div', { class: 'chips' }, r.conditions.map((x) => el('span', { class: `pill${x.state !== 'reported' ? ' amber' : ''}`, title: x.parsed ? `解析为 ${x.parsed}` : null },
        `${x.name} ${x.text}`)))) : null,
    el('div', null, el('div', { class: 'label' }, '来源'),
      el('dl', { class: 'kvs' }, r.source_rows.map(([label, text, url, flag]) => [el('dt', null, label),
        el('dd', { class: flag ? 'warnword' : '' }, url ? el('a', { href: url, target: '_blank', rel: 'noopener noreferrer', referrerpolicy: 'no-referrer' }, text) : text)]))),
    el('div', null, el('div', { class: 'label' }, '可比组'),
      r.groups.length
        ? el('div', { class: 'chips' }, r.groups.map((g) => el('a', { href: `#${g.id}`, class: 'pill accent', title: [g.title, g.tier_reason].filter(Boolean).join('　') },
          `${g.id} · ${g.tier_label}${g.role && g.role !== 'member' ? ' · ' + g.role_label : ''}`)))
        : el('div', { class: 'small mute' }, '未归组')),
    el('div', null, el('div', { class: 'label' }, '核验历史'),
      r.history.length ? el('ol', { class: 'timeline' }, r.history.map(([d, t]) => el('li', null, t, d ? el('span', { class: 'when' }, d) : null)))
        : el('div', { class: 'small mute' }, '还没有记录')),
    risk.tier ? el('div', { class: 'small mute' }, `风险理由：${risk.reasons.join('；') || '没有标出理由'}${risk.note ? '。' + risk.note : ''}`) : null,
    (r.asm_direct.length || r.asm_via.length)
      ? el('div', { class: 'small mute' }, '被数据概览引用：', [...r.asm_direct, ...r.asm_via.map(([a, g]) => `${a}（经 ${g}）`)].join('、')) : null,
    r.extra.length ? el('details', null, el('summary', { class: 'small mute', style: 'cursor: pointer' }, '其余字段'),
      el('dl', { class: 'kvs', style: 'margin-top: 6px' }, r.extra.map(([label, kind, value]) => [el('dt', null, label),
        el('dd', null, kind === 'evidence' ? (value as string[]).map((x, i) => [i ? '、' : '', c.ids.has(x) ? el('a', { href: `#${x}` }, x) : x]) : (value as string))]))) : null,
  ];
}

// ---------------------------------------------------------------- 复制当前显示的行

/** 表格软件会把 = + - @ 开头的格子当公式算。不是单纯的数字就在前面加一个撇号，让它当文字 */
export function clean(text: string): string {
  let value = text.replace(/\s+/g, ' ').trim();
  if (/^[=+\-@]/.test(value) && !/^[+-]?\d+(\.\d+)?([eE][+-]?\d+)?%?$/.test(value)) value = "'" + value;
  return value;
}

export function tsv(rows: Row[], names: Names): string {
  const head = ['编号', '对象', '样品', '层级', '指标或事实项', '数值', '关键条件', '证据类型', '核验状态', '可比档和所在的组', '风险档',
    names.field('evidence', 'snippet'), '出处'];
  const lines = [head.join('\t')];
  for (const r of rows) {
    lines.push([r.id, r.subject, r.sample, r.level_label, r.measure, [r.value, ...r.value_notes].join(' '),
      r.conditions.map((c) => `${c.name} ${c.text}`).join('；'), r.type_label, r.status_label,
      r.groups.map((g) => `${g.tier_label} ${g.id}`).join(' ') || '未归组', r.risk.label || '还没标', r.snippet,
      [r.source_id, r.locator].filter(Boolean).join('｜')].map((x) => clean(String(x ?? ''))).join('\t'));
  }
  return lines.join('\n');
}

// ---------------------------------------------------------------- 整页

export const EvidenceView = defineComponent({
  props: {
    ctx: { type: Object as PropType<Ctx>, required: true },
    name: { type: String, required: true },
    title: { type: String, required: true },
    question: { type: String, required: true },
  },
  setup(props) {
    const open = reactive<Record<string, boolean>>({});
    const more = ref(false);
    const limit = ref(PAGE_ROWS);
    const copyNote = ref('');
    const copyText = ref('');
    const download = ref('');
    let framed = true; // 嵌在别的页面里看的时候（网页版的查看器），浏览器不让页面自己下载文件，下载的链接就不显示
    try {
      framed = window.self !== window.top;
    } catch {
      framed = true;
    }
    onMounted(() => {
      if (!framed && props.ctx.view.rows.length) {
        download.value = URL.createObjectURL(new Blob([props.ctx.view.csv], { type: 'text/csv;charset=utf-8' }));
      }
    });
    const spans = computed(() => ranges(props.ctx.view.rows));
    // 从“数据概览与缺口”点“去证据表看这几条”过来时，先只留那几条，筛选和查找在这几条里面做
    const base = computed(() => {
      if (!state.only) return props.ctx.view.rows;
      const keep = new Set(state.only.ids);
      return props.ctx.view.rows.filter((r) => keep.has(r.id));
    });
    const shown = computed(() => base.value.filter((r) => matches(r, state.filters, state.query)));

    function copy() {
      const text = tsv(shown.value, props.ctx.names);
      const done = (ok: boolean) => {
        copyNote.value = ok ? DONE : FAILED;
        copyText.value = ok ? '' : text;
      };
      try {
        navigator.clipboard.writeText(text).then(() => done(true), () => done(false));
      } catch {
        done(false);
      }
    }

    return () => {
      const { view } = props.ctx;
      const total = view.rows.length;
      const attrs = { class: state.view === props.name ? 'view active' : 'view', id: props.name, 'aria-label': props.title };
      if (!total) {
        return el('section', attrs, el('div', { class: 'panel' }, el('p', { class: 'empty-note', id: 'ev-none' },
          '这个题目还没有证据。来源和证据登记进数据文件之后，重新导出，就会出现在这里。')));
      }
      const rows = shown.value;
      const sel = view.rows.find((r) => r.id === state.selected);
      const selAt = sel ? rows.indexOf(sel) : -1;
      const drawn = rows.slice(0, Math.max(limit.value, selAt + 1));
      const filtered = Object.keys(state.filters).length > 0 || !!state.query || !!state.only;
      return el('section', attrs,
        el('div', { class: 'ev-layout' },
          el('aside', { class: 'facets', 'aria-label': '筛选' },
            el('div', { class: 'head' }, el('span', { class: 'small mute' }, '筛选'),
              el('span', { class: 'num small mute', id: 'ev-shown' }, `${rows.length} / ${total}`)),
            state.only ? el('div', { class: 'only', id: 'ev-only', role: 'status' },
              el('span', null, '只看：', state.only.label, ' ', el('span', { class: 'num mute' }, state.only.ids.length)),
              h('button', { type: 'button', class: 'btn', 'aria-label': '不再只看这几条', onClick: () => { state.only = null; } }, '×')) : null,
            MAIN_FACETS.map(([k, n]) => facet(view, base.value, k, n, open)),
            more.value ? MORE_FACETS.map(([k, n]) => facet(view, base.value, k, n, open)) : null,
            h('button', { type: 'button', class: 'btn', onClick: () => { more.value = !more.value; } }, more.value ? '少一些筛选' : '更多筛选'),
            filtered ? h('button', { type: 'button', class: 'btn', id: 'ev-clear', onClick: clearFilters }, '清除筛选') : null),
          el('div', { class: 'ev-main' },
            el('div', { class: 'ev-tools' },
              el('label', { class: 'vh', for: 'ev-q' }, '查找'),
              h('input', { id: 'ev-q', type: 'search', placeholder: '查找：编号、对象、数值、原文里的字', autocomplete: 'off', value: state.query,
                onInput: (e: Event) => { state.query = (e.target as HTMLInputElement).value; } }),
              h('button', { type: 'button', class: 'btn', id: 'ev-copy', onClick: copy }, '复制显示的行'),
              download.value ? el('a', { class: 'btn', id: 'ev-download', href: download.value, download: CSV_NAME }, '下载表格文件') : null),
            copyNote.value ? el('div', { class: 'small mute', id: 'ev-copy-note', role: 'status', style: 'padding: 6px 16px' }, copyNote.value) : null,
            copyText.value ? h('textarea', { id: 'ev-copy-box', readonly: true, value: copyText.value, 'aria-label': '显示的行，制表符分隔',
              style: 'width: calc(100% - 32px); margin: 0 16px; min-height: 80px' }) : null,
            el('div', { class: 'ev-scroll' },
              el('table', { class: 'grid' },
                el('thead', null, el('tr', null,
                  el('th', { style: 'padding-left: 16px' }, el('span', { class: 'vh' }, '核验状态')), el('th', null, '对象'), el('th', null, '指标'),
                  el('th', null, '数值'), el('th', null, '条件'), el('th', { style: 'padding-right: 16px' }, '可比'))),
                el('tbody', null, drawn.map((r) => h(EvRow, { key: r.id, row: r, span: spans.value.get(r.measure_key) || null }))))),
            drawn.length < rows.length ? el('div', { style: 'padding: 12px 16px; display: flex; gap: 12px; align-items: center' },
              h('button', { type: 'button', class: 'btn', id: 'ev-more', onClick: () => { limit.value += PAGE_ROWS; } }, `再显示 ${Math.min(PAGE_ROWS, rows.length - drawn.length)} 条`),
              el('span', { class: 'small mute' }, `已显示 ${drawn.length} / ${rows.length} 条；复制和下载用的是全部`)) : null,
            rows.length ? null : el('p', { class: 'empty-note', id: 'ev-empty', style: 'padding: 16px' }, '没有符合筛选条件的证据。')),
          el('aside', { class: 'side', 'aria-label': sel ? `${sel.id} 的详情` : '详情', id: 'ev-side' }, detail(sel, props.ctx))));
    };
  },
});

export { fmtNum, NOT_FILLED };
