# Neo4j 图谱图片导出 · neo4j-export-png

把「Neo4j Browser 里的一张图谱，导成能直接放进 Word / PPT 的图片」做成可重复执行的流程，并且**导完能证明图是完整的**。

不是截图工具，是导出 + 审计工具：每张图都记录节点数、关系数、尺寸、方差和 SHA-256，数量不符就是失败。

适用于知识图谱、课程图谱、企业图谱的可视化交付，不写库、不改数据。

---

## 它解决什么问题

| 痛点 | 本技能的做法 |
| --- | --- |
| Browser 默认只画 300 个节点，图被截断却看不出来 | 登录后自动把 `maxRows` / `initialNodeDisplay` 抬到 1,000,000，可再调高 |
| 「下载成功」不等于「图完整」 | 导出后回读文件：SVG 数节点与关系元素，PNG 查尺寸与图像方差 |
| 十几张图要一张张手点 | 任务 JSON 批量驱动，逐条切库、查询、导出、校验 |
| 中途失败只能从头再来 | `--resume` 跳过已通过校验的文件，`--start / --limit` 只补跑失败项 |
| 新旧版 Browser 界面不一样 | 脚本自动识别并按对应选择器登录、切库、导出 |
| 透明背景进 Word 变黑块 | 自动合成白底 |
| 抽样的图被当成全量图交付 | `LIMIT` / `head()` / `[0..n]` 默认拒绝，需显式放行 |

---

## 全链路

```
Neo4j Browser
   │
   ├─ ① login     识别旧版/新版，填账号，强制旧版偏好        → 控制台日志
   ├─ ② config    抬升 maxRows / initialNodeDisplay 上限     → 无显示截断
   ├─ ③ query     逐条切库 + 执行 Cypher（默认拦截断查询）    → 图谱画布
   ├─ ④ export    原生 Export PNG/SVG，失败时按层级降级      → .svg / .png
   └─ ⑤ verify    计数、尺寸、方差、SHA-256                  → manifest.json
```

四道门禁：密码只走环境变量；截断查询默认拒绝；导出必须过校验；manifest 非 `PASS` 即退出码 1。

---

## 连接参数

地址、用户名、数据库都能在提示词里指定，不指定就用内置默认值。

| 参数 | 命令行 | 环境变量 | 默认 |
| --- | --- | --- | --- |
| Browser 地址 | `--url` | `NEO4J_BROWSER_URL` | `http://127.0.0.1:7474` |
| 用户名 | `--user` | `NEO4J_USER` | `neo4j` |
| 数据库 | `--database` | — | `neo4j` |
| bolt 连接串 | `--bolt-url` | `NEO4J_BOLT_URL` | `url 主机 + 7687` |
| 密码 | `--password` | `NEO4J_PASSWORD` | 无（必填） |

连不上时不会静默超时：脚本打印 `[连接失败]` + 当前四项参数 + 排查清单，退出码 2，然后请你提供正确的地址 / 用户名 / 密码 / 库名。

```bash
# 只验证连接，不跑查询
python scripts/neo4j_export_png.py --probe --headless --url http://10.0.0.9:7474 --user graph --database kg_demo
```

---

## 快速开始

```bash
python -m pip install playwright pillow
python -m playwright install chromium

export NEO4J_BROWSER_URL='http://127.0.0.1:7474'
export NEO4J_USER='neo4j'
export NEO4J_PASSWORD='<你的密码>'
```

单条导出（要矢量图就 `--format svg`，两者都要就 `both`）：

```bash
python scripts/neo4j_export_png.py \
  --database neo4j \
  --cypher "MATCH p=(n)-[r]->(m) RETURN p" \
  --output ./images/overview.svg \
  --format svg --expected-nodes 76 --expected-relationships 136 --headless
```

批量导出：

```bash
cp templates/tasks.example.json ./tasks.json   # 按需改库名、Cypher、输出路径
python scripts/neo4j_export_png.py --tasks ./tasks.json --headless
```

失败续跑：

```bash
python scripts/neo4j_export_png.py --tasks ./tasks.json --headless --resume --start 4 --limit 3
```

---

## 验收口径

manifest 的 `status` 必须是 `PASS`、`failure_count` 为 0。

- **SVG**：`svg_nodes` / `svg_relationships` 与期望值一致，文件 > 1 KB，`sha256` 已记录，`query_truncation_markers` 为空
- **PNG**：可打开，尺寸 ≥ 300×180，方差高于空白阈值，背景已合成白色

没给期望计数时，manifest 只能证明「文件有效」，不能证明「结果完整」——要补一条 count 查询做交叉比对。

---

## 目录结构

```
neo4j-export-png/
├── SKILL.md                        # 技能定义（平台解析入口）
├── scripts/
│   ├── neo4j_export_png.py         # 主脚本：登录 / 切库 / 查询 / 导出 / 校验 / manifest
│   └── test_export_helpers.py      # 离线自测，不连数据库
├── references/
│   ├── task-file.md                # 批量任务字段全表与示例
│   └── troubleshooting.md          # 按现象定位的排查路径
├── templates/
│   └── tasks.example.json          # 批量任务模板
└── assets/
    └── icon-512.png                # 市场图标 512×512
```

包内文件全部平铺在二级目录内，符合平台「根目录 / 二级目录 / 文件」两级限制。

---

## 自测

```bash
python scripts/test_export_helpers.py
```

覆盖截断检测、SVG 计数校验、PNG 尺寸与方差校验、输出路径推导，无需 Neo4j 实例。

---

## 安全边界

- 只读：只执行返回图结果的查询与 `:use` / `:config` / `:style` 命令，不写库、不清库
- 密码只从 `NEO4J_PASSWORD` 读取，不落盘、不进 manifest、不进日志
- 不把网页截图冒充 Browser 原生导出；仅在原生导出失败时降级，manifest 保留实际校验结果
- 同名输出会被覆盖，批量前请确认输出目录

---

## License

MIT
