# 批量任务文件

批量导出用一份 UTF-8 JSON 驱动。脚本按 `tasks` 数组顺序执行，每条任务独立切库、查询、导出、校验；任一失败不影响其余任务继续，但整体 manifest 会标 `FAIL`。

不要在 JSON 里写 `password`。密码只从 `NEO4J_PASSWORD` 环境变量读；旧任务文件里的 `password` 字段会被忽略，不要沿用。

## 顶层字段

| 字段 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `tasks` | 是 | — | 导出任务数组，见下节 |
| `url` | 否 | `NEO4J_BROWSER_URL` 或 `http://127.0.0.1:7474` | Neo4j Browser 地址 |
| `user` | 否 | `NEO4J_USER` 或 `neo4j` | 用户名 |
| `database` | 否 | 命令行 `--database` 或 `neo4j` | 全局默认数据库；任务里的 `database` 优先级更高 |
| `format` | 否 | 命令行 `--format`（png） | 全局默认格式：`png` / `svg` / `both` |
| `browser_limit` | 否 | `1000000` | 旧版 Browser 的 `maxRows` 与 `initialNodeDisplay` 阈值 |
| `style` | 否 | 空 | 旧版 Browser 的 `:style` 内容，控制节点直径、标题、字号 |
| `manifest` | 否 | `neo4j_export_manifest.json` | 审计清单输出路径 |
| `resume` | 否 | `false` | 已有文件通过校验则跳过查询 |
| `allow_truncated_query` | 否 | `false` | 全局允许抽样查询；只在该任务显式要求时开启 |

## 任务字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `database` | 是（可用顶层 `database` 兜底） | 查询前切换的数据库；任务、顶层、命令行、默认 `neo4j` 依次兜底 |
| `cypher` | 是 | 必须返回图结果，建议 `RETURN p` 或返回节点与关系；含 `LIMIT`/`head()`/`[0..n]` 会被拒 |
| `output` | 是 | 输出路径；`both` 用同一主文件名生成 `.svg` 与 `.png` |
| `format` | 否 | 覆盖全局格式，取 `png` / `svg` / `both` |
| `name` | 否 | manifest 里的可读任务名，建议写中文主题名 |
| `course` / `direction` | 否 | 教研场景的审计元数据（课程、方向），不进查询 |
| `wait_seconds` | 否 | 该任务额外等待布局稳定的秒数 |
| `expected_nodes` | 否 | SVG 应含节点数；不一致即该任务失败 |
| `expected_relationships` | 否 | SVG 应含关系数；不一致即该任务失败 |
| `allow_truncated_query` | 否 | 仅该任务允许抽样查询 |
| `min_width` / `min_height` | 否 | PNG 最小尺寸，默认 300×180 |
| `min_variance` | 否 | PNG 空白判定阈值，默认 3.0 |

## 示例

```json
{
  "url": "http://127.0.0.1:7474",
  "user": "neo4j",
  "format": "svg",
  "browser_limit": 1000000,
  "manifest": "./images/neo4j_export_manifest.json",
  "resume": true,
  "style": "node { diameter: 58px; caption: '{name}'; font-size: 10px; } relationship { caption: '<type>'; font-size: 8px; }",
  "tasks": [
    {
      "name": "专业图谱全景",
      "database": "bigacct-professional",
      "cypher": "MATCH p=(major:专业)-[:对接产业业务]->(:产业领域)-[:支撑岗位]->(:岗位群)-[:要求能力]->(:能力域)-[:分解为]->(:能力单元)-[:课程支撑]->(:课程) RETURN p",
      "output": "./images/专业图谱全景.svg",
      "expected_nodes": 76,
      "expected_relationships": 136,
      "wait_seconds": 10
    },
    {
      "name": "指定课程双格式图",
      "course": "智能中级财务会计",
      "direction": "知识路径",
      "database": "bigacct-knowledge",
      "cypher": "MATCH p=(source)-[relation]->(target) WHERE source.course_name='智能中级财务会计' AND target.course_name='智能中级财务会计' RETURN p",
      "output": "./images/智能中级财务会计知识路径",
      "format": "both",
      "wait_seconds": 8
    }
  ]
}
```

## 全量与抽样

默认拒绝下列截断模式，因为它们会让「图片看起来完整、实际少了一大半」：

- `LIMIT 100`
- `head(collect(...))`
- `nodes[0..50]`

用户明确要「典型路径」「代表节点」或调试小图时，只对那一条任务加：

```json
{ "allow_truncated_query": true }
```

这放行的是查询截断，不改 Browser 显示阈值（`browser_limit` 单独控制）。

## manifest

每条任务记录：

- `database`、`name`、`course`、`direction`
- `outputs`：绝对路径、字节数、SHA-256
- SVG：`svg_nodes`、`svg_relationships`；PNG：`png_width`、`png_height`、`png_variance`
- `query_truncation_markers`：命中的截断模式，全量任务应为空

顶层汇总：`generated_at`、`status`（`PASS`/`FAIL`）、`task_count`、`success_count`、`failure_count`、`browser_limit`。

有任意失败时 `status` 为 `FAIL`、退出码 1，成功项仍写入 manifest；随后用 `--resume --start N --limit M` 只补跑失败几项。
