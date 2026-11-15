"""pytest 前置：先装 SDK 替身。

工程根目录自带 ``__init__.py``（它就是 Neko 插件包本身），pytest 在收集
``tests/`` 时会顺着包链把根包 import 进来，而插件包硬依赖 ``plugin.sdk``。
在没有 SDK 的机器与 CI 里，这里先装替身，让收集不因缺 SDK 而失败。
"""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "_voice_style_sdk_stub",
    Path(__file__).with_name("_sdk_stub.py"),
)
if _spec is None or _spec.loader is None:
    raise RuntimeError("无法加载 SDK 替身模块")
_stub = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_stub)
_stub.install()
