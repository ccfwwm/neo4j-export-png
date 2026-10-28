# CHANGELOG

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
