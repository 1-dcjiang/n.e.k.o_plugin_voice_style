"""测试用的最小 ``plugin.sdk.plugin`` 替身。

本机与市场 CI 都没有 N.E.K.O 源码，而插件包 ``from plugin.sdk.plugin import ...``
是硬依赖。这里装一份最小替身让测试独立跑；真 SDK 在场时默认不覆盖，
插件类测试会显式要求替换（见 :func:`install` 的 ``force``）。

替身只负责「让 import 与装饰器成立」，不模拟宿主行为——真接口的兼容性由
宿主实机验证覆盖，两者不重复也不互相替代。
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

PACKAGE = "voice_style_under_test"

_state = "pending"


def _sdk_available() -> bool:
    try:
        return importlib.util.find_spec("plugin.sdk.plugin") is not None
    except (ImportError, ValueError):
        return False


def install(force: bool = False) -> str:
    """安装替身，返回 ``"real"`` 或 ``"stub"``。

    ``force=True`` 时即使装了真 SDK 也换成替身——插件类测试需要确定的
    假上下文，真基类会接管 ``self.config`` 等方法，行为就不再可控。
    """
    global _state
    if _state == "stub":
        return _state
    if not force:
        if _state == "real":
            return _state
        if _sdk_available():
            _state = "real"
            return _state
    _state = "stub"

    plugin_pkg = types.ModuleType("plugin")
    plugin_pkg.__path__ = []
    sdk_pkg = types.ModuleType("plugin.sdk")
    sdk_pkg.__path__ = []
    sdk_mod = types.ModuleType("plugin.sdk.plugin")

    class SdkError(Exception):
        """替身：SDK 侧的通用错误。"""

    class _Result:
        def __init__(self, value: object = None, error: object = None) -> None:
            self._value = value
            self._error = error

        def is_ok(self) -> bool:
            return self._error is None

        @property
        def value(self) -> object:
            return self._value

        @property
        def error(self) -> object:
            return self._error

    def Ok(value: object = None) -> _Result:
        return _Result(value=value)

    def Err(error: object) -> _Result:
        return _Result(error=error)

    def lifecycle(id: str | None = None, **_: object):
        def decorator(fn):
            fn.__lifecycle_id__ = id
            return fn

        return decorator

    def plugin_entry(id: str | None = None, **_: object):
        def decorator(fn):
            fn.__entry_id__ = id
            return fn

        return decorator

    def neko_plugin(cls):
        return cls

    class NekoPluginBase:
        """替身基类：只提供插件代码实际触达的那几个成员。"""

        def __init__(self, ctx: object) -> None:
            self.ctx = ctx
            self.logger = ctx.logger
            self.config = ctx.config

        def push_message(self, **kwargs: object):
            return self.ctx.push_message(**kwargs)

        def collect_entries(self) -> dict[str, object]:
            found: dict[str, object] = {}
            for name in dir(type(self)):
                member = getattr(type(self), name, None)
                key = getattr(member, "__entry_id__", None) or getattr(member, "__lifecycle_id__", None)
                if key:
                    found[key] = member
            return found

    sdk_mod.SdkError = SdkError
    sdk_mod.Ok = Ok
    sdk_mod.Err = Err
    sdk_mod.lifecycle = lifecycle
    sdk_mod.plugin_entry = plugin_entry
    sdk_mod.neko_plugin = neko_plugin
    sdk_mod.NekoPluginBase = NekoPluginBase

    sys.modules["plugin"] = plugin_pkg
    sys.modules["plugin.sdk"] = sdk_pkg
    sys.modules["plugin.sdk.plugin"] = sdk_mod
    return _state


def load_plugin_class(root: Path):
    """把插件工程根目录按「包」加载，返回插件类。

    插件类测试一律走替身：真基类会接管 ``self.config``，假上下文便不再可控。
    """
    install(force=True)
    spec = importlib.util.spec_from_file_location(
        PACKAGE,
        root / "__init__.py",
        submodule_search_locations=[str(root)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载插件包")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)
    return module.VoiceStylePlugin
