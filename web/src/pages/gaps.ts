/* 数据概览与缺口（K5），照 tools/gaps_view.py 的 render 和它用到的几块。 */
import { defineComponent, type PropType } from 'vue';
import { el, type Kid } from '../el';
import { NOT_FILLED, fmtNum, type Names } from '../names';
import { state } from '../state';
import type { Gap, GapsModel, Statement } from '../types';
import type { Ctx } from './evidence';
import { bar, cls, idLinks, renderReviews } from './common';
import { facetText } from './overview';

const MAX_LINES = 6; // 一览表一格里最多列几条，多的写“另有几条”

function renderCell(c: GapsModel['table']['rows'][number]['cells'][number]) {
  if (!c.entries.length) {
    const text = ({ not_reported: '未报告', not_applicable: '不适用' } as Record<string, string>)[c.state] ?? '—';
    const sub = ({ not_reported: '找过，原文没有写', not_applicable: '找过，这一项不适用' } as Record<string, string>)[c.state];
    return el('td', { 'data-state': c.state }, el('span', { class: 'muted' }, text), sub ? [' ', el('span', { class: 'sub' }, sub)] : null);
  }
  const lines: Kid[] = c.entries.slice(0, MAX_LINES).map((x) => {
    const note = x.notes.join('｜');
    return el('div', { class: 'entry', 'data-ev': x.id },
      el('span', { class: 'strong' + (x.flag ? ' missing' : '') }, x.value), ' ',
      el('span', { class: 'sub' }, note ? note + '｜' : '', el('a', { href: `#${x.id}` }, x.id), '｜',
        el('span', x.status === 'disputed' ? { class: 'flag' } : null, x.status_label)));
  });
  const more = c.entries.length - MAX_LINES;
  if (more > 0) lines.push(el('div', { class: 'note' }, `另有 ${more} 条，在`, el('a', { href: '#evidence' }, '证据表'), '里。'));
  return el('td', { 'data-state': c.state, 'data-n': c.entries.length }, lines);
}

function renderTable(t: GapsModel['table'], names: Names) {
  const head = el('div', { class: 'view-head' }, el('h2', null, '一览表：按膜摆出各项指标上的数据'));
  const intro = el('p', { class: 'note' }, '不打分，不排名，行的次序是录入的次序。条件不同的数只是摆在一起，不比大小。每条后面是证据编号和核验状态，点了去',
    el('a', { href: '#evidence' }, '证据表'), '里看原文片段和出处。');
  if (!t.rows.length || !t.cols.length) {
    const why = !t.rows.length ? '样品登记里还没有膜。' : '这些膜还没有任何一项指标的证据。';
    return el('section', { class: 'card', id: 'summary-table' }, head, intro, el('p', { class: 'empty' }, why));
  }
  const ths = [el('th', { scope: 'col' }, '膜'), el('th', { scope: 'col' }, '类别'), ...t.cols.map((g) =>
    el('th', { scope: 'col' }, g.label, ' ', el('span', { class: 'sub' }, names.enum('level', g.level) || NOT_FILLED)))];
  const body = t.rows.map((r) => {
    const mem = r.mem;
    const where = mem.kind === 'lab' ? mem.source_id : '商业产品';
    const roles = mem.roles.map((x) => names.enum('sample_role', x)).join('、');
    return el('tr', { 'data-membrane': mem.key },
      el('th', { scope: 'row' }, mem.label, ' ', el('span', { class: 'sub' }, [where, roles].filter(Boolean).join('｜'))),
      el('td', null, facetText(mem)), r.cells.map(renderCell));
  });
  const foot: Kid[] = ['“—”是还没有数据；“未报告”是逐项找过、原文没有写。企业声明、图上读数、预印本、专利实施例在格子里注明；与同文基准之比是脚本现算的换算值，不是证据。'];
  if (t.empty_core.length) foot.push(`核心指标里一条数据都还没有的：${t.empty_core.join('、')}。`);
  foot.push('专利权利要求、政策条款、报告里的数这些事实项不进一览表，见');
  return el('section', { class: 'card', id: 'summary-table', 'aria-label': '一览表' }, head, intro,
    el('div', { class: 'table-wrap' }, el('table', { class: 'cmp-table sum-table' },
      el('thead', null, el('tr', null, ths)), el('tbody', null, body))),
    el('p', { class: 'note' }, foot, el('a', { href: '#non-academic' }, '非学术来源'), '。'));
}

function renderStatements(items: Statement[], known: Set<string>) {
  const head = el('div', { class: 'view-head' }, el('h2', null, '数据概览：逐组陈述数据说了什么'));
  const intro = el('p', { class: 'note' }, '只陈述数量和范围，不写评价和建议。每句后面是它依据的可比组或证据。陈述由人定稿，报告引用的要已复核，依据要专业已复核。');
  if (!items.length) return el('section', { class: 'card', id: 'statements' }, head, intro, el('p', { class: 'empty' }, '这个题目还没有写数据概览。'));
  const out = items.map((a) => {
    const basis = a.basis.map((b, i) => [i ? ' ' : '', el('span', { class: 'basis' }, b.href ? el('a', { href: b.href }, b.id) : b.id, '｜', b.note)]);
    // 每段小字前面留一个空格：复制、查找、读屏时，两段文字不会粘在一起
    const extra = a.extra.map(([k, v]) => [' ', el('div', { class: 'sub' }, `${k}：${v}`)]);
    const warn = a.not_ready.length
      ? [' ', el('div', { class: 'sub' }, el('span', { class: 'missing' }, '依据里还没有到“专业已复核”的：'), idLinks(a.not_ready, known))]
      : null;
    return el('div', { class: 'statement', id: a.id, 'data-status': a.status },
      el('div', { class: 'statement-text' }, a.statement, extra, warn),
      el('div', { class: 'statement-side' },
        el('div', null, el('span', { class: 'strong' }, a.id), '｜', a.question ? a.question + '｜' : '',
          el('span', { class: `asm asm-${cls(a.status)}` }, a.status_label)),
        el('div', { class: 'sub' }, basis.length ? basis : '没有写依据'), el('div', { class: 'sub' }, a.who)));
  });
  return el('section', { class: 'card', id: 'statements', 'aria-label': '数据概览' }, head, intro, el('div', { class: 'statements' }, out));
}

function renderSearch(model: GapsModel) {
  const lines = model.funnel.map(([label, n, ids]) => el('div', { class: 'line' + (ids ? ' muted' : '') },
    el('span', null, label, ids ? [' ', el('span', { class: 'sub' }, ids)] : null), ' ', el('span', { class: 'strong' }, n)));
  const body: Kid[] = [el('div', { class: 'lines' }, lines)];
  if (model.searches.length) {
    const rows = model.searches.map((q) => el('tr', null, el('td', null, q.date), el('td', null, q.where), el('td', null, q.query),
      (['hits', 'screened', 'included'] as const).map((k) => el('td', null, q[k] !== null && q[k] !== undefined ? fmtNum(q[k]) : '—'))));
    body.push(el('div', { class: 'table-wrap' }, el('table', { class: 'cmp-table', id: 'search-log' },
      el('thead', null, el('tr', null, ['日期', '查了哪里', '怎么查', '命中', '筛过', '纳入'].map((x) => el('th', { scope: 'col' }, x)))),
      el('tbody', null, rows))));
  } else {
    body.push(el('p', { class: 'empty' }, '工作记录里还没有检索的记录。'));
  }
  if (model.excluded.length) {
    body.push(el('p', { class: 'note' }, '排除的原因：', model.excluded.map(([sid, why], i) => [i ? '；' : '', sid, ' ', why || NOT_FILLED])));
  }
  return el('section', { class: 'card third', id: 'search-funnel', 'aria-label': '查了什么，读到多少' }, el('h2', null, '查了什么，读到多少'), body);
}

function renderMissing(levels: GapsModel['missing']) {
  const body = levels.map((lv) => el('div', { class: 'lines', 'data-level': lv.level },
    lv.items.map((it) => el('div', { class: 'meter', 'data-condition': it.key },
      el('div', { class: 'line' }, el('span', null, it.name), ' ', el('span', { class: 'strong' }, `${it.n} / ${lv.sources}`)),
      bar(lv.sources ? it.n / lv.sources : 0, fmtNum))),
    el('p', { class: 'note' }, `${lv.level_label}这一层：按在这一层有证据的 ${lv.sources} 个来源算，只看这一层统一必填的 ${lv.items.length} 项。`)));
  return el('section', { class: 'card third', id: 'missing-conditions', 'aria-label': '必填条件，几个来源没有报告' },
    el('h2', null, '必填条件，几个来源没有报告'),
    body.length ? body : el('p', { class: 'empty' }, '指标字典里没有哪一层规定统一必填的条件。'));
}

export function renderGapLines(items: Gap[], known: Set<string>): Kid[] {
  return items.map((g) => el('div', { class: 'gap', 'data-gap': g.key }, g.text, idLinks(g.ids, known), g.ids.length ? '。' : ''));
}

function renderGaps(items: Gap[], known: Set<string>) {
  const lines = renderGapLines(items, known);
  return el('section', { class: 'card third', id: 'other-gaps', 'aria-label': '其他缺口' }, el('h2', null, '其他缺口'),
    lines.length ? el('div', { class: 'lines' }, lines) : el('p', { class: 'empty' }, '数据里没有数出别的缺口。'));
}

export const GapsView = defineComponent({
  props: {
    ctx: { type: Object as PropType<Ctx>, required: true },
    name: { type: String, required: true },
    title: { type: String, required: true },
    question: { type: String, required: true },
  },
  setup(props) {
    const { view, names, ids, groupIds } = props.ctx;
    const model = view.gaps!;
    const known = new Set([...ids, ...groupIds]);
    const body = [
      el('section', { class: 'card' }, el('div', { class: 'view-head' }, el('h2', null, props.title), el('div', { class: 'note' }, props.question)),
        el('p', { class: 'note', id: 'gaps-count' }, model.count)),
      renderTable(model.table, names), renderStatements(model.statements, known),
      renderReviews(model.reviews, names),
      el('div', { class: 'thirds' }, renderSearch(model), renderMissing(model.missing), renderGaps(model.gaps, known)),
      el('p', { class: 'note' }, '对外报告里的“数据概览”和“覆盖与缺口”两节，由这一页用的同一份数据生成。'),
    ];
    return () => el('section', { class: state.view === 'gaps' ? 'view active' : 'view', id: 'gaps', 'aria-label': props.title }, body);
  },
});
