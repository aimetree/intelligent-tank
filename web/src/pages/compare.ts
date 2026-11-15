/* 对标视图（K3），照 tools/compare_view.py 的 render 和它用到的几块。
   图由 Python 的 charts.py 算好、在 views.json 里是 SVG 的节点，这里照白名单画出来（el.ts）；成员表、矩阵、派生指标表照数据摆。 */
import { defineComponent, h, type PropType } from 'vue';
import { el, type Kid } from '../el';
import { NOT_FILLED, fmtNum } from '../names';
import { state } from '../state';
import type { Group, Level, MatrixCell } from '../types';
import type { Ctx } from './evidence';
import { cls, flagged, kv, mark, renderReview } from './common';

const TIER_RANK: Record<string, number> = { direct: 3, conditional: 2, reference: 1, insufficient: 0 };

function renderMembers(g: Group) {
  const multi = g.indicators.length > 1;
  const showRatio = g.members.some((m) => m.ratio);
  const head = ['证据', '对象', ...(multi ? ['指标'] : []), '角色', '数值', ...(showRatio ? ['与基准之比（换算值）'] : []),
    ...g.columns.map((c) => c.name + (c.is_key ? '（关键条件）' : '')), '证据类型', '核验状态'];
  const lines = g.members.map((m) => {
    const row = m.row;
    if (!row) {
      return el('tr', { id: `${g.id}--${m.id}` }, el('td', null, flagged(m.id, true)),
        el('td', { colspan: head.length - 1 }, flagged(m.obj.sub, true)));
    }
    let ratio: Kid = m.role === 'baseline' ? '—（它就是基准）' : '';
    if (m.ratio) {
      const r = m.ratio;
      ratio = r.ratio !== null
        ? `${fmtNum(r.ratio)}（${fmtNum(r.value)} ÷ ${fmtNum(r.base_value)}，基准 ${r.base_id}）`
        : flagged(r.why, true);
    }
    const cells: Kid[] = [el('td', null, el('a', { href: `#${m.id}` }, m.id)),
      el('td', null, el('span', { class: 'strong' }, m.obj.label), ' ', el('span', { class: 'sub' }, m.obj.sub))];
    if (multi) cells.push(el('td', null, row.measure));
    cells.push(el('td', null, m.role_label || m.role, m.note ? [' ', el('span', { class: 'sub' }, m.note)] : null),
      el('td', null, flagged(row.value, row.value_flag), row.value_notes.map((x) => [' ', el('span', { class: 'sub' }, x)])));
    if (showRatio) cells.push(el('td', null, ratio));
    for (const c of g.columns) {
      const cell = c.cells[m.id];
      cells.push(el('td', null, cell ? flagged(cell.text, cell.state !== 'reported') : flagged('没有这一项', true)));
    }
    cells.push(el('td', null, el('span', { class: 'type' }, mark(row.type), row.type_label), row.flags.map((x) => [' ', el('span', { class: 'sub' }, x)])),
      el('td', null, el('span', { class: `status s-${cls(row.status)}` }, row.status_label)));
    return el('tr', { id: `${g.id}--${m.id}`, class: `role-${cls(m.role)}` }, cells);
  });
  return el('div', { class: 'table-wrap' }, el('table', { class: 'cmp-table' },
    el('thead', null, el('tr', null, head.map((x) => el('th', { scope: 'col' }, x)))), el('tbody', null, lines)));
}

function renderGroup(g: Group, c: Ctx) {
  const { names } = c;
  const tags = [el('span', { class: `tier t-${cls(g.tier)}` }, g.tier_label),
    el('span', null, `${names.field('comparison', 'status')}：${g.status_label || NOT_FILLED}`),
    el('span', null, `${names.field('comparison', 'rule')}：${g.rule || NOT_FILLED}`),
    el('span', null, `${names.field('comparison', 'normalization')}：${g.normalization_label}`)];
  const question = g.question ? `${g.question}　${g.question_text}` : '';
  const body: Kid[] = [el('div', { class: 'view-head' }, el('h3', null, `${g.id}　${g.title}`), el('div', { class: 'note' }, question)),
    el('div', { class: 'tags' }, tags)];
  const notes: Array<[Kid, Kid]> = [...g.notes, ...(g.rule_statement ? [['这条规则说的是', g.rule_statement] as [string, string]] : [])];
  if (notes.length) body.push(kv(notes));
  if (g.chart) body.push(el('figure', { class: 'figure' }, g.chart, el('figcaption', { class: 'note' }, g.caption)));
  else body.push(el('p', { class: 'note' }, '这一组没有画图。' + g.caption));
  body.push(renderMembers(g));
  if (g.same.length) {
    body.push(el('p', { class: 'note' }, '各成员都一样的条件：',
      g.same.map(([name, text, st], i) => [i ? '；' : '', flagged(`${name} ${text}`, st !== 'reported')])));
  }
  if (g.skipped.length) {
    body.push(el('div', { class: 'block' }, el('div', { class: 'block-name' }, '没画进图里的'),
      el('ul', { class: 'plain' }, g.skipped.map(([eid, why]) => el('li', null, `${eid}：${why}`)))));
  }
  body.push(g.reviews.length ? g.reviews.map((r) => renderReview(r, names)) : el('p', { class: 'note' }, '这一组还没有复核单。'));
  return el('section', { class: 'card group-card', id: g.id }, body);
}

export function pairKey(a: string, b: string): string {
  return [a, b].sort().join('\u0000');
}

function renderMatrix(matrix: Level['matrix'], levelLabel: string) {
  const objects = matrix.objects;
  if (objects.length < 2) return null;
  const cells = new Map<string, MatrixCell>(matrix.cells.$pairs.map(([k, v]) => [pairKey(k[0], k[1]), v]));
  const head = [el('th', null), ...objects.map((o) => el('th', { scope: 'col' }, o.label, ' ', el('span', { class: 'sub' }, o.sub)))];
  const used = new Map<string, string>();
  const lines = objects.map((a) => {
    const row: Kid[] = [el('th', { scope: 'row' }, a.label, ' ', el('span', { class: 'sub' }, a.sub))];
    for (const b of objects) {
      if (a.key === b.key) {
        row.push(el('td', { class: 'self' }, '—'));
        continue;
      }
      const cell = cells.get(pairKey(a.key, b.key));
      if (cell) {
        used.set(cell.tier, cell.label);
        row.push(el('td', null, el('span', { class: `tier t-${cls(cell.tier)}`, title: `${cell.label}：${cell.groups.join('、')}` },
          Array.from(cell.label)[0] || ''), ' ', el('span', { class: 'sub' }, cell.groups.join('、'))));
      } else {
        row.push(el('td', null));
      }
    }
    return el('tr', null, row);
  });
  const legend = Array.from(used.keys()).sort((x, y) => -(TIER_RANK[x] ?? -1) + (TIER_RANK[y] ?? -1))
    .map((t) => el('span', { class: 'legend-item' }, el('span', { class: `tier t-${cls(t)}` }, Array.from(used.get(t) || '')[0] || ''), ' ', used.get(t)));
  return el('section', { class: 'card' },
    el('div', { class: 'view-head' }, el('h3', null, '可比性矩阵：谁和谁在同一个组里，是哪一档'), el('div', { class: 'note' }, levelLabel)),
    el('div', { class: 'table-wrap' }, el('table', { class: 'cmp-table matrix' }, el('thead', null, el('tr', null, head)), el('tbody', null, lines))),
    el('div', { class: 'tags' }, legend),
    el('p', { class: 'note' }, '空着的格子：这两个对象不在同一个可比组里。同在几个组里的，显示最高的一档；只作参考的成员和谁并排都只算参考。'));
}

function renderDerived(items: Level['derived']) {
  if (!items.length) return null;
  const lines = items.map((d) => {
    const picked = d.picked.map(([name, value, eid], i) => [i ? '；' : '', `${name} ${value}（`, el('a', { href: `#${eid}` }, eid), '）']);
    return el('tr', null, el('td', null, d.indicator), el('td', null, el('span', { class: 'strong' }, d.object), ' ',
      el('span', { class: 'sub' }, `${d.source_id}｜同一批测试 ${d.series}`)),
    el('td', null, `${d.condition} ${d.value}`), el('td', null, picked), el('td', null, `${d.tested} 个`));
  });
  return el('section', { class: 'card' },
    el('div', { class: 'view-head' }, el('h3', null, '派生指标（换算值）'), el('div', { class: 'note' }, '由脚本从同一批测试里取出来的，不是证据')),
    el('div', { class: 'table-wrap' }, el('table', { class: 'cmp-table' },
      el('thead', null, el('tr', null, ['派生指标', '对象', '取到的值', '那一处的证据', '这一批测了几个值'].map((x) => el('th', { scope: 'col' }, x)))),
      el('tbody', null, lines))));
}

/** 一个层级的一块。内容不变，只在切换层级时显示或藏起来 */
const LevelPanel = defineComponent({
  props: { level: { type: Object as PropType<Level>, required: true }, ctx: { type: Object as PropType<Ctx>, required: true } },
  setup(props) {
    const lv = props.level;
    const body: Kid[] = [el('h3', { class: 'level-name' }, lv.label)];
    body.push(lv.groups.length ? lv.groups.map((g) => renderGroup(g, props.ctx))
      : el('section', { class: 'card' }, el('p', { class: 'empty' }, `${lv.label}这一层还没有可比组。`)));
    for (const sm of lv.series) {
      body.push(el('section', { class: 'card' }, el('div', { class: 'view-head' }, el('h3', null, sm.title)),
        el('figure', { class: 'figure' }, sm.chart, el('figcaption', { class: 'note' }, sm.caption))));
    }
    body.push(renderMatrix(lv.matrix, lv.label), renderDerived(lv.derived));
    return () => el('section', { class: 'level', 'data-level-panel': lv.code, 'aria-label': lv.label, hidden: state.level !== lv.code }, body);
  },
});

/** 先显示第一个有可比组的层级；都没有就显示第一个 */
export function firstLevel(levels: Level[]): string {
  return (levels.find((lv) => lv.groups.length) || levels[0])?.code || '';
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
      const levels = model.levels;
      const tabs = levels.map((lv) => h('button', {
        type: 'button', class: 'chip', 'data-level-tab': lv.code, 'aria-pressed': state.level === lv.code ? 'true' : 'false',
        onClick: () => { state.level = lv.code; },
      }, [lv.label, el('span', { class: 'n' }, lv.groups.length)]));
      const head = el('section', { class: 'card' },
        el('div', { class: 'view-head' }, el('h2', null, props.title),
          el('div', { class: 'note' }, `${props.question}｜${model.group_count} 个可比组`)),
        tabs.length ? el('div', { class: 'chips needs-js', role: 'group', 'aria-label': props.ctx.names.field('comparison', 'level') }, tabs) : null,
        el('p', { class: 'note' }, '层级各有各的图，不合并。成员照登记的次序排，不按数值排名，不求平均；不同来源、不同样品的点不连线。'
          + '图上实心的点是专业已复核的，空心的是还没复核的；基准、只作参考、图上读数，写在点旁边的字和点的提示里。'
          + '与基准之比和派生指标是脚本现算的换算值，不是证据。'));
      const panels: Kid[] = levels.map((lv) => h(LevelPanel, { level: lv, ctx: props.ctx, key: lv.code }));
      if (!levels.length) panels.push(el('section', { class: 'card' }, el('p', { class: 'empty' }, '这个题目没有可以建可比组的层级。')));
      return el('section', { class: state.view === 'compare' ? 'view active' : 'view', id: 'compare', 'aria-label': props.title }, head, panels);
    };
  },
});
