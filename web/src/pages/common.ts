/* 几页共用的小块，照旧看板的同名函数（build_dashboard.py、compare_view.py、gaps_view.py）。 */
import { el, type Kid } from '../el';
import { NOT_FILLED, cls, type Names } from '../names';
import type { Review, Target } from '../types';

const TYPES = new Set([
  'experimental', 'company_claim', 'model_simulation', 'verified_fact', 'third_party_analysis', 'expert_judgment',
]);

/** 证据类型的记号：引用页面开头那一组形状（Sprite） */
export function mark(code: string) {
  const ref = TYPES.has(code) ? code : 'unknown';
  return el('svg', { class: 'mark', viewBox: '0 0 12 12', 'aria-hidden': 'true', focusable: 'false' },
    el('use', { href: `#m-${ref}` }));
}

/** 主文字下面的一行小字。前面留一个空格：复制、查找、读屏时，两段文字不会粘在一起 */
export function sub(text: Kid): Kid[] {
  return [' ', el('span', { class: 'sub' }, text)];
}

export function flagged(text: Kid, flag: boolean): Kid {
  return flag ? el('span', { class: 'missing' }, text) : text;
}

export function kv(pairs: Array<[Kid, Kid]>) {
  return el('dl', { class: 'kv' }, pairs.map(([k, v]) => [el('dt', null, k), el('dd', null, v)]));
}

export function block(name: Kid, ...content: Kid[]) {
  return el('div', { class: 'block' }, el('div', { class: 'block-name' }, name), content);
}

/** 一串编号：known 里有的做成跳转 */
export function idLinks(ids: string[], known: Set<string>): Kid[] {
  return ids.map((x, i) => [i ? '、' : '', known.has(x) ? el('a', { href: `#${x}` }, x) : x]);
}

function target(t: Target): Kid[] {
  return [t.href ? el('a', { href: t.href }, t.id) : t.id, ' ', el('span', { class: 'sub' }, t.what)];
}

/** 一张复核单（compare_view.render_review） */
export function renderReview(r: Review, names: Names) {
  const field = (key: string) => names.field('review', 'items', key);
  const decision = (code: string, label: string) => flagged(label, !['confirm', 'modify'].includes(code));
  const head = [
    `${names.field('review', 'status')}：${r.status_label}`,
    `${names.field('review', 'created_by')}：${r.created || NOT_FILLED}`,
    `${names.field('review', 'reviewer')}：${r.reviewed || '还没有复核'}`,
  ];
  const body: Kid[] = [
    el('div', { class: 'block-name' }, `复核单 ${r.id}　${r.title}`),
    el('div', { class: 'tags' }, head.map((x) => [el('span', null, x), ' '])),
  ];
  if (r.items.length) {
    const lines = r.items.map((it) => {
      const extra = [
        it.note ? [' ', el('span', { class: 'sub' }, `${field('note')}：${it.note}`)] : null,
        it.changes.length ? [' ', el('span', { class: 'sub' }, `${field('change_ids')}：${it.changes.join('、')}`)] : null,
      ];
      return el('tr', null, el('td', null, target(it.target)), el('td', null, it.reason), el('td', null, it.why),
        el('td', null, it.suggestion), el('td', null, decision(it.decision, it.decision_label), extra));
    });
    const heads = [names.field('review', 'items'), ...['reason', 'why', 'suggestion', 'decision'].map(field)];
    body.push(el('div', { class: 'table-wrap' }, el('table', { class: 'cmp-table' },
      el('thead', null, el('tr', null, heads.map((x) => el('th', { scope: 'col' }, x)))), el('tbody', null, lines))));
  }
  if (r.batch) {
    const b = r.batch;
    const ids = b.ids.map((t, i) => [i ? '、' : '', t.href ? el('a', { href: t.href }, t.id) : t.id,
      b.sampled.includes(t.id) ? '（抽看）' : '']);
    body.push(el('p', { class: 'note' }, `${names.field('review', 'batch')} ${b.ids.length} 条：`, ids, '｜',
      `${names.field('review', 'batch', 'decision')}：`, decision(b.decision, b.decision_label)));
  }
  if (r.notes) body.push(el('p', { class: 'note' }, `${names.field('review', 'notes')}：${r.notes}`));
  return el('div', { class: 'block review', id: r.id }, body);
}

/** 一列复核单（gaps_view.render_reviews） */
export function renderReviews(reviews: Review[], names: Names, title = '不属于任何可比组的复核单') {
  if (!reviews.length) return null;
  return el('section', { class: 'card', id: 'loose-reviews', 'aria-label': title }, el('h2', null, title),
    reviews.map((r) => renderReview(r, names)));
}

/** 一条横条：只表示数的大小（gaps_view.bar） */
export function bar(share: number, fmt: (x: number) => string) {
  const w = Math.max(0, Math.min(1, share)) * 100;
  return el('svg', { class: 'bar', viewBox: '0 0 100 8', preserveAspectRatio: 'none', 'aria-hidden': 'true', focusable: 'false' },
    el('rect', { class: 'bar-bg', width: '100', height: '8' }),
    el('rect', { class: 'bar-fill', width: fmt(round(w, 2)), height: '8' }));
}

/** Python 的 round(x, n)：照这个数在机器里的真实值舍入，恰好一半时取偶数。
    toFixed 写到 100 位就是机器里的真实值，用它看是不是恰好一半 */
export function round(x: number, n: number): number {
  if (!Number.isFinite(x) || Math.abs(x) >= 1e21) return x;
  const exact = Math.abs(x).toFixed(100);
  const cut = exact.indexOf('.') + 1 + n;
  if (/^50*$/.test(exact.slice(cut))) {
    const down = Number(exact.slice(0, cut));
    const last = Number(exact[cut - 1] === '.' ? exact[cut - 2] : exact[cut - 1]);
    const r = last % 2 === 0 ? down : down + 10 ** -n;
    return Math.sign(x) * Number(r.toFixed(n));
  }
  return Number(x.toFixed(n));
}

export { cls };
