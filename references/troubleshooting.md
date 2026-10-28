# 故障排查

按「先看现象、再定位层级」的顺序排查：环境 → 登录 → 查询 → 导出 → 验收。

## 一、环境

| 现象 | 原因 | 处理 |
|---|---|---|
| `缺少 Playwright。请先执行...` | 未装库或未装浏览器内核 | `python -m pip install playwright pillow` 后 `python -m playwright install chromium` |
| `playwright install` 卡住或下载失败 | 网络到 CDN 不通 | 换网络/代理重试，或设置 `PLAYWRIGHT_DOWNLOAD_HOST` 指向可用镜像 |
| PNG 没有白底、进 Word 变黑块 | 未装 Pillow，`_ensure_white_png_background` 静默跳过 | 安装 Pillow 后重跑；脚本只在有 Pillow 时才合成白底 |
| PNG 校验里没有 `png_width` / `png_variance` | 同上，Pillow 缺失时校验降级为只算哈希 | 装 Pillow，否则 PNG 验收是弱校验 |

## 二、登录

先明确当前参数：脚本在失败时会打印 `[连接失败]`，并列出 `url / user / bolt / database`。拿到这份清单再去问用户要正确值，比反复重试有效。

| 现象 | 原因 | 处理 |
|---|---|---|
| `连接 Neo4j 失败（页面提示：...Unauthorized...）` | 用户名或密码错 | 让用户确认用户名（默认 `neo4j`）并用 `NEO4J_PASSWORD` 提供正确密码 |
| `连接 Neo4j 失败（未出现 Cypher 编辑器）` | 地址能打开但不是 Browser，或停留在错误页 | 确认 `--url` 指向 `http://host:7474`，路径会自动补 `/browser/` |
| `旧版登录失败` / `未进入可操作的 Neo4j Browser 登录页` | Browser 还在加载，或已被强制新版 | 脚本会先写 `localStorage.prefersOldBrowser=true` 并刷新；等 5–10 秒再重试，必要时手动在浏览器里切一次旧版 |
| `新版登录失败` | 新版连接表单选择器变化 | 脚本已覆盖三种入口（`connect` / `connection-form-submit` / `Connect to instance`）；都失败说明版本较新，需按页面结构调整选择器 |
| 远程实例连不上，bolt 地址不对 | 新版 Browser 的连接串默认按 `url 主机 + 7687` 推导 | 用 `--bolt-url` 或 `NEO4J_BOLT_URL` 指定真实 bolt 地址（如 `db.internal:7688`） |
| 登录一直转圈 | 密码错 | 密码错往往没有明确报错，表现为后续查询超时；先用 `--probe` 单独验证登录 |
| 库名写错 | 不存在该数据库 | 用默认 `neo4j` 先验证连通，再换目标库；库名区分大小写 |

## 三、查询

| 现象 | 原因 | 处理 |
|---|---|---|
| `查询包含可能截断图谱的模式: LIMIT` | 默认拦截截断查询 | 去掉截断；确实要抽样才对那一条任务设 `allow_truncated_query: true` |
| `请通过 NEO4J_PASSWORD 环境变量或 --password 提供密码` | 环境变量没进当前进程 | 在同一 shell 里 `export NEO4J_PASSWORD=...`；PowerShell 用 `$env:NEO4J_PASSWORD` |
| 图谱为空 / 0 节点 | Cypher 只返回了表格结果（没返回节点或关系） | 改查询为 `RETURN p` 或 `RETURN n, r, m`，确保进的是可视化视图 |
| 图只在 300 个节点处停住 | 旧版 Browser 显示上限 | 脚本已把 `maxRows`/`initialNodeDisplay` 抬到 1,000,000；更大就加 `--browser-limit` |
| 布局没稳定就导出，节点挤成一团 | 力导引还在迭代 | 加 `--wait 8`（大图 10–15 秒）；每个任务也可单设 `wait_seconds` |

## 四、导出

| 现象 | 原因 | 处理 |
|---|---|---|
| 日志出现 `[提示] Export PNG 失败，尝试截图降级` | 菜单未展开或选择器不匹配 | 结果仍可用，但 manifest 记录的是截图产物；需要原生导出时手动确认 Browser 菜单可点 |
| 日志出现 `[降级] DOM SVG` | Export SVG 未触发下载，改为读页面 DOM | 产物是当前视图的 SVG，节点数一般一致；若 `svg_nodes` 偏少，多半是显示上限或视图未展开 |
| `无法获得图谱 SVG` | 页面上没有匹配的 graph SVG 容器 | 确认查询结果切到了可视化标签页，别停在表格视图 |
| `expect_download` 超时 30 秒 | 下载未开始（大图导出慢或浏览器拦截下载） | 重试；或改用 `--format both` 先拿 SVG 再栅格化 |
| 输出被覆盖 | 同名文件已存在 | 批量前确认输出目录；`--resume` 会在文件通过校验时跳过而不是覆盖 |

## 五、验收

| 现象 | 原因 | 处理 |
|---|---|---|
| `SVG 节点数不符: actual=300, expected=1234` | 显示上限截断 | 提高 `--browser-limit` 后重跑；确认旧版 Browser 已生效（新版不受该配置影响） |
| `SVG 关系数不符` 而节点数正确 | 查询只返回了部分关系，或存在重复关系被合并 | 检查 Cypher 是否只 `RETURN n`（丢了关系）；用 `p=(n)-[r]->(m)` 形态 |
| `SVG 未发现图节点` | 导出到的是表格视图或空画布 | 同上，先切可视化再导 |
| `PNG 疑似空白图: variance=...` | 图极小或几乎无内容 | 降低 `min_variance`，或确认查询真的有结果 |
| `PNG 尺寸过小` | 画布区域比阈值小 | 调 `min_width`/`min_height`，或先 `zoom-to-fit` |
| `现有文件未通过校验，将重新导出` | `--resume` 发现旧文件不合格 | 正常行为，会重新查询导出 |

## 六、仍然失败

1. 先跑离线自测，确认不是脚本本身坏了：`python scripts/test_export_helpers.py`（不需要数据库）。
2. 单条最小复现：一个库、一条 `MATCH p=(n)-[r]->(m) RETURN p LIMIT ...`（去掉 LIMIT 再试）。
3. 保留完整终端输出与 manifest，再判断是 Browser 版本差异还是数据问题。
