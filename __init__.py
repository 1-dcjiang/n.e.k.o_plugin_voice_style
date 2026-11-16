"""voice_style —— N.E.K.O 语气风格插件（表达层）。

它只回答「怎么说」：自称、称呼、语言、语气、emoji、口头禅、拒绝方式。
它不碰「说什么」：不写记忆、不改人格、不改事实与建议，也不改变是否拒绝。
"""

from __future__ import annotations

from collections.abc import Mapping
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
    merge_defaults,
    render_from_section,
    validate_card,
)

#: plugin.toml 里的业务配置段名。卡就存在这个段里。
SECTION = "voice_card"

#: 配置段里不属于卡、但插件自己要读的键。
EXTRA_KEYS: frozenset[str] = frozenset({"inject_on_startup"})

#: 注入用的合并键：多次启动/重载只保留一条待注入内容。
INJECT_COALESCE_KEY = "voice_style:card"

#: 渲染结果放进角色卡时的落点，只用于提示用户，插件本身不写角色卡。
#:
#: 主程序没有名为「附加角色指引（Additional role guidance）」的可编辑输入框；
#: 那段英文前缀是 persona_payload 在拼 system prompt 时按 persona_override 追加的。
#: 角色卡「设定」只是页签名，`system_prompt` 属于 `_reserved` 保留字段，普通表单
#: 不渲染；新增名为「设定」的自定义字段也不会写进 system_prompt。当前版本没有
#: 用户可编辑的 system_prompt 入口，所以这里明确写“需要主程序支持”，不指向一个
#: 实际不存在的输入框。
PASTE_TARGET = "需要主程序支持（当前角色卡没有可编辑的 system_prompt）"


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
        # 只在配置真正变化时提醒，避免每次点入口都刷同一条 warning。
        self._last_unknown_keys: tuple[str, ...] | None = None
        self._last_bad_inject: str | None = None

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
        payload = {
            "status": "ready",
            "valid": not self._problems,
            "characters": len(self._prompt),
        }
        if self._inject_on_startup:
            # 只有真的被 SDK 接收才记为 True；submitted=False 不能当成成功。
            payload["injected"] = self._maybe_push()
        return Ok(payload)

    @lifecycle(id="reload")
    async def on_reload(self, **_: Any):
        await self._reload_card()
        payload = {"status": "reloaded", "valid": not self._problems}
        if self._inject_on_startup:
            # 配置改了而 inject_on_startup 还开着时，模型手里不能继续拿旧卡。
            payload["injected"] = self._maybe_push()
        return Ok(payload)

    @lifecycle(id="config_change")
    async def on_config_change(self, **_: Any):
        await self._reload_card()
        payload = {"status": "config_updated", "valid": not self._problems}
        if self._inject_on_startup:
            payload["injected"] = self._maybe_push()
        return Ok(payload)

    @lifecycle(id="shutdown")
    async def on_shutdown(self, **_: Any):
        self._prompt = ""
        return Ok({"status": "shutdown"})

    # ── 入口 ───────────────────────────────────────────────

    @plugin_entry(
        id="render_voice_prompt",
        name="生成语气提示词",
        description=(
            "把当前语气风格卡渲染成一段提示词；当前主程序的角色卡没有可编辑的 "
            "system_prompt 入口，真正落进系统提示词需要主程序支持。"
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
        except Exception as exc:  # noqa: BLE001 - 宿主 dump 可抛出任意错误，坏配置一律回退默认卡
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
        unknown_signature = tuple(self._unknown_keys)
        if unknown_signature != self._last_unknown_keys:
            # 配置页允许任意键；不阻塞渲染，但要让它可见。只在键集合变化时记，
            # 否则每次点入口都会重复刷同一条 warning。
            if unknown_signature:
                self.logger.warning(
                    "voice_style: [voice_card] 段里有不认识的键，已忽略 -> %s",
                    ", ".join(unknown_signature),
                )
            self._last_unknown_keys = unknown_signature

        raw_inject = section.get("inject_on_startup", False)
        if isinstance(raw_inject, bool):
            self._inject_on_startup = raw_inject
            self._last_bad_inject = None
        else:
            # 手写 TOML 的 "false" 是字符串，不能按真值当真。只认真正的 bool。
            self._inject_on_startup = False
            marker = repr(raw_inject)
            if marker != self._last_bad_inject:
                self.logger.warning(
                    "voice_style: inject_on_startup 只接受 true/false，收到 %s；按 false 处理",
                    marker,
                )
            self._last_bad_inject = marker

        self._card = merge_defaults(section)
        self._prompt, self._problems = render_from_section(section)

    def _maybe_push(self) -> bool:
        """配置允许且卡合法时推送；否则返回 False，避免调用方拿到 null。"""
        if not self._inject_on_startup or self._problems:
            return False
        return self._push_prompt()

    def _push_prompt(self) -> bool:
        """把渲染结果作为只读上下文交给宿主（默认关闭，见 README 的「方案 B」）。

        返回值只表示 SDK 本地是否接收了这次 payload；submitted=False 时不能当成成功。
        日志只写 reason，不写正文。
        """
        try:
            result = self.push_message(
                source="voice_style",
                visibility=[],
                ai_behavior="read",
                parts=[{"type": "text", "text": self._prompt}],
                coalesce_key=INJECT_COALESCE_KEY,
            )
        except Exception as exc:  # noqa: BLE001 - 传输层异常一律按未注入处理，不吞失败
            self.logger.warning("voice_style: 注入失败（异常） -> %s", exc)
            return False

        if isinstance(result, Mapping):
            submitted = result.get("submitted") is True
            reason = result.get("reason")
        else:
            submitted = getattr(result, "submitted", None) is True
            reason = getattr(result, "reason", None)

        if not submitted:
            detail = str(reason or "unknown_reason").replace("\n", " ").replace("\r", " ")
            self.logger.warning(
                "voice_style: 注入未被接受（reason=%s），本次不当作成功",
                detail,
            )
            return False
        return True


__all__ = ["VoiceStylePlugin", "validate_card"]
