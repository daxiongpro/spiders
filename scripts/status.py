# -*- coding: utf-8 -*-
"""一键查看项目进度（换电脑后第一个要跑的脚本）。

除了打印到控制台，还会写一份 UTF-8 快照到 BASE/_status.txt
（Windows 控制台/管道编码容易乱码，看文件最稳）。

用法:
    python -u status.py              # 总览
    python -u status.py --detail     # 额外列出每条未完成的序号
"""
import glob
import json
import os
import re
import shutil
import sys
from collections import defaultdict
from time import time

BASE = os.environ.get("DOUYIN_BASE") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
LIST_DIR = os.path.join(BASE, "config")  # 分类清单目录
OUT_CAT = os.environ.get("DOUYIN_OUT") or os.path.join(
    os.path.dirname(BASE), "抖音收藏文案整理")
TMP = os.path.join(OUT_CAT, "_temp_audio")
SS = os.path.join(BASE, "output", "douyin", "storage_state.json")
SEQ = re.compile(r"seq(\d+)_")

CATS = ["搞钱·事业", "投资·理财", "求职·职场", "学习·成长", "探店·吃喝",
        "家庭·婚姻", "生活·出行", "娱乐·休闲", "未分类"]

LINES = []


def say(s=""):
    print(s)
    LINES.append(s)


def load_index():
    idx = {}
    for p in glob.glob(os.path.join(LIST_DIR, "list_*.json")):
        # 清单文件名用下划线，输出目录用间隔号 —— 必须转换
        cat = os.path.basename(p)[len("list_"):-len(".json")].replace("_", "\u00b7")
        with open(p, encoding="utf-8") as f:
            for v in json.load(f):
                idx[v["序号"]] = cat
    return idx


def main():
    detail = "--detail" in sys.argv

    say("=" * 62)
    say("环境自检")
    say("=" * 62)
    say(f"  BASE    : {BASE}   {'OK' if os.path.isdir(BASE) else '不存在!'}")
    say(f"  OUT_CAT : {OUT_CAT}   {'OK' if os.path.isdir(OUT_CAT) else '不存在!'}")

    n_list = len(glob.glob(os.path.join(LIST_DIR, "list_*.json")))
    say(f"  清单 json: {n_list} 个   {'OK' if n_list == 9 else '异常!'}")

    age = ""
    if os.path.isfile(SS):
        d = (time() - os.path.getmtime(SS)) / 86400
        age = f"（{d:.1f} 天前生成，超过 30 天大概率失效）"
        say(f"  抖音登录态: OK {age}")
    else:
        say("  抖音登录态: 缺失! -> 需重新扫码登录")
    say(f"    {SS}")

    try:
        import av  # noqa: F401
        say("  PyAV    : OK（音频抽取依赖）")
    except ImportError:
        say("  PyAV    : 缺失! -> pip install av")

    lark = os.environ.get("DOUYIN_LARK") or ""
    for c in (
        r"C:\Users\Administrator\.trae-cn\plugins\trae-remote-official\lark\1.0.5\bin\lark-cli.exe",
        r"C:\Users\Administrator\.workbuddy\binaries\node\cli-connector-packages\node_modules\@larksuite\cli\bin\lark-cli.exe",
    ):
        if lark:
            break
        if os.path.isfile(c):
            lark = c
    if lark:
        say(f"  lark-cli: {lark}")
    else:
        say("  lark-cli: 未找到! -> 需安装并授权飞书")
        say("            换机器后路径不同时：set DOUYIN_LARK=<lark-cli.exe 完整路径>")

    idx = load_index()

    def has_md(seq, cat):
        return bool(glob.glob(os.path.join(OUT_CAT, cat, f"{seq}_*.md")))

    say("")
    say("=" * 62)
    say("各分类进度")
    say("=" * 62)
    total_done = 0
    for cat in CATS:
        t = sum(1 for k, v in idx.items() if v == cat)
        if not t:
            continue
        n = sum(1 for s, c in idx.items() if c == cat and has_md(s, c))
        total_done += n
        flag = "  [满贯]" if n >= t else ""
        say(f"  {cat:<10} {n:>3}/{t:<3}{flag}")
    say("  " + "-" * 30)
    say(f"  {'合计':<10} {total_done:>3}/{len(idx)}")

    downloaded = {}
    for f in glob.glob(os.path.join(TMP, "*.mp4")):
        m = SEQ.search(os.path.basename(f))
        if m:
            downloaded[int(m.group(1))] = os.path.getsize(f) / 1048576

    pend = sorted(s for s in idx if not has_md(s, idx[s]))
    wait_tr = [s for s in pend if s in downloaded]
    wait_dl = [s for s in pend if s not in downloaded]

    say("")
    say("=" * 62)
    say(f"剩余 {len(pend)} 条")
    say("=" * 62)
    say(f"  已下载待转写: {len(wait_tr)} 条  -> 跑 lark_transcribe.py")
    say(f"  未下载      : {len(wait_dl)} 条  -> 跑 fetch_only.py")

    if detail:
        if wait_tr:
            say("")
            say("  待转写明细:")
            say("    " + ", ".join(str(s) for s in wait_tr))
        if wait_dl:
            say("")
            say("  未下载明细（按分类）:")
            g = defaultdict(list)
            for s in wait_dl:
                g[idx[s]].append(s)
            for cat in CATS:
                if g.get(cat):
                    say(f"    {cat}: " + ", ".join(str(x) for x in g[cat]))
    else:
        say("")
        say("  （加 --detail 看完整序号清单）")

    say("")
    say("=" * 62)
    say("磁盘占用")
    say("=" * 62)
    try:
        u = shutil.disk_usage(OUT_CAT)
        say(f"  OUT_CAT 所在盘剩余: {u.free/1073741824:.1f}GB")
    except Exception:
        pass
    for name in ("_temp_audio", "_tr", "_trash"):
        p = os.path.join(OUT_CAT, name)
        if os.path.isdir(p):
            fs = [x for x in glob.glob(os.path.join(p, "**", "*"), recursive=True)
                  if os.path.isfile(x)]
            sz = sum(os.path.getsize(x) for x in fs) / 1048576
            say(f"  {name:<14} {sz:>8.1f}MB  ({len(fs)} 文件)  <- 中间产物，可清")
    mds = [x for x in glob.glob(os.path.join(OUT_CAT, "**", "*.md"), recursive=True)
           if os.sep + "_" not in x.replace(OUT_CAT, "")]
    sz = sum(os.path.getsize(x) for x in mds) / 1048576
    say(f"  MD 成品        {sz:>8.1f}MB  ({len(mds)} 篇)  <- 正主，别删")

    snap = os.path.join(BASE, "_status.txt")
    with open(snap, "w", encoding="utf-8") as f:
        f.write("\n".join(LINES))
    print(f"\n[快照已写入] {snap}")


if __name__ == "__main__":
    main()
