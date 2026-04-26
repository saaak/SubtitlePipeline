"""
测试翻译解析中 | 前缀的清理
"""

import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.pipeline import parse_numbered_lines, strip_number_prefix


class TestPipeCleanup(unittest.TestCase):
    def test_strip_number_prefix_removes_leading_pipe(self):
        # 正常情况 - 半角竖线
        self.assertEqual(strip_number_prefix("11|翻译结果"), "翻译结果")

        # LLM 输出了双 |
        self.assertEqual(strip_number_prefix("11||翻译结果"), "翻译结果")

        # 全角竖线
        self.assertEqual(strip_number_prefix("113｜这感觉"), "这感觉")

        # 没有编号前缀，但有 | 开头
        self.assertEqual(strip_number_prefix("|翻译结果"), "翻译结果")

        # 多个 | 开头
        self.assertEqual(strip_number_prefix("|||翻译结果"), "翻译结果")

        # 点号格式
        self.assertEqual(strip_number_prefix("11. 翻译结果"), "翻译结果")

        # 冒号格式
        self.assertEqual(strip_number_prefix("11: 翻译结果"), "翻译结果")
        self.assertEqual(strip_number_prefix("11：翻译结果"), "翻译结果")

        # 裸编号（最后手段）
        self.assertEqual(strip_number_prefix("9怎么样？"), "怎么样？")

    def test_parse_numbered_lines_cleans_pipe_prefix(self):
        # LLM 输出了 编号||译文 格式
        raw_output = """
11||虽然想试着睡觉
12|那我来帮你吧
13||辛苦啦
"""
        result = parse_numbered_lines(raw_output, [11, 12, 13])
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "虽然想试着睡觉")
        self.assertEqual(result[1], "那我来帮你吧")
        self.assertEqual(result[2], "辛苦啦")

    def test_parse_numbered_lines_handles_mixed_formats(self):
        # 混合格式
        raw_output = """
1|正常格式
2||双竖线格式
3. 点号格式
4: 冒号格式
"""
        result = parse_numbered_lines(raw_output, [1, 2, 3, 4])
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "正常格式")
        self.assertEqual(result[1], "双竖线格式")
        self.assertEqual(result[2], "点号格式")
        self.assertEqual(result[3], "冒号格式")

    def test_parse_numbered_lines_handles_fullwidth_pipe(self):
        # 全角竖线格式
        raw_output = """
113｜这感觉…
114｜受不了了…
115｜还要……
"""
        result = parse_numbered_lines(raw_output, [113, 114, 115])
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "这感觉…")
        self.assertEqual(result[1], "受不了了…")
        self.assertEqual(result[2], "还要……")

    def test_parse_numbered_lines_handles_bare_numbers(self):
        # 裸数字格式（LLM 忘记加分隔符）
        raw_output = """
9怎么样？
10那我帮你吧
11诶？
"""
        result = parse_numbered_lines(raw_output, [9, 10, 11])
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "怎么样？")
        self.assertEqual(result[1], "那我帮你吧")
        self.assertEqual(result[2], "诶？")


if __name__ == "__main__":
    unittest.main()
