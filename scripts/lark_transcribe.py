# -*- coding: utf-8 -*-
"""飞书妙记转写器（自研链路，不依赖 social_video_to_minutes.py）。

链路：本地 MP4 --PyAV抽音频--> m4a --drive +upload--> file_token
      --minutes +upload--> minute_token --minutes +detail 轮询--> transcript
      --> 写 MD 到 D 盘分类目录。

为什么不用 social_video_to_minutes.py：它硬编码 `lark-cli vc +notes`，
而本机 lark-cli(1.0.94/1.0.95) 的 vc 域下没有该命令，导致必然拿不到逐字稿。
正确命令是 minutes +detail --transcript。

用法:
    python -u lark_transcribe.py --seq 437          # 只处理指定序号（调试用）
    python -u lark_transcribe.py                    # 处理 _temp_audio 下全部 mp4
    python -u lark_transcribe.py --workers 3
    python -u lark_transcribe.py --no-audio         # 不抽音频，直接传原 MP4
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---- lark-cli 用绝对路径调用，绕开 PATH/shutil.which 找不到的问题 ----
# 换电脑时可用环境变量 DOUYIN_LARK 直接指定 lark-cli.exe 的完整路径
LARK_CANDIDATES = [
    os.environ.get("DOUYIN_LARK") or "",
    shutil.which("lark-cli") or "",
    shutil.which("lark-cli.exe") or "",
    r"C:\Users\Administrator\.workbuddy\binaries\node\cli-connector-packages\node_modules\@larksuite\cli\bin\lark-cli.exe",
    r"C:\Users\Administrator\.trae-cn\plugins\trae-remote-official\lark\1.0.5\bin\lark-cli.exe",
]
LARK = ""
for _c in LARK_CANDIDATES:
    if _c and os.path.isfile(_c):
        LARK = _c
        break

# ---- 路径默认取项目根（脚本在 scripts/ 下，故为上级目录），换电脑用环境变量覆盖 ----
#   set DOUYIN_BASE=X:\path\to\spiders
#   set DOUYIN_OUT=X:\path\to\抖音收藏文案整理
BASE = os.environ.get("DOUYIN_BASE") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
LIST_DIR = os.path.join(BASE, "config")  # 分类清单目录
# 默认：BASE 同级目录下的「抖音收藏文案整理」，与原机器布局一致
OUT_CAT = os.environ.get("DOUYIN_OUT") or os.path.join(
    os.path.dirname(BASE), "抖音收藏文案整理")
TMP_AUDIO = os.path.join(OUT_CAT, "_temp_audio")
# lark-cli 输出白名单只放行「当前工作目录 / 系统 temp / ~/files」。
# 把 cwd 设为 OUT_CAT，中间产物就能落在 D 盘，而不是 C 盘 %TEMP%。
WORK_ROOT = os.path.join(OUT_CAT, "_tr")
TRASH = os.path.join(OUT_CAT, "_trash")


def trash(path):
    """移入 _trash 而不是删除（避开单轮删除阈值，且文件可找回）。"""
    try:
        if not path or not os.path.exists(path):
            return
        os.makedirs(TRASH, exist_ok=True)
        dst = os.path.join(TRASH, os.path.basename(path))
        if os.path.exists(dst):
            stem, ext = os.path.splitext(os.path.basename(path))
            dst = os.path.join(TRASH, f"{stem}_{int(time.time() * 1000)}{ext}")
        shutil.move(path, dst)
    except Exception:
        pass

IIL = re.compile(r'[\\/:*?"<>|\s]')
SEQ_RE = re.compile(r"seq(\d+)_")


def title20(t: str) -> str:
    return IIL.sub("", t)[:20]


def load_index():
    idx = {}
    for p in glob.glob(os.path.join(LIST_DIR, "list_*.json")):
        # 清单文件名用下划线，输出目录用间隔号，必须转换否则会写到新目录
        cat = os.path.basename(p)[len("list_"):-len(".json")].replace("_", "\u00b7")
        with open(p, encoding="utf-8") as f:
            for v in json.load(f):
                idx[v["序号"]] = (cat, v)
    return idx


def run(cmd, timeout=3600, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, cwd=cwd, encoding="utf-8",
                          errors="replace")


def jout(proc):
    """从 lark-cli 输出里抠出 JSON 对象。"""
    s = (proc.stdout or "").strip()
    i = s.rfind("\n{")
    payload = s[i + 1:] if i >= 0 else (s[s.find("{"):] if "{" in s else "")
    try:
        return json.loads(payload)
    except Exception:
        return {}


def extract_audio(mp4: str, dst: str) -> str:
    """PyAV 抽单声道 16k AAC，体积远小于原视频。"""
    import av
    inp = av.open(mp4)
    astream = next((s for s in inp.streams if s.type == "audio"), None)
    if astream is None:
        inp.close()
        raise RuntimeError("无音轨")
    out = av.open(dst, "w")
    enc = out.add_stream("aac", rate=16000)
    enc.layout = "mono"
    res = av.AudioResampler(format="fltp", layout="mono", rate=16000)
    try:
        for frame in inp.decode(astream):
            for nf in res.resample(frame):
                if nf is None:
                    continue
                for p in enc.encode(nf):
                    out.mux(p)
        for p in enc.encode(None):
            out.mux(p)
    finally:
        out.close()
        inp.close()
    return dst


def drive_upload(path: str) -> str:
    p = run([LARK, "drive", "+upload", "--file", path, "--format", "json"],
            timeout=7200, cwd=OUT_CAT)
    d = jout(p)
    tok = ""
    for key in ("file_token", "token"):
        tok = ((d.get("data") or {}).get(key)) or d.get(key) or ""
        if tok:
            break
    if not tok:
        # 兜底：正则在整段输出里找
        m = re.search(r'"file_token"\s*:\s*"([^"]+)"', p.stdout or "")
        tok = m.group(1) if m else ""
    if not tok:
        raise RuntimeError(f"上传失败 rc={p.returncode}: {(p.stdout or p.stderr)[-300:]}")
    return tok


def minutes_upload(file_token: str) -> str:
    p = run([LARK, "minutes", "+upload", "--file-token", file_token,
             "--format", "json"], timeout=3600, cwd=OUT_CAT)
    d = jout(p)
    tok = ((d.get("data") or {}).get("minute_token")) or d.get("minute_token") or ""
    if not tok:
        m = re.search(r'"minute_token"\s*:\s*"([^"]+)"', p.stdout or "")
        tok = m.group(1) if m else ""
    if not tok:
        raise RuntimeError(f"妙记创建失败: {(p.stdout or p.stderr)[-300:]}")
    return tok


def find_transcript(d: str) -> str:
    """找非空 txt（转写产出）。"""
    best = ""
    for p in glob.glob(os.path.join(d, "**", "*.txt"), recursive=True):
        try:
            if os.path.getsize(p) > 0:
                return p
        except OSError:
            pass
        best = best or p
    return best


def poll_transcript(minute_token: str, out_dir: str,
                    timeout=2700, interval=25) -> str:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        run([LARK, "minutes", "+detail", "--minute-tokens", minute_token,
             "--transcript", "--keyword", "--output-dir", out_dir,
             "--format", "json"], timeout=600, cwd=OUT_CAT)
        hit = find_transcript(out_dir)
        if hit:
            try:
                if os.path.getsize(hit) > 0:
                    return hit
            except OSError:
                pass
        last = hit or ""
        time.sleep(interval)
    return last


def parse_transcript(text: str):
    kw, body_lines, in_body = "", [], False
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("Keywords"):
            rest = ln.split(":", 1)[1].strip() if ":" in ln else ""
            if rest:
                kw = rest
            else:
                for j in range(i + 1, len(lines)):
                    if lines[j].strip():
                        kw = lines[j].strip()
                        break
            continue
        if s.startswith("Speaker"):
            in_body = True
        if in_body:
            body_lines.append(ln)
    return kw or "无", "\n".join(body_lines).strip()


def write_md(cat, seq, video, kw, body) -> str:
    d = os.path.join(OUT_CAT, cat)
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, f"{seq}_{title20(video['标题'])}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(
            f"# {video['标题']}\n\n"
            f"- 链接：{video['链接']}\n"
            f"- 原文件夹：{video['原文件夹']}\n"
            f"- 新分类：{video['新分类']}\n"
            f"- 点赞数：{video['点赞数']}\n"
            f"- 相关主题：{video['相关主题备注']}\n\n"
            f"## 口播逐字稿\n\n{body}\n\n"
            f"## 关键词\n\n{kw}\n"
        )
    return out


def process(mp4, seq, video, cat, use_audio=True, keep=False):
    wd = os.path.join(WORK_ROOT, f"seq{seq}")
    os.makedirs(wd, exist_ok=True)
    media = mp4
    try:
        if use_audio:
            m4a = os.path.join(wd, f"seq{seq}.m4a")
            if not (os.path.exists(m4a) and os.path.getsize(m4a) > 0):
                extract_audio(mp4, m4a)
            media = m4a
        smb = os.path.getsize(media) / 1048576
        print(f"    [上传] seq{seq} 媒体 {smb:.1f}MB", flush=True)
        ft = drive_upload(media)
        print(f"    [妙记] seq{seq} -> {ft[:16]}...", flush=True)
        mt = minutes_upload(ft)
        print(f"    [轮询] seq{seq} minute={mt[:16]}...", flush=True)
        tf = poll_transcript(mt, os.path.join(wd, "notes"))
        if not tf or not os.path.exists(tf) or os.path.getsize(tf) == 0:
            raise RuntimeError("未拿到逐字稿（转写超时）")
        with open(tf, encoding="utf-8") as f:
            kw, body = parse_transcript(f.read())
        if not body:
            raise RuntimeError("逐字稿正文为空")
        out = write_md(cat, seq, video, kw, body)
        if not keep:
            # 移入 _trash 而非删除：批量跑会撞「单轮 50 次删除」的安全阈值
            trash(mp4)
            if media != mp4:
                trash(media)
        return f"[OK] 序号{seq} ({cat}) -> {os.path.basename(out)}  正文{len(body)}字"
    except Exception as e:
        return f"[FAIL] 序号{seq} ({cat}): {str(e)[:260]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seq", type=int, action="append")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--src", default=TMP_AUDIO)
    ap.add_argument("--category", help="只处理该分类（用间隔号，如 学习·成长）")
    a = ap.parse_args()

    # 代理会阻断 lark 与抖音，务必清掉
    for k in ("https_proxy", "http_proxy", "all_proxy", "ALL_PROXY"):
        os.environ.pop(k, None)

    if not LARK:
        print("找不到 lark-cli.exe")
        return
    print(f"lark-cli: {LARK}", flush=True)

    idx = load_index()
    mp4s = sorted(glob.glob(os.path.join(a.src, "*.mp4")))
    tasks = []
    for mp4 in mp4s:
        m = SEQ_RE.search(os.path.basename(mp4))
        if not m:
            continue
        seq = int(m.group(1))
        if a.seq and seq not in a.seq:
            continue
        if seq not in idx:
            print(f"  [跳过] 清单无此序号 {seq}", flush=True)
            continue
        cat, video = idx[seq]
        if glob.glob(os.path.join(OUT_CAT, cat, f"{seq}_*.md")):
            print(f"  [跳过] 已有 MD {seq}", flush=True)
            continue
        tasks.append((mp4, seq, video, cat))

    if a.category:
        tasks = [t for t in tasks if t[3] == a.category]
        print(f"[过滤] 只看分类 {a.category}", flush=True)

    if not tasks:
        print("没有需要处理的视频。", flush=True)
        return

    print(f"[开始] {len(tasks)} 条，并发 {a.workers}", flush=True)
    t0 = time.time()
    failed = []
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = {}
        for t in tasks:
            try:
                sz = os.path.getsize(t[0]) / 1048576
            except OSError:
                sz = 0
            print(f"  [待转] 序号{t[1]} ({t[3]}) {sz:.0f}MB", flush=True)
            futs[pool.submit(process, *t, not a.no_audio, a.keep)] = t
        for fu in as_completed(futs):
            t = futs[fu]
            msg = fu.result()
            print(f"  -> {msg}", flush=True)
            if not msg.startswith("[OK]"):
                failed.append(t)
    if failed:
        print(f"\n[重试] 串行 {len(failed)} 条", flush=True)
        for t in failed:
            print(f"  -> {process(*t, not a.no_audio, a.keep)}", flush=True)
    ok = sum(1 for t in tasks if glob.glob(os.path.join(OUT_CAT, t[3], f"{t[1]}_*.md")))
    print(f"\n[完成] 成功 {ok}/{len(tasks)}，耗时 {(time.time()-t0)/60:.1f} 分钟", flush=True)


if __name__ == "__main__":
    main()
