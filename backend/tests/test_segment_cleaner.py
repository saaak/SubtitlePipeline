"""
测试 segment_cleaner 模块
"""

import unittest
from app.segment_cleaner import (
    clean_segments,
    detect_repetition_loop,
    fix_timestamp_anomalies,
    merge_short_segments,
    remove_consecutive_duplicates,
    split_long_segment,
)


class TestSegmentCleaner(unittest.TestCase):
    def test_fix_timestamp_anomalies(self):
        # 修复 start >= end
        seg = {"start": 10.0, "end": 10.0, "text": "test"}
        fixed = fix_timestamp_anomalies(seg)
        self.assertEqual(fixed["start"], 10.0)
        self.assertEqual(fixed["end"], 10.1)

        # 四舍五入到 0.01s
        seg = {"start": 10.123456, "end": 20.987654, "text": "test"}
        fixed = fix_timestamp_anomalies(seg)
        self.assertEqual(fixed["start"], 10.12)
        self.assertEqual(fixed["end"], 20.99)

    def test_detect_repetition_loop(self):
        # 单字符重复
        self.assertTrue(detect_repetition_loop("るるるる"))
        self.assertTrue(detect_repetition_loop("ああああ"))
        self.assertFalse(detect_repetition_loop("るるる"))  # 只有3次

        # 双字符重复
        self.assertTrue(detect_repetition_loop("壊れた壊れた壊れた"))
        self.assertFalse(detect_repetition_loop("壊れた壊れた"))  # 只有2次

        # 正常文本
        self.assertFalse(detect_repetition_loop("これは普通の文章です"))

    def test_split_long_segment(self):
        # 超长片段应该被分割
        seg = {
            "start": 0.0,
            "end": 20.0,
            "text": "これは非常に長い文章です。" * 10,
        }
        result = split_long_segment(seg, max_duration=7.0)
        self.assertGreater(len(result), 1)

        # 每个片段都应该 <= 7秒
        for part in result:
            duration = part["end"] - part["start"]
            self.assertLessEqual(duration, 7.5)  # 允许一点误差

        # 短片段不应该被分割
        seg = {"start": 0.0, "end": 5.0, "text": "短い"}
        result = split_long_segment(seg, max_duration=7.0)
        self.assertEqual(len(result), 1)

    def test_remove_consecutive_duplicates(self):
        segments = [
            {"start": 0.0, "end": 1.0, "text": "同じ"},
            {"start": 1.0, "end": 2.0, "text": "同じ"},
            {"start": 2.0, "end": 3.0, "text": "違う"},
            {"start": 3.0, "end": 4.0, "text": "違う"},
        ]
        result = remove_consecutive_duplicates(segments)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["text"], "同じ")
        self.assertEqual(result[1]["text"], "違う")

    def test_merge_short_segments(self):
        # 模拟强制对齐器把「横山さん、具合は」切成单词的情况
        segments = [
            {"start": 65.57, "end": 70.61, "text": "ありがとうございます失礼."},  # 正常片段
            {"start": 71.79, "end": 71.89, "text": "し."},    # gap_prev=1.18s → 合并到前
            {"start": 76.30, "end": 76.54, "text": "ます."},  # gap_prev=4.41s, gap_next=2.84s → 合并到后
            {"start": 79.38, "end": 79.62, "text": "横山."},  # gap_prev=2.84s → 合并到前
            {"start": 85.02, "end": 85.10, "text": "さん."},  # gap_prev=5.4s, gap_next=2.03s → 合并到后
            {"start": 87.13, "end": 87.21, "text": "具合."},  # gap_prev=2.03s → 合并到前
            {"start": 90.05, "end": 95.38, "text": "どうですか."},  # 正常片段
        ]
        result = merge_short_segments(segments)

        # 5 个短片段应该被合并，最终只剩 4 个（2 正常 + 2 合并组）
        self.assertEqual(len(result), 4)
        # 第一个包含 し（合并到前一正常片段）
        self.assertIn("し", result[0]["text"])
        # 第二个包含 ます 和 横山（ます→后合并，横山→前合并）
        self.assertIn("ます", result[1]["text"])
        self.assertIn("横山", result[1]["text"])
        # 第三个包含 さん 和 具合（さん→后合并，具合→前合并）
        self.assertIn("さん", result[2]["text"])
        self.assertIn("具合", result[2]["text"])
        # 第四个是正常片段
        self.assertIn("どうですか", result[3]["text"])

    def test_merge_short_segments_preserves_isolated(self):
        # 两侧 gap 都 > 3s 的孤立片段不应被合并（如喘息声）
        segments = [
            {"start": 0.0,   "end": 1.0,   "text": "前段落."},
            {"start": 50.0,  "end": 50.1,  "text": "あ."},   # gap_prev=49s, gap_next=49.9s → 保留
            {"start": 100.0, "end": 101.0, "text": "后段落."},
        ]
        result = merge_short_segments(segments)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[1]["text"], "あ.")

    def test_clean_segments_integration(self):
        # 综合测试
        segments = [
            {"start": 0.0, "end": 0.0, "text": "るるるる"},  # 重复循环，应该被过滤
            {"start": 1.0, "end": 1.5, "text": "て"},  # 碎片，应该被合并
            {"start": 1.6, "end": 3.0, "text": "これは"},
            {"start": 10.0, "end": 30.0, "text": "超長片段。" * 20},  # 应该被分割
            {"start": 40.0, "end": 41.0, "text": "重複"},  # 连续重复
            {"start": 41.0, "end": 42.0, "text": "重複"},
        ]

        result = clean_segments(segments)

        # 重复循环被过滤
        self.assertNotIn("るるるる", [s["text"] for s in result])

        # 碎片被合并
        merged_text = "".join([s["text"] for s in result if s["start"] < 5.0])
        self.assertIn("て", merged_text)
        self.assertIn("これは", merged_text)

        # 超长片段被分割
        long_parts = [s for s in result if 10.0 <= s["start"] < 30.0]
        self.assertGreater(len(long_parts), 1)

        # 连续重复被移除
        duplicate_count = sum(1 for s in result if s["text"] == "重複")
        self.assertEqual(duplicate_count, 1)


if __name__ == "__main__":
    unittest.main()
