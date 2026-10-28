# CHANGELOG

## v1.1.0 — 2026-10-28

环境自愈：AI 遇到缺依赖时能自己配好，不用用户手动折腾。

### 新增

- **`scripts/setup_env.py`**：依赖体检 / 自动安装 / 启动验证三合一
  - 体检项：Python ≥ 3.10、`playwright`、`PIL`（pillow 的导入名，不按包名判存在）、Chromium revision
  - `--install` 只补缺失项，pip 按 aliyun → tencent → tuna → 官方源逐个重试；Chromium 走 `cdn.npmmirror.com/binaries/playwright`，失败回落官方 CDN
  - `--verify` 真实启动一次无头 Chromium，证明「装上了」且「能用」
  - 退出码 `0` 可用 / `3` 有缺失 / `4` 安装失败或 Python 过低；`--json` 机器可读
- **`references/environment.md`**：依赖矩阵、pip 与 Playwright 镜像实测表、代理与企业内网、完全离线安装、常见安装失败对照表
- **`scripts/test_setup_env.py`**：5 项离线自测（包名映射、体检结构、镜像配置、浏览器判定、`PLAYWRIGHT_BROWSERS_PATH` 生效）

### 调整

- **导出默认无窗口**（`headless=True`），headless shell 即可跑；新增 `--headed` 弹窗口排查登录页，`--headless` 保留兼容
- 浏览器判定改用 `playwright install --dry-run` 取当前版本要求的目录，能识别「目录存在但 revision 不匹配」与「只有 headless shell、没有完整 chromium」
- SKILL.md 增加「环境准备（缺依赖时自己装）」一节，标准流程第 1 步改为环境自检

### 实测

Windows 11 + Python 3.13：`--install` 从 npmmirror 拉取 chromium-1248 约 40 秒完成，`--verify` 启动成功，退出码 0。

## v1.0.0 — 2026-10-28

首个 WorkBuddy 开放平台版本，基于原 `neo4j-export-png` 技能重构。

### 新增

- **连接参数可配置**：`--url` / `--user` / `--database` / `--bolt-url` 四项支持命令行、环境变量与任务文件三级来源，未指定时使用内置默认值（`http://127.0.0.1:7474` / `neo4j` / `neo4j`）
- **连接失败可诊断**：登录后校验页面报错与 Cypher 编辑器是否出现，失败时输出 `[连接失败]` + 当前四项参数 + 逐项排查清单，退出码 2，不再静默超时
- **`--probe` 探活**：只验证登录不执行查询，批量前先确认凭据可用
- **新版 Browser bolt 地址可覆盖**：原先固定 `127.0.0.1:7687`，改为按 URL 主机推导，支持 `--bolt-url` / `NEO4J_BOLT_URL`
- **批量任务顶层 `database`**：任务、顶层、命令行、默认值依次兜底
- **平台规范适配**：SKILL.md 补齐 `display_name` / `description_zh` / `description_en` / `version` / `author` / `category`，目录压平为两级结构
- **文档**：新增 `references/troubleshooting.md` 按现象定位的排查表、`templates/tasks.example.json` 模板、`assets/icon-512.png` 图标

### 调整

- 单条导出的 `--database` 由必填改为可选（默认 `neo4j`）
- 离线自测从 4 项扩展到 7 项，覆盖默认值、bolt 推导与连接提示文案
