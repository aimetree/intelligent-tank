#!/usr/bin/env python3
"""核对单：人工核对用的单子（方案 5.1 第 5、6 步；D-75、D-80、D-34）。

一个来源一张。核对的人对着原文逐条看：数值、单位、条件、指的是不是这个样品；图上读数自己在图上再读一次。
核对单是一个可以填的网页，填完点“复制核对结果”，把复制到的内容交回来，由脚本写回数据。
回答不由脚本和 AI 代答：写回时核对人必须是人（V-43 同样的道理）。核对单里有原文片段，只留内部（D-56）。

用法
  python3 tools/verify_sheet.py list                              每个来源有几条等着核对
  python3 tools/verify_sheet.py page SRC-000001 --out 核对单.html   生成核对单网页
  python3 tools/verify_sheet.py apply --answers 回答.json           把核对结果写回数据（先在内存里校验，多出问题就不写）
  python3 tools/verify_sheet.py apply --answers 回答.json --dry-run  只看会怎么改

回答文件的样子（就是网页上“复制核对结果”复制出来的）：
  {"source_id": "SRC-000001", "verifier": "yu", "date": "2026-11-16", "minutes": 85,
   "items": {"EV-000001-001": {"decision": "ok"},
             "EV-000001-046": {"decision": "ok", "reread": 99.6},
             "EV-000001-017": {"decision": "fix", "note": "应为 1.89", "change_ids": ["CHG-000002"]},
             "EV-000001-024": {"decision": "dispute", "note": "正文和图对不上"}}}
minutes 是核对的人实际用的分钟数（工作记录要实记）；当时没记就写 minutes_note。

每条的决定
  ok       对。状态改成人工已核，记核对人和日期。图上读数要带 reread（核对人自己读的值）：记复读人、复读的值，
           两次读数之差的绝对值记成读数误差（D-34）。原来标了存疑的保持存疑，只记核对人
  fix      要改。先照核对人说的改数据、记变化记录（kind 为 correction，写错误类型），再带着 change_ids 写回，
           这一条才标成人工已核。没有 change_ids 的 fix 不写回，列出来等着改
  dispute  存疑。要写 note，记成 dispute_note
没有填的条目不动。机器核对没通过的条目现在升不到人工已核（V-27），核对人说对的也先留着，列出来。

退出码  0 做完了；1 有做不了的；2 用法不对。
"""
import argparse
import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import access as A  # noqa: E402
import ids as I  # noqa: E402
import store  # noqa: E402
import validate as V  # noqa: E402

OPEN = ("pending", "machine_checked", "disputed")   # 核对单上列的：还没有人工核对过的
DECISIONS = ("ok", "fix", "dispute")


class VerifyError(Exception):
    pass


def _todo(ds, source_id):
    """这个来源等着人工核对的证据，按页、再按编号排。"""
    rows = []
    for eid in A.evidence_ids(ds):
        e = A.evidence(ds, eid)
        if e.get("source_id") != source_id or e.get("verification_status") not in OPEN:
            continue
        if e.get("verification_status") == "disputed" and e.get("verified_by"):
            continue
        rows.append(e)

    def key(e):
        page = str((e.get("locator") or {}).get("page") or "")
        return (int(page) if page.isdigit() else 10 ** 6, e["id"])
    return sorted(rows, key=key)


def _names(ds, topic_id):
    dic = A.dictionary(ds, topic_id) or {}
    ind = {i["key"]: i.get("name_zh", i["key"]) for i in dic.get("indicators", [])}
    ind.update({f["key"]: f.get("name_zh", f["key"]) for f in dic.get("facts", [])})
    cond = {c["key"]: c.get("name_zh", c["key"]) for c in dic.get("conditions", [])}
    return ind, cond


def _condition_text(v):
    if isinstance(v, str):
        return {"not_reported": "未报告", "not_applicable": "不适用"}.get(v, v)
    return str(v.get("reported", ""))


def rows_for_page(ds, source_id):
    """核对单上的行：给网页用的纯数据。"""
    out = []
    for e in _todo(ds, source_id):
        ind, cond = _names(ds, e.get("topic_id"))
        key = e.get("indicator") or e.get("fact")
        value = e.get("value_reported") or e.get("category_value") or e.get("summary") or ""
        risk = e.get("risk") or {}
        mc = e.get("machine_check") or {}
        out.append({
            "id": e["id"],
            "where": (e.get("locator") or {}).get("text", ""),
            "sample": e.get("sample_label") or e.get("subject_id") or "",
            "what": ind.get(key, key or ""),
            "value": str(value),
            "unit": e.get("unit_reported") or "",
            "qualifier": e.get("value_qualifier") or "",
            "conditions": [[cond.get(k, k), _condition_text(v)] for k, v in (e.get("conditions") or {}).items()],
            "snippet": e.get("snippet") or "",
            "conditions_snippet": e.get("conditions_snippet") or "",
            "figure": e.get("obtained_from") == "figure_read",
            "method": (e.get("figure_read") or {}).get("method", ""),
            "tier": risk.get("tier", ""),
            "reasons": list(risk.get("reasons") or []),
            "machine_failed": any(mc.get(k) == "fail" for k in ("identifier", "snippet", "value_unit")),
            "status": e.get("verification_status"),
            "notes": [x for x in (e.get("scope_note"), e.get("internal_note"), e.get("dispute_note")) if x],
        })
    return out


PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--ink:#1c1c1e;--sub:#5b5b60;--line:#d9d9de;--bg:#f6f6f8;--card:#fff;--hi:#b3261e;--mid:#8a5a00;--ok:#1b6e3c;--accent:#0b57d0}
*{box-sizing:border-box}body{margin:0;font:15px/1.55 -apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif;color:var(--ink);background:var(--bg)}
header{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);padding:12px 20px}
h1{font-size:18px;margin:0 0 4px}.sub{color:var(--sub);font-size:13px}
.bar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin-top:10px}
.bar label{font-size:13px;color:var(--sub)}.bar input[type=number],.bar input[type=text]{width:90px;padding:5px 7px;border:1px solid var(--line);border-radius:6px;font:inherit}
button{font:inherit;padding:7px 14px;border-radius:8px;border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer}
button.plain{background:var(--card);color:var(--accent)}button:focus-visible,input:focus-visible,textarea:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
main{max-width:1080px;margin:0 auto;padding:16px 20px 80px}
.how{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin-bottom:16px;font-size:14px}
.how ol{margin:6px 0 0 18px;padding:0}
.row{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin-bottom:10px}
.row.done{border-left:4px solid var(--ok)}.row.todo{border-left:4px solid var(--line)}
.top{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:baseline}
.id{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;color:var(--sub)}
.val{font-size:17px;font-weight:600}.tag{font-size:12px;padding:1px 8px;border-radius:10px;border:1px solid var(--line);color:var(--sub)}
.tag.high{color:var(--hi);border-color:var(--hi)}.tag.medium{color:var(--mid);border-color:var(--mid)}
.where{color:var(--sub);font-size:13px}.cond{font-size:13px;color:var(--sub);margin:6px 0}.cond b{font-weight:500;color:var(--ink)}
.snip{font-size:13px;background:var(--bg);border-radius:6px;padding:6px 9px;margin:6px 0;white-space:pre-wrap;word-break:break-word}
.note{font-size:13px;color:var(--sub);margin:4px 0}
.ans{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center;margin-top:8px;padding-top:8px;border-top:1px dashed var(--line)}
.ans label{font-size:14px}.ans input[type=text]{flex:1;min-width:220px;padding:5px 7px;border:1px solid var(--line);border-radius:6px;font:inherit}
.ans input[type=number]{width:110px;padding:5px 7px;border:1px solid var(--line);border-radius:6px;font:inherit}
#out{width:100%;height:140px;font:12px ui-monospace,Menlo,Consolas,monospace;margin-top:8px;display:none}
#msg{font-size:13px;color:var(--ok)}
@media (max-width:600px){header,main{padding-left:12px;padding-right:12px}}
</style></head><body>
<header>
<h1>__TITLE__</h1>
<div class="sub">__SUB__</div>
<div class="bar">
<span id="count"></span>
<label>核对的人 <input type="text" id="who" value="yu"></label>
<label>实际用了几分钟 <input type="number" id="minutes" min="0" step="1"></label>
<button id="copy">复制核对结果</button>
<button class="plain" id="allok">没填的非图上读数都标“对”</button>
<span id="msg" role="status"></span>
</div>
<textarea id="out" readonly aria-label="核对结果"></textarea>
</header>
<main>
<div class="how"><b>怎么用</b>
<ol><li>旁边打开原文的 PDF。下面的条目按页码排好了。</li>
<li>每条看四样：数值、单位、条件、指的是不是这个样品。对的点“对”；不对的点“要改”，在后面写应该是什么；拿不准的点“存疑”，写原因。</li>
<li>标着“图上读数”的，请自己在图上读一次，把读到的数填进“我读的值”，再点“对”。两次读数的差会记成读数误差。</li>
<li>做完填上实际用了几分钟，点“复制核对结果”，把复制到的内容贴回对话里。中途关掉页面，填过的会留在这个浏览器里。</li></ol></div>
<div id="rows"></div>
</main>
<script>
const DATA = __DATA__;
const KEY = "verify:" + DATA.source_id + ":" + DATA.data_version;
const REASON = __REASONS__;
let state = {items: {}};
try { const s = localStorage.getItem(KEY); if (s) state = JSON.parse(s); } catch (e) {}
function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} count(); }
function el(tag, cls, text) { const x = document.createElement(tag); if (cls) x.className = cls; if (text !== undefined) x.textContent = text; return x; }
function count() {
  const done = DATA.rows.filter(r => (state.items[r.id] || {}).decision).length;
  document.getElementById("count").textContent = "已填 " + done + " / " + DATA.rows.length;
  for (const r of DATA.rows) { const box = document.getElementById("row-" + r.id); if (box) box.className = "row " + ((state.items[r.id] || {}).decision ? "done" : "todo"); }
}
function render() {
  const host = document.getElementById("rows");
  for (const r of DATA.rows) {
    const it = state.items[r.id] || (state.items[r.id] = {});
    const box = el("div", "row todo"); box.id = "row-" + r.id;
    const top = el("div", "top");
    top.append(el("span", "id", r.id), el("span", "", r.sample), el("span", "", r.what),
      el("span", "val", (r.qualifier && r.qualifier !== "eq" ? "(" + r.qualifier + ") " : "") + r.value + (r.unit ? " " + r.unit : "")));
    if (r.figure) top.append(el("span", "tag high", "图上读数"));
    if (r.tier) top.append(el("span", "tag " + r.tier, "风险 " + ({high: "高", medium: "中", low: "低"}[r.tier] || r.tier)));
    if (r.machine_failed) top.append(el("span", "tag high", "机器核对没通过"));
    if (r.status === "disputed") top.append(el("span", "tag high", "存疑"));
    box.append(top, el("div", "where", r.where + (r.reasons.length ? "｜要留意：" + r.reasons.map(x => REASON[x] || x).join("、") : "")));
    if (r.conditions.length) { const c = el("div", "cond"); r.conditions.forEach(([k, v], i) => { if (i) c.append("；"); c.append(el("b", "", k + " "), v); }); box.append(c); }
    if (r.snippet) box.append(el("div", "snip", "原文片段：" + r.snippet));
    if (r.conditions_snippet) box.append(el("div", "snip", "条件的片段：" + r.conditions_snippet));
    if (r.method) box.append(el("div", "note", "AI 的读法：" + r.method));
    for (const n of r.notes) box.append(el("div", "note", n));
    const ans = el("div", "ans");
    for (const [v, t] of [["ok", "对"], ["fix", "要改"], ["dispute", "存疑"]]) {
      const lab = el("label"); const rb = document.createElement("input"); rb.type = "radio"; rb.name = "d-" + r.id; rb.value = v; rb.checked = it.decision === v;
      rb.addEventListener("change", () => { it.decision = v; save(); }); lab.append(rb, " " + t); ans.append(lab);
    }
    if (r.figure) { const lab = el("label", "", "我读的值 "); const n = document.createElement("input"); n.type = "number"; n.step = "any"; n.value = it.reread ?? "";
      n.addEventListener("input", () => { if (n.value === "") delete it.reread; else it.reread = Number(n.value); save(); }); lab.append(n); ans.append(lab); }
    const note = document.createElement("input"); note.type = "text"; note.placeholder = "要改成什么，或者存疑的原因"; note.value = it.note || ""; note.setAttribute("aria-label", r.id + " 的说明");
    note.addEventListener("input", () => { if (note.value.trim()) it.note = note.value.trim(); else delete it.note; save(); });
    ans.append(note); box.append(ans); host.append(box);
  }
  count();
}
function result() {
  const items = {};
  for (const r of DATA.rows) { const it = state.items[r.id] || {}; if (!it.decision) continue;
    const a = {decision: it.decision}; if (it.reread !== undefined) a.reread = it.reread; if (it.note) a.note = it.note; items[r.id] = a; }
  const out = {source_id: DATA.source_id, data_version: DATA.data_version, verifier: document.getElementById("who").value.trim(),
    date: new Date().toISOString().slice(0, 10), items: items};
  const m = document.getElementById("minutes").value;
  if (m !== "") out.minutes = Number(m); else out.minutes_note = "核对时没有记用了几分钟";
  return out;
}
document.getElementById("copy").addEventListener("click", async () => {
  const text = JSON.stringify(result(), null, 1); const box = document.getElementById("out"); box.value = text; box.style.display = "block";
  const msg = document.getElementById("msg");
  try { await navigator.clipboard.writeText(text); msg.textContent = "复制好了，贴回对话里。"; }
  catch (e) { box.focus(); box.select(); msg.textContent = "浏览器不让自动复制：下面的框已经全选，按复制键。"; }
});
document.getElementById("allok").addEventListener("click", () => {
  for (const r of DATA.rows) { const it = state.items[r.id] || (state.items[r.id] = {}); if (!it.decision && !r.figure) it.decision = "ok"; }
  save(); document.getElementById("rows").textContent = ""; render();
});
document.getElementById("minutes").value = state.minutes ?? "";
document.getElementById("minutes").addEventListener("input", e => { state.minutes = e.target.value; save(); });
render();
</script></body></html>
"""


def build_page(ds, source_id, data_version):
    src = A.source(ds, source_id)
    if not src:
        raise VerifyError(f"没有这个来源：{source_id}")
    rows = rows_for_page(ds, source_id)
    labels = {}
    path = os.path.join(A.data_dir(ds), "labels.json")
    if not os.path.exists(path):
        path = os.path.join(V.DEFAULT_DATA, "labels.json")
    with open(path, encoding="utf-8") as f:
        all_labels = json.load(f)
    for k, v in ((all_labels.get("enums") or {}).get("risk_reason") or {}).items():
        labels[k] = (v.get("zh") or v.get("name_zh") or k) if isinstance(v, dict) else str(v)
    data = {"source_id": source_id, "data_version": data_version, "rows": rows}
    title = f"核对单 {source_id}（只留内部）"
    sub = f"{src.get('title', '')}｜{src.get('container', '')}｜等着核对的 {len(rows)} 条，其中图上读数 {sum(1 for r in rows if r['figure'])} 条｜数据版本 {data_version}"

    def js(obj):   # 放进 <script> 里：不让数据里的 </script> 或 <!-- 提前结束脚本
        return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    page = (PAGE.replace("__TITLE__", html.escape(title)).replace("__SUB__", html.escape(sub))
            .replace("__REASONS__", js(labels)).replace("__DATA__", js(data)))
    return page, len(rows)


def apply_answers(ds, schema, answers):
    """把核对结果写进内存里的数据。返回 (说明, 动了的来源, 工作记录)。不合规矩的抛 VerifyError。"""
    if A.problems(ds):
        raise VerifyError("数据里有读不了的文件或重复的编号，先修好再写回")
    sid, who, date = answers.get("source_id"), answers.get("verifier"), answers.get("date")
    if not A.source(ds, sid):
        raise VerifyError(f"没有这个来源：{sid}")
    if not V.is_human(who):
        raise VerifyError("核对的人必须是人（verifier 不能是 claude、script，也不能空着）")
    if not (isinstance(date, str) and len(date) == 10):
        raise VerifyError("要写核对的日期 date（YYYY-MM-DD）")
    minutes, minutes_note = answers.get("minutes"), answers.get("minutes_note")
    if minutes is None and not minutes_note:
        raise VerifyError("要写实际用的分钟数 minutes；当时没记就写 minutes_note")
    items = answers.get("items") or {}
    if not items:
        raise VerifyError("回答里一条也没有")
    before = set(V.validate(ds, schema))
    said, counts = [], {"evidence_verified": 0, "figure_reread": 0, "corrections": 0, "disputed": 0, "left_waiting": 0}
    waiting = []
    for eid in sorted(items):
        a, e = items[eid], A.evidence(ds, eid)
        if not e or e.get("source_id") != sid:
            raise VerifyError(f"{eid} 不是 {sid} 的证据")
        d = a.get("decision")
        if d not in DECISIONS:
            raise VerifyError(f"{eid} 的决定 {d!r} 不认识，只能是 ok、fix、dispute")
        if e.get("verification_status") not in OPEN:
            raise VerifyError(f"{eid} 现在是 {e.get('verification_status')}，不在等着核对的状态里")
        if d == "dispute":
            if not (a.get("note") or "").strip():
                raise VerifyError(f"{eid} 标存疑要写原因 note")
            e["verification_status"] = "disputed"
            store.put_after(e, "dispute_note", a["note"].strip(), ["expert_reviewed_at", "verified_at", "machine_check", "risk"])
            store.put_after(e, "verified_by", who, ["machine_check", "risk"])
            store.put_after(e, "verified_at", date, ["verified_by"])
            counts["disputed"] += 1
            said.append(f"{eid}：存疑")
            continue
        if d == "fix" and not a.get("change_ids"):
            waiting.append(f"{eid}：要改（{a.get('note', '没有写改成什么')}），还没有改，没有写回")
            counts["left_waiting"] += 1
            continue
        if d == "fix":
            known = {c.get("id"): c for c in A.changes(ds)}
            for cid in a["change_ids"]:
                c = known.get(cid)
                if not c or c.get("target_id") != eid or c.get("kind") != "correction":
                    raise VerifyError(f"{eid} 的 change_ids 里的 {cid} 不是这条证据的核验更正")
            counts["corrections"] += 1
        if e.get("obtained_from") == "figure_read":
            if not isinstance(a.get("reread"), (int, float)) or isinstance(a.get("reread"), bool):
                raise VerifyError(f"{eid} 是图上读数，要带核对人自己读的值 reread")
            number = V.parse_number(e.get("value_reported"))
            if number is None:
                raise VerifyError(f"{eid} 的原读数认不出来，算不了读数误差")
            fr = e["figure_read"]
            fr["reread_by"], fr["reread_at"], fr["reread_value"] = who, date, a["reread"]
            fr["reading_error"] = round(abs(number - a["reread"]), 6)
            counts["figure_reread"] += 1
        if not V.machine_check_ok(e):
            waiting.append(f"{eid}：核对人说对，但机器核对没通过，规则（V-27）不让升到人工已核，先留着")
            counts["left_waiting"] += 1
            continue
        if e.get("verification_status") != "disputed":
            e["verification_status"] = "human_verified"
        store.put_after(e, "verified_by", who, ["machine_check", "risk"])
        store.put_after(e, "verified_at", date, ["verified_by"])
        counts["evidence_verified"] += 1
    extra = [i for i in V.validate(ds, schema) if i not in before]
    if extra:
        raise VerifyError("写回之后校验多出了问题，一个字也没有写：" + "；".join(f"{i.rule} {i.record} {i.message}" for i in extra[:8]))
    topic = (A.source(ds, sid).get("topics") or [{}])[0].get("topic_id")
    log = {"id": I.next_ids(ds, "LOG")[0], "date": date, "topic_id": topic, "arm": "C", "step": "verification",
           "actor_kind": "human", "actor": who,
           "summary": f"{sid} 人工核对：人工已核 {counts['evidence_verified']} 条（其中图上读数复读 {counts['figure_reread']} 条、"
                      f"改过的 {counts['corrections']} 条），存疑 {counts['disputed']} 条，留着没写回的 {counts['left_waiting']} 条"}
    if minutes is not None:
        log["minutes"] = minutes
    else:
        log["minutes_note"] = minutes_note
    log["refs"] = [sid]
    log["counts"] = counts
    head = (f"{sid}：人工已核 {counts['evidence_verified']}，图上复读 {counts['figure_reread']}，改过的 {counts['corrections']}，"
            f"存疑 {counts['disputed']}，留着的 {counts['left_waiting']}")
    return [head] + waiting + said, [sid], log


def main(argv=None):
    ap = argparse.ArgumentParser(description="核对单：人工核对用的单子")
    ap.add_argument("--data", default=V.DEFAULT_DATA)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    p = sub.add_parser("page")
    p.add_argument("source")
    p.add_argument("--out", required=True)
    p = sub.add_parser("apply")
    p.add_argument("--answers", required=True)
    p.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    ds = A.load(args.data)
    if args.command == "list":
        for sid in A.source_ids(ds):
            rows = _todo(ds, sid)
            if rows:
                print(f"{sid}：等着核对 {len(rows)} 条，其中图上读数 {sum(1 for e in rows if e.get('obtained_from') == 'figure_read')} 条")
        return 0
    try:
        if args.command == "page":
            import build_dashboard as B
            page, n = build_page(ds, args.source, B.data_version(args.data))
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(page)
            print(f"写出 {args.out}：{n} 条")
            return 0
        try:
            with open(args.answers, encoding="utf-8") as f:
                answers = json.load(f)
        except (OSError, ValueError) as exc:
            print(f"读不了回答文件：{exc}", file=sys.stderr)
            return 2
        said, touched, log = apply_answers(ds, V.load_schema(), answers)
        print("\n".join(said))
        if args.dry_run:
            print("只看不写（--dry-run）")
            return 0
        store.save_sources(ds, touched)
        store.append_worklog(ds, log)
        return 0
    except VerifyError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
