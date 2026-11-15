/* 整页：页头、问题、五页的导航、五页、图例、页脚。照 tools/build_dashboard.py 的 render_page。
   五页各是一个组件；哪一页画的时候出了错，那一页说明画不出来，别的页面照样出，原因写在页面顶上。 */
import { defineComponent, h, onErrorCaptured, reactive, type Component, type PropType } from 'vue';
import { el, type Kid } from './el';
import { Names } from './names';
import { state } from './state';
import type { SiteData, TopicView } from './types';
import { CompareView } from './pages/compare';
import { EvidenceView, type Ctx } from './pages/evidence';
import { GapsView } from './pages/gaps';
import { NonAcademicView } from './pages/nonacademic';
import { OverviewView } from './pages/overview';

const PAGES: Record<string, { component: Component; model: keyof TopicView | null }> = {
  overview: { component: OverviewView, model: 'overview' },
  evidence: { component: EvidenceView, model: null },
  compare: { component: CompareView, model: 'compare' },
  gaps: { component: GapsView, model: 'gaps' },
  'non-academic': { component: NonAcademicView, model: 'nonacademic' },
};

function failedView(name: string, title: string) {
  return el('section', { class: state.view === name ? 'view active' : 'view', id: name, 'aria-label': title },
    el('section', { class: 'card' }, el('div', { class: 'view-head' }, el('h2', null, title)),
      el('p', { class: 'flag' }, '这一页生成不了，原因列在页面顶上。')));
}

/** 一页。画的时候出了错就换成“这一页生成不了” */
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
    const ctx: Ctx = {
      view, names,
      ids: new Set(view.rows.map((r) => r.id)),
      groupIds: new Set(view.compare?.group_ids || []),
    };
    const failed = reactive<Array<[string, string]>>([]);
    const onFail = (title: string, err: string) => failed.push([title, err]);
    document.title = `${view.title}｜对内看板`;

    function banners(): Kid[] {
      const out: Kid[] = [];
      if (view.notice) out.push(el('div', { class: 'banner', id: 'notice' }, view.notice));
      const problems = [
        ...view.issues.map(([rule, record, msg]) => `${rule}　${record}：${msg}`),
        ...[...view.errors, ...failed].map(([id, err]) => `${id}：显示不出来（${err}）`),
      ];
      if (problems.length) {
        const shown = problems.slice(0, 50);
        const more = problems.length > shown.length
          ? el('li', null, `其余 ${problems.length - shown.length} 处见 python3 tools/validate.py 的输出`) : null;
        out.push(el('div', { class: 'banner', id: 'problems', role: 'status' },
          el('details', null,
            el('summary', null, `这份数据有 ${problems.length} 处没通过校验。页面照样生成了，没通过的地方可能显示不全。点开看是哪几处`),
            el('ul', null, shown.map((p) => el('li', null, p)), more))));
      }
      return out;
    }

    function legend() {
      const L = views.legend;
      const col = (title: string, ...content: Kid[]) => el('div', { class: 'legend-col' }, el('h3', null, title), content);
      const types = L.types.map((t) => el('div', { class: 'legend-item' },
        el('svg', { class: 'mark', viewBox: '0 0 12 12', 'aria-hidden': 'true', focusable: 'false' }, el('use', { href: `#m-${t.code}` })), t.label));
      return el('section', { class: 'card legend', id: 'legend', 'aria-label': '图例' },
        col('证据类型', types, el('div', { class: 'note' }, '是不同的类型，不分高低。')),
        col('核验状态', L.statuses.map((x) => el('div', { class: 'legend-item' }, el('span', { class: `status s-${x.cls}` }, x.label)))),
        col('可比档', L.tiers.map((x) => el('div', null, x.text)), el('div', { class: 'note' }, '没有进任何可比组的，显示“未归组”。')),
        col('风险档', L.risks.map((x) => el('div', { class: 'legend-item' }, el('span', { class: `risk r-${x.code}` }, x.label), ' ', x.text)),
          el('div', { class: 'note' }, '人工核对之前标好，给做人工核对的人看。')));
    }

    const sprite = el('div', { hidden: true }, views.sprite); // 证据类型的六个形状，页面各处用 <use> 引用
    const legendBlock = legend();
    return () => el('div', { class: 'app' }, sprite,
      el('div', { class: 'page' },
        el('header', { class: 'top' },
          el('div', { class: 'top-title' }, el('div', { class: 'eyebrow' }, 'Intelligent Tank｜对内看板'), el('h1', null, view.title)),
          el('div', { class: 'meta', id: 'stamp' }, view.stamp)),
        banners(),
        el('nav', { class: 'pages', 'aria-label': '页面' }, views.views.map((v) =>
          el('a', { href: `#${v.key}`, 'data-view': v.key, 'aria-current': state.view === v.key ? 'page' : null }, v.title))),
        el('main', null, views.views.map((v) => h(Page, { key: v.key, name: v.key, title: v.title, question: v.question, ctx, onFail }))),
        legendBlock,
        el('footer', { class: 'foot' }, `只读。页面打开时不向任何地方发送数据；要改数据就改仓库里的数据文件，再重新生成。｜${view.stamp}`)));
  },
});
