/* 查找面板（⌘K / Ctrl+K，或按 /）：一个框找页面、证据、可比组、来源、数据概览的陈述。参考 Linear 的命令面板。
   只在页面已有的数据里找，不发请求。回车或点一条就跳过去。 */
import { defineComponent, h, nextTick, ref, watch, type PropType } from 'vue';
import { el } from './el';
import { setFilter, clearFilters, show, state } from './state';
import type { Ctx } from './pages/evidence';

interface Item {
  kind: string;
  what: string;
  id: string;
  text: string;
  go: () => void;
}

function index(ctx: Ctx, pages: Array<{ key: string; title: string }>): Item[] {
  const v = ctx.view;
  const out: Item[] = pages.map((p) => ({ kind: '页面', what: p.title, id: '', text: p.title, go: () => void show(p.key) }));
  for (const r of v.rows) {
    const what = [r.sample || r.subject, r.measure, r.value].filter(Boolean).join(' · ');
    out.push({ kind: '证据', what, id: r.id, text: [r.id, r.subject, r.sample, r.measure, r.value, r.source_id, r.source_title].join(' '), go: () => void show(r.id) });
  }
  for (const lv of v.compare?.levels || []) {
    for (const g of lv.groups) out.push({ kind: '可比组', what: g.title, id: g.id, text: `${g.id} ${g.title} ${g.tier_label}`, go: () => void show(g.id) });
  }
  const sources = new Map<string, string>();
  for (const r of v.rows) if (r.source_id && !sources.has(r.source_id)) sources.set(r.source_id, r.source_title);
  for (const [sid, title] of sources) {
    out.push({ kind: '来源', what: title || sid, id: sid, text: `${sid} ${title}`, go: () => { clearFilters(); setFilter('source', sid); void show('evidence'); } });
  }
  for (const a of v.gaps?.statements || []) out.push({ kind: '陈述', what: a.statement, id: a.id, text: `${a.id} ${a.statement}`, go: () => void show(a.id) });
  return out;
}

export const Palette = defineComponent({
  props: {
    ctx: { type: Object as PropType<Ctx>, required: true },
    pages: { type: Array as PropType<Array<{ key: string; title: string }>>, required: true },
  },
  setup(props) {
    const items = index(props.ctx, props.pages);
    const q = ref('');
    const at = ref(0);
    const input = ref<HTMLInputElement | null>(null);
    let opener: Element | null = null;
    watch(() => state.palette, async (open) => {
      if (open) {
        opener = document.activeElement;
        q.value = '';
        at.value = 0;
        await nextTick();
        input.value?.focus();
      } else if (opener instanceof HTMLElement) {
        opener.focus();
      }
    });
    const found = () => {
      const terms = q.value.toLowerCase().split(/\s+/).filter(Boolean);
      const hits = terms.length ? items.filter((it) => terms.every((t) => it.text.toLowerCase().includes(t))) : items.filter((it) => it.kind === '页面');
      return hits.slice(0, 30);
    };
    function pick(it: Item) {
      state.palette = false;
      it.go();
    }
    return () => {
      if (!state.palette) return null;
      const hits = found();
      if (at.value >= hits.length) at.value = Math.max(0, hits.length - 1);
      return el('div', { class: 'overlay', onClick: (e: Event) => { if (e.target === e.currentTarget) state.palette = false; } },
        el('div', { class: 'dialog', role: 'dialog', 'aria-modal': 'true', 'aria-label': '查找' },
          el('div', { class: 'inputrow' },
            el('label', { class: 'vh', for: 'palette-q' }, '查找'),
            h('input', {
              id: 'palette-q', ref: input, type: 'search', autocomplete: 'off', placeholder: '编号、膜、指标、来源…', value: q.value,
              role: 'combobox', 'aria-expanded': 'true', 'aria-controls': 'palette-list',
              onInput: (e: Event) => { q.value = (e.target as HTMLInputElement).value; at.value = 0; },
              onKeydown: (e: KeyboardEvent) => {
                if (e.key === 'ArrowDown') { e.preventDefault(); at.value = Math.min(at.value + 1, hits.length - 1); }
                else if (e.key === 'ArrowUp') { e.preventDefault(); at.value = Math.max(at.value - 1, 0); }
                else if (e.key === 'Enter' && hits[at.value]) { e.preventDefault(); pick(hits[at.value]); }
              },
            }),
            h('button', { type: 'button', class: 'btn', onClick: () => { state.palette = false; } }, 'Esc')),
          hits.length
            ? el('ul', { id: 'palette-list', role: 'listbox' }, hits.map((it, i) => el('li', null,
              h('a', { href: it.id ? `#${it.id}` : `#${''}`, role: 'option', 'aria-selected': i === at.value ? 'true' : 'false',
                onClick: (e: Event) => { e.preventDefault(); e.stopPropagation(); pick(it); },
                onMouseenter: () => { at.value = i; } },
              [el('span', { class: 'kind' }, it.kind), el('span', { class: 'what' }, it.what), el('span', { class: 'id' }, it.id)]))))
            : el('div', { class: 'none' }, '没有找到。'),
          el('div', { class: 'foot' }, '↑↓ 选 · 回车 跳过去 · Esc 关')));
    };
  },
});
