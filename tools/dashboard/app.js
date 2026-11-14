/* 对内看板的页面脚本，由 tools/build_dashboard.py 写进页面。
   只做五件事：切换页面、筛选证据表、展开一条证据、把当前显示的行复制成表格、在对标视图里切换层级。
   不发任何网络请求，不往浏览器里存任何东西；数据都已经写在页面里。
   给人看的字都在 HTML 里，这里不写。 */
(function () {
  'use strict';

  var root = document.documentElement;

  function all(selector, base) {
    return Array.prototype.slice.call((base || document).querySelectorAll(selector));
  }

  function start() {
    var views = all('main .view');
    var links = all('nav.pages a[data-view]');
    var rows = all('tbody.ev');
    var chips = all('button.chip[data-filter]');
    var pickers = all('select[data-filter], input[data-filter]');
    var shown = document.getElementById('ev-shown');
    var empty = document.getElementById('ev-empty');
    var clear = document.getElementById('ev-clear');
    var expand = document.getElementById('ev-expand');
    var copy = document.getElementById('ev-copy');
    var copyNote = document.getElementById('ev-copy-note');
    var copyBox = document.getElementById('ev-copy-box');
    var download = document.getElementById('ev-download');
    var levelTabs = all('[data-level-tab]');
    var levelPanels = all('[data-level-panel]');
    var marked = null;  // 上一次跳到并标出来的那一处

    var state = {};     // 筛选项的名字 → 选中的值。没选的不在里面
    var texts = null;   // 每条证据的全部文字，第一次查找时才算

    /* ---------- 页面切换：网址里 # 后面是页面的名字，或者一条证据的编号 ---------- */

    function showView(name) {
      views.forEach(function (view) { view.classList.toggle('active', view.id === name); });
      links.forEach(function (link) {
        if (link.getAttribute('data-view') === name) {
          link.setAttribute('aria-current', 'page');
        } else {
          link.removeAttribute('aria-current');
        }
      });
    }

    function decoded(hash) {
      try {
        return decodeURIComponent(hash.replace(/^#/, ''));
      } catch (err) {
        return '';
      }
    }

    /* name 是页面的名字，或者页面里某一处的编号（一条证据、一个可比组、可比组里的一行）。
       都不是就回到第一页 */
    function show(name) {
      var node = name ? document.getElementById(name) : null;
      var view = node && node.closest ? node.closest('main .view') : null;
      if (!view) {
        showView(views.length ? views[0].id : '');
        return;
      }
      showView(view.id);
      if (node === view) { return; }
      if (node.classList.contains('ev')) {
        reveal(node);
        return;
      }
      var panel = node.closest('[data-level-panel]');
      if (panel) { showLevel(panel.getAttribute('data-level-panel')); }
      if (marked) { marked.classList.remove('target'); }
      marked = node;
      node.classList.add('target');
      node.setAttribute('tabindex', '-1');
      node.scrollIntoView();
      focusLater(node);
    }

    /* ---------- 对标视图：一次只看一个层级 ---------- */

    function showLevel(code) {
      levelPanels.forEach(function (panel) { panel.hidden = panel.getAttribute('data-level-panel') !== code; });
      levelTabs.forEach(function (tab) {
        tab.setAttribute('aria-pressed', tab.getAttribute('data-level-tab') === code ? 'true' : 'false');
      });
    }

    levelTabs.forEach(function (tab) {
      tab.addEventListener('click', function () { showLevel(tab.getAttribute('data-level-tab')); });
    });

    if (levelPanels.length) {
      // 先显示第一个有可比组的层级；都没有就显示第一个
      var first = levelPanels.filter(function (panel) { return panel.querySelector('.group-card'); })[0] || levelPanels[0];
      showLevel(first.getAttribute('data-level-panel'));
    }

    function route() {
      show(decoded(location.hash));
    }

    /* ---------- 筛选 ---------- */

    function has(row, key, want) {
      return (' ' + (row.getAttribute('data-' + key) || '') + ' ').indexOf(' ' + want + ' ') >= 0;
    }

    function textOf(index) {
      if (!texts) {
        texts = rows.map(function (row) { return row.textContent.toLowerCase(); });
      }
      return texts[index];
    }

    function matches(row, index) {
      var keys = Object.keys(state);
      for (var k = 0; k < keys.length; k += 1) {
        var key = keys[k];
        if (key === 'q') {
          var terms = state.q.toLowerCase().split(/\s+/).filter(Boolean);
          var text = textOf(index);
          for (var t = 0; t < terms.length; t += 1) {
            if (text.indexOf(terms[t]) < 0) { return false; }
          }
        } else if (!has(row, key, state[key])) {
          return false;
        }
      }
      return true;
    }

    function visibleRows() {
      return rows.filter(function (row) { return !row.hidden; });
    }

    function allOpen() {
      var visible = visibleRows();
      return visible.length > 0 && visible.every(function (row) { return row.classList.contains('open'); });
    }

    function syncExpand() {
      if (expand) {
        expand.textContent = expand.getAttribute(allOpen() ? 'data-close' : 'data-open');
      }
    }

    function apply() {
      var count = 0;
      rows.forEach(function (row, index) {
        var ok = matches(row, index);
        row.hidden = !ok;
        if (ok) { count += 1; }
      });
      if (shown) { shown.textContent = String(count); }
      if (empty) { empty.hidden = count > 0 || rows.length === 0; }
      chips.forEach(function (chip) {
        var on = (state[chip.getAttribute('data-filter')] || '') === chip.getAttribute('data-value');
        chip.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
      pickers.forEach(function (picker) {
        var value = state[picker.getAttribute('data-filter')] || '';
        if (picker.value !== value) { picker.value = value; }
      });
      if (clear) { clear.hidden = Object.keys(state).length === 0; }
      syncExpand();
    }

    function setFilter(key, value) {
      if (value) {
        state[key] = value;
      } else {
        delete state[key];
      }
      apply();
    }

    chips.forEach(function (chip) {
      chip.addEventListener('click', function () {
        setFilter(chip.getAttribute('data-filter'), chip.getAttribute('data-value'));
      });
    });

    pickers.forEach(function (picker) {
      picker.addEventListener(picker.tagName === 'SELECT' ? 'change' : 'input', function () {
        setFilter(picker.getAttribute('data-filter'), picker.value.trim() ? picker.value : '');
      });
    });

    if (clear) {
      clear.addEventListener('click', function () {
        state = {};
        apply();
      });
    }

    /* ---------- 展开一条证据 ---------- */

    function setOpen(row, open) {
      row.classList.toggle('open', open);
      var toggle = row.querySelector('.ev-toggle');
      if (toggle) { toggle.setAttribute('aria-expanded', open ? 'true' : 'false'); }
    }

    function reveal(row) {
      if (row.hidden) {
        state = {};
        apply();
      }
      setOpen(row, true);
      syncExpand();
      row.scrollIntoView();
      var toggle = row.querySelector('.ev-toggle');
      if (toggle) { focusLater(toggle); }
    }

    /* 把焦点放到这条证据的编号上，键盘和读屏接着往下走。
       浏览器按网址里的 # 定位时会把焦点清掉，所以等它定位完再放 */
    function focusLater(node) {
      function focus() {
        window.setTimeout(function () {
          try {
            node.focus({ preventScroll: true });
          } catch (err) {
            node.focus();
          }
        }, 0);
      }
      if (document.readyState === 'complete') {
        focus();
      } else {
        window.addEventListener('load', focus);
      }
    }

    rows.forEach(function (row) {
      setOpen(row, false);
      var toggle = row.querySelector('.ev-toggle');
      if (toggle) {
        toggle.addEventListener('click', function () {
          setOpen(row, !row.classList.contains('open'));
          syncExpand();
        });
      }
    });

    if (expand) {
      expand.addEventListener('click', function () {
        var open = !allOpen();
        visibleRows().forEach(function (row) { setOpen(row, open); });
        syncExpand();
      });
    }

    /* ---------- 把当前显示的行复制成表格（制表符分隔，可以直接粘贴到表格软件里） ---------- */

    function clean(text) {
      var value = text.replace(/\s+/g, ' ').trim();
      // 表格软件会把 = + - @ 开头的格子当公式算。不是单纯的数字就在前面加一个撇号，让它当文字
      if (/^[=+\-@]/.test(value) && !/^[+-]?\d+(\.\d+)?([eE][+-]?\d+)?%?$/.test(value)) {
        value = "'" + value;
      }
      return value;
    }

    function tsv() {
      var head = all('table.ev-table thead th').map(function (cell) { return clean(cell.textContent); });
      if (rows.length) {
        all('[data-copy]', rows[0]).forEach(function (node) { head.push(clean(node.getAttribute('data-copy'))); });
      }
      var lines = [head.join('\t')];
      visibleRows().forEach(function (row) {
        var cells = all('tr.ev-main > td', row).map(function (cell) { return clean(cell.textContent); });
        all('[data-copy]', row).forEach(function (node) { cells.push(clean(node.textContent)); });
        lines.push(cells.join('\t'));
      });
      return lines.join('\n');
    }

    function copied(ok, text) {
      if (copyNote) { copyNote.textContent = copy.getAttribute(ok ? 'data-done' : 'data-failed'); }
      if (copyBox) {
        copyBox.hidden = ok;
        if (!ok) {
          copyBox.value = text;
          copyBox.focus();
          copyBox.select();
        }
      }
    }

    if (copy) {
      copy.addEventListener('click', function () {
        var text = tsv();
        try {
          navigator.clipboard.writeText(text).then(
            function () { copied(true, text); },
            function () { copied(false, text); }
          );
        } catch (err) {
          copied(false, text);
        }
      });
    }

    /* 嵌在别的页面里看的时候（比如网页版的查看器），浏览器不让页面自己下载文件，下载的链接就不显示，留“复制” */
    var framed = true;
    try {
      framed = window.self !== window.top;
    } catch (err) {
      framed = true;
    }
    if (download && framed) { download.hidden = true; }

    /* 点页面里的跳转（导航、“同文基准”这类指向另一条证据的链接）：当场就换过去。
       浏览器随后会改网址里 # 后面的名字并通知一次，那时再换一遍也一样；
       有的查看器不让框里的页面改网址，那样网址不变，但页面照样换得过去 */
    document.addEventListener('click', function (event) {
      var link = event.target && event.target.closest ? event.target.closest('a[href^="#"]') : null;
      if (link) { show(decoded(link.getAttribute('href'))); }
    });

    window.addEventListener('hashchange', route);
    apply();
    route();
  }

  try {
    start();
  } catch (err) {
    // 脚本出了错，就退回到不用脚本的样子：五页全部显示，每条证据都展开，内容照样看得到
    root.className = 'no-js';
    throw err;
  }
})();
