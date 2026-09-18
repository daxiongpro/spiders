# -*- coding: utf-8 -*-
"""
抖音 web API 纯 Python 签名模块（无浏览器、无 JS 引擎依赖）。

实现了 a_bogus 签名（SM3 + 自定义 RC4/Base64/混淆，纯 Python），
签名算法参照开源实现 lonone/real-url (GPL, https://github.com/lonone/real-url)，
与 TikTokDownloader / Douyin_TikTok_Download_API 同源（GPL v3 许可）。
仅供个人整理本人账号数据使用。

用法：
    from douyin_sign import sign_params
    qs = sign_params([("aid", "6383"), ("device_platform", "webapp"), ...])
    # qs 已是带 a_bogus 的完整 query string
"""

import random
import string
import struct
import time
from urllib.parse import quote, urlencode

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36")

# ---------------------------------------------------------------- SM3（国密哈希，纯 Python）
_IV = [
    0x7380166F, 0x4914B2B9, 0x172442D7, 0xDA8A0600,
    0xA96F30BC, 0x163138AA, 0xE38DEE4D, 0xB0FB0E4E,
]


def _rotl(x, n):
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF


def _p0(x):
    return x ^ _rotl(x, 9) ^ _rotl(x, 17)


def _p1(x):
    return x ^ _rotl(x, 15) ^ _rotl(x, 23)


def _ff0(x, y, z):
    return x ^ y ^ z


def _ff1(x, y, z):
    return (x & y) | (x & z) | (y & z)


def _gg0(x, y, z):
    return x ^ y ^ z


def _gg1(x, y, z):
    return (x & y) | (~x & z)


def sm3_hash(data: bytes) -> bytes:
    """纯 Python SM3 哈希，返回 32 字节。"""
    msg = bytearray(data)
    bit_len = len(msg) * 8
    msg.append(0x80)
    while (len(msg) * 8) % 512 != 448:
        msg.append(0)
    msg += struct.pack(">Q", bit_len)
    v = list(_IV)
    for i in range(0, len(msg), 64):
        block = msg[i:i + 64]
        w = list(struct.unpack(">16I", bytes(block))) + [0] * 52
        for j in range(16, 68):
            w[j] = _p1(w[j - 16] ^ w[j - 9] ^ _rotl(w[j - 3], 15)) ^ _rotl(w[j - 13], 7) ^ w[j - 6]
        w1 = [0] * 64
        for j in range(64):
            w1[j] = w[j] ^ w[j + 4]
        a, b, c, d, e, f, g, h = v
        for j in range(64):
            ss1 = _rotl((_rotl(a, 12) + e + _rotl(0x79CC4519 if j < 16 else 0x7A879D8A, j % 32)) & 0xFFFFFFFF, 7)
            ss2 = ss1 ^ _rotl(a, 12)
            if j < 16:
                tt1 = (_ff0(a, b, c) + d + ss2 + w1[j]) & 0xFFFFFFFF
                tt2 = (_gg0(e, f, g) + h + ss1 + w[j]) & 0xFFFFFFFF
            else:
                tt1 = (_ff1(a, b, c) + d + ss2 + w1[j]) & 0xFFFFFFFF
                tt2 = (_gg1(e, f, g) + h + ss1 + w[j]) & 0xFFFFFFFF
            d = c
            c = _rotl(b, 9)
            b = a
            a = tt1
            h = g
            g = _rotl(f, 19)
            f = e
            e = _p0(tt2)
        v[0] = (v[0] ^ a) & 0xFFFFFFFF
        v[1] = (v[1] ^ b) & 0xFFFFFFFF
        v[2] = (v[2] ^ c) & 0xFFFFFFFF
        v[3] = (v[3] ^ d) & 0xFFFFFFFF
        v[4] = (v[4] ^ e) & 0xFFFFFFFF
        v[5] = (v[5] ^ f) & 0xFFFFFFFF
        v[6] = (v[6] ^ g) & 0xFFFFFFFF
        v[7] = (v[7] ^ h) & 0xFFFFFFFF
    return struct.pack(">8I", *v)


# ---------------------------------------------------------------- RC4 / 自定义 Base64
def rc4_encrypt(key: bytes, plaintext: str) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) % 256
        s[i], s[j] = s[j], s[i]
    i = j = 0
    result = bytearray()
    for ch in plaintext.encode():
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        result.append(ch ^ s[(s[i] + s[j]) % 256])
    return bytes(result)


_B64_ALPHABET_0 = "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe"
_B64_ALPHABET_1 = "ckdp1h4ZKsUB80/Mfvw36XIgR25+WQAlEi7NLboqYTOPuzmFjJnryx9HVGDaStCe"


def _b64_encode(data: bytes, alphabet: str) -> str:
    out = []
    for i in range(0, len(data), 3):
        b1 = data[i]
        b2 = data[i + 1] if i + 1 < len(data) else 0
        b3 = data[i + 2] if i + 2 < len(data) else 0
        n = (b1 << 16) | (b2 << 8) | b3
        out.append(alphabet[(n >> 18) & 63])
        out.append(alphabet[(n >> 12) & 63])
        if i + 1 < len(data):
            out.append(alphabet[(n >> 6) & 63])
        if i + 2 < len(data):
            out.append(alphabet[n & 63])
    padding = (4 - len(out) % 4) % 4
    return "".join(out) + "=" * padding


def _abogus_encode(values: list, alphabet: str) -> str:
    out = []
    for i in range(0, len(values), 3):
        v1 = values[i]
        v2 = values[i + 1] if i + 1 < len(values) else 0
        v3 = values[i + 2] if i + 2 < len(values) else 0
        n = (v1 << 16) | (v2 << 8) | v3
        out.append(alphabet[(n >> 18) & 63])
        out.append(alphabet[(n >> 12) & 63])
        if i + 1 < len(values):
            out.append(alphabet[(n >> 6) & 63])
        if i + 2 < len(values):
            out.append(alphabet[n & 63])
    padding = (4 - len(out) % 4) % 4
    return "".join(out) + "=" * padding


# ---------------------------------------------------------------- a_bogus 混淆参数
_BIG_ARRAY = [
    121, 243, 55, 234, 103, 36, 47, 228, 30, 231, 106, 6, 115, 95, 78, 101,
    250, 207, 198, 50, 139, 227, 220, 105, 97, 143, 34, 28, 194, 215, 18, 100,
    159, 160, 43, 8, 169, 217, 180, 120, 247, 45, 90, 11, 27, 197, 46, 3,
    84, 72, 5, 68, 62, 56, 221, 75, 144, 79, 73, 161, 178, 81, 64, 187,
    134, 117, 186, 118, 16, 241, 130, 71, 89, 147, 122, 129, 65, 40, 88, 150,
    110, 219, 199, 255, 181, 254, 48, 4, 195, 248, 208, 32, 116, 167, 69, 201,
    17, 124, 125, 104, 96, 83, 80, 127, 236, 108, 154, 126, 204, 15, 20, 135,
    112, 158, 13, 1, 188, 164, 210, 237, 222, 98, 212, 77, 253, 42, 170, 202,
    26, 22, 29, 182, 251, 10, 173, 152, 58, 138, 54, 141, 185, 33, 157, 31,
    252, 132, 233, 235, 102, 196, 191, 223, 240, 148, 39, 123, 92, 82, 128, 109,
    57, 24, 38, 113, 209, 245, 2, 119, 153, 229, 189, 214, 230, 174, 232, 63,
    52, 205, 86, 140, 66, 175, 111, 171, 246, 133, 238, 193, 99, 60, 74, 91,
    225, 51, 76, 37, 145, 211, 166, 151, 213, 206, 0, 200, 244, 176, 218, 44,
    184, 172, 49, 216, 93, 168, 53, 21, 183, 41, 67, 85, 224, 155, 226, 242,
    87, 177, 146, 70, 190, 12, 162, 19, 137, 114, 25, 165, 163, 192, 23, 59,
    9, 94, 179, 107, 35, 7, 142, 131, 239, 203, 149, 136, 61, 249, 14, 156,
]
_SORT_INDEX = [
    18, 20, 52, 26, 30, 34, 58, 38, 40, 53, 42, 21, 27, 54, 55, 31,
    35, 57, 39, 41, 43, 22, 28, 32, 60, 36, 23, 29, 33, 37, 44, 45,
    59, 46, 47, 48, 49, 50, 24, 25, 65, 66, 70, 71,
]
_SORT_INDEX_2 = [
    18, 20, 26, 30, 34, 38, 40, 42, 21, 27, 31, 35, 39, 41, 43, 22,
    28, 32, 36, 23, 29, 33, 37, 44, 45, 46, 47, 48, 49, 50, 24, 25,
    52, 53, 54, 55, 57, 58, 59, 60, 65, 66, 70, 71,
]
_UA_KEY = bytes([0x00, 0x01, 0x0E])
_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"
_BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _params_to_sm3(param: str, salt: bool) -> bytes:
    s = param + "cus" if salt else param
    return sm3_hash(s.encode())


def _transform_bytes(big_array: list, values: list) -> list:
    arr = list(big_array)
    result = []
    idx_b = arr[1]
    init_val = 0
    val_e = 0
    alen = len(arr)
    for index, char_code in enumerate(values):
        if index == 0:
            init_val = arr[idx_b]
            s = (idx_b + init_val) & 0xFF
            arr[1] = init_val
            arr[idx_b] = idx_b
        else:
            s = (init_val + val_e) & 0xFF
        si = s % alen
        val_f = arr[si]
        result.append(char_code ^ val_f)
        ni = (index + 2) % alen
        val_e = arr[ni]
        nsi = ((idx_b + val_e) & 0xFF) % alen
        init_val = arr[nsi]
        arr[nsi], arr[ni] = arr[ni], arr[nsi]
        idx_b = nsi
    return result


def _rand_bytes(n: int) -> str:
    result = ""
    for _ in range(n):
        rd = random.randint(0, 9999)
        result += chr(((rd & 255) & 170) | 1)
        result += chr(((rd & 255) & 85) | 2)
        result += chr(((rd >> 8) & 170) | 5)
        result += chr(((rd >> 8) & 85) | 40)
    return result


def _gen_fingerprint() -> str:
    iw = random.randint(1024, 1920)
    ih = random.randint(768, 1080)
    ow = iw + random.randint(24, 32)
    oh = ih + random.randint(75, 90)
    sy = random.choice([0, 30])
    sw = random.randint(1024, 1920)
    sh = random.randint(768, 1080)
    aw = random.randint(1280, 1920)
    ah = random.randint(800, 1080)
    return f"{iw}|{ih}|{ow}|{oh}|0|{sy}|0|0|{sw}|{sh}|{aw}|{ah}|{iw}|{ih}|24|24|Win32"


def gen_verify_fp() -> str:
    ms = int(time.time() * 1000)
    b36_chars = []
    n = ms
    if n == 0:
        b36_chars = ["0"]
    else:
        while n > 0:
            b36_chars.append(_BASE36[n % 36])
            n //= 36
    b36 = "".join(reversed(b36_chars))
    uuid = []
    for i in range(36):
        if i in (8, 13, 18, 23):
            uuid.append("_")
        elif i == 14:
            uuid.append("4")
        else:
            n = random.randint(0, 61)
            if i == 19:
                n = (3 & n) | 8
            uuid.append(_BASE62[n])
    return f"verify_{b36}_{''.join(uuid)}"


def gen_ms_token() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=107)) + "=="


def _generate_abogus(params_str: str, body: str, ua: str) -> str:
    """生成 a_bogus 签名。params_str = key=value&... 格式。"""
    ab_dir = {8: 3, 18: 44, 66: 0, 69: 0, 70: 0, 71: 0}
    t1 = int(time.time() * 1000)
    arr1_h = _params_to_sm3(params_str, True)
    arr1 = sm3_hash(arr1_h)
    arr2_h = _params_to_sm3(body if body else "", True)
    arr2 = sm3_hash(arr2_h)
    ua_rc4 = rc4_encrypt(_UA_KEY, ua)
    ua_b64 = _b64_encode(ua_rc4, _B64_ALPHABET_1)
    arr3 = _params_to_sm3(ua_b64, False)
    t2 = int(time.time() * 1000)
    ab_dir[20] = (t1 >> 24) & 255
    ab_dir[21] = (t1 >> 16) & 255
    ab_dir[22] = (t1 >> 8) & 255
    ab_dir[23] = t1 & 255
    ab_dir[24] = t1 // 0x100000000
    ab_dir[25] = t1 // 0x10000000000
    ab_dir[26] = 0
    ab_dir[27] = 0
    ab_dir[28] = 0
    ab_dir[29] = 0
    ab_dir[30] = 0
    ab_dir[31] = 1
    ab_dir[32] = 0
    ab_dir[33] = 1
    ab_dir[34] = 0
    ab_dir[35] = 0
    ab_dir[36] = 0
    ab_dir[37] = 14
    ab_dir[38] = arr1[21]
    ab_dir[39] = arr1[22]
    ab_dir[40] = arr2[21]
    ab_dir[41] = arr2[22]
    ab_dir[42] = arr3[23]
    ab_dir[43] = arr3[24]
    ab_dir[44] = (t2 >> 24) & 255
    ab_dir[45] = (t2 >> 16) & 255
    ab_dir[46] = (t2 >> 8) & 255
    ab_dir[47] = t2 & 255
    ab_dir[48] = 3
    ab_dir[49] = t2 // 0x100000000
    ab_dir[50] = t2 // 0x10000000000
    ab_dir[51] = 0
    ab_dir[52] = 0
    ab_dir[53] = 0
    ab_dir[54] = 0
    ab_dir[55] = 0
    ab_dir[56] = 6383
    ab_dir[57] = 6383 & 255
    ab_dir[58] = (6383 >> 8) & 255
    ab_dir[59] = (6383 >> 16) & 255
    ab_dir[60] = (6383 >> 24) & 255
    fp = _gen_fingerprint()
    ab_dir[64] = len(fp)
    ab_dir[65] = len(fp)
    vals = [ab_dir.get(i, 0) for i in _SORT_INDEX]
    fp_bytes = [ord(c) for c in fp]
    ab_xor = 0
    for idx, k in enumerate(_SORT_INDEX_2):
        v = ab_dir.get(k, 0)
        ab_xor = v if idx == 0 else ab_xor ^ v
    vals.extend(fp_bytes)
    vals.append(ab_xor)
    transformed = _transform_bytes(_BIG_ARRAY, vals)
    prefix = [ord(c) for c in _rand_bytes(3)]
    final = prefix + transformed
    ab = _abogus_encode(final, _B64_ALPHABET_0)
    # 与浏览器行为一致：a_bogus 值再做一次 URL 编码（原串含 '/' 等字符）
    return f"{params_str}&a_bogus={quote(ab, safe='')}"


def sign_params(params: list, body: str = "", ua: str = UA) -> str:
    """对参数列表签名，返回带 a_bogus 的完整 query string（已 URL 编码）。"""
    qs = urlencode(params)
    return _generate_abogus(qs, body, ua)


def build_common_params(webid: str = "") -> list:
    """抖音 web API 通用参数（与浏览器请求一致）。"""
    return [
        ("device_platform", "webapp"),
        ("aid", "6383"),
        ("channel", "channel_pc_web"),
        ("pc_client_type", "1"),
        ("pc_libra_divert", "Windows"),
        ("support_h265", "1"),
        ("support_dash", "1"),
        ("cpu_core_num", "16"),
        ("version_code", "170400"),
        ("version_name", "17.4.0"),
        ("cookie_enabled", "true"),
        ("screen_width", "1280"),
        ("screen_height", "720"),
        ("browser_language", "zh-CN"),
        ("browser_platform", "Win32"),
        ("browser_name", "Chrome"),
        ("browser_version", "142.0.0.0"),
        ("browser_online", "true"),
        ("engine_name", "Blink"),
        ("engine_version", "142.0.0.0"),
        ("os_name", "Windows"),
        ("os_version", "10"),
        ("device_memory", "16"),
        ("platform", "PC"),
    ] + ([("webid", webid)] if webid else [])


if __name__ == "__main__":
    qs = sign_params(build_common_params())
    print("a_bogus 长度:", len(qs.split("a_bogus=")[-1]))
    print(qs[:200], "...")
