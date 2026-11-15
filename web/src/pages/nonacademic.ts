/* 非学术来源（K9），照 tools/nonacademic_view.py 的 render 和它用到的几块。 */
import { defineComponent, type PropType } from 'vue';
import { el, type Kid } from '../el';
import { NOT_FILLED, fmtNum } from '../names';
import { state } from '../state';
import type { Block, DocCard, NonAcademicModel } from '../types';
import type { Ctx } from './evidence';
import { bar, cls, idLinks, kv, renderReviews } from './common';
import { renderGapLines } from './gaps';

function statusSpan(code: string, label: string) {
  return el('span', { class: `status s-${cls(code)}` }, label);
}

function renderCard(c: DocCard) {
  const lines = c.evidence.map((x) => {
    const what = [x.sample, x.measure].filter(Boolean).join('｜');
    const tail = [x.conds, x.type_label, ...x.flags, x.locator].filter(Boolean).join('｜');
    return el('li', { 'data-ev': x.id }, el('span', { class: 'strong' }, what, '：', x.value), ' ',
      el('span', { class: 'sub' }, tail ? tail + '｜' : '', el('a', { href: `#${x.id}` }, x.id), '｜', x.status_label));
  });
  const relLines = c.relations.map((r) => el('li', null, r.what, ' ', el('span', { class: 'sub' }, `${r.id}｜${r.how}｜${r.status_label}`)));
  const check = c.verified
    ? el('div', { class: 'sub' }, `登记内容人工核对：${c.verified}`)
    : c.needs_verify ? el('div', { class: 'sub' }, el('span', { class: 'missing' }, '登记内容还没有人工核对')) : null;
  return el('div', { class: 'doc-card', id: c.id, 'data-kind': c.kind },
    el('div', { class: 'doc-head' }, el('span', { class: 'strong' }, c.head), ' ',
      c.chip ? el('span', { class: 'chip-static' }, c.chip) : null, ' ', el('span', { class: 'sub' }, c.id)),
    kv(c.pairs),
    el('div', { class: 'block' }, el('div', { class: 'block-name' }, '证据'),
      lines.length ? el('ul', { class: 'plain' }, lines) : el('div', { class: 'note' }, '这个来源还没有录证据。')),
    relLines.length ? el('div', { class: 'block' }, el('div', { class: 'block-name' }, '对得上的'), el('ul', { class: 'plain' }, relLines)) : null,
    check);
}

function blockSection(b: Block, intro: string, extra: Kid[], note: string | null) {
  const cards = b.cards.map(renderCard);
  return el('section', { class: 'card', id: `block-${b.key}`, 'aria-label': b.title },
    el('div', { class: 'view-head' }, el('h2', null, b.title)), el('p', { class: 'note' }, intro),
    cards.length ? el('div', { class: 'doc-cards' }, cards) : el('p', { class: 'empty' }, '这一批里还没有来源。'),
    extra, note ? el('p', { class: 'note' }, note) : null);
}

function renderMarket(groups: NonAcademicModel['market'], waiting: string[], known: Set<string>): Kid[] {
  const out: Kid[] = groups.map((g) => {
    const rows = g.items.map((x) => {
      const share = g.scale && x.number !== null ? x.number / g.scale : null;
      const tail = [x.basis, x.locator, x.type_label, ...x.flags].filter(Boolean).join('｜');
      return el('div', { class: 'meter', 'data-ev': x.id },
        el('div', { class: 'line' }, el('span', null, x.source), ' ', el('span', { class: 'strong' }, x.value)),
        share !== null ? bar(share, fmtNum) : null,
        el('div', { class: 'sub' }, tail ? tail + '｜' : '', el('a', { href: `#${x.id}` }, x.id), '｜', x.status_label));
    });
    return el('div', { class: 'block', 'data-measure': g.key }, el('h3', null, g.name), el('div', { class: 'lines' }, rows));
  });
  if (waiting.length) {
    out.push(el('p', { class: 'banner-soft' }, `还没有人工核对、不进报告的 ${waiting.length} 条：`, idLinks(waiting, known), '。'));
  }
  return out;
}

function renderEvents(events: NonAcademicModel['events']) {
  if (!events.length) return null;
  const items = events.map((e) => el('li', { class: 'event' + (e.expected ? ' expected' : ''), 'data-source': e.source },
    el('span', { class: 'strong' }, (e.date || NOT_FILLED) + (e.expected ? '，预计' : '')), ' ', e.what,
    e.where ? [' ', el('span', { class: 'sub' }, e.where)] : null));
  return el('div', { class: 'block', id: 'policy-events' }, el('h3', null, '事项'), el('ol', { class: 'events' }, items),
    el('div', { class: 'note' }, '新的在前。带“预计”的是时间表上写的，还没有发生。'));
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
    const known = ids;
    const b = Object.fromEntries(model.blocks.map((x) => [x.key, x])) as Record<string, Block>;
    const tiles = model.blocks.map((x) => el('div', { class: 'tile', 'data-tile': x.key }, el('div', { class: 'tile-name' }, x.title),
      el('div', { class: 'tile-n' }, `${x.n} ${x.unit}`), el('div', { class: 'tile-sub' }, x.sub),
      el('div', { class: 'tile-sub' }, `证据 ${x.evidence.length} 条`)));
    const status = model.by_status.map(([label, n]) => `${label} ${n} 条`).join('，');
    const checks = model.checks;
    const checked = checks.length
      ? `状态查的日期：${checks[0][0]}` + (checks[checks.length - 1][0] !== checks[0][0] ? ` 至 ${checks[checks.length - 1][0]}` : '') + '；每次出报告前再查一次。'
      : '';
    const head = el('section', { class: 'card' },
      el('div', { class: 'view-head' }, el('h2', null, props.title), el('div', { class: 'note' }, props.question)),
      el('p', { class: 'note' }, '这些数不和论文数据放进同一个可比组；只整理和描述，不作评价。和对外报告第 4.2 至 4.5 节是同一份数据。'),
      el('div', { class: 'tiles' }, tiles),
      el('p', { class: 'note', id: 'na-status' }, `${model.evidence_total} 条证据：${status || '还没有'}。`, checked));
    const matrix = model.matrix.length
      ? el('div', { class: 'table-wrap' }, el('table', { class: 'cmp-table matrix', id: 'jurisdictions' },
        el('thead', null, el('tr', null, el('th', { scope: 'col' }, '类别'), model.cols.map((j) => el('th', { scope: 'col' }, j)))),
        el('tbody', null, model.matrix.map((r) => el('tr', null, el('th', { scope: 'row' }, r.type),
          r.cells.map((n) => el('td', null, n ? n : el('span', { class: 'muted' }, '—'))))))))
      : el('p', { class: 'empty' }, '这一批里还没有非学术来源。');
    const juris = el('section', { class: 'card', id: 'by-jurisdiction', 'aria-label': '按法域' }, el('h2', null, '按法域：每一类有几个来源'),
      el('p', { class: 'note' }, '数的是纳入的来源，不是证据。“—”是这一格还没有来源。'), matrix);
    const grantsNote = model.papers ? `${model.papers} 个论文类的来源里，查到资助项目记录的是 ${model.papers_funded} 个。` : null;
    const relRows = model.relations.map((r) => el('div', { class: 'rel', id: r.id, 'data-inferred': r.inferred ? 'yes' : 'no' },
      el('span', { class: 'strong' }, r.id), ' ', el('span', { class: 'rel-what' }, r.what), ' ',
      el('span', { class: 'sub' }, r.from), ' ',
      el('span', { class: 'chip-static' + (r.inferred ? ' dashed' : '') }, r.how), ' ', statusSpan(r.status, r.status_label)));
    const relations = el('section', { class: 'card', id: 'na-relations', 'aria-label': '和论文、企业对得上的' }, el('h2', null, '和论文、企业对得上的'),
      el('p', { class: 'note' }, '每条关系都有出处。“推断”是按出处推出来的，要人确认过才进报告。原文没有写、建立不了的对应，数据里不记。'),
      relRows.length ? el('div', { class: 'rels' }, relRows) : el('p', { class: 'empty' }, '还没有记到和这四块有关的关系。'));
    const gapKnown = new Set([...known, ...model.source_ids]);
    const gaps = el('section', { class: 'card', id: 'na-gaps', 'aria-label': '这四块缺什么' }, el('h2', null, '这四块缺什么'),
      model.gaps.length ? el('div', { class: 'lines' }, renderGapLines(model.gaps, gapKnown)) : el('p', { class: 'empty' }, '数据里没有数出缺口。'),
      el('p', { class: 'note' }, '查了哪里、怎么查的，在', el('a', { href: '#gaps' }, '数据概览与缺口'), '的“查了什么，读到多少”里。'));
    const market = renderMarket(model.market, model.market_waiting, known);
    const body = [head, juris,
      blockSection(b.patent, '同族算一件。法律状态照数据库的记录写，不作解读；不作侵权和自由实施的判断。', [],
        '专利实施例里的数标“专利实施例，未经同行评议”，和论文数据不进同一个可比组。'),
      blockSection(b.policy, '每份文件现在的状态照发布机构的记录写，写明在哪里、哪天查的。', [renderEvents(model.events)], null),
      el('section', { class: 'card', id: 'block-market', 'aria-label': b.market.title },
        el('div', { class: 'view-head' }, el('h2', null, b.market.title)),
        el('p', { class: 'note' }, '报告里的数不进可比组，按口径并排。不同报告对同一件事给的数不一样时照实列出，不合并成一个数。条长只表示数的大小，不表示好坏；口径不同的数不能直接比。'),
        market.length ? market : el('p', { class: 'empty' }, '这一批里还没有报告里的数。'),
        b.market.cards.length ? el('div', { class: 'doc-cards' }, b.market.cards.map(renderCard)) : null),
      blockSection(b.grant, '按论文致谢里的项目号，到基金的项目库里查。', [], grantsNote),
      relations, renderReviews(model.reviews, names, '非学术来源的复核单'), gaps,
      el('p', { class: 'note' }, '对外报告第 4.2 至 4.5 节、第 5 节里的关系和第 7 节里这四块的缺口，由这一页用的同一份数据生成。原文片段和出处，到',
        el('a', { href: '#evidence' }, '证据表'), '里按来源类别筛。')];
    return () => el('section', { class: state.view === 'non-academic' ? 'view active' : 'view', id: 'non-academic', 'aria-label': props.title }, body);
  },
});
