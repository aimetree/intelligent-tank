#!/usr/bin/env python3
"""查来源的标识能不能解析，写进来源的 id_check（设计方案 6.3 关口 1；规则 V-11）。

这个脚本要联网，放在 GitHub Actions 上跑（.github/workflows/identifiers.yml）；在本机能联网时也可以跑。

每个来源照这个顺序选一种查法（id_check.method）：
  doi_registry  有 DOI：到 DOI 注册处查这个号存不存在（https://doi.org/api/handles/…）。
                只问注册处，不碰出版商的网站。
  member        没有 DOI，是成员下载或在官方系统里代查的（fetched_by 为 member_download、member_lookup）：
                成员取到了，就是存在；不发请求。
  http          其余的：先看网站的 robots.txt 让不让自动访问，让的话打开登记的网址看一眼。
条款禁止自动访问（terms.no_scraping）又不是成员取来的，不查，列出来等人处理。
专利号现在不单独查：没有免费又允许自动查询的官方接口，专利按上面的顺序走（多半是查网址）。

结果有三种：通过、不通过（查无此号、404、410）、没查成（超时、被拒、服务器出错、robots.txt 不让）。
没查成的不写进数据，列在报告里，由人打开确认后再定。

用法
  python3 tools/check_identifiers.py                    查还没有结果或上次不通过的来源，只看结果
  python3 tools/check_identifiers.py --write            写回 data/
  python3 tools/check_identifiers.py --all --write      连查过的也重查
  python3 tools/check_identifiers.py --source SRC-000012 --report report.json
  python3 tools/check_identifiers.py --selftest         自检：真的去注册处查一个存在的号和一个不存在的号

联系方式：环境变量 ID_CHECK_CONTACT 里写一个邮箱或网址，会放进请求的 User-Agent，对方有问题能找到人；不设也能跑。
退出码  0 没有不通过的；1 有不通过的（加 --strict 时没查成的也算）；2 用法不对。
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store  # noqa: E402
import validate as V  # noqa: E402

AGENT = "intelligent-tank-id-check/0.1"
MEMBER_FETCH = ("member_download", "member_lookup")
LABEL = {"pass": "通过", "fail": "不通过", "unknown": "没查成", "skipped": "没有查"}
METHOD_LABEL = {"doi_registry": "DOI 注册处", "member": "成员取得时确认", "http": "打开网址", None: "—"}


def user_agent():
    contact = os.environ.get("ID_CHECK_CONTACT", "").strip()
    return f"{AGENT} ({contact})" if contact else AGENT


def http_get(url, timeout=20, max_bytes=262144):
    """发一个 GET，返回 (状态码, 正文的前一段)。连不上、超时会抛异常。"""
    req = urllib.request.Request(url, headers={"User-Agent": user_agent(), "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(max_bytes)
    except urllib.error.HTTPError as exc:
        return exc.code, (exc.read(max_bytes) if exc.fp else b"")


def clean_doi(doi):
    d = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/", "doi:"):
        if d.lower().startswith(prefix):
            d = d[len(prefix):]
    return d


def plan(source):
    """这个来源用哪种查法。返回 (查法, 说明)；查法是 None 就是不查。"""
    ids = source.get("identifiers") or {}
    if ids.get("doi"):
        return "doi_registry", ""
    if source.get("fetched_by") in MEMBER_FETCH:
        return "member", ""
    if (source.get("terms") or {}).get("no_scraping"):
        return None, "条款禁止自动访问，又不是成员取来的"
    url = source.get("url") or ""
    if url.lower().startswith(("http://", "https://")):
        return "http", ""
    return None, "没有可以查的标识（DOI 或网址）"


def check_doi(doi, get):
    """到 DOI 注册处查这个号。responseCode 1 是查到了，100 是查无此号。"""
    url = "https://doi.org/api/handles/" + urllib.parse.quote(clean_doi(doi), safe="/")
    try:
        status, body = get(url)
    except Exception as exc:  # 连不上、超时
        return "unknown", f"注册处没连上（{type(exc).__name__}）"
    try:
        code = json.loads(body.decode("utf-8", "replace")).get("responseCode")
    except (ValueError, AttributeError):
        code = None
    if status == 200 and code == 1:
        return "pass", ""
    if code == 100 or (status == 404 and code is None):
        return "fail", "DOI 注册处查无此号"
    return "unknown", f"注册处返回 HTTP {status}" + (f"、responseCode {code}" if code is not None else "")


class Robots:
    """各网站的 robots.txt，一个网站只取一次。allowed() 返回 True、False，或 None（robots.txt 没读成）。"""

    def __init__(self, get):
        self.get, self.cache = get, {}

    def allowed(self, url):
        parts = urllib.parse.urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self.cache:
            rp = urllib.robotparser.RobotFileParser()
            try:
                status, body = self.get(base + "/robots.txt")
            except Exception:
                rp = None
            else:
                if status in (401, 403):
                    rp.disallow_all = True
                elif 400 <= status < 500:
                    rp.allow_all = True          # 没有 robots.txt：没有限制
                elif status >= 500:
                    rp = None
                else:
                    rp.parse(body.decode("utf-8", "replace").splitlines())
            self.cache[base] = rp
        rp = self.cache[base]
        return None if rp is None else rp.can_fetch(AGENT, url)


def check_url(url, get, robots):
    ok = robots.allowed(url)
    if ok is None:
        return "unknown", "robots.txt 没读成，没有去打开网址"
    if not ok:
        return "unknown", "网站的 robots.txt 不让自动访问，要人打开确认"
    try:
        status, _ = get(url)
    except Exception as exc:
        return "unknown", f"没连上（{type(exc).__name__}）"
    if 200 <= status < 300:
        return "pass", ""
    if status in (404, 410):
        return "fail", f"网址打不开（HTTP {status}）"
    return "unknown", f"HTTP {status}"


def run(ds, get=http_get, at=None, sources=None, recheck=False, pause=1.0, sleep=time.sleep):
    """查 ds 里的来源，通过和不通过的直接写在 ds 上。返回 (逐个来源的结果, 改动了的来源编号)。"""
    at = at or store.today()
    robots = Robots(get)
    rows, touched, asked = [], set(), False
    recheck = recheck or bool(sources)   # 点名要查的来源，查过的也重查
    for sid in sorted(ds["sources"]):
        s = ds["sources"][sid]
        old = s.get("id_check") or {}
        if sources and sid not in sources:
            continue
        if not recheck and old.get("result") == "pass":
            continue
        method, note = plan(s)
        if method is None:
            result = "skipped"
        elif method == "member":
            result = "pass"
        else:
            if asked and pause:
                sleep(pause)   # 一个接一个慢慢查，不给对方添负担
            asked = True
            if method == "doi_registry":
                result, note = check_doi(s["identifiers"]["doi"], get)
            else:
                result, note = check_url(s["url"], get, robots)
        if result in ("pass", "fail"):
            new = {"result": result, "at": at, "method": method}
            same = (old.get("result"), old.get("method")) == (result, method)
            if old != new and (recheck or not same):   # 没重查、结果也没变的，日期不动
                s["id_check"] = new
                touched.add(sid)
        rows.append({"id": sid, "title": s.get("title", ""), "method": method, "result": result, "note": note})
    return rows, touched


SELFTEST_FOUND = "10.1000/1"                                # DOI 手册里的示例号，注册处的文档拿它举例
SELFTEST_MISSING = "10.1000/intelligent-tank-no-such-doi"   # 不存在的号


def selftest(get=http_get):
    """自检：存在的号要查得到，不存在的号要查不到。两样都对，才说明这条查法现在还管用
    （注册处改了接口、网络被挡，都会在这里露出来，而不是把结果写错）。返回 [(说明, 对不对, 细节)]。"""
    out = []
    for name, doi, want in (("存在的号查得到", SELFTEST_FOUND, "pass"), ("不存在的号查不到", SELFTEST_MISSING, "fail")):
        result, note = check_doi(doi, get)
        out.append((name, result == want, f"{doi} → {LABEL[result]}" + (f"（{note}）" if note else "")))
    return out


def markdown(rows):
    """给 GitHub Actions 的运行摘要用的一张表。"""
    lines = ["### 标识解析", "", "| 来源 | 题名 | 查法 | 结果 | 说明 |", "|---|---|---|---|---|"]
    for r in rows:
        title = str(r["title"]).replace("|", "\\|")[:60]
        lines.append(f"| {r['id']} | {title} | {METHOD_LABEL[r['method']]} | {LABEL[r['result']]} | {r['note']} |")
    if not rows:
        lines.append("| — | 没有要查的来源 | — | — | — |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="查来源的标识能不能解析")
    ap.add_argument("--data", default=V.DEFAULT_DATA, help="数据目录，默认是仓库里的 data/")
    ap.add_argument("--source", nargs="*", default=[], metavar="SRC-编号", help="只查这些来源（查过的也重查）")
    ap.add_argument("--all", action="store_true", help="连已经通过的也重查")
    ap.add_argument("--write", action="store_true", help="把结果写回 data/；不加只看结果")
    ap.add_argument("--date", default=store.today(), help="检查日期，默认今天")
    ap.add_argument("--report", help="把逐个来源的结果写成 JSON 文件")
    ap.add_argument("--summary", help="把结果表（Markdown）追加到这个文件，给 GitHub Actions 的运行摘要用")
    ap.add_argument("--strict", action="store_true", help="没查成、没有查的也算失败")
    ap.add_argument("--selftest", action="store_true", help="只做自检，不查数据")
    args = ap.parse_args(argv)
    if args.selftest:
        results = selftest(http_get)
        for name, ok, detail in results:
            print(f"{'对' if ok else '不对'}  {name}：{detail}")
        return 0 if all(ok for _, ok, _ in results) else 1
    if not os.path.isdir(args.data):
        print(f"找不到数据目录：{args.data}", file=sys.stderr)
        return 2
    ds = V.load_dataset(args.data)
    unknown = [s for s in args.source if s not in ds["sources"]]
    if unknown:
        print(f"没有这些来源：{'、'.join(unknown)}", file=sys.stderr)
        return 2
    rows, touched = run(ds, get=http_get, at=args.date, sources=set(args.source), recheck=args.all)
    for r in rows:
        print(f"{LABEL[r['result']]}  {r['id']}（{METHOD_LABEL[r['method']]}）" + (f"：{r['note']}" if r["note"] else ""))
    n = {k: sum(1 for r in rows if r["result"] == k) for k in LABEL}
    print(f"查了 {len(rows)} 个来源：通过 {n['pass']}，不通过 {n['fail']}，没查成 {n['unknown']}，没有查 {n['skipped']}")
    if args.report:
        store.write_json(args.report, {"at": args.date, "results": rows})
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write(markdown(rows))
    if args.write:
        written = store.save_sources(ds, touched)
        print(f"写回了 {len(written)} 个来源文件" + (f"：{'、'.join(written)}" if written else ""))
    elif touched:
        print(f"有 {len(touched)} 个来源文件会改动；没有写回（加 --write 才写）")
    bad = n["fail"] + (n["unknown"] + n["skipped"] if args.strict else 0)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
