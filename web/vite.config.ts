import type { Plugin } from 'vite';
import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';

// 构建出来的页面只许加载自己目录里的脚本、样式和数据文件，别的一律拦住（设计方案 4.4 第 15 项）。
// 开发时不加：开发服务器要往页面里塞样式和热更新的连接。
export const CSP =
  "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; " +
  "base-uri 'none'; form-action 'none'";

function csp(): Plugin {
  return {
    name: 'csp',
    apply: 'build',
    transformIndexHtml(html) {
      return html.replace('<!--csp-->', `<meta http-equiv="Content-Security-Policy" content="${CSP}">`);
    },
  };
}

export default defineConfig({
  base: './', // 放在哪个目录下都能打开，不认网站的根目录
  plugins: [vue(), csp()],
  server: {
    fs: { allow: ['..'] }, // 样式表用的是 tools/dashboard/style.css 那一份
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    modulePreload: { polyfill: false }, // 不往页面里塞一段内联脚本
  },
  test: {
    include: ['tests/unit/**/*.test.ts'],
  },
});
