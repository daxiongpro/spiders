# -*- coding: utf-8 -*-
"""step1 · 扫码登录抖音，并把登录态持久化到本地。

为什么要单独一个脚本
    抖音已把「需登录」的接口整体升级到 ArgusSecurityPlugin 风控，
    纯 HTTP + a_bogus 方案实测 403 报废（详见 docs/日志/2026-10-09.md）。
    现在改成「真浏览器在场」：登录一次，登录态存进配置档目录，
    以后所有访问复用同一个配置档，免扫码。

用法
    python -u scripts/step1_login.py                # 弹窗 → 扫码 → 自动保存
    python -u scripts/step1_login.py --timeout 600  # 等待上限改成 10 分钟
    python -u scripts/step1_login.py --reset        # 换账号：先清空旧配置档
    python -u scripts/step1_login.py --no-check     # 跳过登录后的接口探测
    python -u scripts/step1_login.py --keep-open    # 成功后不自动关窗

两条硬约束（不要改）
    1. 必须有窗口（headless=False）。无头会被抖音识别，落到「验证码中间页」。
    2. 用系统已装的 Edge（channel="msedge"）。无需下载任何浏览器。
"""
import argparse
import json
import os
import shutil
import sys
import time
from urllib.parse import urlencode

# 脚本位于 scripts/ 下，项目根 = 脚本目录的上一级；换机器用环境变量覆盖
BASE = os.environ.get("DOUYIN_BASE") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))

# 路径统一由 src/paths.py 提供，不要在脚本里拼路径
sys.path.insert(0, os.path.join(BASE, "src"))
from paths import browser_profile, douyin_dir, webid_file  # noqa: E402

# 代理会阻断抖音（本机有 HTTPS_PROXY），必须在发请求前清掉
for _k in ("https_proxy", "http_proxy", "all_proxy", "ALL_PROXY",
           "HTTPS_PROXY", "HTTP_PROXY"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"

try:  # Windows 控制台默认 GBK，中文会炸
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from playwright.sync_api import sync_playwright  # noqa: E402

DOUYIN_HOME = "https://www.douyin.com/"
PROFILE_DIR = browser_profile()
RESULT_FILE = os.path.join(douyin_dir(), "last_login.txt")

# 登录成功的判据：出现 sessionid（web 端登录态核心 cookie）
LOGIN_COOKIE_KEYS = ("sessionid", "sessionid_ss")
# 浏览器候选：优先系统 Edge，其次 Chrome，最后 playwright 自带 chromium
BROWSER_CANDIDATES = ("msedge", "chrome", None)

_LAUNCH_ARGS = [
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-blink-features=AutomationControlled",
]


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)


def cookie_map(ctx):
    return {c["name"]: c["value"] for c in ctx.cookies()}


def launch(p, profile_dir):
    """按 Edge → Chrome → 内置 chromium 的顺序尝试启动（持久化配置档）。"""
    last = None
    for ch in BROWSER_CANDIDATES:
        try:
            kw = dict(headless=False, args=_LAUNCH_ARGS, locale="zh-CN",
                      viewport={"width": 1280, "height": 800})
            if ch:
                kw["channel"] = ch
            ctx = p.chromium.launch_persistent_context(profile_dir, **kw)
            log("已启动浏览器：%s" % (ch or "playwright 内置 chromium"))
            return ctx
        except Exception as e:  # noqa: BLE001
            last = e
            log("启动 %s 失败：%s" % (ch or "chromium", str(e).split("\n")[0]))
    raise RuntimeError("没有可用浏览器：%s" % last)


def grab_webid(page):
    """从 localStorage 抓 webid（19 位数字），返回 '' 表示没抓到。"""
    try:
        val = page.evaluate("""() => {
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                if (/webid/i.test(k) && /^\\d{15,20}$/.test(localStorage.getItem(k) || ''))
                    return localStorage.getItem(k);
            }
            for (let i = 0; i < localStorage.length; i++) {
                const v = localStorage.getItem(localStorage.key(i)) || '';
                if (/^\\d{19}$/.test(v)) return v;
            }
            return '';
        }""")
        return str(val or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def probe_collections(page, webid, uifid):
    """在页面上下文里调收藏夹接口，验证「登录之后真的能读到收藏夹」。

    只做探测，失败不影响登录结果。
    """
    try:
        from douyin_sign import build_common_params  # 与纯 HTTP 版共用同一套参数
        params = build_common_params(webid)
    except Exception:  # noqa: BLE001
        params = [("device_platform", "webapp"), ("aid", "6383"),
                  ("channel", "channel_pc_web"), ("pc_client_type", "1"),
                  ("version_code", "170400"), ("version_name", "17.4.0"),
                  ("cookie_enabled", "true"), ("screen_width", "1280"),
                  ("screen_height", "800"), ("browser_language", "zh-CN"),
                  ("browser_platform", "Win32"), ("platform", "PC")]
    if webid:
        params = params + [("webid", webid)]
    params = params + [("uifid", uifid or ""), ("cursor", "0"),
                       ("count", "20"), ("update_version_code", "170400")]

    js = """async (qs) => {
        const u = 'https://www.douyin.com/aweme/v1/web/collects/list/?' + qs;
        try {
            const res = await fetch(u, {credentials: 'include',
                headers: {'referer': 'https://www.douyin.com/'}});
            const t = await res.text();
            return {status: res.status, body: t.slice(0, 20000)};
        } catch (e) { return {status: -1, body: String(e)}; }
    }"""
    r = page.evaluate(js, urlencode(params))
    if r.get("status") != 200:
        return "探测未通过：HTTP %s %s" % (r.get("status"), str(r.get("body"))[:200])
    try:
        data = json.loads(r["body"])
    except ValueError:
        return "探测未通过：返回不是 JSON —— %s" % str(r.get("body"))[:200]

    sc = data.get("status_code")
    lst = data.get("collects_list") or []
    if sc == 0 and isinstance(lst, list) and lst:
        lines = ["收藏夹 %d 个：" % len(lst)]
        for c in lst:
            if not isinstance(c, dict):
                continue
            name = c.get("collects_name") or c.get("collects_id")
            num = c.get("total_number") or 0
            lines.append("    %-16s %5s 条   id=%s"
                         % (name, num, c.get("collects_id") or c.get("collects_id_str")))
        return "\n".join(lines)
    return ("探测未返回列表：status_code=%s msg=%s body=%s"
            % (sc, data.get("status_msg"), str(data)[:300]))


def main():
    ap = argparse.ArgumentParser(description="抖音扫码登录（登录态持久化）")
    ap.add_argument("--timeout", type=int, default=300,
                    help="等待扫码的秒数上限，默认 300")
    ap.add_argument("--reset", action="store_true",
                    help="先清空旧配置档再登录（换账号时用）")
    ap.add_argument("--no-check", action="store_true", help="跳过登录后的接口探测")
    ap.add_argument("--keep-open", action="store_true", help="成功后不自动关窗")
    args = ap.parse_args()

    if args.reset and os.path.isdir(PROFILE_DIR):
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)
        log("已清空旧配置档：%s" % PROFILE_DIR)
    os.makedirs(PROFILE_DIR, exist_ok=True)
    os.makedirs(douyin_dir(), exist_ok=True)

    log("配置档目录：%s" % PROFILE_DIR)
    report = []

    with sync_playwright() as p:
        ctx = launch(p, PROFILE_DIR)

        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(DOUYIN_HOME, wait_until="domcontentloaded", timeout=60000)
            try:
                page.bring_to_front()
            except Exception:  # noqa: BLE001
                pass

            ck = cookie_map(ctx)
            if any(k in ck for k in LOGIN_COOKIE_KEYS):
                log("检测到已登录，无需扫码")
            else:
                log("请在弹出的浏览器窗口里扫码登录（等待上限 %d 秒）" % args.timeout)
                log("提示：用抖音 App 扫窗口里的二维码；登录完成后本脚本自动继续")

            deadline = time.time() + args.timeout
            logged_in = any(k in ck for k in LOGIN_COOKIE_KEYS)
            while not logged_in and time.time() < deadline:
                time.sleep(2)
                try:
                    ck = cookie_map(ctx)
                except Exception:  # 窗口被关掉了
                    log("浏览器窗口已关闭，未完成登录")
                    break
                logged_in = any(k in ck for k in LOGIN_COOKIE_KEYS)

            if not logged_in:
                log("未检测到登录态（可能超时或窗口被关闭）")
                report.append("结果：未完成登录")
            else:
                log("登录成功 ✅")
                time.sleep(3)  # 等页面把 UIFID 等附属 cookie 写全
                ck = cookie_map(ctx)
                names = sorted(k for k in ck if k.lower().startswith(("session", "uifid", "sid_guard", "ttwid", "web_sign")))
                log("已获得登录相关 cookie：%s" % ", ".join(names))
                report.append("结果：登录成功")
                report.append("cookie: " + ", ".join(names))

                webid = grab_webid(page)
                if webid:
                    with open(webid_file(), "w", encoding="utf-8") as f:
                        f.write(webid)
                    log("已保存 webid：%s" % webid)
                    report.append("webid: " + webid)

                # 导出 storage_state（便于排查；真正的登录态在配置档目录里）
                try:
                    ss_path = os.path.join(douyin_dir(), "edge_storage_state.json")
                    ctx.storage_state(path=ss_path)
                    log("已导出 storage_state：%s" % ss_path)
                except Exception as e:  # noqa: BLE001
                    log("导出 storage_state 失败：%s" % e)

                if not args.no_check:
                    log("正在探测收藏夹接口…")
                    res = probe_collections(page, webid, ck.get("UIFID", ""))
                    for ln in res.splitlines():
                        log("  " + ln)
                    report.append("收藏夹探测：\n" + res)

                if args.keep_open:
                    log("按 --keep-open，窗口保持打开；手动关掉即可结束")
                    while True:
                        time.sleep(2)
                        try:
                            if not ctx.pages:
                                break
                        except Exception:  # noqa: BLE001
                            break
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass

    text = "\n".join(report)
    try:
        with open(RESULT_FILE, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        log("结果已写入：%s" % RESULT_FILE)
    except OSError:
        pass
    print(text)
    return 0 if text.startswith("结果：登录成功") else 1


if __name__ == "__main__":
    sys.exit(main())
