"""市场模板要求的 smoke 测试（文件名固定为 tests/test_smoke.py）。

``neko-plugin check --release`` 在严格模式下要求仓库里存在这个文件，并期望它
至少能确认清单、入口与配置结构没写错。它写成 ``unittest.TestCase``，
所以 ``unittest discover`` 和 ``pytest`` 两种 runner 都能收集到它。
真实行为测试在 ``tests/test_voice_card.py`` 与 ``tests/test_plugin.py``。
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SmokeTests(unittest.TestCase):
    def test_plugin_manifest_exists(self) -> None:
        manifest = ROOT / "plugin.toml"
        self.assertTrue(manifest.is_file())
        text = manifest.read_text(encoding="utf-8")
        self.assertIn('id = "voice_style"', text)
        self.assertIn('entry = "plugin.plugins.voice_style:VoiceStylePlugin"', text)
        self.assertIn("passive = true", text)

    def test_entry_module_exists(self) -> None:
        self.assertTrue((ROOT / "__init__.py").is_file())
        self.assertTrue((ROOT / "voice_card.py").is_file())

    def test_config_schema_is_utf8_object(self) -> None:
        schema = ROOT / "config.schema.json"
        self.assertTrue(schema.is_file())
        data = json.loads(schema.read_text(encoding="utf-8"))
        self.assertEqual(data["type"], "object")
        self.assertIn("voice_card", data["properties"])
        self.assertIn("plugin_runtime", data["properties"])

    def test_reference_schema_and_example_exist(self) -> None:
        for rel in ("references/voice-card.schema.json", "examples/voice-card.json"):
            self.assertTrue((ROOT / rel).is_file(), rel)

    def test_license_and_notice_exist(self) -> None:
        for rel in ("LICENSE", "NOTICE", "README.md"):
            self.assertTrue((ROOT / rel).is_file(), rel)


if __name__ == "__main__":
    unittest.main()
