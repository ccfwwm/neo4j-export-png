#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查并按需安装 neo4j-export-png 的运行依赖。

用法:
    python scripts/setup_env.py              # 只体检，缺什么就打印可执行命令
    python scripts/setup_env.py --install    # 缺什么装什么，自动换镜像重试
    python scripts/setup_env.py --verify     # 体检 + 真实启动一次 Chromium
    python scripts/setup_env.py --install --verify
    python scripts/setup_env.py --json       # 机器可读结果

退出码: 0 环境可用 / 3 有缺失（未安装） / 4 安装失败
依赖: 仅 Python 3.10+ 标准库。镜像与排障细节见 references/environment.md
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

PYPI_MIRRORS_CN = [
    ("aliyun", "https://mirrors.aliyun.com/pypi/simple/"),
    ("tencent", "https://mirrors.cloud.tencent.com/pypi/simple/"),
    ("tuna", "https://pypi.tuna.tsinghua.edu.cn/simple/"),
]
PYPI_OFFICIAL = ("pypi", "https://pypi.org/simple/")

# Playwright 浏览器二进制镜像：国内直连 download.playwright.dev 通常很慢或不通
PLAYWRIGHT_MIRRORS = [
    ("npmmirror", "https://cdn.npmmirror.com/binaries/playwright"),
    ("npmmirror-legacy", "https://registry.npmmirror.com/-/binary/playwright"),
]
PLAYWRIGHT_OFFICIAL = ("playwright-cdn", "")

# pip 包名 -> 实际可导入的模块名（pillow 的模块是 PIL，别按包名判存在）
PACKAGE_MODULES = {"playwright": "playwright", "pillow": "PIL"}
MIN_PYTHON = (3, 10)


def browsers_root() -> Path:
    custom = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if custom and custom != "0":
        return Path(custom).expanduser()
    home = Path.home()
    if sys.platform == "win32":
        return home / "AppData" / "Local" / "ms-playwright"
    if sys.platform == "darwin":
        return home / "Library" / "Caches" / "ms-playwright"
    return home / ".cache" / "ms-playwright"


HEADED_MARKERS = (
    "chrome-win/chrome.exe",
    "chrome-win64/chrome.exe",
    "chrome-linux/chrome",
    "chrome-mac/Chromium.app",
    "chrome-mac-arm64/Chromium.app",
)
SHELL_MARKERS = (
    "chrome-headless-shell-win64/chrome-headless-shell.exe",
    "chrome-headless-shell-linux64/chrome-headless-shell",
    "chrome-headless-shell-mac-arm64/chrome-headless-shell",
    "chrome-headless-shell-mac-x64/chrome-headless-shell",
)


def _chrome_binary_ok(folder: Path, headed_only: bool = False) -> bool:
    markers = HEADED_MARKERS if headed_only else HEADED_MARKERS + SHELL_MARKERS
    return any((folder / marker).exists() for marker in markers)


def expected_chromium_dirs() -> list[Path]:
    """用 playwright 自己的 dry-run 拿到当前版本要求的安装目录，避免版本不匹配误判。"""
    if not module_available("playwright"):
        return []
    code, out = run(
        [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"], timeout=120
    )
    if code != 0:
        return []
    dirs = []
    for line in out.splitlines():
        if "Install location" in line and ":" in line:
            raw = line.split(":", 1)[1].strip()
            if raw and "(no install" not in raw.lower():
                dirs.append(Path(raw))
    return dirs


def chromium_installed() -> tuple[bool, str]:
    """回 (可用, 说明)。无窗口模式：headless shell 也算可用；带头模式需要完整 chromium。"""
    if not module_available("playwright"):
        return False, "playwright 未安装，装完后才能校验浏览器版本"

    candidates = [d for d in expected_chromium_dirs() if d.name.startswith(("chromium", "chrome"))]
    if not candidates:
        root = browsers_root()
        if not root.is_dir():
            return False, f"未找到浏览器目录: {root}"
        candidates = sorted(
            (p for p in root.iterdir() if p.is_dir() and p.name.startswith("chromium")),
            key=lambda x: x.name,
        )
        if not candidates:
            return False, f"{root} 下没有 chromium-* 目录"

    usable = [d for d in candidates if d.is_dir() and _chrome_binary_ok(d)]
    if not usable:
        return False, f"当前 playwright 版本要求 {candidates[0].name}，尚未安装"

    headed = [d for d in usable if _chrome_binary_ok(d, headed_only=True)]
    detail = str(headed[0] if headed else usable[0])
    if not headed:
        detail += "（只有 headless shell：默认无窗口导出可用；要弹窗口需再跑 playwright install chromium）"
    return True, detail


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def run(cmd: list[str], timeout: int, env: dict[str, str] | None = None) -> tuple[int, str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            env=merged, encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        return 124, f"超时（>{timeout}s）: {' '.join(cmd)}"
    except Exception as exc:  # noqa: BLE001
        return 1, f"执行失败: {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def check() -> dict:
    report = {
        "python": sys.version.split()[0],
        "python_ok": sys.version_info[:2] >= MIN_PYTHON,
        "platform": f"{platform.system()} {platform.release()}",
        "executable": sys.executable,
        "packages": {},
        "chromium": {},
        "missing": [],
        "commands": [],
    }
    for pkg, modname in PACKAGE_MODULES.items():
        ok = module_available(modname)
        report["packages"][pkg] = ok
        if not ok:
            report["missing"].append(f"python-package:{pkg}")

    installed, detail = chromium_installed()
    report["chromium"] = {"ok": installed, "detail": detail, "dir": str(browsers_root())}
    if not installed:
        report["missing"].append("playwright-chromium")

    pip_cmds = []
    if not report["packages"].get("playwright"):
        pip_cmds.append("python -m pip install playwright --index-url https://mirrors.aliyun.com/pypi/simple/")
    if not report["packages"].get("pillow"):
        pip_cmds.append("python -m pip install pillow --index-url https://mirrors.aliyun.com/pypi/simple/")
    if not installed:
        pip_cmds.append(
            "PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright "
            "python -m playwright install chromium"
        )
    report["commands"] = pip_cmds
    return report


def print_report(report: dict) -> None:
    print("===== 依赖体检 =====")
    print(f"Python      : {report['python']} ({'OK' if report['python_ok'] else '过低，需 >= 3.10'})")
    print(f"系统        : {report['platform']}")
    print(f"解释器      : {report['executable']}")
    for pkg, ok in report["packages"].items():
        print(f"包 {pkg:<11}: {'已安装' if ok else '缺失'}")
    chromium = report["chromium"]
    print(f"Chromium    : {'已安装 ' + chromium['detail'] if chromium['ok'] else '缺失 — ' + chromium['detail']}")
    if report["missing"]:
        print("\n缺失项: " + ", ".join(report["missing"]))
        print("可执行以下命令补齐（或直接跑 setup_env.py --install 让脚本自动换镜像）：")
        for cmd in report["commands"]:
            print(f"  {cmd}")
    else:
        print("\n结论: 环境就绪，可以直接导出。")


def pip_install(mirrors: list[tuple[str, str]], packages: list[str]) -> bool:
    for name, index in mirrors:
        print(f"[pip] 使用镜像 {name}: {index}")
        code, out = run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
             "--index-url", index, "--timeout", "30", *packages],
            timeout=900,
        )
        if code == 0:
            print(f"[pip] 安装成功: {' '.join(packages)}")
            return True
        tail = "\n".join(out.strip().splitlines()[-6:])
        print(f"[pip] 镜像 {name} 失败（exit={code}）：\n{tail}")
    return False


def install_chromium(mirrors: list[tuple[str, str]]) -> bool:
    for name, host in mirrors:
        env = {"PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT": "120000"}
        label = name
        if host:
            env["PLAYWRIGHT_DOWNLOAD_HOST"] = host
        print(f"[chromium] 来源 {label}" + (f": {host}" if host else "（官方 CDN）"))
        code, out = run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            timeout=1800, env=env,
        )
        if code == 0:
            ok, detail = chromium_installed()
            if ok:
                print(f"[chromium] 安装成功: {detail}")
                return True
            print(f"[chromium] 命令成功但目录校验未通过: {detail}")
        else:
            tail = "\n".join(out.strip().splitlines()[-6:])
            print(f"[chromium] 来源 {label} 失败（exit={code}）：\n{tail}")
    return False


def verify() -> bool:
    """真实启动一次无头 Chromium，确认不只是装上了、而是能用。"""
    code = (
        "from playwright.sync_api import sync_playwright\n"
        "with sync_playwright() as p:\n"
        "    b = p.chromium.launch(headless=True)\n"
        "    page = b.new_page()\n"
        "    page.set_content('<h1>ok</h1>')\n"
        "    print('playwright-ok', page.title() == '')\n"
        "    b.close()\n"
    )
    rc, out = run([sys.executable, "-c", code], timeout=180)
    ok = rc == 0 and "playwright-ok" in out
    print("[verify] " + ("启动 Chromium 成功，Playwright 可用" if ok else f"启动失败（exit={rc}）：\n{out.strip()[-500:]}"))
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="neo4j-export-png 依赖体检与安装")
    parser.add_argument("--install", action="store_true", help="缺失项自动安装（多镜像重试）")
    parser.add_argument("--verify", action="store_true", help="体检后真实启动一次 Chromium")
    parser.add_argument("--mirror", choices=["auto", "cn", "global"], default="auto",
                        help="auto=国内镜像优先再回落官方；global=只用官方")
    parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = parser.parse_args()

    report = check()
    if not args.json:
        print_report(report)

    if report["python_ok"] is False:
        print(f"\n[阻断] 需要 Python >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}，当前 {report['python']}。"
              "请先装新版 Python 再回来跑本脚本。")
        return 4

    ok = not report["missing"]
    if not ok and args.install:
        mirrors = (PYPI_MIRRORS_CN + [PYPI_OFFICIAL]) if args.mirror != "global" else [PYPI_OFFICIAL]
        pw_mirrors = (PLAYWRIGHT_MIRRORS + [PLAYWRIGHT_OFFICIAL]) if args.mirror != "global" else [PLAYWRIGHT_OFFICIAL]

        # 第一步：装 Python 包；装完立刻复检，浏览器判定要等 playwright 到位才准
        need_pkgs = [p for p, mod in PACKAGE_MODULES.items() if not module_available(mod)]
        if need_pkgs:
            if not pip_install(mirrors, need_pkgs):
                print("\n[失败] pip 安装未成功。请检查网络/代理，或手动执行：\n  "
                      + "\n  ".join(report["commands"]))
                return 4
            report = check()

        # 第二步：用 playwright 自己的版本要求判定并安装浏览器
        installed, detail = chromium_installed()
        if not installed:
            print(f"[chromium] {detail}")
            if not install_chromium(pw_mirrors):
                print("\n[失败] Chromium 安装未成功，见 references/environment.md 的「镜像与代理」一节。")
                return 4

        report = check()
        ok = not report["missing"]
        print("\n===== 安装后复检 =====")
        print_report(report)

    if args.verify:
        if not verify():
            return 4

    if not ok:
        print("\n结论: 环境未就绪（缺 " + ", ".join(report["missing"]) + "）。加 --install 可自动安装。")
        return 3
    if not args.json:
        print("\n结论: 环境可用。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
