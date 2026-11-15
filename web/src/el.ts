/* 写页面用的小函数，照 tools/htmlgen.py 的 el()：页面各块和旧看板的写法一一对应，逐项对得上。
   - 文字一律当文字放进页面（Vue 本来就这样），不会被当成网页代码。
   - 属性值是 null、undefined 或 false 就不写这个属性；是 true 就只写属性名。
   - 子节点可以是文字、数、别的节点、views.json 里的 HTML 片段，或者它们排成的一串；空的跳过。
   - HTML 片段照白名单画：只认下面这些标签和属性，事件属性和样式属性一律不要，链接只认页面里的 # 和 http、https。 */
import { h, type VNode } from 'vue';
import { isHtml } from './data';
import type { HtmlNode } from './types';

export type Kid = VNode | string | number | null | undefined | false | Kid[] | { $html: Array<HtmlNode | string> };
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Attrs = Record<string, string | number | boolean | null | undefined | ((...args: any[]) => unknown)> | null;

export function flat(kids: Kid[], out: Array<VNode | string> = []): Array<VNode | string> {
  for (const k of kids) {
    if (k === null || k === undefined || k === false || k === '') continue;
    if (Array.isArray(k)) flat(k, out);
    else if (isHtml(k)) out.push(...k.$html.map(fragment));
    else if (typeof k === 'number') out.push(String(k));
    else out.push(k as VNode | string);
  }
  return out;
}

function props(attrs: Attrs): Record<string, unknown> | null {
  if (!attrs) return null;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    out[k] = v === true ? '' : typeof v === 'function' ? v : String(v);
  }
  return out;
}

export function el(tag: string, attrs: Attrs = null, ...kids: Kid[]): VNode {
  return h(tag, props(attrs), flat(kids));
}

// ---------------------------------------------------------------- HTML 片段

const TAGS = new Set([
  'a', 'span', 'div', 'strong', 'em', 'br',
  'svg', 'g', 'title', 'desc', 'circle', 'ellipse', 'rect', 'line', 'polyline', 'polygon', 'path', 'text', 'tspan', 'use',
  'symbol', 'defs',
]);

export function safeHref(v: string): string | null {
  if (/^#[^\s<>"'`]*$/.test(v)) return v;
  if (/^https?:\/\/[^\s<>"'`]+$/.test(v)) return v;
  return null;
}

function fragment(n: HtmlNode | string): VNode | string {
  if (typeof n === 'string') return n;
  if (!TAGS.has(n.t)) return ''; // 不认的标签不画，里面的字也不要
  const attrs: Record<string, string> = {};
  for (const [k, v] of Object.entries(n.a || {})) {
    const key = k.toLowerCase();
    if (key.startsWith('on') || key === 'style' || key === 'xmlns' || key.includes(':')) continue;
    if (key === 'href') {
      const ok = safeHref(v);
      if (ok) attrs.href = ok;
      continue;
    }
    attrs[k] = v;
  }
  return h(n.t, attrs, (n.c || []).map(fragment));
}
