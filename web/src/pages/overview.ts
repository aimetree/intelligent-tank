/* 总览（K1），照 tools/overview_view.py 的 render 和它用到的几块。 */
import { defineComponent, type PropType } from 'vue';
import { el, type Kid } from '../el';
import { NOT_FILLED, fmtNum } from '../names';
import { state } from '../state';
import type { CovCell, Membrane, OverviewModel, Tile } from '../types';
import type { Ctx } from './evidence';
import { cls, round } from './common';
import type { Names } from '../names';

// 覆盖图格子里的字：核验状态的头一个字。图例里写全称
const CELL_TEXT: Record<string, string> = {
  expert_reviewed: '复', human_verified: '人', machine_checked: '机', pending: '待', disputed: '疑',
  unknown: '？', not_reported: '未', not_applicable: '不适用', none: '—',
};

export function facetText(mem: Membrane): string {
  return mem.facets.map(([, v]) => v).join('｜') || NOT_FILLED;
}

function renderTiles(items: Tile[], ids: Set<string>) {
  return el('div', { class: 'tiles' }, items.map((t) => {
    let sub: Kid = [t.sub];
    if (t.key === 'disputed') {
      const list = t.ids || [];
      if (!t.n) sub = ['没有'];
      else if (t.note) sub = [el('a', { href: `#${list[0]}` }, list[0]), '：', t.note];
      else sub = list.map((x, i) => [i ? '、' : '', ids.has(x) ? el('a', { href: `#${x}` }, x) : x]);
    }
    return el('div', { class: 'tile' + (t.warn ? ' warn' : ''), 'data-tile': t.key },
      el('div', { class: 'tile-name' }, t.label), el('div', { class: 'tile-n' }, t.n), el('div', { class: 'tile-sub' }, sub));
  }));
}

function renderStatus(parts: OverviewModel['status'], total: number) {
  const segs: Kid[] = [];
  let x = 0;
  for (const [code, label, n] of parts) {
    if (!n || !total) continue;
    const w = (1000 * n) / total;
    segs.push(el('rect', { class: `seg seg-${cls(code)}`, x: fmtNum(round(x, 2)), y: '0', width: fmtNum(round(w, 2)), height: '18' },
      el('title', null, `${label} ${n} 条`)));
    x += w;
  }
  const summary = parts.map(([, label, n]) => `${label} ${n} 条`).join('，');
  const bar = segs.length
    ? el('svg', { class: 'statusbar', viewBox: '0 0 1000 18', preserveAspectRatio: 'none', role: 'img', 'aria-label': `各核验状态的条数：${summary}` }, segs)
    : null;
  const legend = parts.map(([code, label, n]) => el('span', { class: 'status-count', 'data-status': code },
    el('span', { class: `status s-${cls(code)}` }, label), ' ', el('span', { class: 'strong' }, n)));
  return el('section', { class: 'card', id: 'overview-status', 'aria-label': '核到哪一步' },
    el('h2', null, '核到哪一步'), bar, el('div', { class: 'status-counts' }, legend),
    el('p', { class: 'note' }, '报告只用“人工已核”以上的；用于对比的和数据概览要到“专业已复核”。看板显示全部，含待核的。'));
}

function covCell(c: CovCell) {
  const text = (CELL_TEXT[c.state] ?? '？') + (c.disputed ? '·疑' : '');
  const box = el('span', { class: `cov cov-${cls(c.state)}` + (c.disputed ? ' cov-also-disputed' : '') }, text);
  if (!c.best) return el('td', { 'data-state': c.state }, box);
  const ids = c.rows.map((r) => r.id).join('、');
  const more = c.rows.length > 1 ? [' ', el('span', { class: 'sub' }, `${c.rows.length} 条`)] : null;
  return el('td', { 'data-state': c.state, 'data-n': c.rows.length },
    el('a', { class: 'cov-link', href: `#${c.best.id}`, title: ids }, box), more);
}

function renderCoverage(cov: OverviewModel['coverage'], names: Names) {
  const head = el('div', { class: 'view-head' }, el('h2', null, '覆盖图：哪种膜的哪项指标有数据'),
    el('div', { class: 'note', id: 'coverage-count' }, `${cov.total} 格里 ${cov.with_data} 格有数据，${cov.not_reported} 格是找过、原文没有报告`));
  if (!cov.rows.length || !cov.cols.length) {
    const why = !cov.cols.length ? '指标字典里还没有核心指标。' : '样品登记里还没有膜。来源登记了样品、录了证据之后，重新生成，就会出现在这里。';
    return el('section', { class: 'card', id: 'coverage' }, head, el('p', { class: 'empty' }, why));
  }
  const ths = [el('th', { scope: 'col' }, '膜'), ...cov.cols.map((g) =>
    el('th', { scope: 'col' }, g.label, ' ', el('span', { class: 'sub' }, names.enum('level', g.level) || NOT_FILLED)))];
  const body = cov.rows.map((r) => {
    const mem = r.mem;
    const where = mem.kind === 'lab' ? mem.source_id : '商业产品';
    return el('tr', { 'data-membrane': mem.key },
      el('th', { scope: 'row' }, mem.label, ' ', el('span', { class: 'sub' }, `${facetText(mem)}｜${where}`)), r.cells.map(covCell));
  });
  const table = el('div', { class: 'table-wrap' }, el('table', { class: 'cmp-table cov-table' },
    el('thead', null, el('tr', null, ths)), el('tbody', null, body)));
  const v = (code: string) => names.enum('verification_status', code);
  const legend = ([
    ['expert_reviewed', v('expert_reviewed')], ['human_verified', v('human_verified')], ['machine_checked', v('machine_checked')],
    ['pending', v('pending')], ['disputed', '只有' + v('disputed') + '的'], ['not_reported', '找过，原文没有报告'],
    ['not_applicable', '找过，不适用'], ['none', '还没有数据'],
  ] as Array<[string, string]>).map(([code, text]) => el('span', { class: 'legend-item' }, el('span', { class: `cov cov-${code}` }, CELL_TEXT[code]), text));
  legend.splice(5, 0, el('span', { class: 'legend-item' }, el('span', { class: 'cov cov-expert_reviewed cov-also-disputed' }, '复·疑'),
    '另有一条' + v('disputed')));
  const skipped = cov.skipped.map(([name, why]) => `${name}（${why}）`).join('；');
  return el('section', { class: 'card', id: 'coverage', 'aria-label': '覆盖图' }, head, table,
    el('div', { class: 'cov-legend' }, legend),
    el('p', { class: 'note' }, '每格显示这一项里核得最深的那条，点了去那条证据；别的几条到',
      el('a', { href: '#evidence' }, '证据表'), '里查。行的次序是录入的次序，不是排名。只列核心指标；',
      skipped ? `没有单列的：${skipped}。` : '', '专利、政策法规和标准、产业和市场的数字、科研资助不在这张图里，见',
      el('a', { href: '#non-academic' }, '非学术来源'), '。'));
}

function rowsCard(id: string, title: string, rows: Array<[string, string | number, boolean?]>, notes: string[] = [], empty = '') {
  const lines = rows.map((r) => el('div', { class: 'line' + (r.length > 2 && r[2] ? ' muted' : '') },
    el('span', null, r[0]), ' ', el('span', { class: 'strong' }, r[1])));
  return el('section', { class: 'card third', id, 'aria-label': title }, el('h2', null, title),
    lines.length ? el('div', { class: 'lines' }, lines) : el('p', { class: 'empty' }, empty),
    notes.map((n) => el('p', { class: 'note' }, n)));
}

export const OverviewView = defineComponent({
  props: {
    ctx: { type: Object as PropType<Ctx>, required: true },
    name: { type: String, required: true },
    title: { type: String, required: true },
    question: { type: String, required: true },
  },
  setup(props) {
    const { view, names, ids } = props.ctx;
    const model = view.overview!;
    const head = el('section', { class: 'card' },
      el('div', { class: 'view-head' }, el('h2', null, props.title),
        el('div', { class: 'note' }, `${props.question}｜${model.total} 条证据，来自 ${model.source_count} 个来源`)),
      renderTiles(model.tiles, ids));
    const events = model.recent.map(([d, , text]) => el('li', null, el('span', { class: 'date' }, d), ' ', text as Kid));
    const older = model.older ? [`更早的还有 ${model.older} 条，在各条证据的核验历史和 data/changes.jsonl 里。`] : [];
    const changes = el('section', { class: 'card third', id: 'overview-recent', 'aria-label': '最近的变化' }, el('h2', null, '最近的变化'),
      events.length ? el('ol', { class: 'history' }, events) : el('p', { class: 'empty' }, '还没有记录。'),
      older.map((x) => el('p', { class: 'note' }, x)));
    const body = [head, renderStatus(model.status, model.total), renderCoverage(model.coverage, names),
      el('div', { class: 'thirds' }, changes,
        rowsCard('overview-reading', '来源是怎么读的', model.reading, [], '还没有纳入的来源。'),
        rowsCard('overview-effort', '工时与成本', model.effort, [...model.effort_notes, '首版只显示累计数，明细页以后再做。'], '工作记录里还没有记工时。'))];
    return () => el('section', { class: state.view === 'overview' ? 'view active' : 'view', id: 'overview', 'aria-label': props.title }, body);
  },
});
