# -*- coding: utf-8 -*-
"""路径配置的唯一来源。

历史问题：6 个脚本各自写死 `os.path.dirname(BASE)/"抖音收藏文案整理"`，
改输出位置要同步改 6 处，漏一个就会静默写回桌面，还不容易发现。
现在统一收敛到这里，脚本只调用本模块的函数。

目录布局（全部在仓库内）：

    spiders/
    ├─ output/
    │  ├─ 文案/<分类>/<序号>_标题.md    MD 成品 —— 入库
    │  ├─ downloads/<收藏夹名>/        下载的原始视频 —— 忽略
    │  ├─ douyin/storage_state.json    登录态凭证 —— 忽略
    │  ├─ douyin/edge_profile/         浏览器配置档（登录态持久化，扫码一次） —— 忽略
    │  ├─ douyin/webid.txt             webid（登录时抓取） —— 忽略
    │  ├─ _temp_audio/                 下载的音视频 —— 忽略
    │  ├─ _tr/                         lark-cli 中间产物 —— 忽略
    │  └─ _trash/                      "删除"实为移入此处 —— 忽略

环境变量覆盖（换机器，或想把成品放到别处时用）：

    DOUYIN_BASE       仓库根，默认本文件的上级目录
    DOUYIN_OUT        MD 成品目录，默认 <repo>/output/文案
    DOUYIN_MEDIA      中间产物根目录，默认 <repo>/output
    DOUYIN_DOWNLOADS  视频下载根目录，默认 <repo>/output/downloads
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


def douyin_dir() -> str:
    """抖音凭证目录，如 <repo>/output/douyin（登录态、webid 都放这里）。"""
    return os.path.join(media_root(), "douyin")


def downloads_dir(folder: str = "") -> str:
    """下载的原始视频目录，如 <repo>/output/downloads[/<收藏夹名>]。

    传 folder 得到该收藏夹的子目录，不传则是下载根目录。
    收藏夹名是用户数据，可能含空格/中文/斜杠，交给调用方先做一次
    文件名清洗（脚本里的 safe_name），这里只负责拼路径。
    """
    root = os.environ.get("DOUYIN_DOWNLOADS") or os.path.join(media_root(), "downloads")
    return os.path.join(root, folder) if folder else root


def storage_state() -> str:
    """抖音登录态文件（含 Cookie 凭证，切勿提交）。"""
    return os.path.join(douyin_dir(), "storage_state.json")


def browser_profile() -> str:
    """扫码登录用的浏览器配置档目录。

    登录态（cookie + localStorage）持久化在这里，所以只需扫码一次；
    独立目录，不碰用户日常使用的 Edge 配置，两者互不干扰。
    """
    return os.path.join(douyin_dir(), "edge_profile")


def webid_file() -> str:
    """webid 文件（19 位数字，登录后从 localStorage 提取）。

    webid 参与接口参数构造；旧代码里写死的默认值与本机真实值不一致，
    登录时抓到真实值存下来更可靠。
    """
    return os.path.join(douyin_dir(), "webid.txt")


if __name__ == "__main__":
    for name, val in (("base", base()), ("out_dir", out_dir()),
                      ("media_root", media_root()), ("temp_audio", temp_audio()),
                      ("work_root", work_root()), ("trash_dir", trash_dir()),
                      ("douyin_dir", douyin_dir()), ("storage_state", storage_state()),
                      ("browser_profile", browser_profile()), ("webid_file", webid_file()),
                      ("downloads_dir", downloads_dir()),
                      ("downloads_dir(示例)", downloads_dir("搞钱·事业"))):
        print("%-16s %s" % (name, val))
