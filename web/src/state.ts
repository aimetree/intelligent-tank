/* 页面的状态和跳转。不发网络请求，不往浏览器里存任何东西（深浅色也只在这一次打开里记着，下次照系统设置）。
   网址里 # 后面可以是：页面的名字；一条证据的编号（换到证据表、选中它、打开右边的详情）；
   一个可比组的编号（换到对标视图、选中这一组）；页面里别的编号（换到它所在的页面、标出来、滚过去）。 */
import { nextTick, reactive } from 'vue';

export type Theme = 'light' | 'dark';

export const state = reactive({
  view: '',
  filters: {} as Record<string, string>,
  query: '',
  selected: '',          // 证据表里选中的一条
  group: '',             // 对标视图里选中的可比组
  cmpTab: 'ratio',       // 对标视图：ratio 与基准之比、slope 斜率图、table 表格
  hoverMember: '',       // 对标视图里指着的对象
  step: 0,               // 总览：只亮到核验的第几步及以上（0 是全部）
  hoverCell: '',         // 总览：指着覆盖图的哪一格
  palette: false,        // 查找面板开着没有
  legend: false,         // 图例开着没有
  theme: 'light' as Theme,
});

let views: string[] = [];
let evidenceIds = new Set<string>();
let groupIds = new Set<string>();
let marked: Element | null = null;

export function setup(names: string[], evidence: string[], groups: string[], firstGroup: string) {
  views = names;
  evidenceIds = new Set(evidence);
  groupIds = new Set(groups);
  state.view = names[0] || '';
  state.group = firstGroup;
  state.selected = evidence[0] || '';
  let dark = false;
  try {
    dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  } catch {
    dark = false;
  }
  setTheme(dark ? 'dark' : 'light');
}

export function setTheme(t: Theme) {
  state.theme = t;
  document.documentElement.setAttribute('data-theme', t);
}

export function decoded(hash: string): string {
  try {
    return decodeURIComponent(hash.replace(/^#/, ''));
  } catch {
    return '';
  }
}

export function setFilter(key: string, value: string) {
  if (value) state.filters[key] = value;
  else delete state.filters[key];
}

export function clearFilters() {
  for (const k of Object.keys(state.filters)) delete state.filters[k];
  state.query = '';
}

function focusLater(node: HTMLElement) {
  window.setTimeout(() => {
    try {
      node.focus({ preventScroll: true });
    } catch {
      node.focus();
    }
  }, 0);
}

/** 跳到 name：页面、证据、可比组，或页面里别的编号。都不是就回到第一页 */
export async function show(name: string) {
  state.palette = false;
  if (views.includes(name)) {
    state.view = name;
    return;
  }
  if (evidenceIds.has(name)) {
    state.view = 'evidence';
    state.selected = name;
    await nextTick();
    let row = document.getElementById(name);
    if (!row) {          // 被筛选挡住了：清掉筛选再找
      clearFilters();
      await nextTick();
      row = document.getElementById(name);
    }
    if (row) {
      row.scrollIntoView({ block: 'nearest' });
      const pick = row.querySelector<HTMLElement>('.pick');
      if (pick) focusLater(pick);
    }
    return;
  }
  if (groupIds.has(name)) {
    state.view = 'compare';
    state.group = name;
    state.hoverMember = '';
    await nextTick();
    const head = document.getElementById('cmp-title');
    if (head) head.scrollIntoView({ block: 'nearest' });
    return;
  }
  const node = name ? document.getElementById(name) : null;
  const view = node?.closest('main .view') as HTMLElement | null;
  if (!node || !view || !views.includes(view.id)) {
    state.view = views[0] || '';
    return;
  }
  state.view = view.id;
  await nextTick();
  if (node === view) return;
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

/** 点页面里的跳转当场就换过去；浏览器随后改网址、通知一次，再换一遍也一样（有的查看器不让框里的页面改网址） */
export function listen() {
  document.addEventListener('click', (event) => {
    const target = event.target as Element | null;
    const link = target?.closest ? target.closest('a[href^="#"]') : null;
    if (link) void show(decoded(link.getAttribute('href') || ''));
  });
  window.addEventListener('hashchange', route);
  document.addEventListener('keydown', (event) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((event.target as HTMLElement)?.tagName || '');
    if ((event.key === 'k' || event.key === 'K') && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      state.palette = !state.palette;
    } else if (event.key === '/' && !typing && !state.palette) {
      event.preventDefault();
      state.palette = true;
    } else if (event.key === 'Escape') {
      state.palette = false;
      state.legend = false;
    }
  });
}
