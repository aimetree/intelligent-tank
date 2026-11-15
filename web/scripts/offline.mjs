#!/usr/bin/env node
/* 离线版（D-135）：把构建好的页面和数据文件并成一个网页文件，双击就能在本机打开，不取任何文件、不联网。
   浏览器不让本机打开的页面去读旁边的文件，也不让它加载模块脚本文件，所以脚本、样式、图标和数据都写进这一个文件里。

   用法  node scripts/offline.mjs [--dist dist] [--data public/site-data] [--out offline/index.html]
   先 npm run build，数据文件用 tools/export_site_data.py 导出（给内部看的那一版）。
   同样的构建和数据，写出来逐字节相同。 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';

// 离线版的浏览器策略：脚本和样式只认写在页面里的，图片只认写在页面里的图标，别的一律拦住，也不许连任何地方
export const OFFLINE_CSP =
  "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'";
const FILES = ['meta.json', 'labels.json', 'views.json']; // 和 src/data.ts 的 FILES 一样

function args(argv) {
  const out = { dist: 'dist', data: 'public/site-data', out: 'offline/index.html' };
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i].replace(/^--/, '');
    if (!(key in out) || argv[i + 1] === undefined) throw new Error(`不认识的参数：${argv[i]}`);
    out[key] = argv[i + 1];
  }
  return out;
}

function inlineScript(text, where) {
  if (/<\/script/i.test(text)) throw new Error(`${where} 里有 </script，不能直接写进页面`);
  return text;
}

export function build({ dist, data, out }) {
  let html = readFileSync(join(dist, 'index.html'), 'utf8');
  const take = (re, what) => {
    const m = html.match(re);
    if (!m) throw new Error(`构建出来的 index.html 里找不到${what}`);
    return m;
  };
  const js = take(/<script type="module" crossorigin src="\.\/(assets\/[^"]+\.js)"><\/script>\n?/, '脚本');
  const css = take(/<link rel="stylesheet" crossorigin href="\.\/(assets\/[^"]+\.css)">\n?/, '样式表');
  const icon = take(/<link rel="icon" href="\.\/(favicon\.svg)">/, '图标');
  const csp = take(/<meta http-equiv="Content-Security-Policy" content="[^"]*">/, '浏览器策略');

  const bundle = {};
  for (const name of FILES) bundle[name] = JSON.parse(readFileSync(join(data, name), 'utf8'));
  if (bundle['meta.json'].audience !== 'internal') throw new Error('离线版现在只做对内看板，要用给内部看的导出');
  // JSON 里的 < 写成 <：数据里的文字不会提前关掉这一段
  const json = JSON.stringify(bundle).replace(/</g, '\\u003c');
  const svg = readFileSync(join(dist, icon[1]), 'utf8');

  html = html
    .replace(csp[0], `<meta http-equiv="Content-Security-Policy" content="${OFFLINE_CSP}">`)
    .replace(icon[0], `<link rel="icon" href="data:image/svg+xml,${encodeURIComponent(svg.trim())}">`)
    .replace(css[0], () => `<style>\n${inlineScript(readFileSync(join(dist, css[1]), 'utf8'), css[1])}</style>\n`)
    .replace(js[0], '')
    .replace('</body>', () =>
      `<script type="application/json" id="site-data">${json}</script>\n` +
      `<script type="module">\n${inlineScript(readFileSync(join(dist, js[1]), 'utf8'), js[1])}</script>\n</body>`);
  mkdirSync(dirname(resolve(out)), { recursive: true });
  writeFileSync(out, html);
  return { out, bytes: Buffer.byteLength(html), version: bundle['meta.json'].data_version };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  try {
    const r = build(args(process.argv.slice(2)));
    console.log(`写出离线版 ${r.out}（${Math.ceil(r.bytes / 1024)} KB），数据版本 ${r.version}`);
  } catch (err) {
    console.error(`离线版没有写出来：${err.message}`);
    process.exit(2);
  }
}
