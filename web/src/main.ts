/* 入口：读数据文件，画出整页，接上跳转。数据读不进来就在页面上说为什么。 */
import { createApp } from 'vue';
import '../../tools/dashboard/style.css'; // 旧看板的样式：复核单、页面顶上的提示还用它的写法
import './styles/theme.css'; // A 2.0 的样式，两套颜色，放在后面盖过旧的
import { App } from './App';
import { DataError, load } from './data';
import { el } from './el';
import { firstGroup } from './pages/compare';
import { listen, route, setup, state } from './state';

document.documentElement.className = 'js';

async function start() {
  const root = document.getElementById('app')!;
  try {
    const data = await load();
    const view = data.views.topics[0];
    if (!view) throw new DataError('数据里一个题目也没有。');
    const blocks = view.nonacademic?.blocks || [];
    setup(data.views.views.map((v) => v.key), view.rows.map((r) => r.id), view.compare?.group_ids || [], firstGroup(view.compare?.levels || []),
      blocks.flatMap((b) => b.cards.map((c) => [c.id, b.key] as [string, string])));
    const first = blocks.find((b) => b.cards.length) || blocks[0];
    if (first) {
      state.naBlock = first.key;
      state.naSource = first.cards[0]?.id || '';
    }
    createApp(App, { data }).mount(root);
    listen();
    route();
  } catch (err) {
    const why = err instanceof DataError ? err.message : `${(err as Error)?.name}: ${(err as Error)?.message}`;
    createApp({ render: () => el('div', { class: 'page' }, el('div', { class: 'banner', id: 'load-error', role: 'alert' }, `页面打不开：${why}`)) }).mount(root);
    throw err;
  }
}

void start();
