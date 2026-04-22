"""
ASR 片段后处理模块 - 保守策略
只修复明确可以改善的问题，不试图修复 ASR 模型本身的错误
"""

import re
from typing import Any


def fix_timestamp_anomalies(segment: dict[str, Any]) -> dict[str, Any]:
    """
    修复时间戳异常
    - start >= end: 设置最小持续时间 0.1s
    - 过多小数位: 四舍五入到 0.01s
    """
    start = round(float(segment["start"]), 2)
    end = round(float(segment["end"]), 2)

    if end <= start:
        end = start + 0.1

    return {**segment, "start": start, "end": end}


def detect_repetition_loop(text: str, min_repeat: int = 4) -> bool:
    """
    检测重复循环（るるるる / 壊れた壊れた）
    使用保守阈值避免误杀
    """
    # 单字符重复 >= 4次
    if re.search(r'(.)\1{' + str(min_repeat - 1) + r',}', text):
        return True

    # 双字符重复 >= 3次
    if re.search(r'(..)\1{2,}', text):
        return True

    # 三字符重复 >= 2次
    if re.search(r'(...)\1{2,}', text):
        return True

    return False


def split_long_segment(
    segment: dict[str, Any],
    max_duration: float = 7.0,
) -> list[dict[str, Any]]:
    """
    分割超长片段
    基于时长硬分割，尽量在标点处断开
    """
    duration = segment["end"] - segment["start"]
    if duration <= max_duration:
        return [segment]

    text = str(segment["text"])
    num_parts = int(duration / max_duration) + 1

    # 尝试在标点处分割
    punctuation = r'[。！？.!?、，,]'
    split_points = [m.end() for m in re.finditer(punctuation, text)]

    if not split_points:
        # 没有标点，按字符数均分
        chars_per_part = len(text) // num_parts
        split_points = [i * chars_per_part for i in range(1, num_parts)]

    # 选择最接近理想分割点的标点位置
    ideal_points = [len(text) * i // num_parts for i in range(1, num_parts)]
    selected_points = []
    for ideal in ideal_points:
        closest = min(split_points, key=lambda x: abs(x - ideal), default=ideal)
        selected_points.append(closest)
        split_points = [p for p in split_points if p > closest]

    # 生成分割后的片段，时间按字符比例分配
    result = []
    start_time = segment["start"]
    time_per_char = duration / max(len(text), 1)

    boundaries = [0] + selected_points + [len(text)]
    for i in range(len(boundaries) - 1):
        part_text = text[boundaries[i]:boundaries[i + 1]].strip()
        if not part_text:
            continue

        part_start = start_time + boundaries[i] * time_per_char
        part_end = start_time + boundaries[i + 1] * time_per_char
        # 确保每个分片不超过 max_duration
        if part_end - part_start > max_duration:
            part_end = part_start + max_duration

        result.append({
            "start": round(part_start, 2),
            "end": round(part_end, 2),
            "text": part_text,
        })

    return result if result else [segment]


def remove_consecutive_duplicates(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    移除连续重复的句子
    """
    if not segments:
        return []

    result = [segments[0]]
    for seg in segments[1:]:
        if seg["text"] != result[-1]["text"]:
            result.append(seg)

    return result


def clean_segments(
    segments: list[dict[str, Any]],
    max_duration: float = 7.0,
    max_gap: float = 0.5,
) -> list[dict[str, Any]]:
    """
    清理 ASR 片段 - 保守策略

    处理流程：
    1. 修复时间戳异常
    2. 过滤重复循环
    3. 合并碎片
    4. 分割超长片段
    5. 移除连续重复
    """
    if not segments:
        return []

    # Step 1: 修复时间戳
    segments = [fix_timestamp_anomalies(seg) for seg in segments]

    # Step 2: 过滤重复循环
    filtered = []
    for seg in segments:
        text = str(seg["text"]).strip()
        if not text:
            continue

        if detect_repetition_loop(text):
            continue

        filtered.append(seg)

    # Step 3: 合并碎片（优先合并到前一个片段）
    merged = []
    for i, seg in enumerate(filtered):
        duration = seg["end"] - seg["start"]
        text = str(seg["text"]).strip()

        # 判断是否为碎片
        is_fragment = duration < 1.0 and len(text) < 3

        if is_fragment and merged:
            # 检查与前一个片段的间隔
            prev_seg = merged[-1]
            gap = seg["start"] - prev_seg["end"]

            if gap < max_gap:
                # 合并到前一个片段
                prev_seg["text"] = str(prev_seg["text"]) + str(seg["text"])
                prev_seg["end"] = seg["end"]
                continue

        merged.append(seg)

    # Step 4: 分割超长片段
    split_result = []
    for seg in merged:
        split_result.extend(split_long_segment(seg, max_duration))

    # Step 5: 移除连续重复
    result = remove_consecutive_duplicates(split_result)

    return result
