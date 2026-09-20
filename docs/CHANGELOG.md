# 改动记录

> 格式：`## YYYY-MM-DD` → `### 改了什么` + `### 为什么`。倒序追加，新的在上。

---

## 2026-09-20 · 文档体系与版本管理

### 改了什么

1. 新建 `docs/`：把 `.workbuddy/memory/` 下的历史日志迁到 `docs/日志/`，新增 `docs/README.md`（目录约定）与本文件。
2. 新建分支 `douyin-v2`（基于 `douyin`）并提交上述全部改动，未推送远端。
3. 清理临时文件：5 个调试探针产物 + `src/__pycache__`，已移到 `C:\Users\Administrator\AppData\Local\Temp\spiders_trash_2026-09-20`。

### 为什么

- 工作记忆原本写在 `.workbuddy/`，属于本机私有目录，既不该进 Git 也不可追溯。改成 `docs/` 后，改动思路随代码一起版本化，换机器/回看历史都能查到。
- 分支用 `douyin-v2` 而不是继续在 `douyin` 上提交，是为了把「可移植性改造」和原版分开，出问题好回滚。

### 验证

- `git status` 干净；`git ls-tree HEAD` 确认 33 个文件已入库，不含 `.workbuddy/`、不含 `output/`。
- 确认 `output/` 与 `__pycache__` 从未进入过版本库，登录态凭证无泄露风险。

---

## 2026-09-20 · 可移植性修复 + 分类自动发现

### 改了什么

1. `requirements.txt` 补 `av>=12.0`。
2. `scripts/run_pipeline.py` 新增 `find_python()`，替掉硬编码的 `C:/ProgramData/miniforge3/python.exe`。
3. `scripts/run_pipeline.py` 新增 `discover_order()`，替掉写死的 5 个分类常量。
4. `scripts/run_pipeline.py` 的 `mark_fail()` 处理时间改为当天日期。
5. `scripts/lark_transcribe.py` 的 `lark-cli` 路径增加 `shutil.which` 探测。
6. `.gitignore` 增加 `_probe*`、`_check*`、`.workbuddy/`、`_realtime.json.tmp`。

### 为什么

- **依赖漏登记**：`lark_transcribe.py` 用 PyAV 抽音频，但 `requirements.txt` 里只有 playwright 和 requests。换机器 `pip install -r` 之后一跑就崩，属于典型的"本机跑得好好的"陷阱。
- **解释器路径写死**：流水线用 `subprocess` 拉起 `fetch_only.py` / `lark_transcribe.py`，原来固定指向这台机器的 miniforge 解释器。换电脑路径必失效。策略改为：`DOUYIN_PYTHON` 环境变量 → 当前解释器 → `which python` → 旧路径兜底。保留旧路径是为了不破坏现有环境。
- **分类清单硬编码**：`ORDER` 只有 5 个分类，但 `config/` 下有 9 个清单。实际 9 个分类都跑完了，说明剩下 4 个是手动补跑的——代码和数据已经脱节。改成扫 `config/list_*.json` 自动发现，保留 `PREFERRED_ORDER` 控制优先级，以后新增分类清单不用再改代码。
- **日期写死**：`mark_fail()` 里写死 `2026-09-17`，重试时生成的占位 MD 会带上错误日期，误导排查。
- **`lark-cli` 找不到**：原来只试两个绝对路径。加上 `shutil.which` 后，只要 CLI 在 PATH 里就能直接用。

### 验证

- 三个脚本 `py_compile` 通过。
- `discover_order()` 实测输出 9 个分类：`未分类, 探店·吃喝, 家庭·婚姻, 生活·出行, 娱乐·休闲, 学习·成长, 投资·理财, 搞钱·事业, 求职·职场`，索引到 762 条视频。

### 已知遗留

- **`output/douyin/storage_state.json` 登录态已失效**，调 `aweme/detail` 返回 HTTP 403。跑流水线前必须重新扫码导出登录态覆盖该文件。
- 转写链路下一步打算改为「抖音自带字幕轨优先 + 本地 ASR 兜底」，见 `日志/2026-09-20.md`，尚未动手。
