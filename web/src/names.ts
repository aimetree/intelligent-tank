/* 显示名和几个小写法，照 tools/display.py。枚举的名字取自 labels.json，字段名取自 views.json 里的 fields（schema 的 title）。
   找不到显示名的，原样显示代码，不猜。 */
import type { Labels } from './types';

export const NOT_FILLED = '（没有填）';
export const NONE = '-';

export class Names {
  constructor(
    private labels: Labels,
    private fields: Record<string, Record<string, string>>,
    private lang = 'zh',
  ) {}

  private pick(v: unknown, fallback: string): string {
    if (v && typeof v === 'object') {
      const o = v as Record<string, unknown>;
      const got = o[this.lang] || o.zh;
      return typeof got === 'string' && got ? got : fallback;
    }
    return typeof v === 'string' ? v : fallback;
  }

  enum(group: string, code: unknown): string {
    if (code === null || code === undefined || code === '') return '';
    if (typeof code !== 'string') return JSON.stringify(code);
    const table = ((this.labels.enums || {}) as Record<string, Record<string, unknown>>)[group] || {};
    return this.pick(table[code], code);
  }

  field(obj: string, key: string, sub?: string): string {
    const table = this.fields[obj] || {};
    if (sub !== undefined) return table[`${key}.${sub}`] || sub;
    return table[key] || key;
  }
}

/** 把代码变成能放进 class 的写法（display.cls） */
export function cls(code: unknown): string {
  return String(code ?? '').replace(/[^A-Za-z0-9_-]/g, '') || 'x';
}

const SUPERSCRIPT: Record<string, string> = {
  '-': '⁻', '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
};

/** 脚本算出来的数怎么写（display.fmt_num）：整数不带小数点，最多六位有效数字，很大很小的写成 a×10ⁿ */
export function fmtNum(x: unknown): string {
  if (typeof x !== 'number') return x === null || x === undefined ? '' : String(x);
  if (!Number.isFinite(x)) return x !== x ? 'nan' : x > 0 ? 'inf' : '-inf';
  if (Number.isInteger(x) && Math.abs(x) < 1e15) return String(x);
  const [m0, e0] = x.toExponential(5).split('e');
  const exp = Number(e0);
  if (exp < -4 || exp >= 6) {
    const mant = m0.includes('.') ? m0.replace(/0+$/, '').replace(/\.$/, '') : m0;
    return `${mant}×10${String(exp).replace(/[-0-9]/g, (c) => SUPERSCRIPT[c])}`;
  }
  return String(Number(x.toPrecision(6)));
}
