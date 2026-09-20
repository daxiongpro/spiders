# 抖音收藏文案整理

把抖音收藏视频的口播逐字稿批量提取为 Markdown。

链路：**抖音收藏夹 → 下载 → 飞书妙记转写 → 保存为 MD**

## 目录结构

```
spiders/
├── scripts/               入口脚本（均位于此，统一从这里运行）
│   ├── fetch_only.py          下载视频（抖音接口取直链 → 下载 MP4 到 _temp_audio）
│   ├── lark_transcribe.py     飞书妙记转写（MP4 → 逐字稿 MD）
│   ├── status.py              进度查看（自检 + 各分类统计）
│   ├── run_pipeline.py        按分类自动流水线（下载+转写，断点续传）
│   ├── progress_dashboard.py  本地进度看板（http://localhost:8137）
│   └── cleanup.py             清理中间产物（不动 MD 成品）
├── config/               分类清单（9 个 list_*.json，视频元数据 + 播放地址）
├── src/                 共享库
│   ├── douyin_api.py      抖音接口封装（取直链 / 读登录态）
│   ├── douyin_sign.py     抖音签名
│   └── paths.py           路径唯一来源（所有脚本都从这里取目录，改输出位置只动它）
├── docs/                 项目文档（CHANGELOG.md 改动思路 / 日志/ 每日记录）
├── output/
│   ├── 文案/<分类>/<序号>_标题.md   MD 成品 —— 入库
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
   ```
   > 注意 `.gitignore` 是「忽略 output/*，但放行 output/文案/」。
   > 如果把成品目录改到 output 之外，记得同步改忽略规则，否则 MD 提交不上去。
   子进程解释器与 lark-cli 会自动探测，必要时用环境变量指定：
   ```
   set DOUYIN_PYTHON=X:/path/to/python.exe     :: 跑 fetch/transcribe 用的解释器
   set DOUYIN_LARK=X:/path/to/lark-cli.exe     :: 飞书 CLI
   ```

## 用法

所有命令都在 `scripts/` 目录下运行（或带路径调用）：

- 查看进度：`python -u scripts/status.py [--detail]`
- 单分类手动跑：先 `python -u scripts/fetch_only.py --category 探店·吃喝`，再 `python -u scripts/lark_transcribe.py`
- 一键按序跑完（推荐）：`python -u scripts/run_pipeline.py`
  分类顺序取自 `config/list_*.json`（优先名单在前，其余自动补齐，新增分类无需改代码），
  分块下载+转写，转写失败自动标记存档，断点续传（已处理的幂等跳过）。
- 进度看板：`python -u scripts/progress_dashboard.py`，浏览器开 `http://localhost:8137`
- 清理中间产物：`python -u scripts/cleanup.py`（预览）/ `python -u scripts/cleanup.py --do`（执行）

## 备注

- 代理会阻断抖音，脚本已自动清除 `http(s)_proxy` 环境变量。
- 转写失败的视频会生成 `<序号>_【转写失败】标题.md` 占位，不再重复重试。
- 抖音 / 飞书令牌失效时流水线会停止并写 `PIPELINE_HALT_AUTH`，重授权后重跑即可。
