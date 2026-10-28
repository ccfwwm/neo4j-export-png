# -*- coding: utf-8 -*-
"""setup_env.py 的离线自测：只验证判定逻辑，不联网、不安装。"""
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "setup_env.py"
spec = importlib.util.spec_from_file_location("setup_env", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SetupEnvTests(unittest.TestCase):
    def test_package_module_mapping(self):
        # pillow 的导入名是 PIL，按包名判存在会误报缺失
        self.assertEqual(module.PACKAGE_MODULES["pillow"], "PIL")
        self.assertEqual(module.PACKAGE_MODULES["playwright"], "playwright")

    def test_check_report_shape(self):
        report = module.check()
        for key in ("python", "python_ok", "packages", "chromium", "missing", "commands"):
            self.assertIn(key, report)
        self.assertIsInstance(report["packages"], dict)
        self.assertIsInstance(report["missing"], list)

    def test_mirrors_configured(self):
        self.assertTrue(module.PYPI_MIRRORS_CN)
        self.assertTrue(all(url.startswith("https://") for _, url in module.PYPI_MIRRORS_CN))
        self.assertTrue(all(url.startswith("https://") for _, url in module.PLAYWRIGHT_MIRRORS))

    def test_chromium_status_is_tuple(self):
        ok, detail = module.chromium_installed()
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(detail, str)
        self.assertTrue(detail)

    def test_browsers_root_respects_env(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": "/tmp/pw-test"}):
            self.assertEqual(module.browsers_root(), Path("/tmp/pw-test"))


if __name__ == "__main__":
    unittest.main()
