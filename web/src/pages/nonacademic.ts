/* 非学术来源（K9），A 2.0 的样子（Yu 2026-11-15 看过样图，照建议做）。
   内容照旧由 tools/nonacademic_view.py 算好；每块有哪些来源类别、法域表哪几列必查、卡片最上面放哪三项，由 tools/site_views.py 的 nonacademic_extras 给。
   上面：四块用标签切换，一次看一块；块里左边是来源列表，右边是选中的那个来源。旁边是法域表，当前这一块的行亮出来，必查的法域没有来源时标出来。
   下面：对得上的（一头、关系、另一头，AI 推断、还没人确认的画成虚线），这四块缺什么，复核单。 */
import { defineComponent, h, type PropType } from 'vue';
import { el, type Kid } from '../el';
import { NOT_FILLED, fmtNum } from '../names';
import { state } from '../state';
import type { Block, DocCard, NaEvent, NonAcademicModel, Relation } from '../types';
import type { Ctx } from './evidence';
import { cls, renderReviews } from './common';
import { renderGapLines } from './gaps';

const INTRO: Record<string, string> = {
  patent: '同族算一件。法律状态照数据库的记录写，不作解读；不作侵权和自由实施的判断。专利实施例里的数和论文数据不进同一个可比组。',
  policy: '每份文件现在的状态照发布机构的记录写，写明在哪里、哪天查的。',
  market: '报告里的数不进可比组，按口径并排；不同报告给的数不一样时照实列出，不合并。条长只表示数的大小，口径不同的不能直接比。',
  grant: '按论文致谢里的项目号，到基金的项目库里查。',
};

/** 政策的进程：已经发生的实线实心，时间表上预计的虚线空心。按先后排，间距不表示时间长短；只画来源里写了的 */
function timeline(events: NaEvent[]) {
  if (!events.length) return null;
  const done = events.filter((e) => !e.expected).sort((a, b) => a.date.localeCompare(b.date));
  const all = [...done, ...events.filter((e) => e.expected)];
  return el('div', { class: 'na-time' }, el('div', { class: 'small mute', style: 'margin-bottom: 8px' }, '进程 · 按先后排，间距不表示时间长短'),
    el('ol', { class: 'tl', style: `grid-template-columns: repeat(${all.length}, minmax(0, 1fr))` }, all.map((e, i) => el('li', {
      class: e.expected ? 'ahead' : '', 'data-expected': e.expected ? 'yes' : 'no', title: e.where || null,
    },
      el('span', { class: 'tl-mark' + (i ? '' : ' first') + (all[i + 1]?.expected ? ' next-ahead' : '') + (i === all.length - 1 ? ' last' : '') }, el('i')),
      el('span', { class: 'tl-what' }, e.what.split('：').slice(1).join('：') || e.what, e.expected ? '（预计）' : ''),
      el('span', { class: 'tl-when num' }, e.date || NOT_FILLED)))));
}

function market(groups: NonAcademicModel['market'], ids: Set<string>) {
  if (!groups.length) return null;
  return el('div', { class: 'na-market' }, groups.map((g) => el('div', { 'data-measure': g.key },
    el('div', { class: 'small', style: 'font-weight: 600; margin-bottom: 4px' }, g.name),
    g.items.map((x) => {
      const share = g.scale && x.number !== null ? Math.max(0, Math.min(1, x.number / g.scale)) : null;
      return el('div', { class: 'hbar', 'data-ev': x.id, title: [x.basis, x.locator, x.type_label, ...x.flags].filter(Boolean).join(' · ') },
        el('span', { class: 'hbar-l' }, x.source.split('｜')[0], ' ', el('span', { class: 'small mute' }, x.basis)),
        share !== null ? el('span', { class: 'hbar-t' }, el('span', { class: 'on', style: `width: ${Math.round(share * 1000) / 10}%` })) : el('span'),
        el('span', { class: 'hbar-n' }, el('span', { class: 'num' }, x.value), ' ',
          ids.has(x.id) ? el('a', { href: `#${x.id}`, class: 'num small' }, x.id) : el('span', { class: 'num small' }, x.id)));
    }))));
}

function evLine(x: DocCard['evidence'][number], ids: Set<string>) {
  const what = [x.sample, x.measure].filter(Boolean).join(' · ');
  const tail = [x.conds, x.type_label, ...x.flags, x.locator].filter(Boolean).join(' · ');
  return el('div', { class: 'na-ev', 'data-ev': x.id },
    el('span', { class: `dot s-${cls(x.status)}`, title: x.status_label }),
    el('div', { class: 'grow' }, el('div', null, el('span', { class: 'mute' }, what, '：'), x.value),
      el('div', { class: 'small mute' }, tail ? tail + ' · ' : '', x.status_label)),
    ids.has(x.id) ? el('a', { href: `#${x.id}`, class: 'num small' }, x.id) : el('span', { class: 'num small' }, x.id));
}

function relLine(r: Relation) {
  const [a, kind, b] = r.ends || [r.what, '', ''];
  return el('div', { class: 'rel2', id: r.id, 'data-inferred': r.inferred ? 'yes' : 'no' },
    el('div', { class: 'rel-ends' },
      el('span', { class: 'node' }, a),
      el('span', { class: 'edge' + (r.inferred ? ' inferred' : '') }, el('span', null, kind)),
      el('span', { class: 'node' }, b)),
    el('div', { class: 'small mute' }, el('span', { class: 'num' }, r.id), ' · ', r.from, ' ',
      el('span', { class: r.inferred ? 'pill amber' : 'pill accent' }, r.how), ' ',
      el('span', { class: `dot s-${cls(r.status)}`, style: 'vertical-align: -1px' }), ' ', r.status_label));
}

function sourceDetail(c: DocCard, ids: Set<string>) {
  const line = c.pairs.find(([k]) => k === '题名')?.[1] || c.pairs.find(([k]) => /发布机关|作者|资助机构/.test(k))?.[1] || '';
  const check = c.verified
    ? el('div', { class: 'small mute' }, `登记内容人工核对：${c.verified}`)
    : c.needs_verify ? el('div', { class: 'small warnword' }, '登记内容还没有人工核对') : null;
  return el('div', { class: 'na-detail', id: c.id, 'data-kind': c.kind },
    el('div', { class: 'na-head' },
      el('div', null, el('div', { class: 'num small mute' }, c.id), el('div', { class: 'na-title' }, c.head),
        line && line !== c.head ? el('div', { class: 'small', style: 'color: var(--sub)' }, line) : null),
      c.chip ? el('span', { class: 'pill accent' }, c.chip) : null),
    c.facts.length ? el('div', { class: 'facts' }, c.facts.map(([k, v]) => el('div', null, el('div', { class: 'small mute' }, k), el('div', { class: 'fv' }, v)))) : null,
    el('div', null, c.evidence.length ? c.evidence.map((x) => evLine(x, ids)) : el('p', { class: 'empty-note' }, '这个来源还没有录证据。')),
    timeline(c.events),
    c.relations.length ? el('div', null, el('div', { class: 'small mute', style: 'margin: 8px 0 4px' }, '对得上的'), c.relations.map(relLine)) : null,
    el('details', null, el('summary', { class: 'small mute' }, `全部登记项目 ${c.pairs.length} 项`), el('dl', { class: 'kvs', style: 'margin-top: 6px; grid-template-columns: minmax(96px, 30%) minmax(0, 1fr)' }, c.pairs.map(([k, v]) => [el('dt', null, k), el('dd', null, v)]))),
    check);
}

function blockPanel(b: Block, model: NonAcademicModel, ids: Set<string>) {
  const sel = b.cards.find((c) => c.id === state.naSource) || b.cards[0];
  const list = b.cards.length > 1 ? el('div', { class: 'na-list', role: 'group', 'aria-label': `${b.title}的来源` },
    b.cards.map((c) => h('button', {
      type: 'button', class: 'na-item', 'aria-pressed': c === sel ? 'true' : 'false', 'data-source': c.id,
      onClick: () => { state.naSource = c.id; },
    }, [el('span', { class: 'num small mute' }, c.id), el('span', { class: 'na-item-t' }, c.head), c.chip ? el('span', { class: 'small mute' }, c.chip) : null]))) : null;
  return el('section', { class: 'panel grow3', id: `block-${b.key}`, 'aria-label': b.title },
    el('div', { class: 'small mute', style: 'margin-bottom: 10px' }, INTRO[b.key] || ''),
    b.key === 'market' ? market(model.market, ids) : null,
    b.key === 'grant' && model.papers ? el('div', { class: 'small', style: 'margin-bottom: 8px' },
      `${model.papers} 个论文类的来源里，查到资助项目记录的是 ${model.papers_funded} 个。`) : null,
    b.cards.length
      ? el('div', { class: 'na-body' }, list, sel ? sourceDetail(sel, ids) : null)
      : el('p', { class: 'empty-note' }, '这一批里还没有来源。'));
}

function jurisdictions(model: NonAcademicModel) {
  if (!model.matrix.length) {
    return el('section', { class: 'panel grow2', id: 'by-jurisdiction', 'aria-label': '法域' }, el('h2', null, '法域'),
      el('p', { class: 'empty-note' }, '这一批里还没有非学术来源。'));
  }
  const missing = model.cols.filter((_, i) => model.cols_need[i] && model.cols_empty[i]);
  const grid: Kid[] = [el('span'), model.cols.map((c, i) => el('span', {
    class: 'jcol small' + (model.cols_need[i] && model.cols_empty[i] ? ' warnword' : ' mute'),
    title: model.cols_need[i] ? '必查' : '有来源才列',
  }, c, model.cols_need[i] ? '' : '*'))];
  for (const r of model.matrix) {
    const on = r.block === state.naBlock;
    grid.push(el('span', { class: 'jrow small' + (on ? ' on' : '') }, r.type));
    r.cells.forEach((n, i) => grid.push(el('span', { class: 'jcell', 'aria-label': `${r.type}，${model.cols[i]}：${n} 个来源` },
      n ? el('span', { class: 'jdot num' + (on ? ' on' : '') }, n) : el('span', { class: 'jnone' + (model.cols_need[i] ? ' need' : '') }))));
  }
  return el('section', { class: 'panel grow2', id: 'by-jurisdiction', 'aria-label': '法域' },
    el('h2', null, '法域 ', el('span', { class: 'aside' }, '· 每一类有几个来源')),
    el('div', { class: 'jgrid', id: 'jurisdictions', style: `grid-template-columns: minmax(84px, 120px) repeat(${model.cols.length}, minmax(0, 1fr))` }, grid),
    missing.length ? el('div', { class: 'small warnword', style: 'margin-top: 10px' }, `${missing.join('、')}还没有来源`) : null,
    model.cols_need.some((x) => !x) ? el('div', { class: 'small mute', style: 'margin-top: 4px' }, '带 * 的不是必查的法域，有来源才列。') : null);
}

function statusStrip(model: NonAcademicModel) {
  const total = model.evidence_total;
  const checks = model.checks;
  const checked = checks.length
    ? `状态查于 ${checks[0][0]}` + (checks[checks.length - 1][0] !== checks[0][0] ? ` 至 ${checks[checks.length - 1][0]}` : '') + '，出报告前再查一次'
    : '';
  return el('div', { class: 'small mute', id: 'na-status' },
    `${total} 条证据：`, model.by_status.map(([label, n], i) => [i ? '，' : '', `${label} ${fmtNum(n)}`]), total ? '' : '还没有', checked ? ` · ${checked}` : '');
}

export const NonAcademicView = defineComponent({
  props: {
    ctx: { type: Object as PropType<Ctx>, required: true },
    name: { type: String, required: true },
    title: { type: String, required: true },
    question: { type: String, required: true },
  },
  setup(props) {
    const { view, names, ids } = props.ctx;
    const model = view.nonacademic!;
    const gapKnown = new Set([...ids, ...model.source_ids]);
    return () => {
      const cur = model.blocks.find((b) => b.key === state.naBlock) || model.blocks[0];
      const sources = model.blocks.reduce((n, b) => n + b.n, 0);
      const tabs = el('div', { class: 'seg', role: 'tablist', 'aria-label': '四块' }, model.blocks.map((b) => h('button', {
        type: 'button', role: 'tab', 'aria-selected': b === cur ? 'true' : 'false', 'data-block': b.key, title: b.sub || null,
        onClick: () => { state.naBlock = b.key; state.naSource = b.cards[0]?.id || ''; },
      }, [b.title, ' ', el('span', { class: 'num' }, b.n)])));
      return el('section', { class: state.view === 'non-academic' ? 'view active' : 'view', id: 'non-academic', 'aria-label': props.title },
        el('div', { class: 'topbar' }, el('div', { class: 'title' }, el('h1', null, props.title),
          el('span', { class: 'meta' }, `${sources} 个来源 · ${model.evidence_total} 条证据`)), tabs),
        statusStrip(model),
        el('div', { class: 'row' }, cur ? blockPanel(cur, model, ids) : null, jurisdictions(model)),
        el('div', { class: 'row' },
          el('section', { class: 'panel grow3', id: 'na-relations', 'aria-label': '对得上的' },
            el('h2', null, '对得上的 ', el('span', { class: 'aside' }, '· 虚线是 AI 推断、还没人确认，确认过才进报告')),
            model.relations.length ? model.relations.map(relLine) : el('p', { class: 'empty-note' }, '还没有记到和这四块有关的关系。')),
          el('section', { class: 'panel grow2', id: 'na-gaps', 'aria-label': '这四块缺什么' }, el('h2', null, '缺什么'),
            model.gaps.length ? renderGapLines(model.gaps, gapKnown) : el('p', { class: 'empty-note' }, '数据里没有数出缺口。'),
            el('div', { class: 'small mute', style: 'margin-top: 8px' }, '查了哪里、怎么查的，见', el('a', { href: '#gaps' }, '数据概览与缺口'), '。'))),
        renderReviews(model.reviews, names, '非学术来源的复核单'),
        el('p', { class: 'small mute' }, '这些数不和论文数据放进同一个可比组；只整理和描述，不作评价。对外报告第 4.2 至 4.5 节由同一份数据生成。原文片段和出处，到',
          el('a', { href: '#evidence' }, '证据表'), '里按来源类别筛。'));
    };
  },
});
