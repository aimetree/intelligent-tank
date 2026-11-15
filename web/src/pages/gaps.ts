/* 数据概览与缺口（K5），A 2.0 的样子（Yu 2026-11-15 看过样图，照建议做）。
   内容照旧由 tools/gaps_view.py 算好；点一条缺口时亮哪些格子、陈述的次序由 tools/site_views.py 的 gaps_extras 给。
   上面一排：查了什么（检索一段、来源登记一段，分开画）、必填条件没报告、缺口（点一条，一览表里亮出相关的格子，可以去证据表只看这几条）；
   下面：一览表、数据概览的陈述（已复核的在前）、复核单。 */
import { defineComponent, h, type PropType } from 'vue';
import { el, type Kid } from '../el';
import { NOT_FILLED, fmtNum, type Names } from '../names';
import { show, state } from '../state';
import type { Entry, Gap, GapsModel, Membrane, Statement } from '../types';
import type { Ctx } from './evidence';
import { cls, idLinks, renderReviews } from './common';
import { facetText } from './overview';

const MAX_LINES = 6; // 一览表一格里最多列几条，多的写“另有几条”

type Cell = GapsModel['table']['rows'][number]['cells'][number];

/** 一条缺口的话去掉末尾的冒号：编号另外列 */
function gapLabel(g: Gap) {
  return g.text.replace(/[：:]$/, '');
}

function gapCount(g: Gap) {
  return g.ids.length || (g.ev || []).length;
}

/** 一段横条：label、条、数 */
function barLine(label: Kid, n: number | null, of: number, strong: boolean, sub: Kid = null) {
  const share = n !== null && of ? Math.max(0, Math.min(1, n / of)) : 0;
  return el('div', { class: 'hbar' },
    el('span', { class: 'hbar-l' }, label, sub ? [' ', el('span', { class: 'mute small' }, sub)] : null),
    el('span', { class: 'hbar-t' }, el('span', { class: strong ? 'on' : '', style: `width: ${Math.round(share * 1000) / 10}%` })),
    el('span', { class: 'hbar-n num' }, n === null ? '—' : fmtNum(n)));
}

function searched(model: GapsModel) {
  const parts: Kid[] = [];
  parts.push(el('h3', { class: 'minor' }, '检索'));
  if (model.searches.length) {
    for (const q of model.searches) {
      const top = q.hits ?? q.screened ?? q.included ?? 0;
      parts.push(el('div', { class: 'search', 'data-search': q.id, title: q.query },
        el('div', { class: 'small mute' }, [q.date, q.where].filter(Boolean).join(' · ') || NOT_FILLED),
        barLine('命中', q.hits, top, false), barLine('筛过', q.screened, top, false), barLine('纳入', q.included, top, true)));
    }
    parts.push(el('details', null, el('summary', { class: 'small mute' }, '怎么查的'),
      el('dl', { class: 'kvs' }, model.searches.map((q) => [el('dt', { class: 'num' }, q.id), el('dd', null, q.query || NOT_FILLED)]))));
  } else {
    parts.push(el('p', { class: 'empty-note' }, '工作记录里还没有检索的记录。'));
  }
  parts.push(el('h3', { class: 'minor' }, '来源登记'));
  const top = model.funnel.length ? model.funnel[0][1] : 0;
  parts.push(el('div', { id: 'funnel' }, model.funnel.map(([label, n, ids]) =>
    barLine(label, n, top, label === '纳入', ids || null))));
  if (model.excluded.length) {
    parts.push(el('div', { class: 'small mute', style: 'margin-top: 6px' }, '排除的原因：',
      model.excluded.map(([sid, why], i) => [i ? '；' : '', sid, ' ', why || NOT_FILLED])));
  }
  return el('section', { class: 'panel grow1', id: 'search-funnel', 'aria-label': '查了什么' }, el('h2', null, '查了什么'), parts);
}

function missing(levels: GapsModel['missing']) {
  const body = levels.map((lv) => el('div', { 'data-level': lv.level, style: 'margin-bottom: 10px' },
    el('div', { class: 'small mute', style: 'margin-bottom: 6px' }, `${lv.level_label} · ${lv.sources} 个来源`),
    el('div', { class: 'cols', style: `grid-template-columns: repeat(${lv.items.length}, minmax(0, 1fr))` },
      lv.items.map((it) => {
        const share = lv.sources ? it.n / lv.sources : 0;
        return el('div', { class: 'col', 'data-condition': it.key, title: it.ids.length ? `没报告的：${it.ids.join('、')}` : null },
          el('span', { class: 'num small' }, `${it.n}/${lv.sources}`),
          el('span', { class: 'col-t' }, el('span', { class: it.n ? 'warn' : '', style: `height: ${Math.max(4, Math.round(share * 100))}%` })),
          el('span', { class: 'small mute col-l' }, it.name));
      }))));
  return el('section', { class: 'panel grow1', id: 'missing-conditions', 'aria-label': '必填条件没报告' },
    el('h2', null, '必填条件没报告 ', el('span', { class: 'aside' }, '· 几个来源没写')),
    body.length ? body : el('p', { class: 'empty-note' }, '指标字典里没有哪一层规定统一必填的条件。'));
}

function gapList(items: Gap[], known: Set<string>) {
  const picked = items.find((g) => g.key === state.gap);
  const lines = items.map((g) => {
    const on = g.key === state.gap;
    return h('button', {
      type: 'button', class: 'gapbtn', 'aria-pressed': on ? 'true' : 'false', 'data-gap': g.key,
      onClick: () => { state.gap = on ? '' : g.key; },
    }, [el('span', { class: 'badge num' }, gapCount(g)), el('span', { class: 'gap-t' }, gapLabel(g))]);
  });
  const detail = picked ? el('div', { class: 'gap-detail', id: 'gap-detail', role: 'status' },
    picked.ids.length ? el('div', { class: 'small' }, idLinks(picked.ids, known)) : null,
    (picked.ev || []).length ? h('button', {
      type: 'button', class: 'btn', id: 'gap-to-evidence',
      onClick: () => { state.only = { label: gapLabel(picked), ids: [...picked.ev!] }; void show('evidence'); },
    }, `去证据表看这 ${picked.ev!.length} 条`) : el('div', { class: 'small mute' }, '这一条没有对应的证据。')) : null;
  return el('section', { class: 'panel grow2', id: 'other-gaps', 'aria-label': '缺口' },
    el('h2', null, '缺口 ', el('span', { class: 'aside' }, '· 点一条，一览表里亮出相关的')),
    lines.length ? el('div', { class: 'gaps' }, lines) : el('p', { class: 'empty-note' }, '数据里没有数出别的缺口。'), detail);
}

function entry(x: Entry) {
  return el('a', { class: 'entry', href: `#${x.id}`, 'data-ev': x.id, title: `${x.id} · ${x.status_label}` },
    el('span', { class: `dot s-${cls(x.status)}` }),
    el('span', { class: 'num v' + (x.flag ? ' warnword' : '') }, x.value),
    x.notes.length ? el('span', { class: 'small mute' }, x.notes.join(' · ')) : null,
    el('span', { class: 'vh' }, `${x.id}，${x.status_label}`));
}

function cell(c: Cell, lit: boolean, picking: boolean) {
  const klass = 'tcell' + (picking ? (lit ? ' lit' : ' dim') : '');
  if (!c.entries.length) {
    const text = ({ not_reported: '未报告', not_applicable: '不适用' } as Record<string, string>)[c.state] ?? '—';
    const why = ({ not_reported: '找过，原文没有写', not_applicable: '找过，这一项不适用' } as Record<string, string>)[c.state];
    return el('div', { class: klass, 'data-state': c.state, title: why || '还没有数据' }, el('span', { class: 'small mute' }, text));
  }
  const more = c.entries.length - MAX_LINES;
  return el('div', { class: klass, 'data-state': c.state, 'data-n': c.entries.length },
    c.entries.slice(0, MAX_LINES).map(entry),
    more > 0 ? el('a', { class: 'small', href: '#evidence' }, `另有 ${more} 条`) : null);
}

function table(t: GapsModel['table'], picked: Gap | undefined, names: Names) {
  const ev = new Set(picked?.ev || []);
  const src = new Set(picked?.src || []);
  const picking = !!picked;
  const head = el('div', { class: 'panel-head' }, el('h2', null, '一览'),
    el('span', { class: 'small mute' }, '不打分、不排名 · 条件不同的只并排，不比大小'));
  if (!t.rows.length || !t.cols.length) {
    const why = !t.rows.length ? '样品登记里还没有膜。' : '这些膜还没有任何一项指标的证据。';
    return el('section', { class: 'panel', id: 'summary-table', 'aria-label': '一览' }, head, el('p', { class: 'empty-note' }, why));
  }
  const grid: Kid[] = [el('span'), t.cols.map((g) => el('span', { class: 'colhead', title: names.enum('level', g.level) || NOT_FILLED }, g.label))];
  for (const r of t.rows) {
    const mem: Membrane = r.mem;
    const whole = mem.kind === 'lab' && src.has(mem.source_id);
    const lits = r.cells.map((c) => whole || c.entries.some((x) => ev.has(x.id)));
    const where = mem.kind === 'lab' ? mem.source_id : '商业产品';
    const roles = mem.roles.map((x) => names.enum('sample_role', x)).join('、');
    grid.push(el('div', { class: 'rowhead' + (picking && !lits.some(Boolean) ? ' dim' : ''), 'data-membrane': mem.key, title: facetText(mem) },
      el('span', { class: 'strong' }, mem.label), el('span', { class: 'small mute' }, [where, roles].filter(Boolean).join(' · '))));
    r.cells.forEach((c, i) => grid.push(cell(c, lits[i], picking)));
  }
  const foot: Kid[] = ['“—”是还没有数据；“未报告”是逐项找过、原文没有写。'];
  if (t.empty_core.length) foot.push(`核心指标里一条数据都还没有的：${t.empty_core.join('、')}。`);
  foot.push('专利、政策条款、报告里的数不进一览，见', el('a', { href: '#non-academic' }, '非学术来源'), '。');
  return el('section', { class: 'panel', id: 'summary-table', 'aria-label': '一览' }, head,
    el('div', { class: 'sumgrid', style: `grid-template-columns: minmax(120px, 180px) repeat(${t.cols.length}, minmax(140px, 1fr))` }, grid),
    el('p', { class: 'small mute', style: 'margin: 10px 0 0' }, foot));
}

function statements(items: Statement[], known: Set<string>) {
  const head = el('div', { class: 'panel-head' }, el('h2', null, '数据概览'),
    el('span', { class: 'small mute' }, '只说数量和范围，不评价 · 报告引用的要已复核'));
  if (!items.length) {
    return el('section', { class: 'panel', id: 'statements', 'aria-label': '数据概览' }, head, el('p', { class: 'empty-note' }, '这个题目还没有写数据概览。'));
  }
  const out = items.map((a) => el('div', { class: 'stmt', id: a.id, 'data-status': a.status },
    el('span', { class: a.status === 'reviewed' ? 'pill accent' : 'pill dashed' }, a.status_label),
    el('div', { class: 'stmt-body' },
      el('div', { class: 'stmt-text' }, a.statement),
      a.extra.map(([k, v]) => el('div', { class: 'small mute' }, `${k}：${v}`)),
      a.not_ready.length ? el('div', { class: 'small' }, el('span', { class: 'warnword' }, '依据里还没有到“专业已复核”的：'), idLinks(a.not_ready, known)) : null,
      el('div', { class: 'small mute' },
        el('span', { class: 'num' }, a.id), a.question ? ` · ${a.question}` : '', ' · 依据 ',
        a.basis.length ? a.basis.map((b, i) => [i ? '、' : '', b.href ? el('a', { href: b.href, class: 'num' }, b.id) : el('span', { class: 'num' }, b.id), ` ${b.note}`]) : '没有写',
        ' · ', a.who))));
  return el('section', { class: 'panel', id: 'statements', 'aria-label': '数据概览' }, head, out);
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
    return () => {
      const picked = model.gaps.find((g) => g.key === state.gap);
      return el('section', { class: state.view === 'gaps' ? 'view active' : 'view', id: 'gaps', 'aria-label': props.title },
        el('div', { class: 'topbar' }, el('div', { class: 'title' }, el('h1', null, props.title),
          el('span', { class: 'meta', id: 'gaps-count' }, model.count))),
        el('div', { class: 'row' }, searched(model), missing(model.missing), gapList(model.gaps, known)),
        table(model.table, picked, names),
        statements(model.statements, known),
        renderReviews(model.reviews, names),
        el('p', { class: 'small mute' }, '对外报告里的“数据概览”和“覆盖与缺口”两节，由这一页用的同一份数据生成。'));
    };
  },
});

/** 非学术来源页的缺口也用这个写法列 */
export function renderGapLines(items: Gap[], known: Set<string>): Kid[] {
  return items.map((g) => el('div', { class: 'gapline', 'data-gap': g.key },
    el('span', { class: 'badge num' + (g.key === 'not_verified' || g.key === 'jurisdiction' ? ' warn' : '') }, g.ids.length || '!'),
    el('span', null, g.text, idLinks(g.ids, known), g.ids.length ? '。' : '')));
}
