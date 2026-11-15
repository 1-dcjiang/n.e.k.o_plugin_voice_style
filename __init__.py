"""voice_style —— N.E.K.O 语气风格插件（表达层）。

它只回答「怎么说」：自称、称呼、语言、语气、emoji、口头禅、拒绝方式。
它不碰「说什么」：不写记忆、不改人格、不改事实与建议，也不改变是否拒绝。
"""

from __future__ import annotations

from typing import Any

from plugin.sdk.plugin import (
    Err,
    NekoPluginBase,
    Ok,
    SdkError,
    lifecycle,
    neko_plugin,
    plugin_entry,
)

from .voice_card import (
    ALLOWED_KEYS,
    DEFAULT_CARD,
    render_from_section,
    validate_card,
)

#: plugin.toml 里的业务配置段名。卡就存在这个段里。
SECTION = "voice_card"

#: 配置段里不属于卡、但插件自己要读的键。
EXTRA_KEYS: frozenset[str] = frozenset({"inject_on_startup"})

#: 渲染结果放进角色卡时的落点，只用于提示用户，插件本身不写角色卡。
PASTE_TARGET = "角色卡 → 附加角色指引（Additional role guidance）"


@neko_plugin
class VoiceStylePlugin(NekoPluginBase):
    """把语气风格卡渲染成一段可直接粘贴的提示词。"""

    def __init__(self, ctx: Any) -> None:
        super().__init__(ctx)
        self._card: dict[str, Any] = dict(DEFAULT_CARD)
        self._prompt: str = ""
        self._problems: list[str] = []
        self._unknown_keys: list[str] = []
        self._inject_on_startup: bool = False

    # ── 生命周期 ─────────────────────────────────────────────

    @lifecycle(id="startup")
    async def on_startup(self, **_: Any):
        """启动即读配置、校验、渲染并缓存；坏卡不渲染，只记一条日志。"""
        await self._reload_card()
        if self._problems:
            self.logger.warning(
                "voice_style: 语气风格卡不合法，已跳过渲染 -> %s",
                "；".join(self._problems),
            )
        elif self._inject_on_startup:
            self._push_prompt()
        return Ok(
            {
                "status": "ready",
                "valid": not self._problems,
                "characters": len(self._prompt),
            }
        )

    @lifecycle(id="reload")
    async def on_reload(self, **_: Any):
        await self._reload_card()
        return Ok({"status": "reloaded", "valid": not self._problems})

    @lifecycle(id="config_change")
    async def on_config_change(self, **_: Any):
        await self._reload_card()
        return Ok({"status": "config_updated", "valid": not self._problems})

    @lifecycle(id="shutdown")
    async def on_shutdown(self, **_: Any):
        self._prompt = ""
        return Ok({"status": "shutdown"})

    # ── 入口 ───────────────────────────────────────────────

    @plugin_entry(
        id="render_voice_prompt",
        name="生成语气提示词",
        description=(
            "把当前语气风格卡渲染成一段可以粘贴到角色卡「附加角色指引」的提示词。"
            "只影响措辞，不改变事实、建议或是否拒绝；与角色卡冲突时以角色卡为准。"
        ),
    )
    async def render_prompt(self, **_: Any):
        await self._reload_card()
        if self._problems:
            return Err(SdkError("语气风格卡不合法：" + "；".join(self._problems)))
        return Ok(
            {
                "prompt": self._prompt,
                "characters": len(self._prompt),
                "paste_into": PASTE_TARGET,
            }
        )

    @plugin_entry(
        id="voice_card_status",
        name="查看语气风格卡状态",
        description="只读：返回语气风格卡的校验结果、渲染长度与各字段值，不改动任何配置。",
    )
    async def card_status(self, **_: Any):
        await self._reload_card()
        return Ok(
            {
                "valid": not self._problems,
                "problems": list(self._problems),
                "characters": len(self._prompt),
                "card": dict(self._card),
                "unknown_section_keys": list(self._unknown_keys),
                "inject_on_startup": self._inject_on_startup,
            }
        )

    # ── 内部 ───────────────────────────────────────────────

    async def _read_section(self) -> dict[str, Any]:
        """读 ``[voice_card]`` 段。配置读不出来时交给默认卡兜底。"""
        try:
            cfg = await self.config.dump()
        except Exception as exc:
            self.logger.warning("voice_style: 读取插件配置失败 -> %s", exc)
            return {}
        if not isinstance(cfg, dict):
            return {}
        section = cfg.get(SECTION)
        if not isinstance(section, dict):
            return {}
        return section

    async def _reload_card(self) -> None:
        section = await self._read_section()
        self._unknown_keys = sorted(set(section) - set(ALLOWED_KEYS) - EXTRA_KEYS)
        if self._unknown_keys:
            # 配置页允许任意键；不阻塞渲染，但要让它可见，避免用户以为写进去了。
            self.logger.warning(
                "voice_style: [voice_card] 段里有不认识的键，已忽略 -> %s",
                ", ".join(self._unknown_keys),
            )
        self._inject_on_startup = bool(section.get("inject_on_startup", False))

        card: dict[str, Any] = {}
        for key in ALLOWED_KEYS:
            if key in section:
                card[key] = section[key]
            elif key in DEFAULT_CARD:
                card[key] = DEFAULT_CARD[key]
        self._card = card

        prompt, problems = render_from_section(card)
        self._problems = problems
        self._prompt = prompt

    def _push_prompt(self) -> None:
        """把渲染结果作为只读上下文交给宿主（默认关闭，见 README 的「方案 B」）。"""
        try:
            self.push_message(
                source="voice_style",
                visibility=[],
                ai_behavior="read",
                parts=[{"type": "text", "text": self._prompt}],
                priority=2,
            )
        except Exception as exc:
            self.logger.warning("voice_style: 注入失败 -> %s", exc)


__all__ = ["VoiceStylePlugin", "validate_card"]
