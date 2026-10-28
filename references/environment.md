# 依赖与环境

导出脚本依赖三样东西：Python 3.10+、`playwright` 包、Playwright 自带的 Chromium。`pillow` 可选但**强烈建议装**——没装时 PNG 白底合成与尺寸/方差校验都会静默降级。

AI 遇到环境问题时不要靠猜，按本文的顺序执行即可跑通。

## 一条命令体检 / 安装

```bash
python scripts/setup_env.py            # 体检，缺什么直接打印可执行命令（缺失时退出码 3）
python scripts/setup_env.py --install  # 缺什么装什么，pip 与浏览器都自动换镜像重试
python scripts/setup_env.py --verify   # 体检后真实启动一次无头 Chromium，证明能用而不只是装上
```

`--install --verify` 通过（退出码 0）再执行导出，这比导到一半报缺依赖省时间。

脚本行为：

- `--mirror auto`（默认）：国内镜像优先，失败回落官方源
- `--mirror global`：只走官方源，适合企业内网有统一镜像或海外网络
- 只装缺的那一项，已装的不动；`--json` 给机器可读结果
- 退出码：`0` 可用 / `3` 有缺失（未安装）/ `4` 安装失败或 Python 版本过低

## 镜像

pip（按脚本尝试顺序）：

| 名称 | 地址 | 备注 |
|---|---|---|
| aliyun | `https://mirrors.aliyun.com/pypi/simple/` | 默认首选，本机实测 200 |
| tencent | `https://mirrors.cloud.tencent.com/pypi/simple/` | 备选，本机实测 200 |
| tuna | `https://pypi.tuna.tsinghua.edu.cn/simple/` | 部分网络对 curl 直接 403，浏览器访问正常时可用 |
| pypi | `https://pypi.org/simple/` | 官方兜底 |

Playwright 浏览器二进制（`PLAYWRIGHT_DOWNLOAD_HOST`）：

| 名称 | 值 | 备注 |
|---|---|---|
| npmmirror | `https://cdn.npmmirror.com/binaries/playwright` | 国内首选，实测 `builds/chromium/*` 返回 200 |
| npmmirror-legacy | `https://registry.npmmirror.com/-/binary/playwright` | 老路径，新版本可能缺文件 |
| 官方 | 不设该变量 | `download.playwright.dev`，国内常超时 |

手动等价命令：

```bash
python -m pip install playwright pillow --index-url https://mirrors.aliyun.com/pypi/simple/
PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright python -m playwright install chromium
```

Windows 下第二条写成（同一 shell 内）：

```bash
set PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright
python -m playwright install chromium
```

## 依赖矩阵

| 依赖 | 必需 | 缺失后果 | 检查方式 |
|---|---|---|---|
| Python ≥ 3.10 | 是 | 脚本语法不兼容 | `python -V` |
| `playwright` | 是 | 直接报「缺少 Playwright」并退出 | `python -c "import playwright"` |
| Chromium（Playwright 版） | 是 | 启动浏览器失败 | `setup_env.py` 会用 `playwright install --dry-run` 校验目录是否存在 |
| `pillow` | 否（建议） | PNG 不合成白底；PNG 校验退化为只算哈希 | `python -c "import PIL"` |

**版本绑定**：Chromium 的 revision 由 `playwright` 包版本决定。升级 `playwright` 后必须重跑 `playwright install chromium`，否则会报找不到浏览器——`setup_env.py` 用 dry-run 拿到当前版本要求的目录，能识别这种「目录在但版本不对」的情况。

## 代理与企业内网

- 需要代理时设置 `HTTPS_PROXY` / `HTTP_PROXY`（playwright 下载与 pip 都遵守），并用 `NO_PROXY` 排除 `127.0.0.1,localhost`，避免 Neo4j 本地地址被代理劫持。
- 内网有私有 PyPI/文件源时，直接改 `setup_env.py` 里 `PYPI_MIRRORS_CN` 第一项，或用 `--mirror global` 配合全局 pip 配置（`pip config set global.index-url <内网源>`）。
- 完全离线：在联网机器上 `pip download playwright pillow -d ./wheels`，连同 `ms-playwright` 整个目录拷到目标机，然后设 `PLAYWRIGHT_BROWSERS_PATH=<拷贝路径>`。

## 常见安装失败

| 现象 | 原因 | 处理 |
|---|---|---|
| `SSL: CERTIFICATE_VERIFY_FAILED` | 企业根证书未受信 / 中间人代理 | 装公司根证书，或临时 `--trusted-host mirrors.aliyun.com`（不推荐长期） |
| pip 卡在 `Collecting playwright` 很久 | 走了官方源 | 换 `--index-url` 国内镜像 |
| `Downloading Chromium ...` 后 timeout | 浏览器二进制走了官方 CDN | 设 `PLAYWRIGHT_DOWNLOAD_HOST` 为 npmmirror |
| `Executable doesn't exist at ...chrome.exe` | 浏览器未装或 revision 不匹配 | `python -m playwright install chromium` 重装 |
| 浏览器目录里有 `chromium-XXXX` 但没有可执行文件 | 上次下载中断 | 删掉该半成品目录后重跑安装 |
| Linux 报缺 `libnss3` / `libatk` 等 | 系统依赖没装 | `python -m playwright install --with-deps chromium`（需 sudo） |
| macOS 首次启动被拦 | Gatekeeper | 系统设置里允许，或先手动启动一次 |
| 磁盘不足 | Chromium 约 150–250 MB | 清理后重试；`PLAYWRIGHT_BROWSERS_PATH` 可指到大盘 |
| 多 Python 共存时装到了别的解释器 | `python` 与实际运行的不是同一个 | 用 `setup_env.py` 打印的 `解释器` 路径，统一用 `"<该路径>" -m pip ...` |

## 装完怎么确认真的可用

```bash
python scripts/setup_env.py --verify
python scripts/test_export_helpers.py     # 7 项离线自测，不需要数据库
python scripts/neo4j_export_png.py --probe --headless   # 需要 NEO4J_PASSWORD 与可访问的 Browser
```

三步的顺序是有意的：环境 → 脚本逻辑 → 真实连接。任何一步失败都停在那一步，不要跳到导出。
