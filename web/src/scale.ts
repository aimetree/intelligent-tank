/* 坐标轴：照 tools/charts.py 的 scale_for。刻度取 1、2、5 乘以 10 的整数次方，两头留到刻度上；
   全是正数、最大最小差到一百倍以上时用对数轴。新前端自己画图，刻度的取法和报告里的图一样。 */
import { fmtNum } from './names';

const SUP: Record<string, string> = { '-': '⁻', '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹' };
export const INSET = 18;

export function niceStep(raw: number): number {
  const exponent = Math.floor(Math.log10(raw));
  const fraction = raw / 10 ** exponent;
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
  return nice * 10 ** exponent;
}

export interface Scale {
  (v: number): number;
  ticks: number[];
  log: boolean;
  label: (t: number) => string;
}

function make(lo: number, hi: number, a: number, b: number, log: boolean, ticks: number[]): Scale {
  const inset = b > a ? INSET : -INSET;
  const A = a + inset;
  const B = b - inset;
  const f = ((v: number) => {
    const t = log ? (Math.log10(v) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo)) : (v - lo) / (hi - lo);
    return A + t * (B - A);
  }) as Scale;
  f.ticks = ticks;
  f.log = log;
  f.label = (tick: number) => {
    if (log) {
      const ex = ticks.map((t) => Math.round(Math.log10(t)));
      if (Math.min(...ex) < -3 || Math.max(...ex) > 4) {
        return '10' + String(Math.round(Math.log10(tick))).replace(/[-0-9]/g, (c) => SUP[c]);
      }
    }
    return fmtNum(tick);
  };
  return f;
}

export function scaleFor(values: Array<number | null | undefined>, a: number, b: number): Scale {
  let vals = values.filter((v): v is number => typeof v === 'number' && Number.isFinite(v)).sort((x, y) => x - y);
  if (!vals.length) vals = [0, 1];
  let lo = vals[0];
  let hi = vals[vals.length - 1];
  if (lo > 0 && hi / lo >= 100) {
    const e0 = Math.floor(Math.log10(lo) + 1e-12);
    let e1 = Math.ceil(Math.log10(hi) - 1e-12);
    if (e0 === e1) e1 += 1;
    const ticks: number[] = [];
    for (let e = e0; e <= e1; e += 1) ticks.push(10 ** e);
    return make(10 ** e0, 10 ** e1, a, b, true, ticks);
  }
  if (lo === hi) {
    const pad = Math.abs(lo) * 0.1 || 1;
    lo -= pad;
    hi += pad;
  }
  const step = niceStep((hi - lo) / 4);
  const first = Math.floor(lo / step + 1e-9);
  const last = Math.ceil(hi / step - 1e-9);
  const ticks: number[] = [];
  for (let i = first; i <= last; i += 1) ticks.push(Number((i * step).toFixed(12)));
  return make(ticks[0], ticks[ticks.length - 1], a, b, false, ticks);
}
