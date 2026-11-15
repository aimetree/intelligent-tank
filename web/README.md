# 网页前端（web/）

对内看板的新前端：Vue 3、Vite、TypeScript。Yu 2026-11-15 定的“方案 C”的前半：前端独立成一个工程，只读导出的数据文件（《网页前端_任务卡》v0.1）。

现在是首版五页（总览、证据表、对标视图、数据概览与缺口、非学术来源），和旧的单文件看板（`tools/build_dashboard.py`）逐项对得上。旧看板先留着，五页对上之后撤不撤由 Yu 定。

## 怎么用

要 Node 22.12 以上、Python 3.12 以上。

```bash
cd web
npm ci                 # 装依赖，照 package-lock.json 的版本
npm run data           # 用示例数据（tools/tests/example，全部虚构）导出数据文件到 public/site-data/
npm run dev            # 开发：浏览器打开它给的地址
npm run build          # 类型检查加构建，写到 dist/（页面、脚本、样式，加上 public/site-data/ 里的数据）
npm run offline        # 离线版：dist/ 和数据并成一个网页文件 offline/index.html，双击就能打开
npm test               # 单元测试
```

- 用仓库里的真实数据：`npm run data:repo`（也就是 `python3 ../tools/export_site_data.py --out public/site-data`）。
- 在线版要用网页服务器打开，比如 `python3 -m http.server -d dist`：浏览器不让本机打开的页面去读旁边的数据文件。只是自己看，用离线版。
- 和旧看板的对照、旧看板的浏览器测试：先 `npm run build`，再 `python3 ../tools/tests/test_web.py`。
- `dist/`、`offline/`、`public/site-data/`、`node_modules/` 都不入库。GitHub Actions 的“网页前端”在 main 上把在线版和离线版存成那次运行的附件，保留 14 天。

## 怎么做的

- **数据从哪来。** 只读 `tools/export_site_data.py` 导出的文件，用到其中三个：`meta.json`（写法的版本、给谁看、数据版本）、`labels.json`（代码对应的中文名）、`views.json`（五页要显示的内容）。读的时候先对写法的版本，对不上就在页面上说为什么。
- **页面上的内容谁算。** Yu 2026-11-15 选“甲”：五页要显示的东西照旧由看板的 Python 函数算好（`tools/site_views.py` 把 `build_model` 的结果写成 `views.json`），前端只管摆出来、筛选、展开、跳转、复制、下载。换算、比值、可比组的图、覆盖图、缺口，算法只有 Python 那一份。
- **图。** 图的坐标、刻度、记号由 `tools/charts.py` 算好，在 `views.json` 里是 SVG 的节点；前端照白名单画出来（`src/el.ts`），只认几种标签和属性，事件属性、样式属性、别的链接一律不要。
- **页面怎么写。** 每一块照旧看板里写网页的那个函数，用 Vue 的渲染函数一一对着写（`src/pages/`），元素、类名、属性、字都一样，所以样式表直接用旧看板那一份（`tools/dashboard/style.css`），对照测试也能逐个元素比。
- **守住的做法。** 页面打开后不向别处发请求：在线版只向自己的网站要页面、脚本、样式、图标和三个数据文件，浏览器策略拦住别的；离线版什么都不要。来源里的文字只当文字显示。`#页面名`、`#证据编号`（还有可比组、陈述、来源的编号）能直接跳。
- **和旧看板不一样的地方。** 浏览器不跑脚本时，新前端只显示一句“要开着脚本才能看”（Yu 2026-11-15 同意）；旧看板会五页摊开。哪一页画的时候出了错，那一页写明生成不了，别的页照样出；旧看板是整页退回不跑脚本的样子。

## 版本

Vue 3.5.45、Vite 8.3.8、@vitejs/plugin-vue 6.0.11、vue-tsc 3.3.14、Vitest 5.1.0，都是 2026-11-15 查到的最新稳定版。TypeScript 用的是 6.0.3，不是最新的 7.0.2：TypeScript 7 是重写过的版本，Vue 的类型检查工具 vue-tsc 3.3.14 还调用不了它（`ERR_PACKAGE_PATH_NOT_EXPORTED: ./lib/tsc`）。vue-tsc 支持 7 之后再升。

## 文件

| 文件 | 做什么 |
|---|---|
| `src/main.ts` | 入口：读数据，画出整页，接上跳转 |
| `src/data.ts` | 读数据文件、对版本、把页面内容里写成编号的行换回那一行 |
| `src/types.ts` | 数据文件的样子，和 Python 那边一一对应 |
| `src/names.ts` | 显示名、数的写法（照 `tools/display.py`） |
| `src/el.ts` | 写页面的小函数（照 `tools/htmlgen.py`），和画 HTML 片段的白名单 |
| `src/state.ts` | 换页、换层级、筛选、展开、跳到一处（照旧看板的 `tools/dashboard/app.js`） |
| `src/App.ts` | 页头、页面顶上的提示、导航、图例、页脚；一页出错只影响那一页 |
| `src/pages/*.ts` | 五页，各对着旧看板的一个脚本 |
| `scripts/offline.mjs` | 离线版 |
| `tests/unit/` | 单元测试 |
