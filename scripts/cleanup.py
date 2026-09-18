# -*- coding: utf-8 -*-
"""磁盘回收：清掉本项目自己产生的中间文件，不动任何 MD 成品。

用法:
    python -u cleanup.py            # 预览：只统计，不删
    python -u cleanup.py --do       # 真正执行
    python -u cleanup.py --do --aggressive   # 连 _temp_audio 里已转写的也删
"""
import glob
import os
import re
import shutil
import sys

# 默认取项目根（脚本在 scripts/ 下，故为上级目录）及其同级「抖音收藏文案整理」，
# 换机器用环境变量覆盖
BASE = os.environ.get("DOUYIN_BASE") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get("DOUYIN_OUT") or os.path.join(
    os.path.dirname(BASE), "抖音收藏文案整理")
SEQ = re.compile(r"seq(\d+)_")

CATS = ["学习·成长", "投资·理财", "探店·吃喝", "搞钱·事业", "求职·职场",
        "家庭·婚姻", "生活·出行", "娱乐·休闲", "未分类"]


def human(n):
    return f"{n/1048576:.1f}MB" if n < 1073741824 else f"{n/1073741824:.2f}GB"


def dirsize(d):
    if not os.path.isdir(d):
        return 0, 0
    tot = cnt = 0
    for root, _, files in os.walk(d):
        for f in files:
            try:
                tot += os.path.getsize(os.path.join(root, f))
                cnt += 1
            except OSError:
                pass
    return tot, cnt


def md_done():
    done = {}
    for c in CATS:
        for p in glob.glob(os.path.join(OUT, c, "*.md")):
            m = re.match(r"(\d+)_", os.path.basename(p))
            if m:
                done[int(m.group(1))] = c
    return done


def main():
    do = "--do" in sys.argv
    aggressive = "--aggressive" in sys.argv
    done = md_done()
    plans = []          # (说明, 路径)
    freed = 0

    # 1) 整体可回收目录
    for name in ("_trash", "_tr", "_temp_transcript", "_temp_test_audio"):
        d = os.path.join(OUT, name)
        sz, cnt = dirsize(d)
        if sz:
            plans.append((f"{name}  ({cnt} 文件, {human(sz)})", d))
            freed += sz

    # 2) _temp_audio 里已生成 MD 的临时视频
    tmp = os.path.join(OUT, "_temp_audio")
    stale = []
    for f in glob.glob(os.path.join(tmp, "*.mp4")):
        m = SEQ.search(os.path.basename(f))
        if m and int(m.group(1)) in done:
            try:
                stale.append((f, os.path.getsize(f)))
            except OSError:
                pass
    if stale:
        sz = sum(s for _, s in stale)
        plans.append((f"_temp_audio 中已转写的 {len(stale)} 个 mp4 ({human(sz)})",
                      "STALE"))
        freed += sz

    if aggressive:
        # 3) _tr上部 inspect：已跑完的分类中间产物（这里暂无额外项）
        pass

    print("=== 可回收清单 ===")
    for desc, _ in plans:
        print(f"  - {desc}")
    print(f"\n合计可回收: {human(freed)}")

    if not do:
        print("\n[预览模式] 加 --do 才真正删除。")
        return

    for desc, path in plans:
        if path == "STALE":
            for f, _ in stale:
                try:
                    os.remove(f)
                except OSError as e:
                    print(f"    跳过 {os.path.basename(f)}: {e}")
            print(f"  [已清] {desc}")
        else:
            try:
                shutil.rmtree(path)
                print(f"  [已清] {desc}")
            except Exception as e:
                print(f"  [失败] {desc}: {e}")

    try:
        total, used, free = shutil.disk_usage(OUT)
        print(f"\n清理后 D 盘剩余: {free/1073741824:.1f}GB "
              f"(总 {total/1073741824:.0f}GB)")
    except Exception:
        pass


if __name__ == "__main__":
    main()
