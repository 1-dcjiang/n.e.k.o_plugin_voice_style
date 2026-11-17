"""配置默认值与版本号一致性测试。

这些值散落在 Python 兜底、plugin.toml、config.example.toml 和 config.schema.json；
只靠 `SchemaAlignmentTests` 比对 references/ 会漏掉真正给用户看的默认值。
"""

from __future__ import annotations

import importlib.util
import json
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 与 test_voice_card.py 用同一套写法：用文件路径直接加载，避免改动 sys.path 触发
# E402（市场 CI 带 --ignore-noqa），也不依赖「当前目录恰好是仓库根」。
# tests/ 下没有 __init__.py，裸 pytest 插入的 sys.path 是 tests/ 而不是仓库根，
# 直接 `from voice_card import ...` 会 ModuleNotFoundError。
_spec = importlib.util.spec_from_file_location("voice_card", ROOT / "voice_card.py")
assert _spec is not None and _spec.loader is not None
vc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vc)

ALLOWED_KEYS = vc.ALLOWED_KEYS
DEFAULT_CARD = vc.DEFAULT_CARD
EMOJI_POLICIES = vc.EMOJI_POLICIES
LIMITS = vc.LIMITS
MAX_FLOURISH = vc.MAX_FLOURISH
MAX_FLOURISH_LEN = vc.MAX_FLOURISH_LEN
REGISTERS = vc.REGISTERS


def _toml(name: str) -> dict:
    with (ROOT / name).open("rb") as stream:
        return tomllib.load(stream)


def _json(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


class ConfigConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plugin = _toml("plugin.toml")
        cls.example = _toml("config.example.toml")
        cls.schema = _json("config.schema.json")
        cls.section = cls.schema["properties"]["voice_card"]["properties"]

    def test_plugin_toml_defaults_match_code(self) -> None:
        configured = {
            key: value for key, value in self.plugin["voice_card"].items()
            if key != "inject_on_startup"
        }
        self.assertEqual(configured, DEFAULT_CARD)

    def test_example_toml_defaults_match_code(self) -> None:
        configured = {
            key: value for key, value in self.example["voice_card"].items()
            if key != "inject_on_startup"
        }
        self.assertEqual(configured, DEFAULT_CARD)

    def test_schema_defaults_match_code(self) -> None:
        for key in DEFAULT_CARD:
            if key not in self.section:
                continue
            self.assertEqual(
                self.section[key].get("default"),
                DEFAULT_CARD[key],
                f"config.schema.json 的 {key}.default 与 DEFAULT_CARD 漂移",
            )

    def test_schema_max_lengths_match_limits(self) -> None:
        for key, limit in LIMITS.items():
            self.assertEqual(
                self.section[key].get("maxLength"),
                limit,
                f"config.schema.json 的 {key}.maxLength 与 LIMITS 不一致",
            )

    def test_schema_enum_matches_code(self) -> None:
        self.assertEqual(set(self.section["register"]["enum"]), set(REGISTERS))
        self.assertEqual(set(self.section["emoji_policy"]["enum"]), set(EMOJI_POLICIES))

    def test_schema_flourish_limits_match_code(self) -> None:
        flourish = self.section["flourish"]
        self.assertEqual(flourish["maxItems"], MAX_FLOURISH)
        self.assertEqual(flourish["items"]["maxLength"], MAX_FLOURISH_LEN)

    def test_schema_has_no_unknown_card_keys(self) -> None:
        allowed = set(ALLOWED_KEYS) | {"inject_on_startup"}
        self.assertEqual(set(self.section) - allowed, set())

    def test_versions_match(self) -> None:
        pyproject = _toml("pyproject.toml")
        self.assertEqual(
            self.plugin["plugin"]["version"],
            pyproject["project"]["version"],
            "plugin.toml 与 pyproject.toml 版本号不一致",
        )


if __name__ == "__main__":
    unittest.main()
