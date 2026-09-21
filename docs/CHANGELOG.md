# 改动记录

> 格式：`## YYYY-MM-DD` → `### 改了什么` + `### 为什么`。倒序追加，新的在上。

---

## 2026-09-21 · 收藏台账入库

### 改了什么

1. 桌面 `抖音收藏台账_762条.xlsx`（123KB）移入仓库 `spiders/data/`，桌面不再保留。
2. `README.md` 目录结构补 `data/` 及其字段说明。

### 为什么

- **核心索引一直躺在版本库外**：这份台账是全项目的源头数据——7 列 762 行，含每条视频的**完整链接、标题原文、点赞数、抖音原生文件夹名、新分类、主题备注**。它之前只存在桌面，不受任何版本管理，丢一次就得重新拉一遍接口。
- **它是接口不可用时的兜底**：`config/list_*.json` 虽然也有元数据，但台账是人工复核过的最终版本。抖音侧一旦抽风（比如现在的 403），至少"有哪些视频、标题是什么、链接是什么"这些清单数据不会跟着一起失效。
- **另起 `data/` 而非塞进 `config/`**：`config/` 下是脚本直接消费的机器输入（list_*.json）；台账是人工维护、会被 WPS 反复编辑的产物。两者生命周期不同，混放容易误改。

### 验证

- 移动前后字节数一致：126558 B；已备份到 `%TEMP%\spiders_backup_taizhang\`。
- 新路径下用 openpyxl 重读通过：sheet「收藏台账」，`A1:G763`，数据行 762。
- 762 行**全部**能正则解析出 `aweme_id`，缺链接 0 条，id 去重后仍是 762（无重复）。
- 台账 9 个分类与 `output/文案/` 的 9 个目录一一对应，两侧总数均为 762。
- 分类分布：娱乐·休闲 126 / 探店·吃喝 120 / 搞钱·事业 105 / 家庭·婚姻 104 / 学习·成长 89 / 生活·出行 63 / 求职·职场 63 / 未分类 53 / 投资·理财 39。

### 已知遗留

- `.gitignore` 无需改动——`data/` 不在任何忽略规则内，已确认可直接入库。
- 台账里的「未分类」53 条与此前统计的 53 篇【转写失败】数量吻合，**两者是否同一批尚未比对**，待核实。

---

## 2026-09-20 · MD 成品移入仓库 + 路径统一

### 改了什么

1. 762 篇 MD 从桌面 `抖音收藏文案整理/` 搬入仓库 `spiders/output/文案/`，全部入库。
2. 新增 `src/paths.py`，作为路径的唯一来源。
3. 6 个脚本（fetch_only / lark_transcribe / status / cleanup / run_pipeline / progress_dashboard）全部改为从 `paths.py` 取目录，不再各自拼接。
4. `lark_transcribe.py` 里 lark-cli 的 `cwd` 由 `OUT_CAT` 改为 `MEDIA_ROOT`。
5. `.gitignore`：由整条忽略 `output/` 改为 `output/*` + `!output/文案/`，再单独列出 `output/douyin/`、`output/_temp_audio/`、`output/_tr/`、`output/_trash/`。
6. `cleanup.py`：清理扫描目标改到 `MEDIA_ROOT`；遗留文件扫描从只认 `*.mp4` 扩展到 `mp3/m4a/m4s`。

### 为什么

- **成品在仓库外**：原本输出根目录是 `spiders` 的**同级兄弟目录**（桌面上的 `抖音收藏文案整理`），完全不受版本管理，换电脑等于白干一次。
- **忽略规则冲突**：`.gitignore` 原本整条忽略 `output/`（当初为了挡 `storage_state.json` 凭证）。所以单纯的"把 MD 挪进 output/"是不够的——挪进去照样提交不了。必须改成精确放行 `output/文案/`，同时继续挡住凭证和几十 MB 音视频。
- **路径写死在 6 个地方**：同一个默认值 `dirname(BASE)/"抖音收藏文案整理"` 被复制了 6 份。改输出位置要同步 6 处，漏一个就会静默写回桌面且很难发现。收敛成一个模块是治本。
- **lark-cli 的 cwd 必须改**：它只把中间产物写到"当前工作目录"。原来 cwd 就是输出根目录，同时也是 MD 成品目录；迁移后若继续用 `OUT_CAT`，lark-cli 会把临时文件直接写进 `文案/`，污染成品目录。
- **cleanup 漏扫**：抽音频阶段会留下 `mp3`/`m4a`，而脚本只扫 `*.mp4`。这正是桌面 `_temp_audio` 里 37 个 mp3（51.8MB）常年没被回收的原因——它们对应的 MD 全都已生成，本该被清掉。

### 验证

- 搬迁前后 MD 总数均为 762，9 个分类逐个核对无误。
- `src/paths.py` 直接运行，7 条路径全部落在仓库内。
- `status.py` 跑通：`OUT_CAT` 指向新目录，9 个分类全部满贯 762/762，MD 成品 2.3MB。
- 6 个脚本全部 `py_compile` 通过。
- `git check-ignore` 确认 `output/文案/…md` 未被忽略；`git status -uall` 统计到 763 个待新增（762 MD + paths.py）。

### 已知遗留

- 桌面 `抖音收藏文案整理/_temp_audio/` 还留着 37 个 mp3 + `probe_meta.json`（51.8MB），**等待用户确认是否删除**。已核对其对应 MD 全部已生成，属于可安全回收的残留。
- `storage_state.json` 登录态仍失效（403），流水线暂时跑不动。

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
