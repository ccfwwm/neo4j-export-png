---
name: neo4j-export-png
display_name: Neo4j 图谱图片导出
display_name_en: Neo4j Graph Image Export
description: 用 Playwright 驱动 Neo4j Browser 自动登录、切库、跑 Cypher，并把图谱批量导出为 PNG/SVG，附节点关系计数、SHA-256 与尺寸校验的审计清单。当用户要 Neo4j 图谱截图、知识图谱可视化导出、Export PNG、Export SVG、全量图谱图片、按课程或主题批量出图、图谱图片验收与断点续跑时使用。不用于改图谱数据，也不替代 Neo4j 数据校验。关键词：Neo4j、图谱导出、知识图谱图片、Browser 截图、导出 PNG、导出 SVG、批量截图、图谱可视化。
description_zh: Neo4j 图谱图片导出：自动登录 Neo4j Browser、切换数据库、执行 Cypher，批量导出 PNG/SVG，并给出节点数、关系数、文件哈希的验收清单；缺依赖时用国内镜像自动装好，支持续跑与全量显示。
description_en: Export Neo4j Browser graph visualizations to PNG or SVG. Automates login, database switching and Cypher execution, then verifies node/relationship counts, file size and SHA-256 in a manifest, with batch runs, resume and full-graph display.
category: 开发工具
version: 1.1.0
author: Luwen
---

# Neo4j 图谱图片导出

把「Neo4j Browser 里的一张图谱，导成能直接放进 Word/PPT 的图片」做成可重复执行的流程，并且**导出后能证明图是完整的**：脚本会记录节点数、关系数、尺寸、方差与 SHA-256。

核心脚本：`scripts/neo4j_export_png.py`（Python 3.10+，依赖 Playwright、Pillow）。兼容旧版与新版 Neo4j Browser。

## 何时使用

适用：

- 要把 Neo4j 里的图导成 PNG 或 SVG，或同一张图同时要矢量版和预览版
- 图谱节点多（几百到几千），默认 300 节点显示上限会把图截断
- 要按课程/主题/库批量出图，一次导十几张，失败后还要续跑
- 导出结果要验收：节点数、关系数要和数据库对得上，不能只看「下载成功」
- 图片要进 Word/PPT，透明背景需要合成白底

不适用：

- 要改图谱数据（增删节点、改关系、写库）——本技能只读
- 只想在 Neo4j Browser 里看一眼图，不需要落盘文件
- 要做图数据库建模、Cypher 调优、数据质量校验——导出图片不代表数据正确

## 铁律

1. **只读**。只执行返回图结果的查询与 `:use` / `:config` / `:style` 这类 Browser 命令；禁止在任何环节写入、删除节点关系或清库。
2. **密码只走环境变量**。密码放进 `NEO4J_PASSWORD` 当前进程环境，禁止写进脚本、任务 JSON、报告或日志，也不要在回复里复述。任务文件里出现 `password` 字段时视为无效，不沿用。
3. **全量查询不截断**。`LIMIT n`、`head(collect(...))`、`[0..n]` 会被脚本直接拒绝。只有用户明确要抽样图时，才对**那一条任务**设 `allow_truncated_query: true`。
4. **下载成功 ≠ 图片完整**。必须看 manifest：SVG 核对节点/关系计数，PNG 核对尺寸与方差。用户在已知规模时给出 `expected_nodes` / `expected_relationships`，数量不符即失败。
5. **不靠删节点换可读性**。原始 SVG 全量保存；要给人看的报告图，另出栅格化或分层专题图，不要动源图。
6. **覆盖要确认**。输出同名文件会被覆盖，批量执行前先和用户确认输出目录。

## 连接参数（用户说了就用用户的，没说就用内置默认）

地址、用户名、密码、数据库（以及新版 Browser 的 bolt 串）都可以由用户在自然语言里指定，脚本从命令行参数或任务文件读取；**用户没提就用默认值**，不要为了齐全反复追问。

| 参数 | 命令行 | 环境变量 | 内置默认 |
|---|---|---|---|
| Browser 地址 | `--url` | `NEO4J_BROWSER_URL` | `http://127.0.0.1:7474` |
| 用户名 | `--user` | `NEO4J_USER` | `neo4j` |
| 密码 | `--password`（不推荐） | `NEO4J_PASSWORD` | 无，必须提供 |
| 数据库 | `--database` 或任务里 `database` | — | `neo4j` |
| bolt 连接串（新版 Browser 用） | `--bolt-url` | `NEO4J_BOLT_URL` | `url 主机 + 7687` |

取值规则：

1. **用户明确给了值就直接用**，例如「连 `http://192.168.1.20:7474`，用户 `graph`，库 `kg_demo`」→ `--url http://192.168.1.20:7474 --user graph --database kg_demo`。
2. **用户只给了一部分**，其余保持默认，并在回复里说明用了哪些默认值。
3. **密码永远不由 AI 代填**：让用户在自己的终端 `export NEO4J_PASSWORD='...'`，不要把明文密码写进对话、命令或任务文件。
4. **批量任务的优先级**：任务里的 `database` > 任务文件顶层 `database` > `--database` > 默认 `neo4j`。多库场景每条任务单独写 `database`。
5. **先探活再批量**：不确定能否连通时，先跑 `--probe`（只登录不查询），通过再执行导出。

连接失败时的处理（不要盲目重试）：

- 脚本会打印 `[连接失败]` + 当前 `url / user / bolt / database` 与逐项排查清单，随后以退出码 2 结束，不会带着错参数硬跑十几分钟。
- 此时把脚本给出的当前参数复述给用户，请用户提供**正确的地址 / 用户名 / 密码 / 数据库名**，改完再重试。
- 常见判定：能打开页面但卡在登录 → 用户名或密码错；页面报 `Unauthorized` → 凭据问题；`未出现 Cypher 编辑器` → 地址对但 Browser 版本/路径异常；查询报数据库不存在 → 库名错。

## 环境准备（缺依赖时自己装，不要让用户手动折腾）

一条命令搞定体检、安装、验证：

```bash
python scripts/setup_env.py            # 体检：缺什么就打印可执行命令，缺失时退出码 3
python scripts/setup_env.py --install  # 缺什么装什么：pip 与 Chromium 都自动换国内镜像重试
python scripts/setup_env.py --verify   # 再真实启动一次无头 Chromium，确认能用
```

判定规则：

- 退出码 `0` → 环境可用，直接进入导出。
- 退出码 `3` → 有缺失，跑 `--install`（默认 `--mirror auto`：aliyun → tencent → tuna → 官方源；Chromium 走 `cdn.npmmirror.com/binaries/playwright`，失败再回落官方 CDN）。
- 退出码 `4` → 安装失败或 Python 版本过低。此时读 @references/environment.md 的「代理与企业内网」「常见安装失败」两节，按现象对应处理，再向用户说明缺什么、需要什么权限（如 Linux 的 `--with-deps` 要 sudo）。
- 用户机器已有可用 Playwright 时不要重复安装：`--install` 只补缺失项。

需要手动装时的等价命令：

```bash
python -m pip install playwright pillow --index-url https://mirrors.aliyun.com/pypi/simple/
PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright python -m playwright install chromium
```

密码与连接参数（下面这组环境变量由用户在自己终端设置，不要写进脚本或对话）：

```bash
export NEO4J_BROWSER_URL='http://127.0.0.1:7474'
export NEO4J_USER='neo4j'
export NEO4J_PASSWORD='<本机密码>'
```

Windows 下用 `$env:NEO4J_PASSWORD='...'`；macOS/Linux 用 `export`。Chromium 的 revision 与 `playwright` 包版本绑定，升级包后必须重装浏览器——`setup_env.py` 用 `playwright install --dry-run` 校验，能识别「目录在但版本不对」。

## 标准流程

1. **环境自检**：`python scripts/setup_env.py --verify` 通过再往下走；缺依赖就 `--install`，别带着缺件硬跑。
2. **确认目标**：按用户给的地址、用户名、库名（没给就用默认）先跑 `--probe` 探活，确认「要导哪张图」的 Cypher。连通性不通就先解决连接，别急着导出。
3. **定格式**：要缩放排版、进 Word/PPT、节点多 → SVG；明确要截图/PNG 或目标系统不认 SVG → PNG；两者都要 → `both`（SVG 为原始交付，PNG 为预览）。
4. **定规模**：能查到节点/关系总数时，填进 `expected_nodes` / `expected_relationships`，这是后面验收的唯一硬标准。
5. **执行**：单条用命令行参数；多张用任务 JSON（结构见 @references/task-file.md）。多库任务必须逐条切库，脚本已按任务切库。
6. **验收**：读 manifest，`status` 必须为 `PASS`、`failure_count` 为 0；逐项核对计数与哈希。不通过按 @references/troubleshooting.md 定位，必要时 `--resume` 续跑。
7. **交付**：先给用户结论（成功几张、每张多少节点/关系、文件在哪），再给路径清单。

## 先探活（可选但推荐）

```bash
python scripts/neo4j_export_png.py --probe --headless \
  --url http://127.0.0.1:7474 --user neo4j --database neo4j
```

通过时打印 `[连接成功] url=... user=... bolt=... browser=old|new`；失败时打印 `[连接失败]` 与排查清单并以退出码 2 结束，此时按上文「连接失败时的处理」向用户索取正确参数。

## 单条导出

```bash
python scripts/neo4j_export_png.py \
  --url http://127.0.0.1:7474 --user neo4j --database neo4j \
  --cypher "MATCH p=(n)-[r]->(m) RETURN p" \
  --output ./images/overview.svg \
  --format svg --expected-nodes 76 --expected-relationships 136 --headless
```

`--url` / `--user` / `--database` 省略即用默认值；`--format svg` 换成 `png` 或 `both` 即可；`--headless` 不弹窗，适合批处理。

## 批量导出

任务文件模板：`templates/tasks.example.json`；字段全表与示例见 @references/task-file.md。

```bash
python scripts/neo4j_export_png.py --tasks ./tasks.json --headless --manifest ./images/manifest.json
```

常用控制：

| 参数 | 作用 |
|---|---|
| `--tasks` | 任务 JSON 路径；与单条参数二选一 |
| `--url` / `--user` / `--database` | 覆盖连接与库名，默认 `http://127.0.0.1:7474` / `neo4j` / `neo4j` |
| `--bolt-url` | 新版 Browser 的连接串，默认按 url 主机 + 7687 推导 |
| `--probe` | 只验证登录，不执行任何查询 |
| `--resume` | 已有文件通过校验就跳过查询，但仍重算校验并写 manifest |
| `--start N --limit M` | 从第 N 条开始只跑 M 条，用于失败续跑 |
| `--manifest` | 审计清单路径，默认 `neo4j_export_manifest.json` |
| `--wait 8` | 力导引布局稳定等待秒数，节点越多调越大 |
| `--format png\|svg\|both` | 全局默认格式，单条任务可覆盖 |
| `--browser-limit 2000000` | 旧版 Browser 的 `maxRows` / `initialNodeDisplay` 上限，默认 1,000,000 |
| `--allow-truncated-query` | 仅当用户明确要抽样图时启用 |

旧版 Browser 默认只画 300 个节点，脚本登录后会把 `maxRows` 与 `initialNodeDisplay` 抬到 1,000,000；图比这还大时提高 `--browser-limit`，并仍然以 SVG 实际计数验收——阈值只是显示上限，不是数据保证。

## 验收口径

manifest 的 `status` 必须是 `PASS`，`failure_count` 为 0。

SVG（全量图的默认验收）：

- `svg_nodes` 与 `expected_nodes` 一致，`svg_relationships` 与 `expected_relationships` 一致
- 文件 > 1 KB，`sha256` 已记录
- `query_truncation_markers` 为空

PNG：

- 可正常打开，尺寸不小于 300×180（可用 `min_width` / `min_height` 调）
- 图像方差高于空白阈值（默认 3.0，可用 `min_variance` 调）
- 透明背景已合成白底，进 Word/PPT 不会变黑

没给期望计数时，manifest 只能证明「文件有效」，不能证明「查询结果完整」——此时要补一条 Neo4j 计数查询（`MATCH (n) RETURN count(n)` 等）做交叉比对，并在回复里说明这是弱验收。

## 安全与边界

- 脚本不写库。若用户要求「顺便把图里的节点删掉」，明确拒绝并说明本技能只读。
- 不执行与目标图谱无关的 `:use`、清库或数据库切换。
- 不在日志、报告、任务文件里保留密码；`--password` 仅在无法用环境变量时使用，且不写进任何落盘文件。
- 输出目录写错会覆盖同名图，批量前先 `ls` 确认。

## 参考

- @references/task-file.md —— 批量任务字段全表、示例、截断与 manifest 说明
- @references/troubleshooting.md —— 登录/新版旧版 Browser/导出失败/计数不符的排查路径
- @references/environment.md —— 依赖矩阵、pip 与 Playwright 镜像、代理与离线安装、安装失败对照表
- `scripts/setup_env.py` —— 依赖体检 / 自动安装 / 启动验证（退出码 0 可用、3 缺失、4 失败）
- `scripts/test_export_helpers.py` —— 不连数据库即可跑的离线自测（截断检测、SVG/PNG 校验、默认值与 bolt 推导）
