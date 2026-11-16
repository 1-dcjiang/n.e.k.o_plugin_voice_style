"""有真 SDK 时才跑的最小契约测试。

本仓库单独 checkout 时没有 N.E.K.O 源码，测试会 skip。把本仓库挂到
``neko/plugin/plugins/voice_style`` 并在那棵树里跑测试时，向上两级能找到
``neko/plugin/sdk``，于是用一个独立子进程加载真 ``NekoPluginBase``，确认插件类
能实例化、入口能收集，且 SDK 的 ``push_message`` 仍然接受 ``coalesce_key``。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _find_sdk_root() -> Path | None:
    """返回 N.E.K.O 的 ``plugin`` 包目录（不是它下面的 ``sdk``）。"""
    env_root = os.environ.get("NEKO_SDK_ROOT")
    candidates = [Path(env_root) if env_root else None]
    candidates.append(ROOT.parents[1] if len(ROOT.parents) > 1 else None)
    candidates.extend(ROOT.parents)
    for parent in candidates:
        if parent is None:
            continue
        if (parent / "sdk" / "plugin" / "__init__.py").is_file():
            return parent
    return None


SCRIPT = r"""
import inspect
import json
import logging
import sys
from pathlib import Path

sdk_root, plugin_root = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(sdk_root.parent))
sys.path.insert(0, str(plugin_root.parent))

from plugin.sdk.plugin import NekoPluginBase
from plugin.sdk.shared.core.context import SdkContext
from voice_style import VoiceStylePlugin


class Ctx:
    plugin_id = "voice_style"
    metadata = {"config_path": str(plugin_root / "plugin.toml")}
    logger = logging.getLogger("voice_style.contract")
    config_path = str(plugin_root / "plugin.toml")
    bus = None
    images = None
    models = None
    _effective_config = {}


plugin = VoiceStylePlugin(Ctx())
entries = plugin.collect_entries()
print(json.dumps({
    "base_module": type(plugin).__mro__[1].__module__,
    "is_real_base": isinstance(plugin, NekoPluginBase),
    "entries": sorted(entries),
    "has_coalesce_key": "coalesce_key" in inspect.signature(SdkContext.push_message).parameters,
}))
"""


@unittest.skipUnless(_find_sdk_root(), "当前环境没有 N.E.K.O 真 SDK（CI 挂载后才会跑）")
class RealSdkContractTests(unittest.TestCase):
    def test_real_base_instantiates_and_collects_entries(self) -> None:
        sdk_root = _find_sdk_root()
        assert sdk_root is not None
        proc = subprocess.run(
            [sys.executable, "-c", SCRIPT, str(sdk_root), str(ROOT)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertTrue(payload["is_real_base"], payload)
        self.assertNotIn("stub", payload["base_module"])
        self.assertLessEqual(
            {"render_voice_prompt", "voice_card_status", "startup", "shutdown", "reload", "config_change"},
            set(payload["entries"]),
        )
        self.assertTrue(payload["has_coalesce_key"], "真 SDK 的 push_message 不再接受 coalesce_key")


if __name__ == "__main__":
    unittest.main()
