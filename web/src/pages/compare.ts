/* 对标视图（K3），A 2.0：一次看一个可比组。默认“与基准之比”（Yu 2026-11-15 定），可以切到斜率图或点图、表格；
   右边是指着的那个对象和各成员的条件差异；下面是可比性矩阵、派生指标、同一批测试随条件变化的图。
   参考 Our World in Data：同一份数据在图和表之间切换，选中的对象跟着走。
   成员、数值、比值、档别都由 Python 算好（views.json 的 compare）；这里只摆、画。成员照登记的次序，不排名、不求平均。 */
import { defineComponent, h, type PropType } from 'vue';
import { el, type Kid } from '../el';
import { NOT_FILLED, fmtNum } from '../names';
import { scaleFor } from '../scale';
import { state } from '../state';
import type { Group, Level, MatrixCell, Member } from '../types';
import type { Ctx } from './evidence';
import { cls, renderReview } from './common';

const TIER_RANK: Record<string, number> = { direct: 3, conditional: 2, reference: 1, insufficient: 0 };
const PLOT_ROLES = ['member', 'baseline', 'reference'];

export function pairKey(a: string, b: string): string {
  return [a, b].sort().join('\u0000');
}

/** 先显示第一个有可比组的层级里的第一组 */
export function firstGroup(levels: Level[]): string {
  return (levels.find((lv) => lv.groups.length)?.groups[0]?.id) || '';
}

function usable(g: Group): Member[] {
  return g.members.filter((m) => m.row && PLOT_ROLES.includes(m.role));
}

/** 这一组能怎么看：有比值的先看比值；有基准的能画斜率图；都能看表格 */
export function tabsOf(g: Group): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  const hasRatio = g.members.some((m) => m.ratio && m.ratio.ratio !== null);
  if (hasRatio) out.push(['ratio', '与基准之比']);
  const hasBase = g.members.some((m) => m.role === 'baseline' && m.value !== null);
  const values = usable(g).filter((m) => m.value !== null);
  if (g.indicators.length === 1 && values.length) out.push(['slope', hasBase ? '斜率图' : '点图']);
  out.push(['table', '表格']);
  return out;
}

function solid(m: Member): boolean {
  return m.row?.status === 'expert_reviewed';
}

function ptClass(m: Member): string {
  if (m.role === 'reference') return 'pt ref';
  if (m.role === 'baseline') return 'pt base';
  return solid(m) ? 'pt' : 'pt hollow';
}

function hoverable(m: Member, inner: Kid[]) {
  const on = state.hoverMember === m.id;
  return h('g', {
    class: on ? 'hit hl' : state.hoverMember ? 'hit dim' : 'hit', 'data-evidence': m.id, tabindex: '0', role: 'button',
    'aria-label': `${m.obj.label}（${m.obj.sub}）${m.row?.measure || ''} ${m.row?.value || ''}｜${m.role_label}｜${m.row?.status_label || ''}`,
    onMouseenter: () => { state.hoverMember = m.id; }, onFocus: () => { state.hoverMember = m.id; }, onClick: () => { state.hoverMember = m.id; },
  }, inner as never);
}

/** 与基准之比：一行一个对象，从 1 画到它的比值 */
function ratioChart(g: Group) {
  const ms = g.members.filter((m) => m.row && m.role !== 'baseline' && m.ratio && m.ratio.ratio !== null);
  const W = 760;
  const left = 270;
  const right = W - 90;
  const rowH = 46;
  const top = 26;
  const H = top + rowH * ms.length + 40;
  const sx = scaleFor([...ms.map((m) => m.ratio!.ratio as number), 1], left, right);
  const base = top + rowH * ms.length;
  return el('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}`, role: 'group', 'aria-label': `${g.id} 与同文基准之比` },
    sx.ticks.map((t) => [el('line', { class: 'grid', x1: sx(t).toFixed(1), x2: sx(t).toFixed(1), y1: top - 6, y2: base }),
      el('text', { class: 'axis', x: sx(t).toFixed(1), y: base + 18, 'text-anchor': 'middle' }, sx.label(t))]),
    el('line', { class: 'ref', x1: sx(1).toFixed(1), x2: sx(1).toFixed(1), y1: top - 12, y2: base }),
    el('text', { class: 'reflabel', x: sx(1).toFixed(1), y: top - 16, 'text-anchor': 'middle' }, '基准 = 1'),
    ms.map((m, i) => {
      const y = top + rowH * i + rowH / 2;
      const x = sx(m.ratio!.ratio as number);
      return hoverable(m, [
        el('rect', { x: 0, y: y - rowH / 2, width: W, height: rowH, fill: 'transparent' }),
        el('text', { class: 'lab', x: 0, y: y - 2 }, m.obj.label),
        el('text', { class: 'sublab', x: 0, y: y + 14 }, m.obj.sub.length > 22 ? m.obj.sub.slice(0, 21) + '…' : m.obj.sub, el('title', null, m.obj.sub)),
        el('line', { class: 'stem', x1: sx(1).toFixed(1), x2: x.toFixed(1), y1: y, y2: y, 'stroke-width': 1.5 }),
        el('circle', { class: ptClass(m), cx: x.toFixed(1), cy: y, r: 6 }),
        el('text', { class: 'val', x: (x + (x >= sx(1) ? 12 : -12)).toFixed(1), y: y + 4, 'text-anchor': x >= sx(1) ? 'start' : 'end' }, fmtNum(m.ratio!.ratio)),
      ]);
    }));
}

/** 斜率图：左边是同文的基准膜，右边是样品，一个来源一条线。没有基准的只画右边一个点（只作参考的用虚线圈） */
function slopeChart(g: Group) {
  const ms = usable(g).filter((m) => m.value !== null);
  const bases = ms.filter((m) => m.role === 'baseline');
  const others = ms.filter((m) => m.role !== 'baseline');
  if (!bases.length) return dotChart(g, ms);
  const baseOf = (m: Member): Member | undefined => {
    const id = m.ratio?.base_id;
    return (id && bases.find((b) => b.id === id)) || bases.find((b) => b.row?.source_id === m.row?.source_id);
  };
  const W = 720;
  const H = 320;
  const sy = scaleFor(ms.map((m) => m.value), 270, 24);
  const xl = 230;
  const xr = 470;
  const unit = ms.find((m) => m.unit)?.unit || '';
  return el('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}`, role: 'group', 'aria-label': `${g.id} 斜率图：基准膜到样品` },
    sy.ticks.map((t) => [el('line', { class: 'grid', x1: 120, x2: 640, y1: sy(t).toFixed(1), y2: sy(t).toFixed(1) }),
      el('text', { class: 'axis', x: 110, y: (sy(t) + 4).toFixed(1), 'text-anchor': 'end' }, sy.label(t) + (unit === '%' ? '%' : ''))]),
    el('text', { class: 'sublab', x: xl, y: H - 8, 'text-anchor': 'middle' }, '同文基准膜'),
    el('text', { class: 'sublab', x: xr, y: H - 8, 'text-anchor': 'middle' }, '样品'),
    others.map((m) => {
      const b = baseOf(m);
      const y2 = sy(m.value as number);
      if (!b || m.role === 'reference') {
        return hoverable(m, [el('circle', { class: ptClass(m), cx: xr + 130, cy: y2.toFixed(1), r: 6 }),
          el('text', { class: 'val', x: xr + 144, y: (y2 + 4).toFixed(1) }, `${m.obj.label} ${m.row!.value}`)]);
      }
      const y1 = sy(b.value as number);
      return hoverable(m, [
        el('line', { class: 'stem', x1: xl, y1: y1.toFixed(1), x2: xr, y2: y2.toFixed(1), 'stroke-width': 1.5 }),
        el('circle', { class: 'pt base', cx: xl, cy: y1.toFixed(1), r: 5 }),
        el('circle', { class: ptClass(m), cx: xr, cy: y2.toFixed(1), r: 6 }),
        el('text', { class: 'val', x: xl - 12, y: (y1 + 4).toFixed(1), 'text-anchor': 'end' }, `${b.obj.label} ${b.row!.value}`),
        el('text', { class: 'val', x: xr + 12, y: (y2 + 4).toFixed(1) }, `${m.obj.label} ${m.row!.value}`),
      ]);
    }));
}

/** 点图：一行一个对象，横轴是数值（没有基准的组） */
function dotChart(g: Group, ms: Member[]) {
  const W = 760;
  const left = 270;
  const right = W - 90;
  const rowH = 46;
  const top = 16;
  const H = top + rowH * ms.length + 40;
  const sx = scaleFor(ms.flatMap((m) => [m.value, ...(m.err || [])]), left, right);
  const base = top + rowH * ms.length;
  return el('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}`, role: 'group', 'aria-label': `${g.id} 点图` },
    sx.ticks.map((t) => [el('line', { class: 'grid', x1: sx(t).toFixed(1), x2: sx(t).toFixed(1), y1: top - 6, y2: base }),
      el('text', { class: 'axis', x: sx(t).toFixed(1), y: base + 18, 'text-anchor': 'middle' }, sx.label(t))]),
    ms.map((m, i) => {
      const y = top + rowH * i + rowH / 2;
      const x = sx(m.value as number);
      return hoverable(m, [
        el('rect', { x: 0, y: y - rowH / 2, width: W, height: rowH, fill: 'transparent' }),
        el('text', { class: 'lab', x: 0, y: y - 2 }, m.obj.label),
        el('text', { class: 'sublab', x: 0, y: y + 14 }, m.obj.sub.length > 22 ? m.obj.sub.slice(0, 21) + '…' : m.obj.sub, el('title', null, m.obj.sub)),
        m.err ? el('line', { class: 'stem', x1: sx(m.err[0]).toFixed(1), x2: sx(m.err[1]).toFixed(1), y1: y, y2: y, 'stroke-width': 1.4 }) : null,
        el('circle', { class: ptClass(m), cx: x.toFixed(1), cy: y, r: 6 }),
        el('text', { class: 'val', x: (x + 12).toFixed(1), y: y + 4 }, m.row!.value),
      ]);
    }));
}

function membersTable(g: Group) {
  const multi = g.indicators.length > 1;
  const showRatio = g.members.some((m) => m.ratio);
  const head = ['对象', ...(multi ? ['指标'] : []), '角色', '数值', ...(showRatio ? ['与基准之比'] : []),
    ...g.columns.map((c) => c.name + (c.is_key ? '（关键）' : '')), '核验'];
  return el('div', { class: 'ev-scroll' }, el('table', { class: 'grid cmp-table' },
    el('thead', null, el('tr', null, head.map((x) => el('th', { scope: 'col' }, x)))),
    el('tbody', null, g.members.map((m) => {
      const row = m.row;
      if (!row) return el('tr', { id: `${g.id}--${m.id}` }, el('td', null, m.id), el('td', { colspan: head.length - 1, class: 'warnword' }, m.obj.sub));
      let ratio: Kid = m.role === 'baseline' ? '—' : '';
      if (m.ratio) ratio = m.ratio.ratio !== null ? fmtNum(m.ratio.ratio) : el('span', { class: 'warnword', title: m.ratio.why }, '算不出');
      return h('tr', { id: `${g.id}--${m.id}`, class: state.hoverMember === m.id ? 'hl' : '', onMouseenter: () => { state.hoverMember = m.id; } }, [
        el('td', null, el('span', { style: 'font-weight: 500' }, m.obj.label), ' ', el('a', { href: `#${m.id}`, class: 'num small' }, m.id)),
        multi ? el('td', null, row.measure) : null,
        el('td', { class: 'mute' }, m.role_label || m.role),
        el('td', { class: 'num' }, row.value),
        showRatio ? el('td', { class: 'num' }, ratio) : null,
        g.columns.map((c) => {
          const cell = c.cells[m.id];
          return el('td', { class: cell && cell.state === 'reported' ? 'small' : 'small warnword' }, cell ? cell.text : '没有这一项');
        }),
        el('td', null, el('span', { class: `dot s-${cls(row.status)}`, role: 'img', 'aria-label': row.status_label }), ' ', el('span', { class: 'small' }, row.status_label)),
      ]);
    }))));
}

function pickedCard(g: Group): Kid {
  const ms = usable(g);
  const m = ms.find((x) => x.id === state.hoverMember) || ms.find((x) => x.role === 'member') || ms[0];
  if (!m || !m.row) return el('div', { class: 'empty-note' }, '这一组没有能显示的成员。');
  const r = m.ratio;
  let line = `${m.row.measure} ${m.row.value}`;
  if (r && r.ratio !== null) line += ` · 是基准的 ${fmtNum(r.ratio)} 倍（${fmtNum(r.value)} ÷ ${fmtNum(r.base_value)}）`;
  return [
    el('div', { class: 'small mute' }, m.role_label),
    el('div', { style: 'font-size: 18px; font-weight: 600' }, m.obj.label),
    el('div', { class: 'small', style: 'color: var(--sub)' }, line),
    el('div', { class: 'small mute' }, `${m.obj.sub} · ${m.row.status_label}${m.note ? ' · ' + m.note : ''}`),
    el('div', { class: 'chips', style: 'margin-top: 8px' }, el('a', { href: `#${m.id}`, class: 'pill accent num' }, m.id),
      r && r.ratio !== null ? el('a', { href: `#${r.base_id}`, class: 'pill num' }, `基准 ${r.base_id}`) : null),
  ];
}

function diffs(g: Group): Kid {
  const rows: Kid[] = g.columns.map((c) => {
    const vals = Array.from(new Set(Object.values(c.cells).map((x) => (x.state === 'reported' ? x.text : x.text || '未报告'))));
    const bad = Object.values(c.cells).some((x) => x.state !== 'reported');
    return el('div', null, el('span', null, c.name + (c.is_key ? '（关键）' : '')), el('span', { class: bad ? 'warnword' : '' }, vals.join(' / ')));
  });
  rows.push(...g.same.map(([name, text, st]) => el('div', null, el('span', null, name), el('span', { class: st !== 'reported' ? 'warnword' : '' }, `都是 ${text}`))));
  return rows.length ? rows : el('div', { class: 'small mute' }, '没有记录条件。');
}

function matrix(lv: Level): Kid {
  const objects = lv.matrix.objects;
  if (objects.length < 2) return null;
  const cells = new Map<string, MatrixCell>(lv.matrix.cells.$pairs.map(([k, v]) => [pairKey(k[0], k[1]), v]));
  return el('section', { class: 'panel', 'aria-label': '可比性矩阵' },
    el('h2', null, '谁和谁能比 ', el('span', { class: 'aside' }, `· ${lv.label}`)),
    el('div', { class: 'ev-scroll' }, el('table', { class: 'grid' },
      el('thead', null, el('tr', null, el('th', null), objects.map((o) => el('th', { scope: 'col', title: o.sub }, o.label)))),
      el('tbody', null, objects.map((a) => el('tr', null, el('th', { scope: 'row', title: a.sub }, a.label),
        objects.map((b) => {
          if (a.key === b.key) return el('td', { class: 'mute' }, '·');
          const c = cells.get(pairKey(a.key, b.key));
          return el('td', null, c ? el('span', { class: `pill${c.tier === 'direct' ? ' ink' : c.tier === 'reference' ? ' dashed' : ' accent'}`, title: `${c.label}：${c.groups.join('、')}` }, c.label) : null);
        })))))));
}

function derived(lv: Level): Kid {
  if (!lv.derived.length) return null;
  return el('section', { class: 'panel', 'aria-label': '派生指标' },
    el('h2', null, '派生指标 ', el('span', { class: 'aside' }, '· 换算值，不是证据')),
    el('div', { class: 'ev-scroll' }, el('table', { class: 'grid' },
      el('thead', null, el('tr', null, ['派生指标', '对象', '取到的值', '那一处的证据', '这一批测了'].map((x) => el('th', null, x)))),
      el('tbody', null, lv.derived.map((d) => el('tr', null, el('td', null, d.indicator),
        el('td', null, d.object, ' ', el('span', { class: 'small mute' }, `${d.source_id} · ${d.series}`)),
        el('td', { class: 'num' }, `${d.condition} ${d.value}`),
        el('td', null, d.picked.map(([name, value, eid], i) => [i ? '；' : '', `${name} ${value}（`, el('a', { href: `#${eid}`, class: 'num' }, eid), '）'])),
        el('td', { class: 'num' }, `${d.tested} 个`)))))));
}

function series(lv: Level): Kid {
  if (!lv.series.length) return null;
  // 这几张图由 tools/charts.py 画好，和报告里的同一份；颜色是浅底的，深色下也放在浅底上
  return el('details', { class: 'panel' }, el('summary', { style: 'cursor: pointer; font-size: 13px; font-weight: 600; color: var(--sub)' },
    `同一批测试里随条件变化（${lv.series.length} 张图）`),
  lv.series.map((s) => el('figure', { style: 'margin: 12px 0 0; background: #FFFFFF; border-radius: 8px; padding: 8px' }, s.chart,
    el('figcaption', { class: 'small', style: 'color: #374151' }, s.caption))));
}

export const CompareView = defineComponent({
  props: {
    ctx: { type: Object as PropType<Ctx>, required: true },
    name: { type: String, required: true },
    title: { type: String, required: true },
    question: { type: String, required: true },
  },
  setup(props) {
    return () => {
      const model = props.ctx.view.compare!;
      const { names } = props.ctx;
      const all = model.levels.flatMap((lv) => lv.groups.map((g) => [lv, g] as [Level, Group]));
      const found = all.find(([, g]) => g.id === state.group) || all[0];
      const attrs = { class: state.view === 'compare' ? 'view active' : 'view', id: 'compare', 'aria-label': props.title };
      const levelSeg = model.levels.length > 1 ? el('div', { class: 'seg', role: 'group', 'aria-label': names.field('comparison', 'level') },
        model.levels.map((lv) => h('button', {
          type: 'button', 'aria-pressed': found && found[0].code === lv.code ? 'true' : 'false', 'data-level-tab': lv.code,
          disabled: !lv.groups.length || undefined,
          onClick: () => { if (lv.groups.length) { state.group = lv.groups[0].id; state.hoverMember = ''; } },
        }, [lv.label, ' ', el('span', { class: 'num' }, lv.groups.length)]))) : null;
      if (!found) {
        return el('section', attrs, el('div', { class: 'topbar' }, el('div', { class: 'title' }, el('h1', null, props.title)), levelSeg),
          el('div', { class: 'panel' }, el('p', { class: 'empty-note' }, model.levels.length ? '还没有可比组。' : '这个题目没有可以建可比组的层级。')),
          model.levels.map((lv) => [matrix(lv), derived(lv), series(lv)]));
      }
      const [lv, g] = found;
      const tabs = tabsOf(g);
      const tab = tabs.some(([k]) => k === state.cmpTab) ? state.cmpTab : tabs[0][0];
      const chart = tab === 'ratio' ? ratioChart(g) : tab === 'slope' ? slopeChart(g) : membersTable(g);
      const tierPill = el('span', { class: `pill${g.tier === 'direct' ? ' ink' : g.tier === 'insufficient' ? ' amber' : ' accent'}` }, g.tier_label);
      const notes = [...g.notes, ...(g.rule_statement ? [['这条规则说的是', g.rule_statement] as [string, string]] : [])];
      return el('section', attrs,
        el('div', { class: 'topbar' },
          el('div', { class: 'title' }, el('h1', null, props.title), el('span', { class: 'meta' }, `${lv.label} · ${model.group_count} 个可比组`)),
          levelSeg),
        el('div', { class: 'chips', role: 'group', 'aria-label': '可比组' }, lv.groups.map((x) => h('button', {
          type: 'button', class: 'chipbtn', 'aria-pressed': x.id === g.id ? 'true' : 'false', 'data-group': x.id,
          onClick: () => { state.group = x.id; state.hoverMember = ''; },
        }, [el('span', { class: 'num' }, x.id), ' ', x.title]))),
        el('div', { class: 'row' },
          el('section', { class: 'panel grow3', 'aria-label': g.title },
            el('div', { class: 'cmp-head' },
              el('div', null,
                el('div', { id: 'cmp-title', style: 'font-weight: 600' }, g.title),
                el('div', { class: 'chips', style: 'margin-top: 4px' }, tierPill,
                  el('span', { class: 'small mute' }, `${g.status_label || NOT_FILLED} · ${g.normalization_label}`),
                  g.question ? el('span', { class: 'small mute', title: g.question_text }, g.question) : null)),
              el('div', { class: 'seg', role: 'tablist', 'aria-label': '怎么看' }, tabs.map(([k, label]) => h('button', {
                type: 'button', role: 'tab', 'aria-selected': k === tab ? 'true' : 'false', 'data-tab': k,
                onClick: () => { state.cmpTab = k; },
              }, label)))),
            chart,
            tab !== 'table' ? el('div', { class: 'legendline', style: 'margin-top: 6px' },
              el('span', null, el('i', { style: 'background: var(--accent); border-radius: 50%' }), '专业已复核'),
              el('span', null, el('i', { style: 'border: 2px solid var(--accent); border-radius: 50%' }), '还没复核'),
              el('span', null, el('i', { style: 'border: 2px dashed var(--mute); border-radius: 50%' }), '只作参考'),
              el('span', { style: 'margin-left: auto' }, g.caption.split('｜')[0] + ' · 比值为换算值')) : null,
            g.skipped.length ? el('details', { style: 'margin-top: 8px' }, el('summary', { class: 'small mute', style: 'cursor: pointer' }, `没画进图里的 ${g.skipped.length} 条`),
              el('ul', { class: 'small', style: 'margin: 6px 0 0; padding-left: 18px' }, g.skipped.map(([eid, why]) => el('li', null, `${eid}：${why}`)))) : null),
          el('aside', { class: 'grow1', style: 'display: flex; flex-direction: column; gap: 16px; max-width: 360px' },
            el('section', { class: 'panel', 'aria-label': '指着的对象' }, pickedCard(g)),
            el('section', { class: 'panel diffs', 'aria-label': '条件差异' }, el('h2', null, '条件'), diffs(g)),
            notes.length ? el('details', { class: 'panel' }, el('summary', { class: 'small', style: 'cursor: pointer; color: var(--sub); font-weight: 600' }, '定档理由和备注'),
              el('dl', { class: 'kvs', style: 'margin-top: 8px' }, notes.map(([k, v]) => [el('dt', null, k), el('dd', null, v)]))) : null)),
        g.reviews.length ? el('details', { class: 'panel' },
          el('summary', { class: 'small', style: 'cursor: pointer; color: var(--sub); font-weight: 600' }, `复核单 ${g.reviews.length} 张`),
          g.reviews.map((r) => renderReview(r, names))) : null,
        matrix(lv), derived(lv), series(lv));
    };
  },
});

export { TIER_RANK };
