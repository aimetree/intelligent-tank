/* 整页（A 2.0）：左边一条图标侧栏（五页、图例、深浅色）；上面一行是题目、截至日期和数据版本、查找；页面顶上的提示；五页。
   哪一页画的时候出了错，那一页写明生成不了，别的页面照样出，原因写在页面顶上。 */
import { defineComponent, h, onErrorCaptured, reactive, type Component, type PropType } from 'vue';
import { el, type Kid } from './el';
import { Names } from './names';
import { setTheme, state } from './state';
import type { SiteData, TopicView } from './types';
import { CompareView } from './pages/compare';
import { EvidenceView, type Ctx } from './pages/evidence';
import { GapsView } from './pages/gaps';
import { NonAcademicView } from './pages/nonacademic';
import { OverviewView } from './pages/overview';
import { mark } from './pages/common';
import { Palette } from './palette';

const PAGES: Record<string, { component: Component; model: keyof TopicView | null; icon: string }> = {
  overview: { component: OverviewView, model: 'overview', icon: 'M3 3h5v5H3zM10 3h5v5h-5zM3 10h5v5H3zM10 10h5v5h-5z' },
  evidence: { component: EvidenceView, model: null, icon: 'M3 4h12M3 9h12M3 14h8' },
  compare: { component: CompareView, model: 'compare', icon: 'M4 15V8M9 15V3M14 15v-5' },
  gaps: { component: GapsView, model: 'gaps', icon: 'M9 3a6 6 0 1 0 6 6M9 3v6h6' },
  'non-academic': { component: NonAcademicView, model: 'nonacademic', icon: 'M5 2.5h6l3 3v10H5zM11 2.5v3h3' },
};

function icon(d: string) {
  return el('svg', { viewBox: '0 0 18 18', 'aria-hidden': 'true', focusable: 'false' },
    el('path', { d, fill: 'none', stroke: 'currentColor', 'stroke-width': '1.5', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }));
}

function failedView(name: string, title: string) {
  return el('section', { class: state.view === name ? 'view active' : 'view', id: name, 'aria-label': title },
    el('div', { class: 'panel' }, el('h2', null, title), el('p', { class: 'warnword' }, '这一页生成不了，原因列在页面顶上。')));
}

const Page = defineComponent({
  props: {
    name: { type: String, required: true },
    title: { type: String, required: true },
    question: { type: String, required: true },
    ctx: { type: Object as PropType<Ctx>, required: true },
    onFail: { type: Function as PropType<(title: string, err: string) => void>, required: true },
  },
  setup(props) {
    const s = reactive({ failed: false });
    onErrorCaptured((err) => {
      s.failed = true;
      props.onFail(props.title, `${(err as Error)?.name || 'Error'}: ${(err as Error)?.message || String(err)}`);
      return false;
    });
    return () => {
      const page = PAGES[props.name];
      if (s.failed || (page.model && !props.ctx.view[page.model])) return failedView(props.name, props.title);
      return h(page.component, { ctx: props.ctx, name: props.name, title: props.title, question: props.question });
    };
  },
});

export const App = defineComponent({
  props: { data: { type: Object as PropType<SiteData>, required: true } },
  setup(props) {
    const { views } = props.data;
    const view = views.topics[0];
    const names = new Names(props.data.labels, views.fields);
    const ctx: Ctx = { view, names, ids: new Set(view.rows.map((r) => r.id)), groupIds: new Set(view.compare?.group_ids || []) };
    const failed = reactive<Array<[string, string]>>([]);
    const onFail = (title: string, err: string) => failed.push([title, err]);
    document.title = `${view.title}｜对内看板`;
    const pages = views.views.map((v) => ({ key: v.key, title: v.title }));

    function banners(): Kid[] {
      const out: Kid[] = [];
      if (view.notice) out.push(el('div', { class: 'banner', id: 'notice' }, view.notice));
      const problems = [
        ...view.issues.map(([rule, record, msg]) => `${rule}　${record}：${msg}`),
        ...[...view.errors, ...failed].map(([id, err]) => `${id}：显示不出来（${err}）`),
      ];
      if (problems.length) {
        const shown = problems.slice(0, 50);
        out.push(el('div', { class: 'banner', id: 'problems', role: 'status' }, el('details', null,
          el('summary', null, `这份数据有 ${problems.length} 处没通过校验。页面照样生成了，没通过的地方可能显示不全。点开看是哪几处`),
          el('ul', null, shown.map((p) => el('li', null, p)),
            problems.length > shown.length ? el('li', null, `其余 ${problems.length - shown.length} 处见 python3 tools/validate.py 的输出`) : null))));
      }
      return out;
    }

    function legend() {
      if (!state.legend) return null;
      const L = views.legend;
      return el('div', { class: 'overlay', onClick: (e: Event) => { if (e.target === e.currentTarget) state.legend = false; } },
        el('div', { class: 'dialog', role: 'dialog', 'aria-modal': 'true', 'aria-label': '图例', id: 'legend' },
          el('div', { class: 'inputrow' }, el('strong', { style: 'flex: 1 1 auto' }, '图例'),
            h('button', { type: 'button', class: 'btn', onClick: () => { state.legend = false; } }, '关')),
          el('div', { class: 'legend-dialog' },
            el('div', null, el('h3', null, '核验状态'), L.statuses.map((x) => el('div', { class: 'item' }, el('span', { class: `dot s-${x.cls}` }), x.label))),
            el('div', null, el('h3', null, '证据类型 · 不分高低'), L.types.map((t) => el('div', { class: 'item' }, mark(t.code), t.label))),
            el('div', null, el('h3', null, '可比档'), L.tiers.map((t) => el('div', { class: 'item' }, t.text))),
            el('div', null, el('h3', null, '风险档 · 人工核对之前标好'), L.risks.map((r) => el('div', { class: 'item' }, el('span', { class: `pill${r.code === 'high' ? ' amber' : ''}` }, r.label), r.text))))));
    }

    const sprite = el('div', { hidden: true }, views.sprite); // 证据类型的六个形状，页面各处用 <use> 引用
    return () => el('div', { class: 'shell' }, sprite,
      el('nav', { class: 'rail', 'aria-label': '页面' },
        el('div', { class: 'logo', 'aria-hidden': 'true' }, el('svg', { width: 14, height: 14, viewBox: '0 0 16 16' },
          el('rect', { x: 2, y: 8, width: 2.4, height: 6, fill: 'currentColor' }), el('rect', { x: 6.8, y: 4, width: 2.4, height: 10, fill: 'currentColor' }),
          el('rect', { x: 11.6, y: 6, width: 2.4, height: 8, fill: 'currentColor' }))),
        views.views.map((v) => el('a', { href: `#${v.key}`, 'data-view': v.key, title: v.title, 'aria-label': v.title, 'aria-current': state.view === v.key ? 'page' : null }, icon(PAGES[v.key].icon))),
        el('span', { class: 'grow' }),
        h('button', { type: 'button', title: '图例', 'aria-label': '图例', id: 'legend-open', onClick: () => { state.legend = true; } },
          [icon('M9 2.5a6.5 6.5 0 1 0 0 13a6.5 6.5 0 0 0 0-13zM9 8v4.5M9 5.5v.2')]),
        h('button', { type: 'button', title: state.theme === 'dark' ? '换成浅色' : '换成深色', 'aria-label': state.theme === 'dark' ? '换成浅色' : '换成深色', id: 'theme-toggle',
          onClick: () => setTheme(state.theme === 'dark' ? 'light' : 'dark') },
        [icon(state.theme === 'dark' ? 'M9 1.5v2M9 14.5v2M1.5 9h2M14.5 9h2M3.7 3.7l1.4 1.4M12.9 12.9l1.4 1.4M3.7 14.3l1.4-1.4M12.9 5.1l1.4-1.4M9 5.5a3.5 3.5 0 1 0 0 7a3.5 3.5 0 0 0 0-7z'
          : 'M14 10.5A6 6 0 1 1 7.5 4a5 5 0 0 0 6.5 6.5z')])),
      el('div', { class: 'content' },
        el('header', { class: 'topbar', style: 'margin-bottom: 12px' },
          el('div', { class: 'title' }, el('span', { style: 'font-weight: 600' }, view.title), el('span', { class: 'meta', id: 'stamp' }, view.stamp)),
          h('button', { type: 'button', class: 'find', id: 'find-open', onClick: () => { state.palette = true; } },
            [icon('M8 3.5a4.5 4.5 0 1 0 0 9a4.5 4.5 0 0 0 0-9zM11.5 11.5L15 15'), el('span', { class: 'grow' }, '查找'), el('span', { class: 'key' }, '⌘K')])),
        el('div', { class: 'banners' }, banners()),
        el('main', null, views.views.map((v) => h(Page, { key: v.key, name: v.key, title: v.title, question: v.question, ctx, onFail }))),
        el('footer', { class: 'small mute', style: 'margin-top: 24px' }, `只读。页面打开时不向任何地方发送数据。｜${view.stamp}`)),
      h(Palette, { ctx, pages }),
      legend());
  },
});
