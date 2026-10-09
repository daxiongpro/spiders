# 抖音收藏文案整理

把抖音收藏视频的口播逐字稿批量提取为 Markdown。

链路：**抖音收藏夹 → 下载 → 飞书妙记转写 → 保存为 MD**

## 目录结构

```
spiders/
├── scripts/               入口脚本（均位于此，统一从这里运行）
│   ├── step1_login.py         扫码登录抖音（登录态持久化，只需一次）
│   ├── step2_download_folder.py  下载某个收藏夹分类的全部视频到本地（增量）
│   ├── fetch_only.py          下载视频（旧的纯 HTTP 版，接口已失效，保留备查）
│   ├── lark_transcribe.py     飞书妙记转写（MP4 → 逐字稿 MD）
│   ├── status.py              进度查看（自检 + 各分类统计）
│   ├── run_pipeline.py        按分类自动流水线（下载+转写，断点续传）
│   ├── progress_dashboard.py  本地进度看板（http://localhost:8137）
│   └── cleanup.py             清理中间产物（不动 MD 成品）
├── config/               分类清单（9 个 list_*.json，视频元数据 + 播放地址）
├── data/                 源数据台账
│   └── 抖音收藏台账_762条.xlsx   收藏总台账 —— 入库
│       7 列 762 行：序号 / 原文件夹 / 新分类 / 标题 / 点赞数 / 链接 / 相关主题备注
│       全项目索引 —— 抖音接口挂掉时，清单侧数据（链接、标题原文）不会丢
├── src/                 共享库
│   ├── douyin_api.py      抖音接口封装（取直链 / 读登录态）
│   ├── douyin_sign.py     抖音签名
│   └── paths.py           路径唯一来源（所有脚本都从这里取目录，改输出位置只动它）
├── docs/                 项目文档（CHANGELOG.md 改动思路 / 日志/ 每日记录）
├── output/
│   ├── 文案/<分类>/<序号>_标题.md   MD 成品 —— 入库
│   ├── downloads/<收藏夹名>/       下载的原始视频 + 清单 —— 忽略
│   ├── douyin/storage_state.json    抖音登录态 —— 忽略（含凭证）
│   ├── _temp_audio/                 下载的音视频 —— 忽略
│   ├── _tr/ _trash/                 中间产物与回收站 —— 忽略
├── requirements.txt       依赖：requests, av
└── README.md
```

输出：`spiders/output/文案/<分类>/<序号>_标题.md`（**在仓库内，随代码一起提交**）

## 环境准备

1. Python 3，安装依赖：
   ```
   pip install -r requirements.txt
   ```
   `av`（PyAV）用于下载后校验音轨是否正常。
2. 抖音登录态：`output/douyin/storage_state.json` 必须存在且有效（约 30 天内）。
   失效需重新登录抖音后导出最新登录态覆盖该文件。
3. 飞书授权：转写走飞书妙记，需 `lark-cli` 已登录（用户身份）。授权：
   ```
   lark-cli auth login --no-wait --json --domain drive,minutes
   ```
   用飞书 App 扫码确认。飞书开放平台后台需给该应用开通
   `drive`（`drive:drive` / `drive:file` / `drive:file:upload`）与 `minutes` 权限并发布。
4. 路径：脚本会自动以「项目根（spiders 目录）」定位 `config/`、`src/`、`output/`，
   输出成品默认落在仓库内 `output/文案/`，中间产物在 `output/_temp_audio/`。
   所有路径集中定义在 `src/paths.py`，换机器用环境变量覆盖：
   ```
   set DOUYIN_BASE=X:/path/to/spiders           :: 仓库根
   set DOUYIN_OUT=X:/path/to/spiders/output/文案   :: MD 成品目录
   set DOUYIN_MEDIA=X:/path/to/spiders/output      :: 中间产物根目录
   set DOUYIN_DOWNLOADS=X:/path/to/videos          :: 视频下载根目录（默认 output/downloads）
   ```
   > 注意 `.gitignore` 是「忽略 output/*，但放行 output/文案/」。
   > 如果把成品目录改到 output 之外，记得同步改忽略规则，否则 MD 提交不上去。
   子进程解释器与 lark-cli 会自动探测，必要时用环境变量指定：
   ```
   set DOUYIN_PYTHON=X:/path/to/python.exe     :: 跑 fetch/transcribe 用的解释器
   set DOUYIN_LARK=X:/path/to/lark-cli.exe     :: 飞书 CLI
   ```

## 用法

`scripts/` 下有两个**入口脚本**，按顺序跑。

> ⚠️ **Windows 上不要直接敲脚本名**（如 `scripts\step2_download_folder.py`）。
> 本机 `.py` **没有文件关联**、`py.exe` 不存在、`PATHEXT` 里也没有 `.PY`，
> 所以 PowerShell 会**静默不执行**——不报错、零输出，看起来像脚本没反应。
> 要么双击 `.bat`，要么把解释器写全（见下面的例子）。

解释器统一用 **base 环境** `C:\ProgramData\miniforge3\python.exe`：项目其它脚本依赖的
`av` / `requests` 只装在这里。具名环境（如 `douyin`）虽然也有 playwright，但**别混用**，
免得出现「A 脚本能跑、B 脚本报缺包」。下面命令都写全路径，复制即可，不受当前激活环境影响。

### 入口 1 · 登录（只需一次）

```
C:\ProgramData\miniforge3\python.exe -u scripts\step1_login.py
```
弹出 Edge → 扫抖音二维码 → 登录态存进 `output/douyin/edge_profile`，之后长期免扫。
参数：`--reset`（换账号）/ `--timeout N` / `--keep-open`。也可直接双击 `scripts\step1_login.bat`。

### 入口 2 · 下载一个收藏夹分类的全部视频

```
C:\ProgramData\miniforge3\python.exe -u scripts\step2_download_folder.py --list                  # ① 看有哪些收藏夹
C:\ProgramData\miniforge3\python.exe -u scripts\step2_download_folder.py --check --folder 搞钱    # ② 只比对本地，看缺哪些
C:\ProgramData\miniforge3\python.exe -u scripts\step2_download_folder.py --folder 搞钱·事业        # ③ 下载（会跳过已下过的）
C:\ProgramData\miniforge3\python.exe -u scripts\step2_download_folder.py --folder 搞钱 --limit 5   # 先小样本试 5 条
```
不带参数运行会**交互式列出收藏夹让你选**。

**最不容易出错的跑法**是走 `.bat`（它内部写死了 base 解释器，不受当前 conda 环境影响，
且 `.bat` 在 `PATHEXT` 里，PowerShell 能直接执行）：
```
scripts\step2_download_folder.bat                  # 双击或直接敲，交互式选收藏夹
scripts\step2_download_folder.bat --list           # 也支持带参数，等价于上面的长命令
scripts\step2_download_folder.bat --check --folder 搞钱
```

**增量下载，重复运行很安全**：判定「已下过」看的是 `aweme_id` 而不是文件名，
且要同时满足「文件存在 + 大于 10KB + 文件头带 `ftyp`」才算数。所以收藏夹新增视频只下新增的、
上次中断的会自动补、误删的会自动重下、收藏夹顺序变了也不会重复下载。

输出 `output/downloads/<收藏夹名>/`：`<序号>_<标题>.mp4` + `_manifest.csv`（逐条状态，Excel 可开）+
`_下载报告.txt`。常用参数：`--overwrite`（强制重下）/ `--delay`（限速）/ `--keep-open`。

### 3 · 转写与其它

- 查看进度：`python -u scripts/status.py [--detail]`
- 一键按序跑完（推荐）：`python -u scripts/run_pipeline.py`
  分类顺序取自 `config/list_*.json`（优先名单在前，其余自动补齐，新增分类无需改代码），
  分块下载+转写，转写失败自动标记存档，断点续传（已处理的幂等跳过）。
- 进度看板：`python -u scripts/progress_dashboard.py`，浏览器开 `http://localhost:8137`
- 清理中间产物：`python -u scripts/cleanup.py`（预览）/ `python -u scripts/cleanup.py --do`（执行）

> `fetch_only.py` 是早期的纯 HTTP 下载脚本，抖音已把需登录接口升级到
> `ArgusSecurityPlugin` 风控，它现在会 403，**已被 step2 取代**，保留仅供备查。

## 备注

- 代理会阻断抖音，脚本已自动清除 `http(s)_proxy` 环境变量。
- step1 / step2 **必须有窗口 + 用系统已装的 Edge**（`channel="msedge"`，零下载）：
  无头会被抖音识别并落到验证码中间页。
- 视频下载根目录默认 `output/downloads`，可用 `set DOUYIN_DOWNLOADS=X:/path` 改到别处（如移动硬盘）。
- 转写失败的视频会生成 `<序号>_【转写失败】标题.md` 占位，不再重复重试。
- 抖音 / 飞书令牌失效时流水线会停止并写 `PIPELINE_HALT_AUTH`，重授权后重跑即可。
