#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抖音收藏文案整理 - 按序自动流水线驱动（实时状态版）
顺序由 ORDER 指定；每块先 fetch 再 transcribe，并实时把逐条状态写入 _realtime.json
供 progress_dashboard 展示。转写失败的自动打【转写失败】标记存档。
遇到授权失效自动停止（PIPELINE_HALT_AUTH），重授权后重跑即可（幂等）。
"""
import glob, json, os, re, shutil, subprocess, sys, threading, time

SP  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根 spiders
OUT = os.environ.get("DOUYIN_OUT") or os.path.join(
    os.path.dirname(SP), "抖音收藏文案整理")
TA  = os.path.join(OUT, "_temp_audio")


def find_python():
    """优先环境变量 → 当前解释器 → 常见安装路径，避免写死某台机器的绝对路径。

    想把 fork/转写固定到某个已装依赖的解释器时用：
        set DOUYIN_PYTHON=X:/path/to/python.exe
    """
    cands = [os.environ.get("DOUYIN_PYTHON"), sys.executable,
             shutil.which("python"), shutil.which("python3"),
             r"C:/ProgramData/miniforge3/python.exe"]
    for c in cands:
        if c and (os.path.isfile(c) or shutil.which(c)):
            return c
    return sys.executable


PY  = find_python()
FETCH = os.path.join(SP, "scripts", "fetch_only.py")
TRANS = os.path.join(SP, "scripts", "lark_transcribe.py")

# 分类处理顺序：先跑优先列表，剩余分类按 config/list_*.json 自动补齐，
# 免得以后新增了分类清单却忘了在这里登记。
PREFERRED_ORDER = ["未分类", "探店·吃喝", "家庭·婚姻", "生活·出行", "娱乐·休闲"]
CHUNK = 20


def discover_order():
    """扫描 config/list_*.json 得到全部分类，优先列表内的排在前面。"""
    found = []
    for jf in sorted(glob.glob(os.path.join(SP, "config", "list_*.json"))):
        cat = os.path.basename(jf)[len("list_"):-len(".json")].replace("_", "\u00b7")
        if cat not in found:
            found.append(cat)
    order = [c for c in PREFERRED_ORDER if c in found]
    order += [c for c in found if c not in order]
    return order


ORDER = discover_order()
MAX_ITER = 40
LOG = os.path.join(SP, "_pipeline.log")
RT  = os.path.join(SP, "_realtime.json")

ENV = dict(os.environ, DOUYIN_BASE=SP, DOUYIN_OUT=OUT)
for k in ["https_proxy", "http_proxy", "all_proxy", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"]:
    ENV.pop(k, None)

SEQINFO = {}
for jf in glob.glob(os.path.join(SP, "config", "list_*.json")):
    try:
        data = json.load(open(jf, encoding="utf-8"))
    except Exception:
        continue
    if not isinstance(data, list):
        continue
    for it in data:
        if isinstance(it, dict):
            s = it.get("序号")
            if s is not None:
                SEQINFO[s] = (it.get("新分类", ""), it.get("标题", ""))

_state = {"phase": "idle", "category": "", "fetch_round": 0, "fetch_plan": [],
          "fetch_done": 0, "fetch_failed": [], "transcribe_items": {},
          "auth_error": False, "ts": time.strftime("%H:%M:%S")}
_lock = threading.Lock()
_last_write = [0.0]

def write_rt():
    try:
        with _lock:
            _state["ts"] = time.strftime("%H:%M:%S")
            tmp = RT + ".tmp"
            json.dump(_state, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
            os.replace(tmp, RT)
    except Exception:
        pass

def log(m):
    line = "[%s] %s" % (time.strftime("%m-%d %H:%M:%S"), m)
    open(LOG, "a", encoding="utf-8").write(line + "\n")
    print(line, flush=True)

def title_of(seq):
    return SEQINFO.get(seq, ("", "序号%d" % seq))[1]

def safe_name(title):
    r"""清洗 Windows 文件名非法字符： \ / : * ? " < > | 以及控制字符"""
    bad = r'\/:*?"<>|'
    s = "".join("_" if ch in bad else ch for ch in str(title))
    s = re.sub(r"[\x00-\x1f]", "", s)
    s = s.strip().strip(".")
    return (s or "untitled")[:40]

def mark_fail(seq, cat, reason):
    catdir = os.path.join(OUT, cat); os.makedirs(catdir, exist_ok=True)
    t = title_of(seq); fn = "%d_【转写失败】%s.md" % (seq, safe_name(t))
    p = os.path.join(catdir, fn)
    if os.path.exists(p):
        return
    c = ("# %s（转写失败）\n\n- 分类：%s\n- 序号：%d\n- 状态：转写失败\n- 原因：%s\n- 处理时间：%s\n\n"
         "## 逐字稿\n\n> 转写失败，无可用口播文本。\n") % (
        t, cat, seq, reason, time.strftime("%Y-%m-%d"))
    open(p, "w", encoding="utf-8").write(c)

def compute_fetch_plan(cat, limit):
    safe = cat.replace("·", "_").replace(" ", "_")
    jf = os.path.join(SP, "config", "list_%s.json" % safe)
    if not os.path.isfile(jf):
        return []
    try:
        vids = json.load(open(jf, encoding="utf-8"))
    except Exception:
        return []
    cat_dir = os.path.join(OUT, cat); out = []
    for v in vids:
        s = v.get("序号")
        if s is None:
            continue
        if not v.get("链接"):
            continue
        if glob.glob(os.path.join(cat_dir, "%s_*.md" % s)):
            continue
        if glob.glob(os.path.join(TA, "seq%s_*.mp4" % s)):
            continue
        out.append(s)
    out.sort()
    if limit:
        out = out[:limit]
    return out

def parse_line(line):
    s = line.strip()
    if not s:
        return
    low = s.lower()
    if ("token" in low or "auth" in low or "99991672" in s) and \
       any(k in low for k in ("expire", "unauthor", "invalid", "not_configured", "scope_not")):
        _state["auth_error"] = True
    if s.startswith("[下载]"):
        m = re.match(r"\[下载\] (.+?) 共 (\d+) 条", s)
        if m:
            _state["phase"] = "fetch"; _state["category"] = m.group(1)
        return
    if s.startswith("[OK]") and _state["phase"] == "fetch":
        if re.match(r"\[OK\] (\d+)", s):
            _state["fetch_done"] = _state.get("fetch_done", 0) + 1
        return
    if s.startswith("[FAIL]") and _state["phase"] == "fetch":
        m = re.match(r"\[FAIL\] (\d+)", s)
        if m:
            _state["fetch_failed"].append(int(m.group(1)))
            _state["fetch_done"] = _state.get("fetch_done", 0) + 1
        return
    # transcribe 阶段：捕获 seq / 序号 的逐条状态
    if "seq" in s:
        mh = re.search(r"序号(\d+)", s)
        mi = re.search(r"seq(\d+)", s)
        key = mh or mi
        if not key:
            return
        seq = key.group(1)
        if "[上传]" in s or "上传] seq" in s:
            _state["transcribe_items"][seq] = {"status": "upload", "info": s}
        elif "[妙记]" in s or "妙记] seq" in s:
            _state["transcribe_items"][seq] = {"status": "minutes", "info": s}
        elif "[轮询]" in s or "轮询] seq" in s:
            _state["transcribe_items"][seq] = {"status": "polling", "info": s}
        elif "-> [OK] 序号" in s or "->[OK] 序号" in s:
            _state["transcribe_items"][seq] = {"status": "ok", "info": s}
        elif "-> [FAIL] 序号" in s or "->[FAIL] 序号" in s:
            _state["transcribe_items"][seq] = {"status": "fail", "info": s}

def run_stream(cmd, is_transcribe=False):
    if is_transcribe:
        with _lock:
            _state["transcribe_items"] = {}; _state["phase"] = "transcribe"
    proc = subprocess.Popen(cmd, env=ENV, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", bufsize=1)
    while True:
        line = proc.stdout.readline()
        if not line:
            break
        parse_line(line)
        now = time.time()
        if now - _last_write[0] > 0.5:
            write_rt(); _last_write[0] = now
    proc.wait()
    write_rt()
    return proc.returncode

def remaining_unmarked(cat):
    res = []
    for mp in glob.glob(os.path.join(TA, "seq*_*.mp4")):
        m = re.search(r"seq(\d+)_", os.path.basename(mp))
        if not m:
            continue
        seq = int(m.group(1))
        c = SEQINFO.get(seq, ("", ""))[0]
        if c != cat:
            continue
        if not glob.glob(os.path.join(OUT, cat, "%d_*.md" % seq)):
            res.append(seq)
    return res

def main():
    write_rt()
    for cat in ORDER:
        log("=== 开始分类: %s ===" % cat)
        for it in range(MAX_ITER):
            plan = compute_fetch_plan(cat, CHUNK)
            with _lock:
                _state["phase"] = "fetch"; _state["category"] = cat
                _state["fetch_round"] = it; _state["fetch_plan"] = plan
                _state["fetch_done"] = 0; _state["fetch_failed"] = []
            if not plan:
                log("  [%s] 无可下载新项，下载阶段结束" % cat); break
            log("  [%s] fetch 轮%d: 计划 %d 条" % (cat, it, len(plan)))
            run_stream([PY, "-u", FETCH, "--category", cat, "--limit", str(CHUNK)])
            if _state.get("auth_error"):
                log("  [%s] 检测到飞书授权失效，停止流水线。" % cat)
                log("PIPELINE_HALT_AUTH"); write_rt(); sys.exit(0)
            run_stream([PY, "-u", TRANS, "--workers", "2"], is_transcribe=True)
            for seq_s, item in list(_state["transcribe_items"].items()):
                if item["status"] == "fail":
                    mark_fail(int(seq_s), cat, "飞书妙记转写失败（详见 _pipeline.log）")
            if _state.get("auth_error"):
                log("  [%s] 检测到飞书授权失效，停止流水线。" % cat)
                log("PIPELINE_HALT_AUTH"); write_rt(); sys.exit(0)
        left = remaining_unmarked(cat)
        if left:
            # 对下载了但没转出文字的遗留视频，最后再转写一次，挽救瞬时失败
            cmd = [PY, "-u", TRANS]
            for s in left:
                cmd += ["--seq", str(s)]
            run_stream(cmd, is_transcribe=True)
            left = remaining_unmarked(cat)
        for seq in left:
            mark_fail(seq, cat, "转写多次失败/无音轨（自动标记）")
        log("=== 完成分类: %s（遗留自动标记 %d 条）===" % (cat, len(left)))
    log("PIPELINE_DONE"); write_rt()

if __name__ == "__main__":
    main()
