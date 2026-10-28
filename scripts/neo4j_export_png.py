# -*- coding: utf-8 -*-
"""Export Neo4j Browser graph visualizations as PNG, SVG, or both.

The script automates login, database switching, Cypher execution, Browser graph
export, batch manifests, resumable runs, and output validation. Credentials are
read from CLI arguments or NEO4J_* environment variables; they are never stored
in manifests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


DEFAULT_URL = "http://127.0.0.1:7474"
DEFAULT_USER = "neo4j"
DEFAULT_DATABASE = "neo4j"
DEFAULT_BOLT_PORT = 7687
DEFAULT_BROWSER_LIMIT = 1_000_000

# 登录/连接失败时页面上常见的提示片段，用于给出可操作的报错而不是超时
CONNECTION_ERROR_HINTS = (
    "Neo.ClientError.Security.Unauthorized",
    "Unauthorized",
    "The client is unauthorized",
    "Connection failed",
    "Unable to connect",
    "ERR_CONNECTION",
    "ServiceUnavailable",
    "Failed to establish connection",
)


def derive_bolt_address(url: str) -> str:
    """按 Browser 地址推导 bolt 地址；可用 NEO4J_BOLT_URL 整体覆盖。"""
    override = os.environ.get("NEO4J_BOLT_URL", "").strip()
    if override:
        return override
    raw = url if "://" in url else f"http://{url}"
    parsed = urlparse(raw)
    host = parsed.hostname or "127.0.0.1"
    port = os.environ.get("NEO4J_BOLT_PORT", str(DEFAULT_BOLT_PORT))
    return f"{host}:{port}"

TRUNCATION_PATTERNS = {
    "LIMIT": re.compile(r"(?i)\bLIMIT\s+\d+"),
    "head()": re.compile(r"(?i)\bhead\s*\("),
    "array_slice": re.compile(r"\[\s*0\s*\.\.\s*\d+\s*\]"),
}


def normalize_cypher(command: str) -> str:
    return " ".join(line.strip() for line in command.strip().splitlines() if line.strip())


def truncation_markers(cypher: str) -> list[str]:
    return [name for name, pattern in TRUNCATION_PATTERNS.items() if pattern.search(cypher)]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def svg_counts(path: Path) -> tuple[int, int]:
    content = path.read_text(encoding="utf-8-sig", errors="replace")
    return (
        len(re.findall(r'class=["\']node["\']', content)),
        len(re.findall(r'class=["\']relationship["\']', content)),
    )


def validate_svg(path: Path, expected_nodes: int | None = None,
                 expected_relationships: int | None = None) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size < 1000:
        raise RuntimeError(f"SVG 不存在或过小: {path}")
    content = path.read_text(encoding="utf-8-sig", errors="replace")
    if "<svg" not in content:
        raise RuntimeError(f"文件不是有效 SVG: {path}")
    nodes, relationships = svg_counts(path)
    if nodes < 1:
        raise RuntimeError(f"SVG 未发现图节点: {path}")
    if expected_nodes is not None and nodes != expected_nodes:
        raise RuntimeError(f"SVG 节点数不符: actual={nodes}, expected={expected_nodes}")
    if expected_relationships is not None and relationships != expected_relationships:
        raise RuntimeError(
            f"SVG 关系数不符: actual={relationships}, expected={expected_relationships}"
        )
    return {
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "svg_nodes": nodes,
        "svg_relationships": relationships,
    }


def validate_png(path: Path, min_width: int = 300, min_height: int = 180,
                 min_variance: float = 3.0) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size < 1000:
        raise RuntimeError(f"PNG 不存在或过小: {path}")
    try:
        from PIL import Image, ImageStat
    except ImportError:
        return {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
    with Image.open(path) as image:
        image.load()
        width, height = image.size
        if width < min_width or height < min_height:
            raise RuntimeError(f"PNG 尺寸过小: {width}x{height}")
        preview = image.convert("RGB")
        preview.thumbnail((256, 256))
        variance = sum(ImageStat.Stat(preview).var) / 3
        if variance < min_variance:
            raise RuntimeError(f"PNG 疑似空白图: variance={variance:.2f}")
    return {
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "png_width": width,
        "png_height": height,
        "png_variance": round(variance, 2),
    }


class Neo4jExporter:
    """Automate Neo4j Browser graph export with legacy/new Browser support."""

    def __init__(self, url=DEFAULT_URL, user=DEFAULT_USER, password="",
                 headless=True, wait_seconds=3,
                 browser_limit=DEFAULT_BROWSER_LIMIT):
        self.url = (url or DEFAULT_URL).rstrip("/")
        self.user = user or DEFAULT_USER
        self.password = password
        self.headless = headless
        self.wait_seconds = wait_seconds
        self.browser_limit = browser_limit
        self.bolt_address = derive_bolt_address(self.url)
        self.pw_ctx = None
        self.browser = None
        self.page = None
        self.current_db = None
        self.browser_mode = "old"

    def connection_help(self, reason: str = "") -> str:
        """连接失败时给用户的可操作提示，明确列出当前参数与需要用户补充的信息。"""
        head = f"连接 Neo4j 失败（{reason}）" if reason else "连接 Neo4j 失败"
        return (
            f"{head}。当前参数：url={self.url}，user={self.user}，"
            f"bolt={self.bolt_address}，database={self.current_db or DEFAULT_DATABASE}。\n"
            "请确认并按需提供正确信息后重试：\n"
            "  1) Neo4j 是否已启动，Browser 地址是否可访问（默认 http://127.0.0.1:7474）；\n"
            "  2) 用户名是否需要更换（默认 neo4j），密码是否已写入 NEO4J_PASSWORD；\n"
            "  3) 目标数据库名是否存在（默认 neo4j，可用 --database 或任务文件指定）；\n"
            "  4) 远程实例请确认 bolt 地址（默认按 url 主机 + 7687 推导，可用 NEO4J_BOLT_URL 覆盖）。\n"
            "拿到正确的地址/用户名/密码/数据库名后，重新执行即可。"
        )

    def _page_connection_error(self) -> str:
        """从页面抓取登录失败的可见提示；没有就返回空串。"""
        try:
            body = self.page.inner_text("body", timeout=2000)
        except Exception:
            return ""
        for hint in CONNECTION_ERROR_HINTS:
            if hint.lower() in body.lower():
                snippet = " ".join(body.split())
                return snippet[:200]
        return ""

    def _verify_login(self) -> None:
        """登录后确认真的进到了可操作的 Browser，而不是停在报错页。"""
        error = self._page_connection_error()
        if error:
            raise RuntimeError(self.connection_help(f"页面提示：{error}"))
        editor = self.page.locator(
            "[aria-label*='Editor'], .monaco-editor textarea, "
            "[data-testid='activeEditor'], textarea[role='textbox']"
        )
        try:
            editor.first.wait_for(state="visible", timeout=15000)
        except Exception as exc:
            raise RuntimeError(self.connection_help("未出现 Cypher 编辑器")) from exc
        print(f"  -> 已连接：url={self.url} user={self.user} bolt={self.bolt_address}")

    def start(self) -> None:
        if sync_playwright is None:
            raise RuntimeError(
                "缺少 Playwright，还没有配好运行环境。先跑一次：\n"
                "  python scripts/setup_env.py --install --verify\n"
                "它会自动换国内镜像装 playwright/pillow 与 Chromium 并验证；"
                "也可手动执行: python -m pip install playwright && python -m playwright install chromium"
            )
        self.pw_ctx = sync_playwright().start()
        self.browser = self.pw_ctx.chromium.launch(headless=self.headless)
        self.page = self.browser.new_page(
            viewport={"width": 3200, "height": 2200}, device_scale_factor=1
        )
        self.page.add_init_script("localStorage.setItem('prefersOldBrowser', 'true')")
        try:
            self._full_login()
            self._verify_login()
            self.configure_full_graph_display()
        except RuntimeError as exc:
            if "连接 Neo4j 失败" in str(exc):
                raise
            raise RuntimeError(self.connection_help(str(exc))) from exc
        except Exception as exc:
            raise RuntimeError(self.connection_help(str(exc))) from exc

    def _full_login(self) -> None:
        print(f"[1/3] 打开 Neo4j Browser {self.url}/browser/ ...")
        self.page.goto(f"{self.url}/browser/", wait_until="networkidle")
        self.page.wait_for_timeout(5000)
        self._force_old_browser()
        print("[2/3] 识别 Browser 版本...")
        if self._is_old_browser_login():
            self._assert_old_browser()
            print("[3/3] 旧版登录中...")
            self._do_old_login()
        else:
            self.browser_mode = "new"
            print("[3/3] 新版登录中...")
            self._do_new_login()

    def _force_old_browser(self) -> None:
        try:
            if self.page.evaluate("localStorage.getItem('prefersOldBrowser')") != "true":
                self.page.evaluate("localStorage.setItem('prefersOldBrowser', 'true')")
                self.page.reload(wait_until="networkidle")
                self.page.wait_for_timeout(5000)
        except Exception as exc:
            raise RuntimeError(f"无法设置旧版 Browser 偏好: {exc}") from exc

    def _is_old_browser_login(self) -> bool:
        try:
            return self.page.get_by_role("textbox", name="Username").is_visible(timeout=3000)
        except Exception:
            return False

    def _assert_old_browser(self) -> None:
        try:
            self.page.get_by_role("textbox", name="Username").wait_for(
                state="visible", timeout=10000
            )
            print("  -> 已确认旧版 Browser")
        except Exception as exc:
            raise RuntimeError("未进入可操作的 Neo4j Browser 登录页") from exc

    def _do_old_login(self) -> None:
        try:
            self.page.get_by_role("textbox", name="Username").fill(self.user)
            self.page.get_by_role("textbox", name="Password").fill(self.password)
            connect = self.page.locator("[data-testid='connect']")
            if connect.count() > 0:
                connect.click()
            else:
                self.page.get_by_role("button", name="Connect").click()
            self.page.wait_for_timeout(5000)
            print("  -> 旧版登录成功")
        except Exception as exc:
            raise RuntimeError(f"旧版登录失败: {exc}") from exc

    def _do_new_login(self) -> None:
        try:
            if self.page.get_by_test_id("connect").is_visible(timeout=3000):
                self.page.get_by_test_id("bolt-scheme-select").select_option("bolt://")
                self.page.get_by_test_id("boltaddress").fill(self.bolt_address)
                self.page.get_by_test_id("username").fill(self.user)
                self.page.get_by_test_id("password").fill(self.password)
                self.page.get_by_test_id("connect").click()
            elif self.page.get_by_test_id("connection-form-submit").is_visible(timeout=3000):
                self.page.get_by_label("Connection URL").fill(self.bolt_address)
                self.page.get_by_label("Database user").fill(self.user)
                self.page.get_by_label("Password").fill(self.password)
                self.page.get_by_test_id("connection-form-submit").click()
            elif self.page.get_by_text("Connect to instance", exact=True).is_visible(timeout=3000):
                self.page.get_by_text("Connect to instance", exact=True).click()
                self.page.get_by_label("Connection URL").fill(self.bolt_address)
                self.page.get_by_label("Database user").fill(self.user)
                self.page.get_by_label("Password").fill(self.password)
                self.page.get_by_test_id("connection-form-submit").click()
            self.page.wait_for_timeout(8000)
            print("  -> 新版登录完成")
        except Exception as exc:
            raise RuntimeError(f"新版登录失败: {exc}") from exc

    def configure_full_graph_display(self) -> None:
        """Raise legacy Browser row and graph display ceilings before queries."""
        if self.browser_mode != "old" or self.browser_limit <= 0:
            return
        print(
            f"[配置] maxRows/initialNodeDisplay={self.browser_limit}，"
            "避免默认 300 节点显示上限截断"
        )
        self._run_cypher(f":config maxRows: {self.browser_limit}")
        self.page.wait_for_timeout(800)
        self._run_cypher(f":config initialNodeDisplay: {self.browser_limit}")
        self.page.wait_for_timeout(800)

    def switch_database(self, db_name: str) -> None:
        if self.current_db == db_name:
            return
        print(f"[数据库] 切换到 {db_name} ...")
        if self.browser_mode == "new":
            self._run_cypher(f":use {db_name}")
            self.current_db = db_name
            return
        try:
            self.page.get_by_role("button", name="Database").first.click()
            self.page.wait_for_timeout(800)
        except Exception:
            pass
        db_select = self.page.locator("select:not([data-testid='bolt-scheme-select'])")
        try:
            db_select.first.wait_for(state="visible", timeout=5000)
            db_select.first.select_option(db_name)
            self.page.wait_for_timeout(1500)
        except Exception:
            self._run_cypher(f":use {db_name}")
        self.current_db = db_name
        print(f"[数据库] 已切换到 {db_name}")

    def _run_cypher(self, command: str) -> None:
        command = normalize_cypher(command)
        if self.browser_mode == "new":
            self._run_cypher_new(command)
            return
        editor = self.page.locator(
            "[aria-label*='Editor'], .monaco-editor textarea, [data-testid='activeEditor']"
        ).first
        editor.click()
        self.page.keyboard.press("Control+a")
        self.page.keyboard.press("Backspace")
        self.page.keyboard.insert_text(command)
        self.page.wait_for_timeout(400)
        self.page.keyboard.press("Control+Enter")
        self.page.wait_for_timeout(3000)

    def _run_cypher_new(self, command: str) -> None:
        editor = self.page.locator(
            "[aria-label*='Editor'], .monaco-editor textarea, textarea[role='textbox']"
        ).first
        editor.click()
        self.page.keyboard.press("Control+a")
        self.page.keyboard.press("Backspace")
        self.page.keyboard.insert_text(command)
        self.page.wait_for_timeout(400)
        run_button = self.page.get_by_test_id("editor-Run")
        if run_button.count() == 0:
            run_button = self.page.get_by_test_id("run-button")
        if run_button.count() > 0:
            run_button.click()
        else:
            self.page.keyboard.press("Control+Enter")
        self.page.wait_for_timeout(7000)

    def run_graph_query(self, cypher: str, wait_seconds: int | None = None) -> None:
        print(f"[查询] {normalize_cypher(cypher)[:100]}...")
        self._run_cypher(cypher)
        wait = self.wait_seconds if wait_seconds is None else wait_seconds
        print(f"[等待] 图谱布局稳定 ({wait}s)...")
        self.page.wait_for_timeout(max(0, wait) * 1000)

    def export_png(self, cypher: str, output_path: str,
                   wait_seconds: int | None = None) -> bool:
        self.run_graph_query(cypher, wait_seconds)
        return self.export_current_png(output_path)

    def export_svg(self, cypher: str, output_path: str,
                   wait_seconds: int | None = None) -> bool:
        self.run_graph_query(cypher, wait_seconds)
        return self.export_current_svg(output_path)

    def export_current_png(self, output_path: str) -> bool:
        output = Path(output_path).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        success = self._export_png_new(output) if self.browser_mode == "new" else self._export_png_old(output)
        if success:
            self._ensure_white_png_background(output)
        return success

    def export_current_svg(self, output_path: str) -> bool:
        output = Path(output_path).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        return self._export_svg_new(output) if self.browser_mode == "new" else self._export_svg_old(output)

    def _export_png_old(self, output: Path) -> bool:
        try:
            export_link = self.page.get_by_text("Export PNG", exact=True).first
            if not export_link.is_visible(timeout=4000):
                self._click_download_icon()
            with self.page.expect_download(timeout=30000) as download_info:
                self.page.get_by_text("Export PNG", exact=True).first.click()
            download_info.value.save_as(str(output))
            print(f"[导出] PNG: {output}")
            return True
        except Exception as exc:
            print(f"[提示] Export PNG 失败，尝试截图降级: {exc}")
            return self._fallback_screenshot(output)

    def _export_png_new(self, output: Path) -> bool:
        try:
            frame = self._prepare_new_frame()
            frame.locator("[data-testid='frame-export-dropdown']").first.click()
            export_button = frame.locator("[data-testid='exportPNGButton']").first
            with self.page.expect_download(timeout=30000) as download_info:
                export_button.click(force=True)
            download_info.value.save_as(str(output))
            print(f"[导出] 新版 PNG: {output}")
            return True
        except Exception as exc:
            print(f"[错误] 新版 Export PNG 失败: {exc}")
            return self._fallback_screenshot(output)

    def _export_svg_old(self, output: Path) -> bool:
        try:
            export_link = self.page.get_by_text("Export SVG", exact=True).first
            if not export_link.is_visible(timeout=4000):
                self._click_download_icon()
            with self.page.expect_download(timeout=30000) as download_info:
                self.page.get_by_text("Export SVG", exact=True).first.click()
            download_info.value.save_as(str(output))
            print(f"[导出] SVG: {output}")
            return True
        except Exception as exc:
            print(f"[提示] Export SVG 失败，尝试读取 DOM SVG: {exc}")
            return self._fallback_dom_svg(output)

    def _export_svg_new(self, output: Path) -> bool:
        try:
            frame = self._prepare_new_frame()
            frame.locator("[data-testid='frame-export-dropdown']").first.click()
            export_button = frame.locator("[data-testid='exportSVGButton']").first
            if export_button.count() == 0:
                export_button = self.page.get_by_text("Export SVG", exact=True).first
            with self.page.expect_download(timeout=30000) as download_info:
                export_button.click(force=True)
            download_info.value.save_as(str(output))
            print(f"[导出] 新版 SVG: {output}")
            return True
        except Exception as exc:
            print(f"[提示] 新版 Export SVG 失败，尝试读取 DOM SVG: {exc}")
            return self._fallback_dom_svg(output)

    def _prepare_new_frame(self):
        frame = self.page.locator("[data-testid='frame']").first
        frame.wait_for(state="visible", timeout=15000)
        viz_tab = frame.locator("[data-testid='cypherFrameSidebarVisualization']").first
        if viz_tab.count() > 0:
            try:
                viz_tab.click(timeout=3000)
                self.page.wait_for_timeout(500)
            except Exception:
                pass
        fit_button = frame.locator("[aria-label='zoom-to-fit']").first
        if fit_button.count() > 0:
            try:
                fit_button.click(timeout=3000)
                self.page.wait_for_timeout(900)
            except Exception:
                pass
        return frame

    def _click_download_icon(self) -> None:
        for selector in [
            "button:has-text('Export')", "[aria-label*='Export']", "[title*='Export']"
        ]:
            try:
                element = self.page.locator(selector).first
                if element.is_visible(timeout=1500):
                    element.click()
                    self.page.wait_for_timeout(400)
                    return
            except Exception:
                continue

    def _fallback_dom_svg(self, output: Path) -> bool:
        selectors = [
            "svg.neod3viz", "[data-testid='frame-loaded-contents'] svg",
            "[data-testid='frame'] svg", ".neo4j-viz svg", "article svg",
        ]
        for selector in selectors:
            try:
                matches = self.page.locator(selector)
                for index in range(matches.count() - 1, -1, -1):
                    svg = matches.nth(index)
                    if not svg.is_visible(timeout=1000):
                        continue
                    markup = svg.evaluate("element => element.outerHTML")
                    if "<svg" not in markup or not re.search(r'class=["\']node["\']', markup):
                        continue
                    if "xmlns=" not in markup[:500]:
                        markup = markup.replace(
                            "<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1
                        )
                    output.write_text(markup, encoding="utf-8")
                    print(f"[降级] DOM SVG: {output}")
                    return True
            except Exception:
                continue
        print("[错误] 无法获得图谱 SVG")
        return False

    def _fallback_screenshot(self, output: Path) -> bool:
        selectors = [
            "[data-testid='frame-loaded-contents']", "[data-testid='frameContents']",
            "[data-testid='frame']", "svg.neod3viz", ".neo4j-viz", "article", "canvas",
        ]
        for selector in selectors:
            try:
                matches = self.page.locator(selector)
                for index in range(matches.count() - 1, -1, -1):
                    element = matches.nth(index)
                    if not element.is_visible(timeout=1000):
                        continue
                    box = element.bounding_box()
                    if not box or box.get("width", 0) < 300 or box.get("height", 0) < 180:
                        continue
                    element.screenshot(path=str(output))
                    self._ensure_white_png_background(output)
                    print(f"[降级] PNG 截图: {output}")
                    return True
            except Exception:
                continue
        print("[错误] PNG 截图降级失败")
        return False

    def apply_style(self, style: str) -> None:
        if not style or self.browser_mode != "old":
            return
        print("[样式] 应用 Neo4j Browser 样式...")
        self._run_cypher(":style " + style)
        self.page.wait_for_timeout(800)

    @staticmethod
    def _ensure_white_png_background(output: Path) -> None:
        try:
            from PIL import Image
        except ImportError:
            return
        with Image.open(output) as image:
            if image.mode not in ("RGBA", "LA") and "transparency" not in image.info:
                return
            rgba = image.convert("RGBA")
            white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            white.alpha_composite(rgba)
            white.convert("RGB").save(output)

    def close(self) -> None:
        if self.browser:
            self.browser.close()
        if self.pw_ctx:
            self.pw_ctx.stop()
        print("[完成] 浏览器已关闭")


def output_paths(task: dict[str, Any], default_format: str) -> dict[str, Path]:
    fmt = task.get("format", default_format).lower()
    raw = Path(task["output"]).resolve()
    if fmt == "png":
        return {"png": raw.with_suffix(".png")}
    if fmt == "svg":
        return {"svg": raw.with_suffix(".svg")}
    if fmt == "both":
        stem = raw.with_suffix("")
        return {"svg": stem.with_suffix(".svg"), "png": stem.with_suffix(".png")}
    raise ValueError(f"不支持的格式: {fmt}")


def export_task(exporter: Neo4jExporter, task: dict[str, Any], default_format: str,
                allow_truncated_query: bool, resume: bool,
                default_database: str = DEFAULT_DATABASE) -> dict[str, Any]:
    database = task.get("database") or default_database or DEFAULT_DATABASE
    cypher = normalize_cypher(task["cypher"])
    markers = truncation_markers(cypher)
    allow_task_truncation = task.get("allow_truncated_query", allow_truncated_query)
    if markers and not allow_task_truncation:
        raise RuntimeError(
            "查询包含可能截断图谱的模式: " + ", ".join(markers)
            + "。如确需抽样，显式设置 allow_truncated_query=true。"
        )
    paths = output_paths(task, default_format)
    reusable = False
    if resume:
        try:
            for fmt, path in paths.items():
                if fmt == "svg":
                    validate_svg(
                        path, task.get("expected_nodes"), task.get("expected_relationships")
                    )
                else:
                    validate_png(
                        path,
                        task.get("min_width", 300),
                        task.get("min_height", 180),
                        task.get("min_variance", 3.0),
                    )
            reusable = True
        except Exception as exc:
            print(f"[续跑] 现有文件未通过校验，将重新导出: {exc}")
    if reusable:
        print(f"[续跑] 已通过校验，跳过查询: {', '.join(str(p) for p in paths.values())}")
    else:
        exporter.switch_database(database)
        exporter.run_graph_query(cypher, task.get("wait_seconds"))
        if "svg" in paths and not exporter.export_current_svg(str(paths["svg"])):
            raise RuntimeError("SVG 导出失败")
        if "png" in paths and not exporter.export_current_png(str(paths["png"])):
            raise RuntimeError("PNG 导出失败")
    result: dict[str, Any] = {
        "database": database,
        "name": task.get("name", ""),
        "course": task.get("course", ""),
        "direction": task.get("direction", ""),
        "query_truncation_markers": markers,
        "outputs": {},
    }
    for fmt, path in paths.items():
        if fmt == "svg":
            metadata = validate_svg(
                path, task.get("expected_nodes"), task.get("expected_relationships")
            )
        else:
            metadata = validate_png(
                path,
                task.get("min_width", 300),
                task.get("min_height", 180),
                task.get("min_variance", 3.0),
            )
        result["outputs"][fmt] = {"path": str(path), **metadata}
    result["success"] = True
    return result


def load_config(args) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if args.tasks:
        config = json.loads(Path(args.tasks).read_text(encoding="utf-8"))
        tasks = config.get("tasks", [])
        if not tasks:
            raise ValueError("任务文件里没有任何任务：请检查 tasks 数组")
        return config, tasks
    if not (args.cypher and args.output):
        raise ValueError("单条导出至少需要 --cypher 和 --output（数据库未填时用默认 neo4j）")
    return {}, [{
        "database": args.database or DEFAULT_DATABASE, "cypher": args.cypher,
        "output": args.output, "format": args.format,
        "expected_nodes": args.expected_nodes,
        "expected_relationships": args.expected_relationships,
    }]


def main() -> None:
    parser = argparse.ArgumentParser(description="Neo4j Browser PNG/SVG 批量导出与审计")
    parser.add_argument("--tasks")
    parser.add_argument("--url", default=os.environ.get("NEO4J_BROWSER_URL", DEFAULT_URL),
                        help=f"Neo4j Browser 地址，默认 {DEFAULT_URL}")
    parser.add_argument("--user", default=os.environ.get("NEO4J_USER", DEFAULT_USER),
                        help=f"用户名，默认 {DEFAULT_USER}")
    parser.add_argument("--password", default=os.environ.get("NEO4J_PASSWORD", ""),
                        help="优先用 NEO4J_PASSWORD 环境变量，避免密码留在命令历史里")
    parser.add_argument("--bolt-url", default=os.environ.get("NEO4J_BOLT_URL", ""),
                        help="新版 Browser 的连接串，默认按 url 主机 + 7687 推导")
    parser.add_argument("--database", default=None,
                        help=f"目标数据库，默认 {DEFAULT_DATABASE}；不填就用内置默认")
    parser.add_argument("--probe", action="store_true",
                        help="只验证连接与登录，不执行任何查询")
    parser.add_argument("--cypher")
    parser.add_argument("--output")
    parser.add_argument("--format", choices=["png", "svg", "both"], default="png")
    parser.add_argument("--expected-nodes", type=int)
    parser.add_argument("--expected-relationships", type=int)
    parser.add_argument("--headless", action="store_true",
                        help="无窗口运行（默认行为，保留以兼容旧命令）")
    parser.add_argument("--headed", action="store_true",
                        help="弹出可见浏览器窗口，便于人工排查登录页；需要完整 chromium")
    parser.add_argument("--wait", type=int, default=3)
    parser.add_argument("--browser-limit", type=int, default=DEFAULT_BROWSER_LIMIT)
    parser.add_argument("--allow-truncated-query", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--start", type=int, default=1, help="1-based task index")
    parser.add_argument("--limit", type=int, default=0, help="0 means all remaining tasks")
    parser.add_argument("--manifest")
    args = parser.parse_args()
    if args.bolt_url:
        os.environ["NEO4J_BOLT_URL"] = args.bolt_url
    if not args.password:
        raise SystemExit(
            "缺少密码：请先在当前 shell 设置环境变量后重跑，"
            "例如 export NEO4J_PASSWORD='<密码>'；Windows 用户可用 " + chr(36) + "env:NEO4J_PASSWORD。\n"
            f"当前连接参数：url={args.url}，user={args.user}，"
            f"database={args.database or DEFAULT_DATABASE}。"
        )
    try:
        config, tasks = load_config(args)
    except ValueError as exc:
        parser.error(str(exc))
    tasks = tasks[max(0, args.start - 1):]
    if args.limit > 0:
        tasks = tasks[:args.limit]
    default_format = config.get("format", args.format)
    manifest_path = Path(
        args.manifest or config.get("manifest", "neo4j_export_manifest.json")
    ).resolve()
    exporter = Neo4jExporter(
        config.get("url", args.url), config.get("user", args.user), args.password,
        headless=not args.headed, wait_seconds=args.wait,
        browser_limit=config.get("browser_limit", args.browser_limit),
    )
    results = []
    try:
        exporter.start()
    except Exception as exc:
        print(f"[连接失败] {exc}")
        raise SystemExit(2)
    if args.probe:
        print(
            f"[连接成功] url={exporter.url} user={exporter.user} "
            f"bolt={exporter.bolt_address} browser={exporter.browser_mode}"
        )
        exporter.close()
        return
    exporter.apply_style(config.get("style", ""))
    try:
        for index, task in enumerate(tasks, 1):
            print(f"\n[{index}/{len(tasks)}] {task.get('name') or task.get('output')}")
            try:
                result = export_task(
                    exporter, task, default_format,
                    config.get("allow_truncated_query", args.allow_truncated_query),
                    config.get("resume", args.resume),
                    config.get("database", args.database or DEFAULT_DATABASE),
                )
            except Exception as exc:
                print(f"[错误] {exc}")
                result = {
                    "database": task.get("database") or args.database or DEFAULT_DATABASE,
                    "name": task.get("name", ""),
                    "course": task.get("course", ""),
                    "direction": task.get("direction", ""),
                    "output": task.get("output", ""),
                    "success": False,
                    "error": str(exc),
                }
            results.append(result)
    finally:
        exporter.close()
    manifest = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "PASS" if all(item.get("success") for item in results) else "FAIL",
        "task_count": len(results),
        "success_count": sum(bool(item.get("success")) for item in results),
        "failure_count": sum(not item.get("success") for item in results),
        "browser_limit": exporter.browser_limit,
        "results": results,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in ("status", "task_count", "success_count", "failure_count")}, ensure_ascii=False))
    if manifest["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
