/* 总览（K1），A 2.0：上面一排是五个数；核验的四步（点一步，覆盖图只亮到这一步及以上）；
   覆盖热力图（膜 × 核心指标，格子的深浅是核得最深的那一条，指着看是哪条，点了去那条证据）；最近的变化。
   来源怎么读的、工时与成本收在“更多”里。数都由 Python 算好（views.json 的 overview）。只数、只摆，不评价。 */
import { defineComponent, type PropType } from 'vue';
import { el, type Kid } from '../el';
import { NOT_FILLED } from '../names';
import { state } from '../state';
import type { CovCell, Membrane, OverviewModel } from '../types';
import { DEPTH, type Ctx } from './evidence';
import { cls } from './common';

export function facetText(mem: Membrane): string {
  return mem.facets.map(([, v]) => v).join('｜') || NOT_FILLED;
}

const STEPS: Array<[number, string]> = [[1, '录入'], [2, '机器已核'], [3, '人工已核'], [4, '专业已复核']];
const CELL_DEPTH: Record<string, number> = { ...DEPTH, unknown: 1 };

function steps(model: OverviewModel) {
  const counts = Object.fromEntries(model.status.map(([code, , n]) => [code, n]));
  const live = model.status.filter(([code]) => code !== 'void').reduce((s, [, , n]) => s + n, 0);
  const atLeast = (d: number) => Object.entries(counts).filter(([code]) => (DEPTH[code] || 0) >= d).reduce((s, [, n]) => s + n, 0);
  const others = model.status.filter(([code, , n]) => !DEPTH[code] && n);
  return el('section', { class: 'panel', 'aria-label': '核验' },
    el('h2', null, '核验 ', others.length ? el('span', { class: 'aside' }, others.map(([, label, n]) => `· ${label} ${n}`).join(' ')) : null),
    el('div', { class: 'steps' }, STEPS.map(([d, label]) => {
      const n = d === 1 ? live : atLeast(d);
      const on = state.step === d;
      return el('button', {
        type: 'button', class: 'step', 'aria-pressed': on ? 'true' : 'false', 'data-step': d,
        'aria-label': `${label}${d > 1 && d < 4 ? '及以上' : ''} ${n} 条。点了覆盖图只亮到这一步及以上`,
        onClick: () => { state.step = on ? 0 : d; },
      }, el('span', { class: 'top' }, el('span', null, label + (d > 1 && d < 4 ? '+' : '')), el('span', { class: 'n num' }, n)),
      el('span', { class: 'track' }, el('span', { style: `width: ${live ? Math.round((n / live) * 100) : 0}%; background: ${d === 4 ? 'var(--accent)' : d === 3 ? 'var(--mid)' : d === 2 ? 'var(--low)' : 'var(--line-dark)'}` })));
    })));
}

function cellKey(mem: Membrane, i: number): string {
  return `${mem.key}#${i}`;
}

function heat(model: OverviewModel, ctx: Ctx) {
  const cov = model.coverage;
  const { names } = ctx;
  if (!cov.rows.length || !cov.cols.length) {
    return el('section', { class: 'panel grow3', id: 'coverage', 'aria-label': '覆盖' }, el('h2', null, '覆盖'),
      el('p', { class: 'empty-note' }, !cov.cols.length ? '指标字典里还没有核心指标。' : '样品登记里还没有膜。'));
  }
  let hovered: { mem: Membrane; col: string; c: CovCell } | null = null;
  const grid: Kid[] = [el('span'), cov.cols.map((g) => el('span', { class: 'colhead', title: g.label }, g.label, ' ', el('span', { class: 'mute' }, `· ${names.enum('level', g.level) || NOT_FILLED}`)))];
  for (const r of cov.rows) {
    const mem = r.mem;
    grid.push(el('span', { class: 'rowhead', title: `${mem.label}｜${facetText(mem)}` }, mem.label, ' ',
      el('span', null, mem.kind === 'lab' ? mem.source_id : '商业产品')));
    r.cells.forEach((c, i) => {
      const key = cellKey(mem, i);
      const d = CELL_DEPTH[c.state] || 0;
      const dim = state.step > 0 && (!c.best || d < state.step);
      if (state.hoverCell === key) hovered = { mem, col: cov.cols[i].label, c };
      const klass = `cell d${d ? d : c.state === 'disputed' ? 'disputed' : cls(c.state)}${dim ? ' dim' : ''}`;
      const label = `${mem.label}，${cov.cols[i].label}：` + (c.best ? `${c.best.value}（${c.best.status_label}）${c.rows.length > 1 ? `，共 ${c.rows.length} 条` : ''}` : c.state === 'not_reported' ? '找过，原文没有报告' : c.state === 'not_applicable' ? '找过，不适用' : '还没有数据');
      const props = {
        class: klass, 'data-state': c.state, 'aria-label': label,
        onMouseenter: () => { state.hoverCell = key; }, onFocus: () => { state.hoverCell = key; },
      };
      grid.push(c.best
        ? el('a', { ...props, href: `#${c.best.id}` }, el('span', { class: 'num' }, c.best.value + (c.disputed ? ' · 疑' : '')))
        : el('button', { ...props, type: 'button', onClick: () => { state.hoverCell = key; } }, c.state === 'not_reported' ? '未' : c.state === 'not_applicable' ? '不适用' : ''));
    });
  }
  const h0 = hovered as { mem: Membrane; col: string; c: CovCell } | null;
  const line = h0
    ? [el('span', { class: `dot s-${h0.c.best ? cls(h0.c.best.status) : 'x'}` }),
      el('span', { style: 'font-weight: 500' }, `${h0.mem.label} · ${h0.col}`),
      el('span', { style: 'color: var(--sub)' }, h0.c.best
        ? `${h0.c.rows.map((x) => `${x.value}（${x.status_label}）`).join('、')}`
        : h0.c.state === 'not_reported' ? '找过，原文没有报告' : h0.c.state === 'not_applicable' ? '找过，不适用' : '还没有数据'),
      h0.c.best ? el('a', { href: `#${h0.c.best.id}`, class: 'num small', style: 'margin-left: auto' }, h0.c.best.id) : null]
    : el('span', { class: 'mute' }, '指着一格看是哪条证据');
  const skipped = cov.skipped.map(([name, why]) => `${name}（${why}）`).join('；');
  return el('section', { class: 'panel grow3', id: 'coverage', 'aria-label': '覆盖' },
    el('div', { style: 'display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap; margin-bottom: 12px' },
      el('h2', { style: 'margin: 0' }, '覆盖 ', el('span', { class: 'aside', id: 'coverage-count' }, `· ${cov.with_data}/${cov.total} 格有数据`)),
      el('span', { class: 'legendline' },
        el('span', null, el('i', { style: 'background: var(--accent)' }), '专业'),
        el('span', null, el('i', { style: 'background: var(--mid)' }), '人工'),
        el('span', null, el('i', { style: 'background: var(--low); border: 1px solid var(--mid)' }), '机器'),
        el('span', null, el('i', { style: 'border: 1.5px dashed var(--mute)' }), '待核'),
        el('span', null, el('i', { style: 'background: repeating-linear-gradient(45deg, var(--track) 0 2px, var(--surface) 2px 4px); border: 1px solid var(--border)' }), '原文没写'))),
    el('div', { class: 'heat', style: `grid-template-columns: minmax(120px, 170px) repeat(${cov.cols.length}, minmax(64px, 1fr))` }, grid),
    el('div', { class: 'hoverline', role: 'status' }, line),
    skipped ? el('div', { class: 'small mute', style: 'margin-top: 6px' }, `没有单列：${skipped}`) : null);
}

function tiles(model: OverviewModel, ids: Set<string>) {
  return el('div', { class: 'row' }, model.tiles.map((t) => el('div', {
    class: 'panel', style: `flex: 1 1 150px; padding: 12px 16px${t.warn ? '; border-color: var(--amber)' : ''}`, 'data-tile': t.key, title: t.sub || null,
  }, el('div', { class: 'kpi' }, el('span', { class: 'small mute' }, t.label), el('span', { class: `n num${t.warn ? ' warnword' : ''}` }, t.n)),
  t.key === 'disputed' && t.n
    ? el('div', { class: 'small' }, (t.ids || []).map((x, i) => [i ? '、' : '', ids.has(x) ? el('a', { href: `#${x}`, class: 'num' }, x) : x]))
    : el('div', { class: 'small mute', style: 'white-space: nowrap; overflow: hidden; text-overflow: ellipsis' }, t.key === 'disputed' ? '没有' : t.sub))));
}

function feed(model: OverviewModel) {
  return el('section', { class: 'panel grow2', id: 'overview-recent', 'aria-label': '最近' },
    el('h2', null, '最近'),
    model.recent.length ? el('div', { class: 'feed' }, model.recent.map(([d, order, text]) => el('div', null,
      el('span', { class: `dot ${order >= 3 ? 's-disputed' : order === 2 ? 's-expert_reviewed' : order === 1 ? 's-human_verified' : 's-x'}` }),
      el('span', null, text as Kid), el('span', { class: 'when num' }, d))))
      : el('p', { class: 'empty-note' }, '还没有记录。'),
    model.older ? el('div', { class: 'small mute' }, `更早的还有 ${model.older} 条`) : null,
    el('details', { style: 'margin-top: 10px' }, el('summary', { class: 'small mute', style: 'cursor: pointer' }, '来源是怎么读的 · 工时'),
      el('dl', { class: 'kvs', style: 'margin-top: 6px; grid-template-columns: minmax(0, 1fr) auto' },
        model.reading.map(([label, n, muted]) => [el('dt', { class: muted ? 'warnword' : '' }, label), el('dd', { class: 'num' }, n)]),
        model.effort.map(([label, v]) => [el('dt', null, label), el('dd', { class: 'num' }, v)])),
      model.effort_notes.map((n) => el('div', { class: 'small mute' }, n))));
}

export const OverviewView = defineComponent({
  props: {
    ctx: { type: Object as PropType<Ctx>, required: true },
    name: { type: String, required: true },
    title: { type: String, required: true },
    question: { type: String, required: true },
  },
  setup(props) {
    return () => {
      const { view, ids } = props.ctx;
      const model = view.overview!;
      return el('section', { class: state.view === 'overview' ? 'view active' : 'view', id: 'overview', 'aria-label': props.title },
        el('div', { class: 'topbar' }, el('div', { class: 'title' }, el('h1', null, props.title),
          el('span', { class: 'meta' }, `${model.total} 条证据 · ${model.source_count} 个来源`))),
        tiles(model, ids),
        steps(model),
        el('div', { class: 'row' }, heat(model, props.ctx), feed(model)));
    };
  },
});
