"""voice_card.py 的行为测试：校验、读取、渲染。

只用标准库 unittest，不依赖 Neko SDK，便于在插件仓库根目录直接跑
``python -m unittest discover -s tests -v``。
"""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 用文件路径直接加载，避免改动 sys.path 触发的 E402（市场 CI 带 --ignore-noqa）。
_spec = importlib.util.spec_from_file_location("voice_card", ROOT / "voice_card.py")
assert _spec is not None and _spec.loader is not None
vc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vc)


def make_card(**overrides):
    card = {
        "spec": vc.SPEC_NAME,
        "spec_version": vc.SPEC_VERSION,
        "name": "示例",
        "self": "我",
        "user": "{MASTER_NAME}",
        "language": "跟随对方使用的语言",
        "register": "neutral",
        "emoji_policy": "sparse",
        "flourish": ["这个我看看"],
        "refusal_style": "直接说做不到，再给替代",
    }
    card.update(overrides)
    return card


class ValidateCardTests(unittest.TestCase):
    def test_valid_card_passes(self):
        self.assertEqual(vc.validate_card(make_card()), [])

    def test_top_level_not_dict(self):
        for bad in ([], "x", 3, None):
            with self.subTest(bad=bad):
                problems = vc.validate_card(bad)
                self.assertEqual(len(problems), 1)
                self.assertIn("顶层必须是 JSON 对象", problems[0])

    def test_unknown_key(self):
        problems = vc.validate_card(make_card(memory=["用户喜欢猫"]))
        self.assertTrue(any("unknown keys" in item for item in problems))

    def test_self_too_long(self):
        problems = vc.validate_card(make_card(self="姐" * 17))
        self.assertTrue(any("self exceeds 16 chars (17)" == item for item in problems))

    def test_boundary_values_pass(self):
        card = make_card(
            name="名" * 32,
            self="我" * 16,
            user="{MASTER_NAME}"[:24],
            language="语" * 80,
            refusal_style="拒" * 120,
            flourish=["口" * 80] * 5,
        )
        self.assertEqual(vc.validate_card(card), [])

    def test_register_wrong_type_list(self):
        problems = vc.validate_card(make_card(register=[]))
        self.assertIn("register must be a string", problems)

    def test_register_wrong_type_dict(self):
        problems = vc.validate_card(make_card(register={"a": 1}))
        self.assertIn("register must be a string", problems)

    def test_register_not_in_enum(self):
        problems = vc.validate_card(make_card(register="shouty"))
        self.assertTrue(any(item.startswith("register must be one of") for item in problems))

    def test_emoji_wrong_type_list(self):
        problems = vc.validate_card(make_card(emoji_policy=["sparse"]))
        self.assertIn("emoji_policy must be a string", problems)

    def test_flourish_is_string(self):
        problems = vc.validate_card(make_card(flourish="口头禅"))
        self.assertIn("flourish must be a list of strings", problems)

    def test_flourish_item_not_string(self):
        problems = vc.validate_card(make_card(flourish=[1]))
        self.assertTrue(any("flourish[0] must be a string" == item for item in problems))

    def test_flourish_too_many(self):
        problems = vc.validate_card(make_card(flourish=["a"] * 6))
        self.assertTrue(any("at most 5 items" in item for item in problems))

    def test_flourish_item_too_long(self):
        problems = vc.validate_card(make_card(flourish=["口" * 81]))
        self.assertTrue(any("flourish[0] exceeds 80 chars (81)" == item for item in problems))

    def test_blank_field(self):
        problems = vc.validate_card(make_card(self="   "))
        self.assertIn("self must not be blank", problems)

    def test_spec_mismatch(self):
        problems = vc.validate_card(make_card(spec="persona-voice-card"))
        self.assertTrue(any(item.startswith("spec must be") for item in problems))

    def test_spec_version_mismatch(self):
        problems = vc.validate_card(make_card(spec_version="2.0"))
        self.assertTrue(any(item.startswith("spec_version must be") for item in problems))

    def test_missing_field(self):
        card = make_card()
        card.pop("language")
        problems = vc.validate_card(card)
        self.assertIn("language must be a string", problems)


class LoadCardTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_load_ok(self):
        path = self.tmp / "card.json"
        path.write_text(json.dumps(make_card(), ensure_ascii=False), encoding="utf-8")
        card, problems = vc.load_card(path)
        self.assertEqual(problems, [])
        self.assertEqual(card["self"], "我")

    def test_load_bom(self):
        path = self.tmp / "bom.json"
        path.write_text(json.dumps(make_card(), ensure_ascii=False), encoding="utf-8-sig")
        card, problems = vc.load_card(path)
        self.assertEqual(problems, [])
        self.assertIsNotNone(card)

    def test_load_invalid_utf8(self):
        path = self.tmp / "broken.json"
        path.write_bytes(b"\xff\xfe\x00\x00")
        card, problems = vc.load_card(path)
        self.assertIsNone(card)
        self.assertTrue(any("UTF-8" in item for item in problems))

    def test_load_directory(self):
        card, problems = vc.load_card(self.tmp)
        self.assertIsNone(card)
        self.assertTrue(any("不是文件" in item for item in problems))

    def test_load_missing(self):
        card, problems = vc.load_card(self.tmp / "nope.json")
        self.assertIsNone(card)
        self.assertTrue(problems)

    def test_load_json_error(self):
        path = self.tmp / "bad.json"
        path.write_text("{ not json", encoding="utf-8")
        card, problems = vc.load_card(path)
        self.assertIsNone(card)
        self.assertTrue(any("JSON 无法解析" in item for item in problems))

    def test_load_bad_card_returns_problems(self):
        path = self.tmp / "bad_card.json"
        path.write_text(json.dumps(make_card(self="姐" * 17), ensure_ascii=False), encoding="utf-8")
        card, problems = vc.load_card(path)
        self.assertIsNone(card)
        self.assertTrue(any("self exceeds" in item for item in problems))

    def test_example_file_passes(self):
        card, problems = vc.load_card(ROOT / "examples" / "voice-card.json")
        self.assertEqual(problems, [])
        self.assertIsNotNone(card)


class RenderTests(unittest.TestCase):
    def test_render_contains_key_lines(self):
        prompt = vc.render_voice_prompt(make_card())
        self.assertIn("【说话方式——只管怎么说，不改变说什么】", prompt)
        self.assertIn("自称：我；称呼对方：{MASTER_NAME}", prompt)
        self.assertIn("语气：中性平实", prompt)
        self.assertIn("emoji：很少用", prompt)
        self.assertIn("口头禅（偶尔用，别每句都带）：「这个我看看」", prompt)
        self.assertIn(vc.FOOTER, prompt)

    def test_render_rejects_bad_card(self):
        with self.assertRaises(vc.VoiceCardError):
            vc.render_voice_prompt(make_card(flourish="不是列表"))

    def test_render_flattens_newlines(self):
        prompt = vc.render_voice_prompt(make_card(self="我\n喜欢说"))
        self.assertIn("自称：我 喜欢说", prompt)

    def test_render_truncates(self):
        prompt = vc.render_voice_prompt(make_card(language="语" * 80, flourish=["口" * 80] * 5), max_chars=60)
        self.assertLessEqual(len(prompt), 60)
        self.assertTrue(prompt.endswith("…"))

    def test_render_has_no_memory_mechanics(self):
        prompt = vc.render_voice_prompt(make_card())
        for word in ("记住这条", "情节记忆", "记忆条目", "写入记忆"):
            self.assertNotIn(word, prompt)

    def test_render_from_section_uses_defaults(self):
        prompt, problems = vc.render_from_section({})
        self.assertEqual(problems, [])
        self.assertIn("自称：我", prompt)

    def test_render_from_section_partial_override(self):
        prompt, problems = vc.render_from_section({"self": "本机", "register": "formal"})
        self.assertEqual(problems, [])
        self.assertIn("自称：本机", prompt)
        self.assertIn("语气：正式克制", prompt)

    def test_render_from_section_rejects_bad_type(self):
        prompt, problems = vc.render_from_section({"self": 42})
        self.assertEqual(prompt, "")
        self.assertTrue(any("self must be a string" in item for item in problems))


class SchemaAlignmentTests(unittest.TestCase):
    def test_schema_limits_match_validator(self):
        schema = json.loads((ROOT / "references" / "voice-card.schema.json").read_text(encoding="utf-8"))
        props = schema["properties"]
        for key, limit in vc.LIMITS.items():
            self.assertEqual(props[key]["maxLength"], limit, key)
        self.assertEqual(set(props["register"]["enum"]), set(vc.REGISTERS))
        self.assertEqual(set(props["emoji_policy"]["enum"]), set(vc.EMOJI_POLICIES))
        self.assertEqual(props["flourish"]["maxItems"], vc.MAX_FLOURISH)
        self.assertEqual(props["flourish"]["items"]["maxLength"], vc.MAX_FLOURISH_LEN)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(vc.ALLOWED_KEYS))


if __name__ == "__main__":
    unittest.main()
