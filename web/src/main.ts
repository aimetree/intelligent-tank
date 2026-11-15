/* 入口：读数据文件，画出整页，接上跳转。数据读不进来就在页面上说为什么。 */
import { createApp } from 'vue';
import '../../tools/dashboard/style.css'; // 样式和旧看板是同一份文件
import { App } from './App';
import { DataError, load } from './data';
import { el } from './el';
import { firstLevel } from './pages/compare';
import { listen, route, setViews } from './state';

document.documentElement.className = 'js';

async function start() {
  const root = document.getElementById('app')!;
  try {
    const data = await load();
    const view = data.views.topics[0];
    if (!view) throw new DataError('数据里一个题目也没有。');
    setViews(data.views.views.map((v) => v.key), firstLevel(view.compare?.levels || []));
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
