"""市场模板要求的 smoke test（文件名固定为 tests/test_smoke.py）。

N.E.K.O 的 ``check -r`` 在严格模式下要求仓库里存在这个文件，
并期望它至少能确认清单与入口没写错。真实行为测试在
``tests/test_voice_card.py``。
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_plugin_manifest_exists() -> None:
    manifest = ROOT / "plugin.toml"
    assert manifest.is_file()
    text = manifest.read_text(encoding="utf-8")
    assert 'id = "voice_style"' in text
    assert 'entry = "plugin.plugins.voice_style:VoiceStylePlugin"' in text
    assert "passive = true" in text


def test_entry_module_exists() -> None:
    assert (ROOT / "__init__.py").is_file()
    assert (ROOT / "voice_card.py").is_file()


def test_config_schema_is_utf8_object() -> None:
    schema = ROOT / "config.schema.json"
    assert schema.is_file()
    data = json.loads(schema.read_text(encoding="utf-8"))
    assert data["type"] == "object"
    assert "voice_card" in data["properties"]
    assert "plugin_runtime" in data["properties"]


def test_reference_schema_and_example_exist() -> None:
    for rel in ("references/voice-card.schema.json", "examples/voice-card.json"):
        assert (ROOT / rel).is_file(), rel


def test_license_and_notice_exist() -> None:
    for rel in ("LICENSE", "NOTICE", "README.md"):
        assert (ROOT / rel).is_file(), rel
