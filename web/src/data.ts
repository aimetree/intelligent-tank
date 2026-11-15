/* 读数据文件。前端只读 tools/export_site_data.py 导出的文件，不认 data/ 的目录结构。
   两种读法，后面是同一条路：
   - 在线版：从页面旁边的 site-data/ 目录取（同一个网站，不向别处发请求）。
   - 离线版：数据写在页面里的 <script type="application/json" id="site-data">，不取任何文件（scripts/offline.mjs 写进去）。 */
import type { Html, Labels, Meta, Row, SiteData, Views } from './types';

/** 前端认得的数据文件写法（meta.json 的 format、views.json 的 format）。导出脚本改了写法就加一，这里跟着改 */
export const META_FORMAT = 2;
export const VIEWS_FORMAT = 2;
export const FILES = ['meta.json', 'labels.json', 'views.json'] as const;
export const DATA_DIR = 'site-data/';

export class DataError extends Error {}

type Raw = Record<(typeof FILES)[number], unknown>;

function embedded(): Raw | null {
  const node = document.getElementById('site-data');
  if (!node) return null;
  return JSON.parse(node.textContent || '{}') as Raw;
}

async function fetched(): Promise<Raw> {
  const out: Partial<Raw> = {};
  for (const name of FILES) {
    let res: Response;
    try {
      res = await fetch(DATA_DIR + name, { cache: 'no-store' });
    } catch (err) {
      throw new DataError(`取不到数据文件 ${DATA_DIR}${name}：${String(err)}`);
    }
    if (!res.ok) throw new DataError(`取不到数据文件 ${DATA_DIR}${name}（${res.status}）`);
    out[name] = await res.json();
  }
  return out as Raw;
}

/** 页面模型里写成 {"$row": 编号} 的地方换回证据表的那一行（同一个对象）。别的原样 */
export function resolveRows(x: unknown, rows: Map<string, Row>): unknown {
  if (Array.isArray(x)) {
    for (let i = 0; i < x.length; i += 1) x[i] = resolveRows(x[i], rows);
    return x;
  }
  if (x && typeof x === 'object') {
    const obj = x as Record<string, unknown>;
    if (typeof obj.$row === 'string' && Object.keys(obj).length === 1) {
      const row = rows.get(obj.$row);
      if (!row) throw new DataError(`页面内容指向证据表里没有的一行：${obj.$row}`);
      return row;
    }
    if ('$html' in obj) return obj; // HTML 片段里没有行
    for (const k of Object.keys(obj)) obj[k] = resolveRows(obj[k], rows);
  }
  return x;
}

export function prepare(raw: Raw): SiteData {
  const meta = raw['meta.json'] as Meta;
  if (!meta || meta.format !== META_FORMAT) {
    throw new DataError(
      `数据文件的写法是第 ${meta?.format ?? '？'} 版，这个页面认的是第 ${META_FORMAT} 版。要用同一次提交的导出脚本重新导出，或者重新构建页面。`,
    );
  }
  if (meta.audience !== 'internal' || !raw['views.json']) {
    throw new DataError('这份数据是对外的导出，里面没有五页的内容。对外给谁看、看哪几页还没有定；现在只做了对内看板。');
  }
  const views = raw['views.json'] as Views;
  if (views.format !== VIEWS_FORMAT) {
    throw new DataError(`views.json 的写法是第 ${views.format} 版，这个页面认的是第 ${VIEWS_FORMAT} 版。`);
  }
  for (const t of views.topics) {
    const rows = new Map(t.rows.map((r) => [r.id, r]));
    for (const key of ['filters', 'compare', 'overview', 'gaps', 'nonacademic', 'errors'] as const) {
      resolveRows(t[key], rows);
    }
  }
  return { meta, labels: raw['labels.json'] as Labels, views };
}

export async function load(): Promise<SiteData> {
  return prepare(embedded() ?? (await fetched()));
}

export function isHtml(x: unknown): x is Html {
  return !!x && typeof x === 'object' && Array.isArray((x as Html).$html);
}
