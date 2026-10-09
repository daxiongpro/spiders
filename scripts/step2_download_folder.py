# -*- coding: utf-8 -*-
"""step2 · 把一个收藏夹分类里的视频全部下载到本地。

为什么不用纯 HTTP
    抖音已把「需登录」的接口整体升级到 ArgusSecurityPlugin 风控：
    同一条 /collects/list/ 纯 HTTP 是 403，在浏览器页面上下文里是 200
    （实测见 docs/日志/2026-10-09.md）。所以访问层必须让真浏览器在场 ——
    本脚本沿用 step1 的配置档，所有接口调用都在页面里 fetch，
    签名由页面自身的 JS 生成，我们只做编排。

前置条件
    先跑一次 scripts/step1_login.py 完成扫码登录（登录态落在
    output/douyin/edge_profile，长期免扫）。没登录时本脚本也会等扫码。

用法
    python -u scripts/step2_download_folder.py                      # 交互式选收藏夹
    python -u scripts/step2_download_folder.py --list               # 只看有哪些收藏夹
    python -u scripts/step2_download_folder.py --check --folder 搞钱  # 只比对本地，不下载
    python -u scripts/step2_download_folder.py --folder 搞钱·事业     # 下载该收藏夹全部视频
    python -u scripts/step2_download_folder.py --folder 搞钱 --limit 5        # 先试 5 条
    python -u scripts/step2_download_folder.py --list-videos --folder 搞钱    # 只看清单不下
    python -u scripts/step2_download_folder.py --folder-id 1234567890       # 直接指定夹 id

增量下载（重复运行很安全）
    判定「已经下过」的唯一依据是 aweme_id，不是文件名：
    `_manifest.json` 记了每条 aweme_id → 本地文件名，脚本先把清单和磁盘
    两头都核一遍（文件在不在、够不够大、文件头是不是 MP4），三个都过才算
    已下载。所以：
      - 收藏夹新增视频 → 只下新增的那几条
      - 上次下到一半断掉 → 那几条会被判为「没下好」，自动重下
      - 手滑把某个 mp4 删了 → 下次运行会自动补齐
      - 收藏夹顺序变了导致序号位移 → 不影响判定（认 aweme_id）
    `--check` 只比对不下载，用来先看「已有哪些、缺哪些」。

输出（目录由 src/paths.py 决定，可用 DOUYIN_DOWNLOADS 覆盖根目录）
    output/downloads/<收藏夹名>/<序号>_<标题>.mp4     视频本体
    output/downloads/<收藏夹名>/_manifest.json       逐条状态（断点续传的依据）
    output/downloads/<收藏夹名>/_manifest.csv        同上，Excel 可直接打开
    output/downloads/<收藏夹名>/_下载报告.txt          本次运行摘要

两条硬约束（不要改，与 step1 一致）
    1. 必须有窗口（headless=False）。无头会被抖音识别并落到「验证码中间页」。
    2. 用系统已装的 Edge（channel="msedge"）。无需下载任何浏览器。

只用于整理本人账号自己的收藏数据，脚本内置请求间隔，不做高频采集。
"""
import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import urlencode

# 脚本位于 scripts/ 下，项目根 = 脚本目录的上一级；换机器用环境变量覆盖
BASE = os.environ.get("DOUYIN_BASE") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))

# 路径统一由 src/paths.py 提供，不要在脚本里拼路径
sys.path.insert(0, os.path.join(BASE, "src"))
from paths import (browser_profile, douyin_dir, downloads_dir,  # noqa: E402
                   trash_dir, webid_file)

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
API_PREFIX = "https://www.douyin.com/aweme/v1/web"
PROFILE_DIR = browser_profile()
REPORT_FILE = "_下载报告.txt"
MANIFEST_JSON = "_manifest.json"
MANIFEST_CSV = "_manifest.csv"

# 登录成功的判据：出现 sessionid（web 端登录态核心 cookie）
LOGIN_COOKIE_KEYS = ("sessionid", "sessionid_ss")
# 浏览器候选：优先系统 Edge，其次 Chrome，最后 playwright 自带 chromium
BROWSER_CANDIDATES = ("msedge", "chrome", None)

_LAUNCH_ARGS = [
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-blink-features=AutomationControlled",
]

# 小于这个字节数视为坏文件（正常的抖音视频都是几百 KB 起步）
MIN_VIDEO_BYTES = 10 * 1024
# 下载失败时重试次数（换下一个直链算一次）
DOWNLOAD_RETRIES = 2

_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_WS = re.compile(r"\s+")

# 收藏夹列表：只把需要的字段带出页面，避免把整个响应体搬到 Python 侧
JS_COLLECTS = """async (url) => {
    try {
        const res = await fetch(url, {credentials: 'include'});
        const txt = await res.text();
        if (res.status !== 200) return {status: res.status, body: txt.slice(0, 800)};
        let d;
        try { d = JSON.parse(txt); } catch (e) { return {status: -2, body: txt.slice(0, 800)}; }
        const raw = d.collects_list || [];
        const list = raw.map(it => {
            const c = (it && it.collects_info) ? it.collects_info : (it || {});
            return {
                id: String(c.collects_id || c.collects_id_str || ''),
                name: c.collects_name || '',
                total: Number(c.total_number || 0)
            };
        }).filter(c => c.id);
        return {
            status: 200, code: d.status_code, msg: d.status_msg || '',
            has_more: !!(d.has_more || d.has_more_collects), cursor: d.cursor || 0,
            list: list
        };
    } catch (e) { return {status: -1, body: String(e)}; }
}"""

# 收藏夹视频列表：同样只回传下载需要的字段
# 注意：部分响应把 aweme 包在 aweme_info 里，这里两种都兼容
JS_VIDEOS = """async (url) => {
    try {
        const res = await fetch(url, {credentials: 'include'});
        const txt = await res.text();
        if (res.status !== 200) return {status: res.status, body: txt.slice(0, 800)};
        let d;
        try { d = JSON.parse(txt); } catch (e) { return {status: -2, body: txt.slice(0, 800)}; }
        const raw = d.aweme_list || [];
        const list = raw.map(it => {
            const a = (it && it.aweme_info) ? it.aweme_info : (it || {});
            const v = a.video || {};
            const urls = o => (o && o.url_list) ? o.url_list : [];
            return {
                aweme_id: String(a.aweme_id || a.aweme_id_str || ''),
                desc: a.desc || '',
                author: (a.author && (a.author.nickname || a.author.unique_id)) || '',
                create_time: Number(a.create_time || 0),
                duration: Number(v.duration || 0),
                is_image: !!(a.images && a.images.length),
                size: Number((v.play_addr && v.play_addr.data_size) || 0),
                play_h264: urls(v.play_addr_h264),
                play: urls(v.play_addr),
                play_byte: urls(v.play_addr_bytevc1)
            };
        }).filter(a => a.aweme_id);
        return {
            status: 200, code: d.status_code, msg: d.status_msg || '',
            has_more: !!d.has_more, cursor: d.cursor || 0, list: list
        };
    } catch (e) { return {status: -1, body: String(e)}; }
}"""

# 详情接口：列表里带的直链过期时用它刷新
JS_DETAIL = """async (url) => {
    try {
        const res = await fetch(url, {credentials: 'include'});
        const txt = await res.text();
        if (res.status !== 200) return {status: res.status, body: txt.slice(0, 800)};
        let d;
        try { d = JSON.parse(txt); } catch (e) { return {status: -2, body: txt.slice(0, 800)}; }
        const a = d.aweme_detail || d.aweme || {};
        const v = a.video || {};
        const urls = o => (o && o.url_list) ? o.url_list : [];
        return {
            status: 200, code: d.status_code, msg: d.status_msg || '',
            play_h264: urls(v.play_addr_h264), play: urls(v.play_addr),
            play_byte: urls(v.play_addr_bytevc1)
        };
    } catch (e) { return {status: -1, body: String(e)}; }
}"""


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def safe_name(text, maxlen=60):
    """把标题/收藏夹名清洗成合法的 Windows 文件名。

    顺序有讲究：先压空白再换非法字符。反过来的话，\n 和 \t 会先被
    _BAD_CHARS 命中变成下划线，得到 "a __ b" 这种脏名字。
    """
    s = _WS.sub(" ", str(text or "")).strip()  # 换行/制表符等先压成单空格
    s = _BAD_CHARS.sub("_", s).strip()
    s = s.strip(". ")  # Windows 不允许结尾是点或空格
    if len(s) > maxlen:
        s = s[:maxlen].strip(". ")
    return s or "未命名"


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


def ensure_login(ctx, page, timeout):
    """确认登录态；没登录就在窗口里等扫码。返回 (已登录, webid, uifid)。"""
    ck = cookie_map(ctx)
    logged = any(k in ck for k in LOGIN_COOKIE_KEYS)
    if not logged:
        log("检测到未登录 —— 请在刚弹出的窗口里扫码（等待上限 %d 秒）" % timeout)
        log("提示：也可以单独跑 scripts/step1_login.py 完成登录，之后长期免扫")
        deadline = time.time() + timeout
        while not logged and time.time() < deadline:
            time.sleep(2)
            try:
                ck = cookie_map(ctx)
            except Exception:  # noqa: BLE001
                log("浏览器窗口已关闭，未完成登录")
                return False, "", ""
            logged = any(k in ck for k in LOGIN_COOKIE_KEYS)
    if not logged:
        log("未检测到登录态（超时或窗口被关闭）")
        return False, "", ""

    time.sleep(3)  # 等页面把 UIFID 等附属 cookie 写全
    ck = cookie_map(ctx)
    webid = ""
    try:
        if os.path.exists(webid_file()):
            with open(webid_file(), encoding="utf-8") as f:
                v = f.read().strip()
            if v.isdigit():
                webid = v
    except OSError:
        pass
    if not webid:
        webid = grab_webid(page)
        if webid:
            try:
                os.makedirs(douyin_dir(), exist_ok=True)
                with open(webid_file(), "w", encoding="utf-8") as f:
                    f.write(webid)
                log("已保存 webid：%s" % webid)
            except OSError:
                pass
    log("登录态就绪（webid=%s, sessionid=%s）"
        % (webid or "未知", "有" if "sessionid" in ck else "无"))
    return True, webid, ck.get("UIFID", "")


def build_params(webid, uifid, extra):
    """与 step1 一致的公共参数；douyin_sign 不可用时退回内置默认值。"""
    try:
        from douyin_sign import build_common_params
        params = list(build_common_params(webid))
    except Exception:  # noqa: BLE001
        params = [("device_platform", "webapp"), ("aid", "6383"),
                  ("channel", "channel_pc_web"), ("pc_client_type", "1"),
                  ("version_code", "170400"), ("version_name", "17.4.0"),
                  ("cookie_enabled", "true"), ("screen_width", "1280"),
                  ("screen_height", "800"), ("browser_language", "zh-CN"),
                  ("browser_platform", "Win32"), ("platform", "PC")]
    if webid:
        params.append(("webid", webid))
    params.append(("uifid", uifid or ""))
    params.extend(extra)
    params.append(("update_version_code", "170400"))
    return params


def fetch(page, js, path, params, what, retries=3):
    """在页面上下文里 GET 抖音接口，返回解析后的 dict（失败抛 RuntimeError）。"""
    url = API_PREFIX + path + "?" + urlencode(params)
    last = ""
    for attempt in range(1, retries + 1):
        r = page.evaluate(js, url)
        st = r.get("status")
        if st == 200:
            if r.get("code") not in (0, None):
                last = "status_code=%s %s" % (r.get("code"), r.get("msg") or "")
            else:
                return r
        else:
            last = "HTTP %s %s" % (st, str(r.get("body"))[:200])
        if attempt < retries:
            log("  %s 第 %d 次失败（%s），重试…" % (what, attempt, last))
            time.sleep(1.5 * attempt)
    raise RuntimeError("%s 获取失败：%s" % (what, last))


def list_collections(page, webid, uifid, page_delay=0.6):
    """拉全部收藏夹： [{"id","name","total"}]。"""
    out, cursor, guard = [], 0, 0
    while True:
        data = fetch(page, JS_COLLECTS, "/collects/list/",
                     build_params(webid, uifid, [("cursor", str(cursor)), ("count", "20")]),
                     "收藏夹列表")
        out.extend(data.get("list") or [])
        if not data.get("has_more"):
            break
        new_cursor = int(data.get("cursor") or 0)
        if new_cursor == cursor:
            break
        cursor = new_cursor
        guard += 1
        if guard > 200:
            break
        time.sleep(page_delay)
    # 同名夹去重（抖音偶尔返回重复项）
    seen, uniq = set(), []
    for c in out:
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        uniq.append(c)
    return uniq


def list_videos(page, webid, uifid, cid, count, limit, page_delay=0.6):
    """分页拉某收藏夹的全部视频条目。"""
    out, cursor, page_no, guard = [], 0, 0, 0
    while True:
        data = fetch(page, JS_VIDEOS, "/collects/video/list/",
                     build_params(webid, uifid, [("collects_id", str(cid)),
                                                 ("collects_id_str", str(cid)),
                                                 ("cursor", str(cursor)),
                                                 ("count", str(count))]),
                     "视频列表")
        got = data.get("list") or []
        out.extend(got)
        page_no += 1
        log("  第 %d 页：+%d 条，累计 %d 条" % (page_no, len(got), len(out)))
        if limit and len(out) >= limit:
            return out[:limit]
        if not data.get("has_more") or not got:
            break
        new_cursor = int(data.get("cursor") or 0)
        if new_cursor == cursor:
            break
        cursor = new_cursor
        guard += 1
        if guard > 500:
            break
        time.sleep(page_delay)
    return out


def detail_urls(page, webid, uifid, aweme_id):
    """直链失效时用详情接口刷新，返回候选 URL 列表。"""
    try:
        d = fetch(page, JS_DETAIL, "/aweme/detail/",
                  build_params(webid, uifid, [("aweme_id", str(aweme_id))]),
                  "视频详情", retries=2)
    except RuntimeError as e:
        log("    详情刷新失败：%s" % e)
        return []
    return list(d.get("play_h264") or []) + list(d.get("play") or []) + \
        list(d.get("play_byte") or [])


def candidate_urls(aweme):
    """按「无水印 h264 → 默认 → bytevc1」的顺序排候选直链。"""
    seen, out = set(), []
    for key in ("play_h264", "play", "play_byte"):
        for u in aweme.get(key) or []:
            if u and u not in seen:
                seen.add(u)
                out.append(u)
    return out


def looks_like_mp4(data):
    """校验确实是 MP4：文件头里带 ftyp box。"""
    return len(data) > MIN_VIDEO_BYTES and b"ftyp" in data[:64]


def local_video_ok(path, expect_size=0):
    """本地文件是不是一个「已经下好的成品」。返回 (是否完好, 实际字节数)。

    三道关，缺一不可 —— 只看「文件存在」会漏掉两种真实故障：
      1. 存在且大于 MIN_VIDEO_BYTES（防 0 字节 / 半截文件）
      2. 文件头带 ftyp（防把 403 的 HTML 错误页当 mp4 存下来）
      3. 远端声明了大小就顺带对一下，小于 95% 视为没下完
         （只卡「明显偏小」，因为 h264 版通常比 play_addr 更大，不算异常）
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return False, 0
    if size <= MIN_VIDEO_BYTES:
        return False, size
    if expect_size and size < expect_size * 0.95:
        return False, size
    try:
        with open(path, "rb") as f:
            head = f.read(64)
    except OSError:
        return False, size
    if b"ftyp" not in head:
        return False, size
    return True, size


def discard_bad(path, folder):
    """把确认损坏的残骸移进回收站目录（项目约定：不直接删，往 _trash 移）。

    只对「刚被 local_video_ok 判定为损坏」的那一个文件调用，
    且用时间戳后缀避免覆盖回收站里的旧残骸 —— 脚本里不做任何删除动作。
    """
    try:
        dest_dir = os.path.join(trash_dir(), "downloads", safe_name(folder))
        os.makedirs(dest_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(dest_dir, "%s.%s.bad" % (os.path.basename(path), stamp))
        os.replace(path, dest)
        log("    已把残骸移入回收站：%s" % dest)
        return True
    except OSError as e:
        log("    移入回收站失败（不影响继续，会被新文件覆盖）：%s" % e)
        return False


def scan_local(out_dir):
    """盘点本地已下载情况，返回 (state, order, stats)。

    主键是 aweme_id。manifest 记了「aweme_id → 文件名」的映射，
    所以判断依据不是文件名、也不是序号 —— 收藏夹顺序变了也不影响。

    只信「manifest 有记录 + 磁盘上文件确实完好」双重确认：
      - 两边都有 → 算已下载
      - 记录在、文件没了或坏了 → 当作没下过（本次会重下）
      - 文件在、没记录（比如手工拷进来的）→ 无法对应 aweme_id，
        只统计数量提醒，不参与跳过判断
    """
    state, order, seen = {}, [], set()
    checked = 0
    mpath = os.path.join(out_dir, MANIFEST_JSON)
    if os.path.exists(mpath):
        try:
            with open(mpath, encoding="utf-8") as f:
                items = json.load(f).get("items") or []
        except (OSError, ValueError):
            items = []
        for e in items:
            aid = str(e.get("aweme_id") or "")
            if not aid or aid in seen:
                continue
            checked += 1
            fname = e.get("file") or ""
            good, size = (False, 0)
            if fname and e.get("status") in ("ok", "skip"):
                good, size = local_video_ok(os.path.join(out_dir, fname))
            if good:
                e["status"] = "skip"
                e["note"] = "本地已存在"
                e["size_kb"] = size // 1024
                state[aid] = e
                order.append(aid)
                seen.add(aid)

    # 磁盘上「完好但没记录」的 mp4 数量，用来提示人工放进来的文件
    # （坏的/半截的不算 —— 它们要么会被重下覆盖，要么本就是垃圾）
    disk = 0
    try:
        for name in os.listdir(out_dir):
            if name.lower().endswith(".mp4") and local_video_ok(
                    os.path.join(out_dir, name))[0]:
                disk += 1
    except OSError:
        pass
    return state, order, {"recorded": checked, "known": len(state),
                          "stale": checked - len(state), "disk": disk}


def download_video(ctx, page, webid, uifid, aweme, out_path):
    """下载单个视频。返回 (status, size, note)，status ∈ ok/fail。"""
    urls = candidate_urls(aweme)
    if not urls:
        urls = detail_urls(page, webid, uifid, aweme["aweme_id"])
    if not urls:
        return "fail", 0, "拿不到播放直链"

    last = ""
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        if attempt > 1:  # 重试前刷新直链（CDN 链接带过期参数）
            fresh = detail_urls(page, webid, uifid, aweme["aweme_id"])
            urls = fresh or urls
        for url in urls:
            try:
                resp = ctx.request.get(
                    url, headers={"Referer": DOUYIN_HOME}, timeout=180000)
            except Exception as e:  # noqa: BLE001
                last = "请求异常 %s" % str(e).split("\n")[0]
                continue
            if not resp.ok:
                last = "HTTP %s" % resp.status
                continue
            try:
                data = resp.body()
            except Exception as e:  # noqa: BLE001
                last = "读取响应失败 %s" % str(e).split("\n")[0]
                continue
            if not looks_like_mp4(data):
                last = "返回内容不是视频（%d 字节）" % len(data)
                continue
            tmp = out_path + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, out_path)  # 先写临时文件再改名，避免半截文件被当成品
            return "ok", len(data), ""
        if attempt < DOWNLOAD_RETRIES:
            log("    下载失败（%s），刷新直链后重试…" % last)
            time.sleep(2)
    return "fail", 0, last or "未知原因"


def write_manifest(out_dir, state, order):
    """写 json + csv（增量覆盖，中断后仍能续传）。"""
    rows = []
    for aid in order:
        e = state.get(aid)
        if e:
            rows.append(e)
    for aid, e in state.items():
        if aid not in order:
            rows.append(e)
    try:
        with open(os.path.join(out_dir, MANIFEST_JSON), "w", encoding="utf-8") as f:
            json.dump({"updated": datetime.now().isoformat(timespec="seconds"),
                       "count": len(rows), "items": rows}, f,
                      ensure_ascii=False, indent=1)
    except OSError:
        pass
    try:
        # utf-8-sig：Excel 直接双击打开不乱码
        with open(os.path.join(out_dir, MANIFEST_CSV), "w", encoding="utf-8-sig",
                  newline="") as f:
            w = csv.writer(f)
            w.writerow(["序号", "aweme_id", "标题", "作者", "时长秒", "状态",
                        "大小KB", "文件名", "备注", "更新时间"])
            for e in rows:
                w.writerow([e.get("seq", ""), e.get("aweme_id", ""), e.get("title", ""),
                            e.get("author", ""), e.get("duration", ""), e.get("status", ""),
                            e.get("size_kb", ""), e.get("file", ""), e.get("note", ""),
                            e.get("ts", "")])
    except OSError:
        pass


def pick_collection(cols, name, cid):
    """按 id 或名称（精确 → 部分匹配）定位收藏夹，返回 dict 或 None。"""
    if cid:
        for c in cols:
            if c["id"] == str(cid):
                return c
        return {"id": str(cid), "name": "收藏夹_%s" % cid, "total": 0}
    if not name:
        return None
    for c in cols:
        if c["name"] == name:
            return c
    hits = [c for c in cols if name.lower() in (c["name"] or "").lower()]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        log("「%s」匹配到多个收藏夹，请用更完整的名称：" % name)
        for c in hits:
            log("    %-16s %5d 条   id=%s" % (c["name"], c["total"], c["id"]))
        return None
    return None


def print_collections(cols):
    if not cols:
        print("（没有读到任何收藏夹）", flush=True)
        return
    print("收藏夹 %d 个：" % len(cols), flush=True)
    for i, c in enumerate(cols, 1):
        print("  %2d) %-20s %5d 条   id=%s"
              % (i, c["name"] or "(未命名)", c["total"], c["id"]), flush=True)


def ask_folder(cols):
    """交互式选收藏夹；非交互环境（无 stdin）返回 None。"""
    print_collections(cols)
    try:
        raw = input("\n输入序号或收藏夹名称（回车退出）：").strip()
    except (EOFError, KeyboardInterrupt):
        print("", flush=True)
        return None
    if not raw:
        return None
    if raw.isdigit():
        idx = int(raw)
        if 1 <= idx <= len(cols):
            return cols[idx - 1]
        print("序号超出范围", flush=True)
        return None
    return pick_collection(cols, raw, "")


def main():
    ap = argparse.ArgumentParser(
        description="把一个抖音收藏夹分类里的视频全部下载到本地")
    ap.add_argument("--folder", help="收藏夹名称（支持部分匹配）")
    ap.add_argument("--folder-id", help="直接指定收藏夹 id（collects_id）")
    ap.add_argument("--list", action="store_true", help="只列出所有收藏夹，不下载")
    ap.add_argument("--list-videos", action="store_true",
                    help="只列出该收藏夹的视频清单，不下载")
    ap.add_argument("--check", action="store_true",
                    help="只比对本地已下载情况（列出缺哪些），不下载")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（0=全部）")
    ap.add_argument("--count", type=int, default=20, help="每页条数，默认 20")
    ap.add_argument("--delay", type=float, default=1.0, help="每个视频下载后的间隔秒数")
    ap.add_argument("--page-delay", type=float, default=0.6, help="翻页间隔秒数")
    ap.add_argument("--overwrite", action="store_true", help="已存在的文件也重新下载")
    ap.add_argument("--timeout", type=int, default=180, help="等待扫码的秒数上限")
    ap.add_argument("--keep-open", action="store_true", help="结束后不自动关窗")
    args = ap.parse_args()

    os.makedirs(PROFILE_DIR, exist_ok=True)
    log("配置档目录：%s" % PROFILE_DIR)

    report = []
    code = 0
    summary = "本次未产生下载"

    with sync_playwright() as p:
        ctx = launch(p, PROFILE_DIR)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(DOUYIN_HOME, wait_until="domcontentloaded", timeout=60000)
            try:
                page.bring_to_front()
            except Exception:  # noqa: BLE001
                pass

            logged, webid, uifid = ensure_login(ctx, page, args.timeout)
            if not logged:
                log("未登录，退出。请先跑 scripts/step1_login.py")
                return 1

            log("正在读取收藏夹列表…")
            cols = list_collections(page, webid, uifid, args.page_delay)
            if args.list:
                print_collections(cols)
                return 0

            target = pick_collection(cols, args.folder, args.folder_id)
            if target is None and not args.folder and not args.folder_id:
                target = ask_folder(cols)  # 没给参数时交互式选
            if target is None:
                if args.folder or args.folder_id:
                    log("没找到匹配的收藏夹，用 --list 看全部名称")
                    return 2
                log("未选择收藏夹，退出")
                return 0

            log("目标收藏夹：%s（接口报 %d 条）id=%s"
                % (target["name"] or "(未命名)", target["total"], target["id"]))

            log("正在拉取视频清单…")
            videos = list_videos(page, webid, uifid, target["id"],
                                 args.count, args.limit, args.page_delay)

            out_dir = downloads_dir(safe_name(target["name"] or target["id"]))
            os.makedirs(out_dir, exist_ok=True)
            log("视频清单共 %d 条，输出目录：%s" % (len(videos), out_dir))

            if args.list_videos:
                for i, a in enumerate(videos, 1):
                    print("%3d  %-22s %6.0fs  %s"
                          % (i, a["aweme_id"], a["duration"] / 1000.0,
                             (a["desc"] or "(无标题)")[:48]), flush=True)
                return 0

            if target["total"] and len(videos) < target["total"]:
                log("提示：接口报 %d 条，实际取到 %d 条，可能有下架/私密视频"
                    % (target["total"], len(videos)))

            # 增量：先盘点本地（manifest 记录 + 磁盘文件双重校验）
            state, order, lstat = scan_local(out_dir)
            if lstat["recorded"]:
                log("历史记录 %d 条：可用 %d，失效（文件缺失或损坏）%d"
                    % (lstat["recorded"], lstat["known"], lstat["stale"]))
            if lstat["disk"] > lstat["known"]:
                log("提示：目录里有 %d 个 mp4 没有对应记录（可能是手工放进来的）"
                    % (lstat["disk"] - lstat["known"]))

            if args.check:
                missing = [a for a in videos if a["aweme_id"] not in state]
                n_img = sum(1 for a in missing if a["is_image"])
                todo = [a for a in missing if not a["is_image"]]
                print("收藏夹：%s（接口报 %d 条，实际 %d 条）"
                      % (target["name"], target["total"], len(videos)), flush=True)
                print("已下载：%d 条" % len(state), flush=True)
                print("缺失：%d 条（图集 %d 条不算视频，需下载 %d 条）"
                      % (len(missing), n_img, len(todo)), flush=True)
                if todo:
                    print("\n待下载清单：", flush=True)
                    for i, a in enumerate(todo, 1):
                        print("  %3d  %-22s %6.0fs  %s"
                              % (i, a["aweme_id"], a["duration"] / 1000.0,
                                 (a["desc"] or "(无标题)")[:48]), flush=True)
                else:
                    print("\n该收藏夹已全部下载完毕。", flush=True)
                return 0

            ok = skip = fail = img = 0
            t0 = time.time()
            width = len(str(len(videos)))
            for idx, aweme in enumerate(videos, 1):
                aid = aweme["aweme_id"]
                seq = "%0*d" % (max(width, 2), idx)
                title = safe_name(aweme["desc"] or aweme["author"] or aid)
                fname = "%s_%s.mp4" % (seq, title)
                path = os.path.join(out_dir, fname)
                head = "[%d/%d] %s" % (idx, len(videos), title[:36])
                ts = datetime.now().isoformat(timespec="seconds")

                if aweme["is_image"]:
                    img += 1
                    log("%s → 图集，跳过" % head)
                    state[aid] = {"seq": seq, "aweme_id": aid, "title": aweme["desc"],
                                  "author": aweme["author"], "duration": 0,
                                  "status": "image", "size_kb": 0, "file": "",
                                  "note": "图集非视频", "ts": ts}
                    order = [x for x in order if x != aid] + [aid]
                    continue

                # ── 已下载判定（主键 = aweme_id，不是文件名）──────────────
                if not args.overwrite:
                    rec = state.get(aid)
                    if rec:
                        old_file = rec.get("file") or fname
                        old_path = os.path.join(out_dir, old_file)
                        good, size = local_video_ok(old_path, aweme.get("size") or 0)
                        if good:
                            skip += 1
                            rec.update({"seq": seq, "status": "skip", "size_kb": size // 1024,
                                        "note": "本地已存在", "ts": ts})
                            state[aid] = rec
                            order = [x for x in order if x != aid] + [aid]
                            tail = "" if old_file == fname else \
                                "（沿用已下好的 %s）" % old_file
                            log("%s → 已下载过，跳过%s" % (head, tail))
                            continue
                        # 记录在但文件坏了/没了 → 残骸移进回收站再重下，别留在目录里冒充成品
                        if os.path.exists(old_path):
                            log("%s → 本地文件不完整（%d 字节），移入回收站后重下"
                                % (head, size))
                            discard_bad(old_path, target["name"] or target["id"])
                        else:
                            log("%s → 上次的记录里文件已不存在，重新下载" % head)
                        state.pop(aid, None)
                    elif os.path.exists(path) and local_video_ok(
                            path, aweme.get("size") or 0)[0]:
                        # 没有记录但磁盘上正好是这个文件名 → 也算下过
                        skip += 1
                        size = os.path.getsize(path)
                        log("%s → 本地已有同名文件，跳过" % head)
                        state[aid] = {"seq": seq, "aweme_id": aid, "title": aweme["desc"],
                                      "author": aweme["author"],
                                      "duration": round(aweme["duration"] / 1000.0, 1),
                                      "status": "skip", "size_kb": size // 1024,
                                      "file": fname, "note": "本地已存在", "ts": ts}
                        order = [x for x in order if x != aid] + [aid]
                        continue

                status, size, note = download_video(ctx, page, webid, uifid, aweme, path)
                if status == "ok":
                    ok += 1
                    log("%s → 完成（%.1f MB）" % (head, size / 1048576.0))
                    size_kb = size // 1024
                else:
                    fail += 1
                    log("%s → 失败：%s" % (head, note))
                    size_kb = 0
                    fname = ""
                state[aid] = {"seq": seq, "aweme_id": aid, "title": aweme["desc"],
                              "author": aweme["author"],
                              "duration": round(aweme["duration"] / 1000.0, 1),
                              "status": status, "size_kb": size_kb, "file": fname,
                              "note": note, "ts": ts}
                order = [x for x in order if x != aid] + [aid]
                write_manifest(out_dir, state, order)  # 每条都落盘，中断可续
                if idx < len(videos):
                    time.sleep(max(args.delay, 0))

            elapsed = time.time() - t0
            write_manifest(out_dir, state, order)  # 收尾一次，把纯跳过的条目也落盘
            have = sum(1 for e in state.values() if e.get("status") in ("ok", "skip"))
            summary = ("收藏夹：%s\n视频总数：%d\n本次新下载：%d\n已下载过跳过：%d\n"
                       "下载失败：%d\n图集跳过：%d\n本地累计可用：%d\n耗时：%.0f 秒\n输出目录：%s"
                       % (target["name"], len(videos), ok, skip, fail, img,
                          have, elapsed, out_dir))
            for ln in summary.splitlines():
                log(ln)
            report.append(summary)
            code = 1 if fail else 0

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

    text = "\n".join(report) or summary
    if report:
        try:
            with open(os.path.join(out_dir, REPORT_FILE), "w", encoding="utf-8") as f:
                f.write(text + "\n")
            log("报告已写入：%s" % os.path.join(out_dir, REPORT_FILE))
        except (OSError, NameError):
            pass
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
