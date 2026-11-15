/* 页面的状态和跳转，做法照旧看板的页面脚本（tools/dashboard/app.js）：
   - 网址里 # 后面是页面的名字，或者页面里某一处的编号（一条证据、一个可比组、可比组里的一行、一条陈述、一个来源）。
   - 跳到一条证据：换到证据表页，筛选挡住了就清掉筛选，展开它，滚过去，把焦点放在它的编号上。
   - 跳到别的一处：换到它所在的页面（在对标视图的某一层里就换到那一层），标出来，滚过去。
   不发任何网络请求，不往浏览器里存任何东西。 */
import { nextTick, reactive } from 'vue';

export const state = reactive({
  view: '',
  level: '',
  filters: {} as Record<string, string>,
  open: {} as Record<string, boolean>,
});

let views: string[] = [];
let marked: Element | null = null;

export function setViews(names: string[], firstLevel: string) {
  views = names;
  state.view = names[0] || '';
  state.level = firstLevel;
}

export function decoded(hash: string): string {
  try {
    return decodeURIComponent(hash.replace(/^#/, ''));
  } catch {
    return '';
  }
}

/** 把焦点放到 node 上。浏览器按网址里的 # 定位时会把焦点清掉，所以等它定位完再放 */
function focusLater(node: HTMLElement) {
  const focus = () =>
    window.setTimeout(() => {
      try {
        node.focus({ preventScroll: true });
      } catch {
        node.focus();
      }
    }, 0);
  if (document.readyState === 'complete') focus();
  else window.addEventListener('load', focus, { once: true });
}

export function setFilter(key: string, value: string) {
  if (value) state.filters[key] = value;
  else delete state.filters[key];
}

export function clearFilters() {
  for (const k of Object.keys(state.filters)) delete state.filters[k];
}

/** 证据表现在真的显示着的行（页面上算出来的，不是记的状态） */
export function visibleRows(): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>('tbody.ev')).filter((r) => !r.hidden);
}

async function reveal(row: HTMLElement) {
  if (row.hidden) clearFilters();
  state.open[row.id] = true;
  await nextTick();
  row.scrollIntoView();
  const toggle = row.querySelector<HTMLElement>('.ev-toggle');
  if (toggle) focusLater(toggle);
}

/** name 是页面的名字，或者页面里某一处的编号。都不是就回到第一页 */
export async function show(name: string) {
  const node = name ? document.getElementById(name) : null;
  const view = node?.closest('main .view') as HTMLElement | null;
  if (!node || !view || !views.includes(view.id)) {
    state.view = views[0] || '';
    return;
  }
  state.view = view.id;
  if (node === view) return;
  if (node.classList.contains('ev')) {
    await reveal(node);
    return;
  }
  const panel = node.closest('[data-level-panel]');
  if (panel) state.level = panel.getAttribute('data-level-panel') || '';
  await nextTick();
  if (marked) marked.classList.remove('target');
  marked = node;
  node.classList.add('target');
  node.setAttribute('tabindex', '-1');
  node.scrollIntoView();
  focusLater(node);
}

export function route() {
  void show(decoded(location.hash));
}

/** 点页面里的跳转：当场就换过去。浏览器随后会改网址里 # 后面的名字并通知一次，那时再换一遍也一样；
    有的查看器不让框里的页面改网址，那样网址不变，但页面照样换得过去 */
export function listen() {
  document.addEventListener('click', (event) => {
    const target = event.target as Element | null;
    const link = target?.closest ? target.closest('a[href^="#"]') : null;
    if (link) void show(decoded(link.getAttribute('href') || ''));
  });
  window.addEventListener('hashchange', route);
}
