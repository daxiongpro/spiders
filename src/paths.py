# -*- coding: utf-8 -*-
"""路径配置的唯一来源。

历史问题：6 个脚本各自写死 `os.path.dirname(BASE)/"抖音收藏文案整理"`，
改输出位置要同步改 6 处，漏一个就会静默写回桌面，还不容易发现。
现在统一收敛到这里，脚本只调用本模块的函数。

目录布局（全部在仓库内）：

    spiders/
    ├─ output/
    │  ├─ 文案/<分类>/<序号>_标题.md    MD 成品 —— 入库
    │  ├─ douyin/storage_state.json    登录态凭证 —— 忽略
    │  ├─ _temp_audio/                 下载的音视频 —— 忽略
    │  ├─ _tr/                         lark-cli 中间产物 —— 忽略
    │  └─ _trash/                      "删除"实为移入此处 —— 忽略

环境变量覆盖（换机器，或想把成品放到别处时用）：

    DOUYIN_BASE    仓库根，默认本文件的上级目录
    DOUYIN_OUT     MD 成品目录，默认 <repo>/output/文案
    DOUYIN_MEDIA   中间产物根目录，默认 <repo>/output
"""
import os

# 本文件在 spiders/src/ 下，仓库根 = 上级的上级
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

# MD 成品目录名：做成常量，改名时只动一处
OUT_NAME = "文案"


def base() -> str:
    """仓库根。"""
    return os.environ.get("DOUYIN_BASE") or _ROOT


def out_dir() -> str:
    """MD 成品根目录，如 <repo>/output/文案。"""
    return os.environ.get("DOUYIN_OUT") or os.path.join(base(), "output", OUT_NAME)


def media_root() -> str:
    """中间产物根目录，如 <repo>/output。临时文件与凭证都挂在它下面。"""
    return os.environ.get("DOUYIN_MEDIA") or os.path.join(base(), "output")


def temp_audio() -> str:
    """下载的音视频暂存目录。"""
    return os.path.join(media_root(), "_temp_audio")


def work_root() -> str:
    """lark-cli 中间产物目录。"""
    return os.path.join(media_root(), "_tr")


def trash_dir() -> str:
    """回收站目录：批量删除会被安全阈值拦下，所以改成往这里移。"""
    return os.path.join(media_root(), "_trash")


def storage_state() -> str:
    """抖音登录态文件（含 Cookie 凭证，切勿提交）。"""
    return os.path.join(base(), "output", "douyin", "storage_state.json")


if __name__ == "__main__":
    for name, val in (("base", base()), ("out_dir", out_dir()),
                      ("media_root", media_root()), ("temp_audio", temp_audio()),
                      ("work_root", work_root()), ("trash_dir", trash_dir()),
                      ("storage_state", storage_state())):
        print("%-14s %s" % (name, val))
