/* 前端里几件不靠浏览器的小事。页面对不对，由 tools/tests/test_web.py 拿旧看板逐项对照。 */
import { describe, expect, it } from 'vitest';
import { resolveRows, prepare, META_FORMAT, VIEWS_FORMAT, DataError } from '../../src/data';
import { el, safeHref } from '../../src/el';
import { renderToString } from 'vue/server-renderer';
import { createSSRApp } from 'vue';
import { Names, cls, fmtNum } from '../../src/names';
import { matches, clean, textOf } from '../../src/pages/evidence';
import { scaleFor } from '../../src/scale';
import { round } from '../../src/pages/common';
import type { Row } from '../../src/types';

describe('fmtNum 和 tools/display.py 的 fmt_num 写出来一样', () => {
  // 期望值是 Python 的 fmt_num 对同一批数算出来的
  const cases: Array<[number, string]> = [
    [0, '0'], [1, '1'], [-3, '-3'], [85.6, '85.6'], [0.45, '0.45'], [1.2e-6, '1.2×10⁻⁶'], [1234567, '1234567'],
    [999999.5, '1×10⁶'], [0.0001, '0.0001'], [1.234e-5, '1.234×10⁻⁵'], [3.14159265, '3.14159'], [100, '100'],
    [1e15, '1×10¹⁵'], [2.5e20, '2.5×10²⁰'], [-1.2e-5, '-1.2×10⁻⁵'], [123456.789, '123457'], [0.1 + 0.2, '0.3'],
    [1.0439, '1.0439'], [7, '7'],
  ];
  it.each(cases)('%s → %s', (x, want) => expect(fmtNum(x)).toBe(want));
  it('不是数的原样', () => {
    expect(fmtNum('85.6%')).toBe('85.6%');
    expect(fmtNum(null)).toBe('');
  });
});

describe('round 照 Python 的 round', () => {
  it('恰好一半时取偶数', () => {
    expect(round(0.5, 0)).toBe(0);
    expect(round(1.5, 0)).toBe(2);
    expect(round(2.675, 2)).toBe(2.67); // 机器里的 2.675 比一半略小，Python 的 round 也是 2.67
    expect(round(0.125, 2)).toBe(0.12);
    expect(round(538.4615384, 2)).toBe(538.46);
    expect(round(8.345, 2)).toBe(8.35);
    expect(round(1.005, 2)).toBe(1);
    expect(round(-2.5, 0)).toBe(-2);
    expect(round(0.375, 2)).toBe(0.38);
    expect(round(33.333333, 2)).toBe(33.33);
  });
});

describe('Names', () => {
  const names = new Names(
    { enums: { level: { material: { zh: '材料', en: 'Material' }, plain: '直接写的' } } },
    { evidence: { snippet: '原文片段', 'risk.reasons': '理由' } },
  );
  it('枚举和字段的显示名，找不到的原样显示代码', () => {
    expect(names.enum('level', 'material')).toBe('材料');
    expect(names.enum('level', 'plain')).toBe('直接写的');
    expect(names.enum('level', 'nowhere')).toBe('nowhere');
    expect(names.enum('level', '')).toBe('');
    expect(names.enum('nope', 'x')).toBe('x');
    expect(names.field('evidence', 'snippet')).toBe('原文片段');
    expect(names.field('evidence', 'risk', 'reasons')).toBe('理由');
    expect(names.field('evidence', 'nope')).toBe('nope');
  });
  it('cls 只留能放进 class 的字', () => {
    expect(cls('looked at')).toBe('lookedat');
    expect(cls('"><x')).toBe('x');
    expect(cls('')).toBe('x');
  });
});

describe('链接只认页面里的 # 和 http、https', () => {
  it.each([
    ['#EV-000001-001', '#EV-000001-001'], ['https://doi.org/10.1/x', 'https://doi.org/10.1/x'],
    ['javascript:alert(1)', null], ['data:text/html,x', null], ['//evil.example', null], ['#a b', null],
  ])('%s', (href, want) => expect(safeHref(href)).toBe(want));
});

function row(id: string, f: Record<string, string>, tiers = ['-'], extra: Partial<Row> = {}): Row {
  return { id, f, tiers, subject: '', sample: '', measure: '', value: '', value_notes: [], conditions: [], type_label: '', status_label: '',
    source_id: '', source_title: '', locator: '', snippet: '', level_label: '', groups: [], ...extra } as unknown as Row;
}

describe('筛选', () => {
  const r = row('EV-1', { level: 'material', status: 'pending' }, ['direct', 'reference'],
    { sample: 'X-1', measure: '能量效率', value: '85.6%', conditions: [{ key: 'j', name: '电流密度', text: '80 mA cm-2', state: 'reported', parsed: '' }] });
  it('每一项都要对上；可比档对上其中一个就算；skip 的那一项不管', () => {
    expect(matches(r, {})).toBe(true);
    expect(matches(r, { level: 'material', status: 'pending' })).toBe(true);
    expect(matches(r, { level: 'device' })).toBe(false);
    expect(matches(r, { level: 'device' }, '', 'level')).toBe(true);
    expect(matches(r, { tier: 'reference' })).toBe(true);
    expect(matches(r, { tier: 'direct ' })).toBe(false);
  });
  it('查找：每个词都要出现，不分大小写，条件里的字也算', () => {
    expect(matches(r, {}, 'x-1  能量')).toBe(true);
    expect(matches(r, {}, 'x-1 80 MA')).toBe(true);
    expect(matches(r, {}, 'x-1 电压')).toBe(false);
    expect(matches(r, {}, '   ')).toBe(true);
    expect(textOf(r)).toContain('ev-1');
  });
  it('复制成表格时，像公式的格子加撇号', () => {
    expect(clean('  =SUM(A1)\n')).toBe("'=SUM(A1)");
    expect(clean('-3.5')).toBe('-3.5');
    expect(clean('@x')).toBe("'@x");
    expect(clean('-x')).toBe("'-x");
    expect(clean('+1')).toBe('+1');
    expect(clean('a   b')).toBe('a b');
  });
});

describe('坐标轴和 tools/charts.py 的 scale_for 一样', () => {
  // 期望值是 Python 的 scale_for 对同一批数算出来的
  const cases: Array<[number[], number[], string[]]> = [
    [[82, 85.6], [82, 83, 84, 85, 86], ['82', '83', '84', '85', '86']],
    [[0.98, 1.0439, 1.0075, 1.0], [0.98, 1, 1.02, 1.04, 1.06], ['0.98', '1', '1.02', '1.04', '1.06']],
    [[1e-7, 3e-5], [1e-7, 1e-6, 1e-5, 1e-4], ['10⁻⁷', '10⁻⁶', '10⁻⁵', '10⁻⁴']],
    [[5, 5], [4.5, 5, 5.5], ['4.5', '5', '5.5']],
  ];
  it.each(cases)('%j', (vals, ticks, labels) => {
    const s = scaleFor(vals, 0, 100);
    expect(s.ticks.map((x) => Number(x.toPrecision(12)))).toEqual(ticks);
    expect(s.ticks.map(s.label)).toEqual(labels);
    expect(Math.round(s(vals[0]) * 1000) / 1000).toBe(vals[0] === vals[1] ? 50 : 18);
  });
});

describe('读数据文件', () => {
  it('{$row} 换回证据表里的同一行；指向没有的一行要报错', () => {
    const a = row('EV-1', {});
    const rows = new Map([['EV-1', a]]);
    const model = { x: [{ $row: 'EV-1' }], y: { best: { $row: 'EV-1' } }, z: { $html: [{ t: 'span', c: ['$row'] }] } };
    resolveRows(model, rows);
    expect(model.x[0]).toBe(a);
    expect(model.y.best).toBe(a);
    expect(() => resolveRows({ b: { $row: 'EV-9' } }, rows)).toThrow(DataError);
  });
  const base = () => ({
    'meta.json': { format: META_FORMAT, audience: 'internal' },
    'labels.json': {},
    'views.json': { format: VIEWS_FORMAT, topics: [] as unknown[] },
  });
  it('写法对不上、对外的导出，都说明为什么', () => {
    expect(() => prepare(base() as never)).not.toThrow();
    const old = base();
    old['meta.json'].format = 1;
    expect(() => prepare(old as never)).toThrow(/第 1 版/);
    const ext = base();
    ext['meta.json'].audience = 'external';
    expect(() => prepare(ext as never)).toThrow(/对外/);
    const v = base();
    v['views.json'].format = 99;
    expect(() => prepare(v as never)).toThrow(/第 99 版/);
  });
});

describe('HTML 片段照白名单画', () => {
  it('事件属性、样式属性、别的链接、不认的标签都不要', async () => {
    const frag = { $html: [
      { t: 'a', a: { href: 'javascript:alert(1)', onclick: 'alert(2)', onMouseOver: 'x', style: 'color:red', title: 't' }, c: ['点'] },
      { t: 'script', c: ['alert(3)'] },
      { t: 'svg', a: { viewBox: '0 0 1 1', 'xlink:href': '#x' }, c: [{ t: 'use', a: { href: '#m-experimental' } }] },
      '<b>字</b>',
    ] };
    const html = await renderToString(createSSRApp({ render: () => el('div', null, frag as never) }));
    expect(html).toContain('<a title="t">点</a>');
    expect(html).not.toMatch(/onclick|onmouseover|style=|javascript|script|xlink/i);
    expect(html).toContain('<use href="#m-experimental">');
    expect(html).toContain('&lt;b&gt;字&lt;/b&gt;');
  });
});
