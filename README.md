# 语气风格（voice_style）

N.E.K.O 的表达层插件。它只回答一个问题：**怎么说**。

自称、称呼、语言、语气、emoji、口头禅、拒绝措辞——这些进提示词；
记忆、人格、事实、建议、是否拒绝——这些不进，也不会被插件改动。

与角色卡冲突时，以角色卡为准。

---

## 它做什么 / 不做什么

| 做 | 不做 |
| --- | --- |
| 把语气卡渲染成一段可粘贴的提示词 | 不写入角色卡，不改 `lanlan_prompt` |
| 校验卡片（键、类型、长度、枚举） | 不创建、不修改、不读取记忆条目 |
| 提供 `render_voice_prompt` 入口 | 不改变事实、建议、是否拒绝 |
| 可选：启动时推一条只读上下文（默认关） | 不改角色名（角色名以角色卡为准） |

插件没有数据库、没有网络请求、没有后台定时任务；启动只做「读配置 → 校验 → 渲染」。

---

## 目录

```
voice_style/
├── plugin.toml            # 插件身份、运行设置、[voice_card] 默认值
├── config.example.toml    # 可变的配置默认值（不含 [plugin]）
├── config.schema.json     # 通用配置页的字段名/说明/控件
├── __init__.py            # VoiceStylePlugin
├── voice_card.py          # 校验 + 渲染（纯标准库）
├── references/voice-card.schema.json
├── examples/voice-card.json
├── tests/                 # test_smoke / test_voice_card / test_plugin + SDK 替身
├── pyproject.toml         # 项目元数据、ruff 与 pytest 配置
├── LICENSE
└── NOTICE
```

---

## 安装

源码树（开发）：

```
# 把整个 voice_style 目录放到 N.E.K.O 的插件目录
plugin/plugins/voice_style/
```

打包（发布）：目录名、`plugin.id`、`plugin.entry` 的包路径三处一致，`config.schema.json`
随包分发，不要放进用户的运行时配置目录。

---

## 配置

卡片存在 `plugin.toml` 的 `[voice_card]` 段；用户的实际配置在
`<用户数据根>/plugins/voice_style/config/plugin.toml`。

| 字段 | 类型 | 上限 / 取值 | 说明 |
| --- | --- | --- | --- |
| `spec` | string | 固定 `voice-card` | 格式标识，改了就校验失败 |
| `spec_version` | string | 固定 `1.0` | 格式版本 |
| `name` | string | 32 | 卡片标签，不是角色名 |
| `self` | string | 16 | 角色怎么自称 |
| `user` | string | 24 | 角色怎么称呼对方；可用 `{MASTER_NAME}` |
| `language` | string | 80 | 用哪种语言回答（措辞偏好） |
| `register` | enum | `casual` / `neutral` / `formal` | 语气 |
| `emoji_policy` | enum | `none` / `sparse` / `free` | emoji 使用量 |
| `flourish` | array | ≤5 条，每条 ≤80 | 可原样使用的口头禅 |
| `refusal_style` | string | 120 | 拒绝时怎么说 |
| `inject_on_startup` | bool | 默认 `false` | 见下方「方案 B」 |

校验器比 `references/voice-card.schema.json` 严一处：**纯空白字符串**也会被拒，
而 JSON Schema 的 `minLength: 1` 拦不住 `"   "`。

渲染结果默认上限 1200 字符。正常卡片远达不到这个数（各字段本身都有上限），它是给
外部调用方留的硬闸；真的触发截断时只截正文并补 `…`，`以上只影响措辞…` 那句固定尾句
完整保留——边界声明不能被截掉。

`config.schema.json` 只提供表单展示，不是校验边界：`required` / `pattern` 不被表单支持，
运行时合法性仍由 `voice_card.validate_card` 判定。

`[voice_card]` 段里出现不认识的键（例如 `memory`）不会被写进卡：插件会忽略它、记一条
warning，并在 `voice_card_status` 的 `unknown_section_keys` 里列出来。

---

## 怎么让它生效

主程序的初始提示词是写死的（`main_logic/core/notify.py` 的 `_build_initial_prompt`），
没有给插件留 `plugin_prompt` 钩子。所以插件只能把文本交给你，由你放进提示词。

### 方案 A：手动粘贴（推荐，稳定）

1. 在插件面板执行入口 `render_voice_prompt`；
2. 把它返回的 `prompt` 粘贴到角色卡的「附加角色指引（Additional role guidance）」；
3. 粘贴后插件可以不再启动——文本已经是角色卡的一部分。

优点：随角色卡持久化、不受历史压缩影响、不会被套上「来自插件的新消息」措辞。
缺点：卡片改了要重新粘贴一次。

### 方案 B：启动时自动注入（可选，默认关闭）

把 `inject_on_startup` 设为 `true`。插件在 `startup` 调
`push_message(visibility=[], ai_behavior="read")`，把渲染文本作为只读上下文推进对话。

这是**聊天消息**，不是系统提示词，因此：

- 是一次性的：后续会话不重复注入；
- 历史压缩可能把它丢掉；
- 宿主可能在外层加一句「来自插件的新消息」，模型未必按原文理解；
- 会话中途的系统级注入在实时语音下是否吞掉回复，尚未在真实宿主上验证。

所以默认关闭。README 不把方案 B 说成「推荐」，也不宣称它已验证。

### 方案 C（未实现）

长期正解是在 `_build_initial_prompt` 里加一个插件片段注册点，让插件提供一段系统级
文字。这需要改主程序，不在本插件范围内。

---

## 优先级

```
用户禁令与安全规则  >  角色卡（lanlan_prompt）  >  语气风格卡
```

- 角色名以角色卡为准；卡里的 `self` / `user` 只管「怎么自称、怎么叫对方」。
- 用户说了「别叫我亲爱的」，声音卡不能覆盖它。
- 拒绝与否由事实、安全规则和角色卡决定；`refusal_style` 只决定拒绝时的措辞。

## 与「自然表达」的相互影响

主程序有一层「口头禅避让」，会压低高频口头禅的重复（受「自然表达」开关控制）。
本插件方向相反：模板写的是「偶尔用，别每句都带」。
开着自然表达时，卡里放太多口头禅可能被那层逻辑抵消——这是预期行为，不是 bug。

---

## 入口

| entry id | 作用 |
| --- | --- |
| `render_voice_prompt` | 返回渲染后的提示词、字符数、粘贴位置 |
| `voice_card_status` | 只读：校验结果、渲染长度、当前字段值、未知配置键 |

插件是 `passive = true`：它不参与 Agent 主动分派，入口在插件面板里执行。
如果你希望模型能自己调用它，把 `plugin.toml` 的 `passive` 改成 `false` 并 reload。

---

## 自检

两条 runner 都能跑（CI 走 pytest，本机习惯 unittest）：

```bash
python -m unittest discover -s tests -v
python -m pytest -q

ruff check --ignore-noqa --isolated --no-respect-gitignore --target-version py311 \
  --line-length 120 --select E4,E7,E9,F,I --exclude vendor .
```

测试不依赖 N.E.K.O 源码树：`tests/_sdk_stub.py` 提供一份最小的
`plugin.sdk.plugin` 替身，`tests/conftest.py` 在 pytest 收集前装上它。插件类测试一律
强制走替身（真基类会接管 `self.config`，假上下文便不可控）——所以「逻辑对不对」由
本地测试保证，「接口接不接得上」由宿主实机跑入口验证，两件事分开。

---

## 许可

MIT，见 `LICENSE`。改编来源、上游设计纪律与改动清单见 `NOTICE`。
`references/voice-card.schema.json` 的 `$id` 指向本仓库。
