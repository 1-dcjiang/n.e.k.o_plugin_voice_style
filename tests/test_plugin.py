"""插件类自身的行为测试：生命周期、配置重载、注入形态、坏卡不推送。

不依赖 N.E.K.O 源码树——``plugin.sdk.plugin`` 由 ``tests/_sdk_stub.py`` 提供
最小替身，所以在没有 SDK 的 CI 里也能跑。真 SDK 的兼容性由宿主实机验证覆盖。
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from typing import ClassVar

ROOT = Path(__file__).resolve().parents[1]

GOOD = {
    "spec": "voice-card",
    "spec_version": "1.0",
    "name": "测试卡",
    "self": "我",
    "user": "{MASTER_NAME}",
    "language": "跟随对方使用的语言",
    "register": "neutral",
    "emoji_policy": "sparse",
    "flourish": ["这个我看看"],
    "refusal_style": "直接说做不到，并给一个可行的替代",
}


def _load_stub_module():
    spec = importlib.util.spec_from_file_location(
        "_voice_style_sdk_stub",
        Path(__file__).with_name("_sdk_stub.py"),
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 SDK 替身模块")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stub = _load_stub_module()
stub.install()


class _Logger:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, fmt: str, *args: object) -> None:
        self.warnings.append(fmt % args if args else fmt)


class _Config:
    def __init__(self, ctx: _FakeCtx) -> None:
        self._ctx = ctx

    async def dump(self) -> dict[str, object]:
        if self._ctx.dump_error:
            raise RuntimeError("宿主配置不可用")
        return {
            "voice_card": dict(self._ctx.section),
            "plugin_runtime": {"enabled": True},
        }


class _FakeCtx:
    """最小宿主上下文：只实现插件代码真正触达的部分。"""

    plugin_id = "voice_style"
    metadata: ClassVar[dict[str, object]] = {}

    def __init__(self, section: dict[str, object] | None = None, *, dump_error: bool = False,
                 push_error: bool = False, push_result: dict[str, object] | None = None) -> None:
        self.section: dict[str, object] = dict(section or {})
        self.logger = _Logger()
        self.config = _Config(self)
        self.dump_error = dump_error
        self.push_error = push_error
        self.push_result = {"submitted": True} if push_result is None else dict(push_result)
        self.pushed: list[dict[str, object]] = []

    def push_message(self, **kwargs: object) -> dict[str, object]:
        if self.push_error:
            raise RuntimeError("IPC 不可用")
        self.pushed.append(kwargs)
        return dict(self.push_result)


class PluginLifecycleTests(unittest.IsolatedAsyncioTestCase):
    """覆盖 ``__init__.py`` 里的生命周期、重载与注入形态。"""

    async def asyncSetUp(self) -> None:
        self.plugin_cls = stub.load_plugin_class(ROOT)

    async def test_startup_renders_valid_card_without_pushing(self) -> None:
        ctx = _FakeCtx(GOOD)
        plugin = self.plugin_cls(ctx)

        result = await plugin.on_startup()

        self.assertTrue(result.is_ok())
        self.assertTrue(result.value["valid"])
        self.assertIn("以上只影响措辞", plugin._prompt)
        self.assertEqual(ctx.pushed, [], "默认不开注入时不应该推送")

    async def test_entries_collected(self) -> None:
        plugin = self.plugin_cls(_FakeCtx(GOOD))
        entries = plugin.collect_entries()

        self.assertLessEqual({"render_voice_prompt", "voice_card_status"}, set(entries))
        self.assertLessEqual({"startup", "shutdown", "reload", "config_change"}, set(entries))

    async def test_reload_picks_up_new_config(self) -> None:
        ctx = _FakeCtx(GOOD)
        plugin = self.plugin_cls(ctx)
        await plugin.on_startup()

        ctx.section = {**GOOD, "self": "换过的自称"}
        await plugin.on_reload()

        self.assertIn("自称：换过的自称", plugin._prompt)
        self.assertEqual(plugin._card["self"], "换过的自称")

    async def test_config_change_marks_state(self) -> None:
        ctx = _FakeCtx(GOOD)
        plugin = self.plugin_cls(ctx)
        await plugin.on_startup()

        ctx.section = {**GOOD, "register": "formal"}
        result = await plugin.on_config_change()

        self.assertTrue(result.is_ok())
        self.assertEqual(result.value["status"], "config_updated")
        self.assertIn("正式克制", plugin._prompt)

    async def test_shutdown_clears_prompt(self) -> None:
        plugin = self.plugin_cls(_FakeCtx(GOOD))
        await plugin.on_startup()

        result = await plugin.on_shutdown()

        self.assertTrue(result.is_ok())
        self.assertEqual(plugin._prompt, "")

    async def test_inject_on_startup_pushes_once(self) -> None:
        ctx = _FakeCtx({**GOOD, "inject_on_startup": True})
        plugin = self.plugin_cls(ctx)

        result = await plugin.on_startup()

        self.assertEqual(len(ctx.pushed), 1, "注入只应发生一次")
        self.assertTrue(result.value["injected"])
        payload = ctx.pushed[0]
        self.assertEqual(payload["visibility"], [])
        self.assertEqual(payload["ai_behavior"], "read")
        self.assertEqual(payload["source"], "voice_style")
        self.assertEqual(payload["coalesce_key"], "voice_style:card")
        parts = payload["parts"]
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0]["type"], "text")
        self.assertIn("以上只影响措辞", parts[0]["text"])

    async def test_inject_failure_is_swallowed(self) -> None:
        ctx = _FakeCtx({**GOOD, "inject_on_startup": True}, push_error=True)
        plugin = self.plugin_cls(ctx)

        result = await plugin.on_startup()

        self.assertTrue(result.is_ok(), "注入失败不应该让启动失败")
        self.assertFalse(result.value["injected"])
        self.assertTrue(any("注入失败" in item for item in ctx.logger.warnings), ctx.logger.warnings)

    async def test_submitted_false_is_not_treated_as_success(self) -> None:
        ctx = _FakeCtx(
            {**GOOD, "inject_on_startup": True},
            push_result={"submitted": False, "reason": "backpressure"},
        )
        plugin = self.plugin_cls(ctx)

        result = await plugin.on_startup()

        self.assertTrue(result.is_ok(), "本地背压不应该让启动失败")
        self.assertFalse(result.value["injected"], "submitted=False 不能当成注入成功")
        self.assertTrue(
            any("未被接受" in item and "backpressure" in item for item in ctx.logger.warnings),
            ctx.logger.warnings,
        )
        self.assertNotIn("以上只影响措辞", "\n".join(ctx.logger.warnings), "日志不应写入正文")

    async def test_reload_repushes_with_same_coalesce_key(self) -> None:
        ctx = _FakeCtx({**GOOD, "inject_on_startup": True})
        plugin = self.plugin_cls(ctx)
        await plugin.on_startup()

        ctx.section = {**GOOD, "self": "换过的自称", "inject_on_startup": True}
        result = await plugin.on_reload()

        self.assertEqual(len(ctx.pushed), 2)
        self.assertTrue(result.value["injected"])
        self.assertEqual(ctx.pushed[0]["coalesce_key"], ctx.pushed[1]["coalesce_key"])

    async def test_config_change_repushes_when_enabled(self) -> None:
        ctx = _FakeCtx({**GOOD, "inject_on_startup": True})
        plugin = self.plugin_cls(ctx)
        await plugin.on_startup()

        ctx.section = {**GOOD, "register": "formal", "inject_on_startup": True}
        result = await plugin.on_config_change()

        self.assertEqual(len(ctx.pushed), 2)
        self.assertTrue(result.value["injected"])
        self.assertIn("正式克制", ctx.pushed[1]["parts"][0]["text"])

    async def test_string_false_is_not_a_true_boolean(self) -> None:
        ctx = _FakeCtx({**GOOD, "inject_on_startup": "false"})
        plugin = self.plugin_cls(ctx)

        result = await plugin.on_startup()

        self.assertTrue(result.is_ok())
        self.assertFalse(plugin._inject_on_startup)
        self.assertEqual(ctx.pushed, [], "字符串 'false' 不能触发注入")
        self.assertTrue(any("只接受 true/false" in item for item in ctx.logger.warnings))

    async def test_unknown_key_warning_is_not_repeated_per_entry(self) -> None:
        ctx = _FakeCtx({**GOOD, "memory": ["用户喜欢猫"]})
        plugin = self.plugin_cls(ctx)

        await plugin.on_startup()
        await plugin.card_status()
        await plugin.card_status()
        await plugin.render_prompt()

        warnings = [item for item in ctx.logger.warnings if "不认识的键" in item]
        self.assertEqual(len(warnings), 1, warnings)

    async def test_bad_card_does_not_render_or_push(self) -> None:
        ctx = _FakeCtx({**GOOD, "self": "姐" * 17, "inject_on_startup": True})
        plugin = self.plugin_cls(ctx)

        result = await plugin.on_startup()

        self.assertTrue(result.is_ok(), "坏卡不应该让启动抛异常")
        self.assertFalse(result.value["valid"])
        self.assertFalse(result.value["injected"], "坏卡没有可注入内容")
        self.assertEqual(plugin._prompt, "")
        self.assertEqual(ctx.pushed, [], "坏卡一律不推送")
        self.assertTrue(any("不合法" in item for item in ctx.logger.warnings))
        self.assertFalse((await plugin.render_prompt()).is_ok())

        reloaded = await plugin.on_reload()
        self.assertFalse(reloaded.value["injected"], "坏卡重载也不能报注入成功")
        self.assertEqual(ctx.pushed, [], "坏卡重载仍不推送")

    async def test_unknown_section_keys_are_reported(self) -> None:
        ctx = _FakeCtx({**GOOD, "memory": ["用户喜欢猫"]})
        plugin = self.plugin_cls(ctx)

        await plugin.on_startup()
        status = await plugin.card_status()

        self.assertEqual(status.value["unknown_section_keys"], ["memory"])
        self.assertTrue(status.value["valid"], "多余键不应该阻塞渲染")
        self.assertTrue(any("不认识的键" in item for item in ctx.logger.warnings))

    async def test_config_failure_falls_back_to_default_card(self) -> None:
        ctx = _FakeCtx({}, dump_error=True)
        plugin = self.plugin_cls(ctx)

        result = await plugin.on_startup()

        self.assertTrue(result.is_ok())
        self.assertTrue(result.value["valid"])
        self.assertIn("以上只影响措辞", plugin._prompt)
        self.assertTrue(any("读取插件配置失败" in item for item in ctx.logger.warnings))

    async def test_partial_card_uses_defaults(self) -> None:
        ctx = _FakeCtx({"self": "本机"})
        plugin = self.plugin_cls(ctx)

        await plugin.on_startup()

        self.assertIn("自称：本机", plugin._prompt)
        self.assertEqual(plugin._card["language"], "跟随对方使用的语言")


if __name__ == "__main__":
    unittest.main()
