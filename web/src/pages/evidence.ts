/* 证据表页（K2），照 tools/build_dashboard.py 的 render_evidence_view 和它用到的几块。
   每一行要显示什么由 Python 算好（views.json 的 rows）；这里只摆出来，加上筛选、展开、复制、下载。 */
import { defineComponent, h, nextTick, onMounted, ref, type PropType } from 'vue';
import { el, type Kid } from '../el';
import { NOT_FILLED, NONE, type Names } from '../names';
import { clearFilters, setFilter, state, visibleRows } from '../state';
import type { FilterOption, Row, TopicView } from '../types';
import { block, cls, flagged, kv, mark, sub } from './common';

export const CSV_NAME = 'evidence-internal.csv';
const DONE = '已复制，可以直接粘贴到表格软件里。';
const FAILED = '浏览器没让自动复制。请在下面的框里全选，再复制。';

const COLUMNS: Array<[string, string]> = [
  ['c-id', '编号'], ['c-subject', '对象'], ['c-level', '层级'], ['c-measure', '指标或事实项'], ['c-value', '数值'],
  ['c-cond', '关键条件'], ['c-type', '证据类型'], ['c-status', '核验状态'], ['c-group', '可比档和所在的组'],
  ['c-risk', '风险档'],
];

export interface Ctx {
  view: TopicView;
  names: Names;
  ids: Set<string>;
  groupIds: Set<string>;
}

// ---------------------------------------------------------------- 筛选

const texts = new Map<string, string>(); // 每条证据的全部文字，第一次查找时才取

function textOf(id: string): string {
  let t = texts.get(id);
  if (t === undefined) {
    t = (document.getElementById(id)?.textContent || '').toLowerCase();
    texts.set(id, t);
  }
  return t;
}

function values(row: Row, key: string): string[] {
  return key === 'tier' ? row.tiers : [row.f[key] ?? NONE];
}

export function matches(row: Row, filters: Record<string, string>, text: (id: string) => string = textOf): boolean {
  for (const [key, want] of Object.entries(filters)) {
    if (key === 'q') {
      const terms = want.toLowerCase().split(/\s+/).filter(Boolean);
      const body = terms.length ? text(row.id) : '';
      if (terms.some((t) => !body.includes(t))) return false;
    } else if (!values(row, key).includes(want)) {
      return false;
    }
  }
  return true;
}

function chipGroup(key: string, label: string, options: FilterOption[], total: number) {
  const now = state.filters[key] || '';
  const chip = (value: string, text: string, n: number) =>
    el('button', { type: 'button', class: 'chip', 'data-filter': key, 'data-value': value, 'aria-pressed': now === value ? 'true' : 'false',
      onClick: () => setFilter(key, value) }, text, el('span', { class: 'n' }, n));
  return el('fieldset', { class: 'filter' }, el('legend', { class: 'filter-name' }, label),
    el('div', { class: 'chips' }, chip('', '全部', total), options.map(([code, text, n]) => chip(code, text, n))));
}

function picker(key: string, label: string, options: FilterOption[]) {
  return el('label', { class: 'picker' }, label,
    h('select', {
      'data-filter': key, value: state.filters[key] || undefined,
      onChange: (e: Event) => setFilter(key, (e.target as HTMLSelectElement).value),
    }, [h('option', { value: '' }, '全部'), ...options.map(([code, text, n]) => h('option', { value: code }, `${text}（${n}）`))]));
}

function renderFilters(v: TopicView) {
  const f = v.filters;
  const total = v.rows.length;
  return el('section', { class: 'card filters needs-js', 'aria-label': '筛选' },
    chipGroup('level', '层级', f.level, total),
    chipGroup('status', '核验状态', f.status, total),
    chipGroup('srctype', '来源类别', f.srctype, total),
    chipGroup('risk', '风险档', f.risk, total),
    el('div', { class: 'pickers' },
      picker('type', '证据类型', f.type),
      picker('tier', '可比档', f.tier),
      picker('vis', '可见范围', f.vis),
      picker('subject', '对象', f.subject),
      picker('measure', '指标或事实项', f.measure),
      picker('source', '来源', f.source),
      el('label', { class: 'picker' }, '查找',
        h('input', {
          type: 'search', 'data-filter': 'q', autocomplete: 'off', placeholder: '编号、对象、数值、原文片段里的字',
          value: state.filters.q || undefined,
          onInput: (e: Event) => {
            const value = (e.target as HTMLInputElement).value;
            setFilter('q', value.trim() ? value : '');
          },
        }))));
}

// ---------------------------------------------------------------- 一行和展开的一块

function renderConditions(items: Row['conditions']): Kid[] {
  return items.map((c, i) => [i ? '；' : '', flagged(`${c.name} ${c.text}`, c.state !== 'reported')]);
}

function renderGroups(groups: Row['groups']): Kid {
  if (!groups.length) return '未归组';
  return groups.map((g, i) => {
    const role = !['', 'member'].includes(g.role) ? `，${g.role_label}` : '';
    return [i ? ' ' : '', el('span', { class: 'group' }, el('span', { class: 'strong' }, g.tier_label), sub(`${g.id}${role}`))];
  });
}

function evRefs(ids: string[], known: Set<string>): Kid[] {
  return ids.map((x, i) => [i ? '、' : '', known.has(x) ? el('a', { href: `#${x}` }, x) : x]);
}

function renderDetail(r: Row, c: Ctx) {
  const { names, ids } = c;
  const left: Kid[] = [];
  const right: Kid[] = [];
  const f = (key: string) => names.field('evidence', key);

  if (r.snippet) {
    left.push(block(`${f('snippet')}（只在内部看板显示）`, el('blockquote', { class: 'snippet', 'data-copy': f('snippet') }, r.snippet)));
  } else {
    left.push(block(f('snippet'), el('div', { 'data-copy': f('snippet') },
      '这条没有原文片段。' + (r.figure_read.length ? '图上读数不留片段，读图的记录在下面。' : ''))));
  }
  if (r.figure_read.length) left.push(block(f('figure_read'), kv(r.figure_read)));
  const where = [r.source_id, r.locator, r.obtained_from_label ? `${f('obtained_from')}：${r.obtained_from_label}` : '']
    .filter(Boolean).join('｜');
  left.push(block('出处', el('div', { 'data-copy': '出处' }, where || NOT_FILLED)));
  const conds: Array<[Kid, Kid]> = r.conditions.map((x) => [x.name,
    [flagged(x.text, x.state !== 'reported'), x.parsed ? sub(`解析为 ${x.parsed}`) : null]]);
  if (conds.length) left.push(block(f('conditions'), kv(conds)));
  if (r.cond_snippet || r.cond_locator) {
    left.push(block(`${f('conditions_locator')}和${f('conditions_snippet')}`, el('div', null, r.cond_locator),
      r.cond_snippet ? el('blockquote', { class: 'snippet' }, r.cond_snippet) : null));
  }
  const srcPairs: Array<[Kid, Kid]> = r.source_rows.map(([label, text, url, flag]) => {
    const shown = url
      ? el('a', { href: url, target: '_blank', rel: 'noopener noreferrer', referrerpolicy: 'no-referrer' }, text)
      : text;
    return [label, flag ? el('span', { class: 'flag' }, shown) : shown];
  });
  left.push(block('来源', srcPairs.length ? kv(srcPairs) : NOT_FILLED));

  const steps = r.history.map(([d, t]) => el('li', null, d ? [el('span', { class: 'date' }, d), ' '] : null, t));
  right.push(block('核验历史', steps.length ? el('ol', { class: 'history' }, steps) : '还没有记录'));
  const risk = r.risk;
  if (risk.tier) {
    let line = risk.label + '：' + (risk.reasons.length ? risk.reasons.join('；') : '没有标出理由');
    line += risk.note ? `。${risk.note}` : '';
    right.push(block(`${f('risk')}和理由`, el('div', null, line)));
  } else {
    right.push(block(`${f('risk')}和理由`, el('div', null, '还没标。人工核对之前要标好。')));
  }
  if (r.groups.length) {
    const items = r.groups.map((g) => {
      const head = [g.tier_label, g.role_label, g.status_label].filter(Boolean).join('｜');
      const gid = c.groupIds.has(g.id) ? el('a', { href: `#${g.id}` }, g.id) : g.id; // 点了去对标视图里这一组
      return el('li', null, el('span', { class: 'strong' }, gid, head ? '｜' + head : null),
        sub([g.title, g.tier_reason, g.note].filter(Boolean).join('　')));
    });
    right.push(block('所在可比组', el('ul', { class: 'plain' }, items)));
  } else {
    right.push(block('所在可比组', el('div', null, '未归组')));
  }
  const cited = [...r.asm_direct, ...r.asm_via.map(([a, g]) => `${a}（经可比组 ${g}）`)];
  right.push(block('被这些数据概览引用', el('div', null, cited.length ? cited.join('、') : '还没有被引用')));
  if (r.extra.length) {
    const pairs: Array<[Kid, Kid]> = r.extra.map(([label, kind, value]) =>
      [label, kind === 'evidence' ? evRefs(value as string[], ids) : (value as string)]);
    right.push(block('其余字段', kv(pairs)));
  }
  return el('div', { class: 'detail' }, el('div', { class: 'detail-col' }, left), el('div', { class: 'detail-col' }, right));
}

function td(i: number, ...content: Kid[]) {
  return el('td', { class: COLUMNS[i][0], 'data-label': COLUMNS[i][1] }, el('div', { class: 'c' }, content));
}

/** 一行的十栏。只在展开或收起时重画这一行 */
const RowMain = defineComponent({
  props: { row: { type: Object as PropType<Row>, required: true } },
  setup(props) {
    return () => {
      const r = props.row;
      const open = !!state.open[r.id];
      const risk = r.risk;
      return el('tr', { class: 'ev-main' },
        td(0, h('button', {
          type: 'button', class: 'ev-toggle', 'aria-expanded': open ? 'true' : 'false', 'aria-controls': `d-${r.id}`,
          onClick: () => { state.open[r.id] = !open; },
        }, r.id)),
        td(1, el('span', { class: 'strong' }, flagged(r.subject, r.subject_flag)), r.sample ? sub(r.sample) : null),
        td(2, r.level_label),
        td(3, flagged(r.measure, r.measure_flag)),
        td(4, flagged(r.value, r.value_flag), r.value_notes.map((n) => sub(n))),
        td(5, renderConditions(r.conditions)),
        td(6, el('span', { class: 'type' }, mark(r.type), r.type_label), r.flags.map((x) => sub(x))),
        td(7, el('span', { class: `status s-${cls(r.status)}` }, r.status_label)),
        td(8, renderGroups(r.groups)),
        td(9, el('span', { class: `risk r-${cls(risk.tier || 'none')}` }, risk.label || '还没标')));
    };
  },
});

/** 展开的一块。内容不会变，画一次就不再重画 */
const RowDetail = defineComponent({
  props: { row: { type: Object as PropType<Row>, required: true }, ctx: { type: Object as PropType<Ctx>, required: true } },
  setup(props) {
    const r = props.row;
    const detail = r.error
      ? el('div', { class: 'detail' }, el('div', { class: 'flag' }, `这条证据显示不出来：${r.error}`))
      : renderDetail(r, props.ctx);
    return () => el('tr', { class: 'ev-detail', id: `d-${r.id}` }, el('td', { colspan: COLUMNS.length }, detail));
  },
});

const EvidenceRow = defineComponent({
  props: { row: { type: Object as PropType<Row>, required: true }, ctx: { type: Object as PropType<Ctx>, required: true } },
  setup(props) {
    return () => {
      const r = props.row;
      const f = r.f;
      return el('tbody', {
        class: state.open[r.id] ? 'ev open' : 'ev', id: r.id, hidden: !matches(r, state.filters),
        'data-level': f.level, 'data-status': f.status, 'data-type': f.type, 'data-srctype': f.srctype,
        'data-tier': r.tiers.join(' '), 'data-vis': f.vis, 'data-risk': f.risk, 'data-subject': f.subject,
        'data-measure': f.measure, 'data-source': f.source,
      }, h(RowMain, { row: r }), h(RowDetail, { row: r, ctx: props.ctx }));
    };
  },
});

// ---------------------------------------------------------------- 复制当前显示的行

/** 表格软件会把 = + - @ 开头的格子当公式算。不是单纯的数字就在前面加一个撇号，让它当文字 */
export function clean(text: string): string {
  let value = text.replace(/\s+/g, ' ').trim();
  if (/^[=+\-@]/.test(value) && !/^[+-]?\d+(\.\d+)?([eE][+-]?\d+)?%?$/.test(value)) value = "'" + value;
  return value;
}

function tsv(): string {
  const all = (sel: string, base: ParentNode = document) => Array.from(base.querySelectorAll(sel));
  const rows = all('tbody.ev');
  const head = all('table.ev-table thead th').map((c) => clean(c.textContent || ''));
  if (rows.length) all('[data-copy]', rows[0]).forEach((n) => head.push(clean(n.getAttribute('data-copy') || '')));
  const lines = [head.join('\t')];
  for (const row of visibleRows()) {
    const cells = all('tr.ev-main > td', row).map((c) => clean(c.textContent || ''));
    all('[data-copy]', row).forEach((n) => cells.push(clean(n.textContent || '')));
    lines.push(cells.join('\t'));
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
    const copyNote = ref('');
    const copyText = ref('');
    const copyFailed = ref(false);
    const copyBox = ref<HTMLTextAreaElement | null>(null);
    let framed = true; // 嵌在别的页面里看的时候（比如网页版的查看器），浏览器不让页面自己下载文件，下载的链接就不显示
    try {
      framed = window.self !== window.top;
    } catch {
      framed = true;
    }
    const download = ref('');
    onMounted(() => {
      if (!framed && props.ctx.view.rows.length) {
        download.value = URL.createObjectURL(new Blob([props.ctx.view.csv], { type: 'text/csv;charset=utf-8' }));
      }
    });

    async function copied(ok: boolean, text: string) {
      copyNote.value = ok ? DONE : FAILED;
      copyFailed.value = !ok;
      copyText.value = ok ? '' : text;
      if (!ok) {
        await nextTick();
        copyBox.value?.focus();
        copyBox.value?.select();
      }
    }

    function copy() {
      const text = tsv();
      try {
        navigator.clipboard.writeText(text).then(() => copied(true, text), () => copied(false, text));
      } catch {
        void copied(false, text);
      }
    }

    function expandAll() {
      const visible = visibleRows();
      const open = !allOpen();
      visible.forEach((row) => { state.open[row.id] = open; });
    }

    function allOpen(): boolean {
      const shown = props.ctx.view.rows.filter((r) => matches(r, state.filters));
      return shown.length > 0 && shown.every((r) => state.open[r.id]);
    }

    return () => {
      const { view } = props.ctx;
      const total = view.rows.length;
      const head = el('div', { class: 'view-head' }, el('h2', null, props.title),
        el('div', { class: 'note' }, `${props.question}｜${total} 条证据，来自 ${view.source_count} 个来源`));
      const attrs = { class: state.view === props.name ? 'view active' : 'view', id: props.name, 'aria-label': props.title };
      if (!total) {
        return el('section', attrs, el('section', { class: 'card' }, head,
          el('p', { class: 'empty', id: 'ev-none' }, '这个题目还没有证据。来源和证据登记进数据文件之后，重新生成，就会出现在这里。')));
      }
      const shown = view.rows.filter((r) => matches(r, state.filters)).length;
      const toolbar = el('div', { class: 'toolbar' },
        el('div', { class: 'count needs-js', role: 'status' },
          '显示 ', el('span', { class: 'strong', id: 'ev-shown' }, shown),
          ` 条，共 ${total} 条。点编号看原文片段、出处、来源和核验历史。`),
        el('div', { class: 'toolbar-buttons' },
          h('button', { type: 'button', class: 'btn needs-js', id: 'ev-clear', hidden: !Object.keys(state.filters).length, onClick: clearFilters }, '清除筛选'),
          h('button', { type: 'button', class: 'btn needs-js', id: 'ev-expand', 'data-open': '全部展开', 'data-close': '全部收起', onClick: expandAll }, allOpen() ? '全部收起' : '全部展开'),
          h('button', { type: 'button', class: 'btn needs-js', id: 'ev-copy', 'data-done': DONE, 'data-failed': FAILED, onClick: copy }, '复制当前显示的行'),
          h('a', { class: 'btn', id: 'ev-download', href: download.value || undefined, download: CSV_NAME, hidden: !download.value },
            `下载表格文件（全部 ${total} 条，含只留内部的字段）`)),
        el('div', { class: 'note needs-js', id: 'ev-copy-note', role: 'status' }, copyNote.value),
        h('textarea', {
          class: 'copy-box', id: 'ev-copy-box', hidden: !copyFailed.value, readonly: true, ref: copyBox,
          'aria-label': '当前显示的行，制表符分隔', value: copyText.value || undefined,
        }));
      const table = el('table', { class: 'ev-table' },
        el('thead', null, el('tr', null, COLUMNS.map(([c, label]) => el('th', { scope: 'col', class: c }, label)))),
        view.rows.map((r) => h(EvidenceRow, { row: r, ctx: props.ctx, key: r.id })));
      return el('section', attrs,
        el('section', { class: 'card' }, head, toolbar),
        renderFilters(view),
        el('section', { class: 'card table-card' }, table,
          el('p', { class: 'empty', id: 'ev-empty', hidden: shown > 0 }, '没有符合筛选条件的证据。')));
    };
  },
});
