# -*- coding: utf-8 -*-
"""
抖音 web API 纯代码客户端（无浏览器、无 Playwright、无 JS 引擎）。

登录一次（扫码）后保存 cookies，之后全部用纯 HTTP 请求调抖音 web 接口：
  - 收藏夹列表（分页）        /aweme/v1/web/collects/list/
  - 收藏夹视频列表（分页）     /aweme/v1/web/collects/video/list/
  - 视频详情                  /aweme/v1/web/aweme/detail/
  - 评论列表（分页）          /aweme/v1/web/comment/list/

签名：a_bogus（见 douyin_sign.py，纯 Python 实现）。
仅用于整理本人账号数据，控制请求频率。
"""

import json
import os
import sys
import time
from typing import Any, Dict, Iterable, List, Optional

import requests

# 允许作为独立脚本运行时的 import 路径修正
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from douyin_sign import (  # noqa: E402
    UA,
    build_common_params,
    gen_ms_token,
    gen_verify_fp,
    sign_params,
)

API_BASE = "https://www.douyin.com/aweme/v1/web"
DEFAULT_WEBID = "7683161877676918307"  # 浏览器会话同源 webid（登录时从 localStorage 提取后覆盖）
DEFAULT_DELAY = 0.5  # 翻页间隔（秒），避免高频请求


def load_douyin_cookies(storage_state_path: str) -> Dict[str, str]:
    """从 Playwright storage_state.json 读取 douyin 域 cookie。"""
    with open(storage_state_path, encoding="utf-8") as f:
        ss = json.load(f)
    out: Dict[str, str] = {}
    for c in ss.get("cookies", []):
        if str(c.get("domain", "")).endswith("douyin.com"):
            out[c["name"]] = c["value"]
    return out


def load_webid(webid_path: str) -> str:
    """读取 webid（登录时保存），不存在返回默认值。"""
    try:
        with open(webid_path, encoding="utf-8") as f:
            v = f.read().strip()
        if v and v.isdigit():
            return v
    except OSError:
        pass
    return DEFAULT_WEBID


def save_webid(webid_path: str, webid: str) -> None:
    if webid and webid.isdigit():
        with open(webid_path, "w", encoding="utf-8") as f:
            f.write(webid)


class DouyinApiError(RuntimeError):
    pass


class DouyinApiClient:
    """纯 HTTP 的抖音 web API 客户端。"""

    def __init__(
        self,
        storage_state_path: str,
        webid: Optional[str] = None,
        webid_path: Optional[str] = None,
        delay: float = DEFAULT_DELAY,
        ua: str = UA,
    ):
        if not os.path.exists(storage_state_path):
            raise DouyinApiError(
                "找不到登录会话 %s，请先运行: python src/douyin_spider.py login（扫码一次）"
                % storage_state_path
            )
        self.cookies = load_douyin_cookies(storage_state_path)
        if not self.cookies:
            raise DouyinApiError("登录会话中没有 douyin.com 的 cookie，请重新 login")
        self.webid = webid or (load_webid(webid_path) if webid_path else DEFAULT_WEBID)
        self.uifid = self.cookies.get("UIFID", "")
        self.delay = delay
        self.ua = ua
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": ua,
            "Referer": "https://www.douyin.com/",
            "Accept": "application/json, text/plain, */*",
            "Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items()),
        })
        # 自检：最低要求 sessionid / sid_guard 存在
        if not any(k in self.cookies for k in ("sessionid", "sid_guard")):
            raise DouyinApiError("会话 cookie 缺少登录态（sessionid/sid_guard），请重新 login")

    # ------------------------------------------------------------ 基础请求
    def _signed_url(self, path: str, extra: List[tuple]) -> str:
        fp = gen_verify_fp()
        params = build_common_params(self.webid) + [
            ("uifid", self.uifid),
            ("verifyFp", fp),
            ("fp", fp),
            ("msToken", gen_ms_token()),
        ] + extra
        qs = sign_params(params)
        return API_BASE + path + "?" + qs

    def _get(self, path: str, extra: List[tuple], retries: int = 3) -> Dict[str, Any]:
        last_err: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                url = self._signed_url(path, extra)
                resp = self.session.get(url, timeout=20)
                if resp.status_code != 200:
                    raise DouyinApiError("HTTP %s: %s" % (resp.status_code, path))
                data = resp.json()
                sc = data.get("status_code")
                if sc == 0:
                    return data
                # 常见错误：未登录/风控
                msg = data.get("status_msg") or ""
                raise DouyinApiError(
                    "接口 %s 返回 status_code=%s %s" % (path, sc, msg)
                )
            except (requests.RequestException, ValueError) as e:
                last_err = e
                time.sleep(1.5 * attempt)
        raise DouyinApiError("请求 %s 失败: %s" % (path, last_err))

    # ------------------------------------------------------------ 收藏夹
    def list_collections(self) -> List[Dict[str, Any]]:
        """分页拉取全部收藏夹。返回 [{"id","name","total_number"}]。"""
        out: List[Dict[str, Any]] = []
        cursor = 0
        while True:
            data = self._get("/collects/list/", [
                ("cursor", str(cursor)),
                ("count", "10"),
                ("update_version_code", "170400"),
            ])
            for c in data.get("collects_list") or []:
                if not isinstance(c, dict):
                    continue
                cid = str(c.get("collects_id") or c.get("collects_id_str") or "")
                if cid:
                    out.append({
                        "id": cid,
                        "name": c.get("collects_name") or cid,
                        "total_number": int(c.get("total_number") or 0),
                    })
            if not data.get("has_more"):
                break
            cursor = int(data.get("cursor") or 0) or (cursor + 10)
            time.sleep(self.delay)
        return out

    def collection_videos(
        self, collection_id: str, limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """分页拉取某个收藏夹的全部视频 aweme。"""
        out: List[Dict[str, Any]] = []
        cursor = 0
        while True:
            data = self._get("/collects/video/list/", [
                ("collects_id", str(collection_id)),
                ("cursor", str(cursor)),
                ("count", "10"),
                ("update_version_code", "170400"),
            ])
            awemes = data.get("aweme_list") or []
            out.extend(a for a in awemes if isinstance(a, dict))
            if limit and len(out) >= limit:
                return out[:limit]
            if not data.get("has_more") or not awemes:
                break
            cursor = int(data.get("cursor") or 0) or (cursor + 10)
            time.sleep(self.delay)
        return out

    # ------------------------------------------------------------ 详情 / 评论
    def aweme_detail(self, aweme_id: str) -> Dict[str, Any]:
        data = self._get("/aweme/detail/", [
            ("aweme_id", str(aweme_id)),
            ("update_version_code", "170400"),
        ])
        aweme = data.get("aweme_detail") or data.get("aweme") or {}
        if not isinstance(aweme, dict):
            raise DouyinApiError("详情接口未返回 aweme_detail: %s" % aweme_id)
        return aweme

    def comments(
        self, aweme_id: str, limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """分页拉取某视频的评论。"""
        out: List[Dict[str, Any]] = []
        cursor = 0
        while True:
            data = self._get("/comment/list/", [
                ("aweme_id", str(aweme_id)),
                ("cursor", str(cursor)),
                ("count", "20"),
                ("update_version_code", "170400"),
            ])
            comments = data.get("comments") or []
            out.extend(c for c in comments if isinstance(c, dict))
            if limit and len(out) >= limit:
                return out[:limit]
            if not data.get("has_more") or not comments:
                break
            cursor = int(data.get("cursor") or 0) or (cursor + 20)
            time.sleep(self.delay)
        return out

    # ------------------------------------------------------------ 下载
    def download_video(
        self, aweme: Dict[str, Any], videos_dir: str, ua: str = UA,
    ) -> str:
        """下载单个 aweme 视频（CDN 直连，无需签名）。返回 ok/skip/fail。"""
        aweme_id = str(aweme.get("aweme_id") or "")
        if not aweme_id:
            return "fail"
        out_path = os.path.join(videos_dir, aweme_id + ".mp4")
        if os.path.exists(out_path) and os.path.getsize(out_path) > 1024:
            print("[下载] %s 已存在，跳过" % aweme_id)
            return "skip"
        url_list = (
            (aweme.get("video") or {}).get("play_addr") or {}
        ).get("url_list") or []
        url = url_list[0] if url_list else ""
        if not url:
            print("[下载] %s 无播放地址，跳过" % aweme_id)
            return "fail"
        try:
            resp = self.session.get(
                url,
                headers={"User-Agent": ua, "Referer": "https://www.douyin.com/"},
                timeout=120,
            )
            if resp.ok and len(resp.content) > 1024:
                with open(out_path, "wb") as f:
                    f.write(resp.content)
                print("[下载] %s -> %s (%d KB)" % (aweme_id, out_path, len(resp.content) // 1024))
                return "ok"
            print("[下载] %s 请求失败: HTTP %s" % (aweme_id, resp.status_code))
        except requests.RequestException as e:
            print("[下载] %s 异常: %s" % (aweme_id, e))
        return "fail"

    # ------------------------------------------------------------ 写操作（收藏夹整理）
    def _post(self, path: str, extra: List[tuple], body: Any = None, retries: int = 3) -> Dict[str, Any]:
        """POST 写接口：参数走 query（a_bogus 签名），body 为 JSON 对象。"""
        fp = gen_verify_fp()
        params = build_common_params(self.webid) + [
            ("uifid", self.uifid),
            ("verifyFp", fp),
            ("fp", fp),
            ("msToken", gen_ms_token()),
        ] + extra
        qs = sign_params(params)
        url = API_BASE + path + "?" + qs
        last_err: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                resp = self.session.post(url, json=body if body is not None else {}, timeout=20)
                if resp.status_code != 200:
                    raise DouyinApiError("写接口 HTTP %s: %s" % (resp.status_code, path))
                data = resp.json()
                if data.get("status_code") == 0:
                    return data
                raise DouyinApiError("写接口 %s 返回 status_code=%s %s" % (
                    path, data.get("status_code"), data.get("status_msg") or ""))
            except (requests.RequestException, ValueError) as e:
                last_err = e
                time.sleep(1.5 * attempt)
        raise DouyinApiError("写接口 %s 失败: %s" % (path, last_err))

    def move_videos(self, to_collects_id: str, aweme_ids: Iterable[str]) -> Dict[str, Any]:
        """把视频加入（移动到）指定收藏夹。aweme_ids 可传多个。
        注意：抖音收藏夹允许一视频在多个夹，此操作只加入目标夹，不从原夹移除。"""
        ids = [str(i) for i in aweme_ids if str(i)]
        if not ids:
            raise DouyinApiError("move_videos 需要至少一个 aweme_id")
        extra: List[tuple] = []
        for i in ids:
            extra.append(("item_ids", i))
        extra += [
            ("item_type", "2"),
            ("to_collects_id", str(to_collects_id)),
            ("update_collects_sort", "true"),
        ]
        return self._post("/collects/video/move/", extra)

    def remove_videos_from_collection(
        self, from_collects_id: str, aweme_ids: Iterable[str], collects_name: str = "",
    ) -> Dict[str, Any]:
        """把视频从指定收藏夹移除（不移除收藏本身，视频仍可在“我的收藏-视频”看到）。

        与 move_videos 共用 /collects/video/move/ 接口，只是把 to_collects_id
        换成 from_collects_id（JS 逆向结论：网页端“从收藏夹移除”即此调用）。
        collects_name 为收藏夹名，可省略。
        """
        ids = [str(i) for i in aweme_ids if str(i)]
        if not ids:
            raise DouyinApiError("remove_videos_from_collection 需要至少一个 aweme_id")
        extra: List[tuple] = []
        for i in ids:
            extra.append(("item_ids", i))
        extra += [
            ("item_type", "2"),
            ("from_collects_id", str(from_collects_id)),
        ]
        if collects_name:
            extra.append(("collects_name", collects_name))
        return self._post("/collects/video/move/", extra)

    def maintain_collection(
        self, action: int, collects_id: str = "", name: str = "", secret: str = "0",
    ) -> Dict[str, Any]:
        """维护收藏夹。action: 1=创建, 0=重命名, 2=删除。"""
        extra: List[tuple] = [("action", str(action))]
        if collects_id:
            extra.append(("collects_id", str(collects_id)))
        if name:
            extra.append(("collects_name", name))
        if secret:
            extra.append(("secret", secret))
        return self._post("/collects/maintain/", extra)

    def create_collection(self, name: str, secret: str = "0") -> Dict[str, Any]:
        return self.maintain_collection(1, name=name, secret=secret)

    def rename_collection(self, collects_id: str, name: str) -> Dict[str, Any]:
        return self.maintain_collection(0, collects_id=collects_id, name=name)

    def delete_collection(self, collects_id: str) -> Dict[str, Any]:
        return self.maintain_collection(2, collects_id=collects_id)


if __name__ == "__main__":
    # 自测：列出收藏夹
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    client = DouyinApiClient(
        os.path.join(base, "output", "douyin", "storage_state.json"),
        webid_path=os.path.join(base, "output", "douyin", "webid.txt"),
    )
    cols = client.list_collections()
    print("收藏夹数量:", len(cols))
    for c in cols:
        print("  -", c["name"], c["total_number"])
