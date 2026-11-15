"""语气风格卡（voice card）的解析、校验与渲染。

边界：本模块只处理「怎么说」，不涉及记忆、人格、事实与判断。
它不读写宿主的角色卡与记忆，也不改变任何模型结论——只输出一段描述表达方式的文本。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

SPEC_NAME = "voice-card"
SPEC_VERSION = "1.0"

#: 卡片允许的全部键。多一个键就拒绝，避免把「记忆」类字段偷偷带进来。
ALLOWED_KEYS: tuple[str, ...] = (
    "spec",
    "spec_version",
    "name",
    "self",
    "user",
    "language",
    "register",
    "emoji_policy",
    "flourish",
    "refusal_style",
)

#: 单行字符串字段的长度上限。
LIMITS: dict[str, int] = {
    "name": 32,
    "self": 16,
    "user": 24,
    "language": 80,
    "refusal_style": 120,
}

REGISTERS: frozenset[str] = frozenset({"casual", "neutral", "formal"})
EMOJI_POLICIES: frozenset[str] = frozenset({"none", "sparse", "free"})

MAX_FLOURISH = 5
MAX_FLOURISH_LEN = 80

#: 渲染结果的总长度上限，防止一张卡把提示词撑爆。
MAX_PROMPT_CHARS = 1200

#: 配置里缺少字段时的兜底值。``{MASTER_NAME}`` 由宿主在注入边界展开。
DEFAULT_CARD: dict[str, Any] = {
    "spec": SPEC_NAME,
    "spec_version": SPEC_VERSION,
    "name": "语气风格",
    "self": "我",
    "user": "{MASTER_NAME}",
    "language": "跟随对方使用的语言",
    "register": "neutral",
    "emoji_policy": "sparse",
    "flourish": [],
    "refusal_style": "直接说明做不到，并给出一个可行的替代",
}

REGISTER_TEXT: dict[str, str] = {
    "casual": "随意口语，像熟人聊天",
    "neutral": "中性平实",
    "formal": "正式克制",
}

EMOJI_TEXT: dict[str, str] = {
    "none": "完全不用 emoji",
    "sparse": "很少用，一条消息最多一个",
    "free": "可以随意用",
}

#: 渲染固定尾句。措辞层不得越界改动事实、建议或拒绝决定。
FOOTER = "以上只影响措辞。不改变事实、建议，也不改变是否拒绝；与角色设定、记忆、用户禁令冲突时，以它们为准。"


class VoiceCardError(ValueError):
    """卡片不合法，拒绝渲染。"""


def _clean(value: Any, limit: int) -> str:
    """把任意值压成单行文本：折叠换行与多余空白，并截到上限。"""
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    return text[:limit]


def validate_card(card: object) -> list[str]:
    """校验一张已解析的卡片，返回问题清单（空列表表示通过）。

    纯函数：不读文件、不抛异常。文件读取交给 :func:`load_card`。
    """
    if not isinstance(card, dict):
        return ["卡片顶层必须是 JSON 对象（dict）"]

    problems: list[str] = []

    unknown = sorted(set(card) - set(ALLOWED_KEYS))
    if unknown:
        problems.append("unknown keys: " + ", ".join(unknown))

    if card.get("spec") != SPEC_NAME:
        problems.append(f'spec must be "{SPEC_NAME}"')
    if card.get("spec_version") != SPEC_VERSION:
        problems.append(f'spec_version must be "{SPEC_VERSION}"')

    for key, limit in LIMITS.items():
        value = card.get(key)
        if not isinstance(value, str):
            problems.append(f"{key} must be a string")
            continue
        text = value.strip()
        if not text:
            problems.append(f"{key} must not be blank")
        elif len(text) > limit:
            problems.append(f"{key} exceeds {limit} chars ({len(text)})")

    for key, allowed in (("register", REGISTERS), ("emoji_policy", EMOJI_POLICIES)):
        value = card.get(key)
        if not isinstance(value, str):
            problems.append(f"{key} must be a string")
        elif value not in allowed:
            problems.append(f"{key} must be one of {sorted(allowed)}")

    flourish = card.get("flourish")
    if not isinstance(flourish, list):
        problems.append("flourish must be a list of strings")
    elif len(flourish) > MAX_FLOURISH:
        problems.append(f"flourish may hold at most {MAX_FLOURISH} items ({len(flourish)})")
    else:
        for index, item in enumerate(flourish):
            if not isinstance(item, str):
                problems.append(f"flourish[{index}] must be a string")
            elif not item.strip():
                problems.append(f"flourish[{index}] must not be blank")
            elif len(item) > MAX_FLOURISH_LEN:
                problems.append(f"flourish[{index}] exceeds {MAX_FLOURISH_LEN} chars ({len(item)})")

    return problems


def load_card(path: str | os.PathLike[str]) -> tuple[dict[str, Any] | None, list[str]]:
    """读取并校验卡片文件。

    返回 ``(card, problems)``：校验通过时 ``card`` 是 dict、``problems`` 为空；
    否则 ``card`` 为 ``None``。任何坏输入都折叠成问题字符串，不抛异常。
    """
    try:
        target = Path(path)
    except (TypeError, ValueError):
        return None, ["路径无效"]

    try:
        if not target.is_file():
            return None, [f"不是文件或不存在：{target}"]
    except OSError as exc:
        return None, [f"无法访问路径：{exc}"]

    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [f"无法读取文件：{exc}"]
    except UnicodeDecodeError as exc:
        return None, [f"文件不是合法的 UTF-8：{exc}"]

    if raw.startswith("\ufeff"):
        raw = raw[1:]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, [f"JSON 无法解析：{exc}"]

    problems = validate_card(data)
    if problems:
        return None, problems
    return data, []


def render_voice_prompt(card: object, *, max_chars: int = MAX_PROMPT_CHARS) -> str:
    """把卡片渲染成可粘贴的语气提示词。

    卡片不合法时抛 :class:`VoiceCardError`——坏卡一律不渲染。
    """
    problems = validate_card(card)
    if problems:
        raise VoiceCardError("；".join(problems))

    assert isinstance(card, dict)  # validate_card 已确认
    data = card

    lines = [
        "【说话方式——只管怎么说，不改变说什么】",
        f"自称：{_clean(data['self'], LIMITS['self'])}；"
        f"称呼对方：{_clean(data['user'], LIMITS['user'])}",
        f"语言：{_clean(data['language'], LIMITS['language'])}；"
        f"语气：{REGISTER_TEXT[data['register']]}；"
        f"emoji：{EMOJI_TEXT[data['emoji_policy']]}",
    ]

    phrases = [
        cleaned
        for cleaned in (_clean(item, MAX_FLOURISH_LEN) for item in data["flourish"])
        if cleaned
    ]
    if phrases:
        lines.append("口头禅（偶尔用，别每句都带）：" + "、".join(f"「{item}」" for item in phrases))

    lines.append(f"需要拒绝时的说法：{_clean(data['refusal_style'], LIMITS['refusal_style'])}")
    lines.append(FOOTER)

    prompt = "\n".join(lines)
    if len(prompt) > max_chars:
        prompt = prompt[: max_chars - 1].rstrip() + "…"
    return prompt


def render_from_section(section: object) -> tuple[str, list[str]]:
    """从 ``[voice_card]`` 配置段渲染，缺字段用 :data:`DEFAULT_CARD` 补齐。

    这是插件启动路径用的入口：配置里少写几个键不会让整张卡失效，
    但类型/长度/枚举错误仍会被拦住。
    """
    source = section if isinstance(section, dict) else {}
    card: dict[str, Any] = {}
    for key in ALLOWED_KEYS:
        if key in source:
            card[key] = source[key]
        elif key in DEFAULT_CARD:
            card[key] = DEFAULT_CARD[key]

    problems = validate_card(card)
    if problems:
        return "", problems
    try:
        return render_voice_prompt(card), []
    except VoiceCardError as exc:  # 理论上不会触发，保留兜底
        return "", [str(exc)]
