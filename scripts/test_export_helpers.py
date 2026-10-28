# -*- coding: utf-8 -*-
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent / "neo4j_export_png.py"
spec = importlib.util.spec_from_file_location("neo4j_export_png", SCRIPT)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class ExportHelperTests(unittest.TestCase):
    def test_truncation_detection(self):
        self.assertEqual(module.truncation_markers("MATCH (n) RETURN n"), [])
        self.assertIn("LIMIT", module.truncation_markers("MATCH (n) RETURN n LIMIT 10"))
        self.assertIn("head()", module.truncation_markers("RETURN head(collect(n))"))
        self.assertIn("array_slice", module.truncation_markers("RETURN nodes(p)[0..20]"))

    def test_svg_counts_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            svg = Path(directory) / "graph.svg"
            svg.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg">'
                '<g class="node"></g><g class="node"></g>'
                '<g class="relationship"></g></svg>' + (' ' * 1000),
                encoding="utf-8",
            )
            result = module.validate_svg(svg, expected_nodes=2, expected_relationships=1)
            self.assertEqual(result["svg_nodes"], 2)
            self.assertEqual(result["svg_relationships"], 1)
            self.assertEqual(len(result["sha256"]), 64)

    def test_png_validation(self):
        from PIL import Image, ImageDraw
        with tempfile.TemporaryDirectory() as directory:
            png = Path(directory) / "graph.png"
            image = Image.new("RGB", (640, 360), "white")
            draw = ImageDraw.Draw(image)
            draw.ellipse((80, 60, 240, 220), fill="red")
            draw.line((240, 140, 500, 280), fill="black", width=5)
            image.save(png)
            result = module.validate_png(png)
            self.assertEqual(result["png_width"], 640)
            self.assertEqual(result["png_height"], 360)
            self.assertGreater(result["png_variance"], 3)

    def test_output_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            task = {"output": str(Path(directory) / "graph.any"), "format": "both"}
            paths = module.output_paths(task, "png")
            self.assertEqual(paths["svg"].suffix, ".svg")
            self.assertEqual(paths["png"].suffix, ".png")

    def test_default_connection_values(self):
        self.assertEqual(module.DEFAULT_URL, "http://127.0.0.1:7474")
        self.assertEqual(module.DEFAULT_USER, "neo4j")
        self.assertEqual(module.DEFAULT_DATABASE, "neo4j")
        exporter = module.Neo4jExporter()
        self.assertEqual(exporter.url, module.DEFAULT_URL)
        self.assertEqual(exporter.user, module.DEFAULT_USER)

    def test_bolt_address_derivation(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NEO4J_BOLT_URL", None)
            self.assertEqual(
                module.derive_bolt_address("http://127.0.0.1:7474"), "127.0.0.1:7687"
            )
            self.assertEqual(
                module.derive_bolt_address("https://neo4j.example.com:7474"),
                "neo4j.example.com:7687",
            )
        with mock.patch.dict(os.environ, {"NEO4J_BOLT_URL": "db.internal:7688"}):
            self.assertEqual(
                module.derive_bolt_address("http://127.0.0.1:7474"), "db.internal:7688"
            )

    def test_connection_help_lists_current_params(self):
        exporter = module.Neo4jExporter(url="http://10.0.0.9:7474", user="custom")
        help_text = exporter.connection_help("登录超时")
        self.assertIn("10.0.0.9", help_text)
        self.assertIn("custom", help_text)
        self.assertIn("连接失败", help_text.replace("连接 Neo4j 失败", "连接失败"))


if __name__ == "__main__":
    unittest.main()
