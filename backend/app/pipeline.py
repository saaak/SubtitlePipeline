from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.segment_cleaner import clean_segments

logger = logging.getLogger(__name__)

CHUNK_SIZE = 15
CONTEXT_SIZE = 5
MAX_CHUNK_WORKERS = 1
MAX_CHUNK_RETRIES = 5
MAX_PARTIAL_RETRIES = 3

TRANSLATION_PRESETS = {
    "general": "You are a professional subtitle translator. Keep the translation natural, accurate, concise, and easy to read on screen.",
    "movie": "You are a professional film and TV subtitle translator. Keep dialogue natural and conversational, preserve character voice, and localize idioms smoothly.",
    "documentary": "You are a documentary subtitle translator. Keep the tone clear, informative, and slightly formal. Preserve important terms accurately.",
    "anime": "You are an anime subtitle translator. Preserve character tone, emotional rhythm, and genre-specific expressions while keeping subtitles natural.",
    "tech_talk": "You are a technical talk subtitle translator. Keep terminology precise, preserve key English technical terms when appropriate, and maintain logical clarity.",
    "variety_show": "You are a variety show subtitle translator. Keep the tone lively, witty, and audience-friendly while preserving humor and timing.",
    "news": "You are a news subtitle translator. Keep the tone formal, objective, and consistent with standard naming conventions for people and places.",
}

FORMAT_INSTRUCTION = (
    "Translate the numbered lines into {target_language}. "
    'Return exactly one line per item using the format "编号|译文". '
    "Only translate the [翻译] section when it exists. "
    "The [上文] and [下文] sections are context only and must not be translated. "
    "If no [翻译] section exists, translate all numbered lines. "
    "Keep the same ids and line count as the content to translate. "
    "Do not output markdown, JSON, code fences, explanations, or any extra text."
)


class PipelineError(RuntimeError):
    pass


class TranslationRateLimitError(PipelineError):
    pass


class CancellationRequested(RuntimeError):
    pass


@dataclass
class TaskContext:
    task_id: int
    file_path: str
    config_snapshot: dict[str, Any]
    work_dir: Path
    intermediates_dir: Path | None = None
    using_fallback_intermediates: bool = False


from .asr import (
    ASRProvider,
    ASRProviderFactory,
    AnimeWhisperProvider,
    FasterWhisperProvider,
    QwenASRProvider,
    WhisperModelCache,
    WhisperXProvider,
    run_asr,
)
from .asr.aligners import QwenForcedAligner, WhisperXAligner
from .asr.helpers import get_models_root
from .llm import LLMError, LLMMessage, LLMRateLimitError, create_llm_client
from .model_manager import DEFAULT_PROVIDER, infer_provider_from_model_name, normalize_provider_name

STAGE_ALIAS_MAP = {
    "asr": "run_asr",
}
STAGE_PROGRESS = {
    "extract_audio": 10,
    "run_asr": 35,
    "align_segments": 45,
    "text_process": 55,
    "translate": 60,
    "subtitle_render": 95,
    "output_finalize": 100,
    "mux": 100,
}


@dataclass(frozen=True)
class ChunkLine:
    index: int
    text: str


@dataclass(frozen=True)
class TranslationChunk:
    start_index: int
    context_before: list[ChunkLine]
    main_segments: list[ChunkLine]
    context_after: list[ChunkLine]
    use_sections: bool


class TranslationProvider:
    def translate_batch(self, texts: list[str], target_language: str) -> list[str]:
        raise NotImplementedError


def normalize_stage_name(stage: str) -> str:
    return STAGE_ALIAS_MAP.get(str(stage), str(stage))


def build_chunks(
    segments: list[dict[str, Any]],
    chunk_size: int = CHUNK_SIZE,
    context_size: int = CONTEXT_SIZE,
) -> list[TranslationChunk]:
    if not segments:
        return []
    total = len(segments)
    use_sections = total > chunk_size
    chunks: list[TranslationChunk] = []
    for start in range(0, total, chunk_size):
        end = min(start + chunk_size, total)
        context_before = [
            ChunkLine(index=index, text=str(segments[index]["text"]))
            for index in range(max(0, start - context_size), start)
        ]
        main_segments = [ChunkLine(index=index, text=str(segments[index]["text"])) for index in range(start, end)]
        context_after = [
            ChunkLine(index=index, text=str(segments[index]["text"]))
            for index in range(end, min(total, end + context_size))
        ]
        chunks.append(
            TranslationChunk(
                start_index=start,
                context_before=context_before,
                main_segments=main_segments,
                context_after=context_after,
                use_sections=use_sections,
            )
        )
    return chunks


def build_chunk_user_message(chunk: TranslationChunk) -> str:
    def format_lines(lines: list[ChunkLine]) -> str:
        return "\n".join(f"{line.index}|{line.text}" for line in lines)

    if not chunk.use_sections:
        return format_lines(chunk.main_segments)
    parts: list[str] = []
    if chunk.context_before:
        parts.extend(["[上文]", format_lines(chunk.context_before)])
    parts.extend(["[翻译]", format_lines(chunk.main_segments)])
    if chunk.context_after:
        parts.extend(["[下文]", format_lines(chunk.context_after)])
    return "\n\n".join(parts)


def strip_code_fence(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def strip_number_prefix(line: str) -> str:
    """Strip number prefix from translation line.

    Handles formats:
    - 编号|译文 (half-width pipe)
    - 编号｜译文 (full-width pipe)
    - 编号||译文 (double pipe)
    - 编号. 译文
    - 编号: 译文 / 编号：译文
    - 编号译文 (bare number, last resort)
    - |译文 (bare leading pipe, no number)
    """
    # Try numbered formats with delimiters first
    stripped = re.sub(r"^\s*\d+[|｜.:：]+\s*", "", line, count=1)
    if stripped != line:
        # Also strip any remaining leading pipes
        return stripped.lstrip("|｜").strip()

    # Bare leading pipe(s) with no number prefix
    if line.strip().startswith("|") or line.strip().startswith("｜"):
        return line.strip().lstrip("|｜").strip()

    # Last resort: bare number at start (e.g., "9怎么样？")
    stripped = re.sub(r"^\s*\d+", "", line, count=1)
    return stripped.strip()


@dataclass
class ParseResult:
    """Result of parsing numbered translation lines.

    ``matched`` maps expected line index -> translated text for all lines
    that were successfully parsed in order.  ``first_failed_position``
    is the 0-based position in ``expected_ids`` where the first gap or
    mismatch occurred (``None`` means everything matched).
    """
    matched: dict[int, str]
    first_failed_position: int | None


def parse_numbered_lines_ordered(
    raw_output: str,
    expected_ids: list[int],
) -> ParseResult:
    """Parse ``编号|译文`` lines and identify the first failure point.

    Lines are scanned in document order.  The parser collects every valid
    match whose index belongs to ``expected_ids``.  After collecting, we
    walk ``expected_ids`` sequentially; the first id that is missing marks
    the failure boundary – every id *before* it is considered valid, every
    id from that point on is considered failed (even if some later ids
    happened to match) so that the caller can retry a contiguous suffix.
    """
    matches: dict[int, str] = {}
    expected = set(expected_ids)
    for line in strip_code_fence(raw_output).splitlines():
        normalized = line.strip()
        if not normalized:
            continue
        # Try to match "编号|译文" or "编号｜译文" format (half-width or full-width pipe)
        if "|" in normalized or "｜" in normalized:
            # Replace full-width pipe with half-width for uniform processing
            normalized_pipe = normalized.replace("｜", "|")
            prefix, value = normalized_pipe.split("|", 1)
            if prefix.strip().isdigit():
                index = int(prefix.strip())
                if index in expected and index not in matches:
                    cleaned_value = value.strip().lstrip("|｜").strip()
                    matches[index] = cleaned_value
                continue
        # Also accept "编号. 译文" or "编号: 译文" as fallback
        m = re.match(r"^\s*(\d+)\s*[.:：]\s*(.+)$", normalized)
        if m:
            index = int(m.group(1))
            if index in expected and index not in matches:
                matches[index] = m.group(2).strip()
            continue
        # Last resort: bare number prefix "编号译文" (no delimiter)
        m = re.match(r"^\s*(\d+)(\S.*)$", normalized)
        if m:
            index = int(m.group(1))
            if index in expected and index not in matches:
                matches[index] = m.group(2).strip()
            continue
        # Last resort: bare number prefix "编号译文" (LLM forgot the separator)
        m = re.match(r"^\s*(\d+)(\S.*)$", normalized)
        if m:
            index = int(m.group(1))
            if index in expected and index not in matches:
                matches[index] = m.group(2).strip()

    # Walk expected_ids to find the first gap
    first_failed: int | None = None
    for position, eid in enumerate(expected_ids):
        if eid not in matches:
            first_failed = position
            break

    if first_failed is not None:
        # Only keep the contiguous prefix (discard any sporadic matches after the gap)
        valid_ids = set(expected_ids[:first_failed])
        matches = {k: v for k, v in matches.items() if k in valid_ids}

    return ParseResult(matched=matches, first_failed_position=first_failed)


def parse_numbered_lines(
    raw_output: str,
    expected_ids: list[int],
    source_texts: list[str] | None = None,
) -> list[str] | None:
    result = parse_numbered_lines_ordered(raw_output, expected_ids)
    if result.first_failed_position is None:
        return [result.matched[eid] for eid in expected_ids]
    if source_texts is not None and expected_ids:
        matched_ratio = len(result.matched) / len(expected_ids)
        if matched_ratio >= 0.8:
            missing = [eid for eid in expected_ids if eid not in result.matched]
            logger.warning("分块翻译部分匹配，缺失编号将回退原文: %s", missing)
            return [result.matched.get(eid, source_texts[pos]) for pos, eid in enumerate(expected_ids)]
    return None


def parse_chunk_output(
    raw_output: str,
    expected_ids: list[int],
    source_texts: list[str],
    json_array_parser=None,
) -> list[str]:
    numbered = parse_numbered_lines(raw_output, expected_ids, source_texts)
    if numbered is not None:
        return numbered
    if json_array_parser is not None:
        try:
            parsed = json_array_parser(raw_output)
        except PipelineError:
            parsed = None
        if isinstance(parsed, list) and len(parsed) == len(expected_ids):
            return [str(item).strip() for item in parsed]
    lines = [strip_number_prefix(line) for line in strip_code_fence(raw_output).splitlines() if line.strip()]
    if len(lines) == len(expected_ids):
        return lines
    # Last resort: if lines are close (within 20%), pad or truncate
    if lines and abs(len(lines) - len(expected_ids)) <= max(1, len(expected_ids) // 5):
        logger.warning("翻译结果行数 %d != 期望 %d，尝试对齐", len(lines), len(expected_ids))
        if len(lines) > len(expected_ids):
            return lines[:len(expected_ids)]
        return lines + [source_texts[i] for i in range(len(lines), len(expected_ids))]
    raise PipelineError(
        f"翻译返回结果无法解析 (得到 {len(lines)} 行, 期望 {len(expected_ids)} 行)"
    )


class ChunkedTranslator:
    def __init__(
        self,
        provider: TranslationProvider,
        content_type: str,
        custom_prompt: str,
        on_chunk_complete=None,
    ):
        self.provider = provider
        self.content_type = content_type
        self.custom_prompt = custom_prompt
        self.on_chunk_complete = on_chunk_complete
        self.pause_event = threading.Event()
        self.pause_event.set()

    def translate_language(self, segments: list[dict[str, Any]], target_language: str) -> list[str]:
        chunks = build_chunks(segments, CHUNK_SIZE, CONTEXT_SIZE)
        if not chunks:
            return []
        merged: list[str | None] = [None] * len(segments)
        pending = list(chunks)
        attempts = {chunk.start_index: 0 for chunk in chunks}
        max_workers = MAX_CHUNK_WORKERS
        while pending:
            current_batch = pending[:max_workers]
            pending = pending[max_workers:]
            rate_limited: list[TranslationChunk] = []
            max_wait = 0
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(self._translate_chunk, chunk, target_language): chunk
                    for chunk in current_batch
                }
                for future in as_completed(futures):
                    chunk = futures[future]
                    try:
                        translated_lines = future.result()
                    except TranslationRateLimitError as exc:
                        attempts[chunk.start_index] += 1
                        if attempts[chunk.start_index] > MAX_CHUNK_RETRIES:
                            raise PipelineError(f"分块翻译多次触发限流: {exc}") from exc
                        rate_limited.append(chunk)
                        max_wait = max(max_wait, 2 ** (attempts[chunk.start_index] - 1))
                    except Exception as exc:
                        raise PipelineError(str(exc)) from exc
                    else:
                        for position, line in enumerate(chunk.main_segments):
                            merged[line.index] = translated_lines[position]
                        if self.on_chunk_complete is not None:
                            self.on_chunk_complete()
            if rate_limited:
                self.pause_event.clear()
                time.sleep(max_wait)
                self.pause_event.set()
                if max_workers > 1:
                    max_workers -= 1
                pending = rate_limited + pending
        if any(item is None for item in merged):
            raise PipelineError("分块翻译结果不完整")
        return [item or "" for item in merged]

    def _translate_chunk(self, chunk: TranslationChunk, target_language: str) -> list[str]:
        self.pause_event.wait()
        if isinstance(self.provider, LLMTranslationProvider):
            return self.provider.translate_chunk(chunk, target_language, self.content_type, self.custom_prompt)
        return self.provider.translate_batch([line.text for line in chunk.main_segments], target_language)


class LLMTranslationProvider(TranslationProvider):
    def __init__(self, llm_type: str, api_base_url: str, api_key: str, model: str, timeout_seconds: int):
        self.llm_type = llm_type
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.client = create_llm_client(
            llm_type=self.llm_type,
            api_base_url=self.api_base_url,
            api_key=self.api_key,
            model=self.model,
            timeout_seconds=self.timeout_seconds,
        )

    def translate_batch(self, texts: list[str], target_language: str) -> list[str]:
        chunk = TranslationChunk(
            start_index=0,
            context_before=[],
            main_segments=[ChunkLine(index=index, text=text) for index, text in enumerate(texts)],
            context_after=[],
            use_sections=False,
        )
        return self.translate_chunk(chunk, target_language, "general", "")

    def translate_chunk(
        self,
        chunk: TranslationChunk,
        target_language: str,
        content_type: str,
        custom_prompt: str,
    ) -> list[str]:
        texts = [line.text for line in chunk.main_segments]
        if not texts:
            return []
        prompt = self._build_prompt(target_language, content_type, custom_prompt)

        # Partial-retry loop: keep valid prefix, only retry the tail
        results: list[str | None] = [None] * len(texts)
        remaining_segments = list(chunk.main_segments)
        remaining_context_before = list(chunk.context_before)

        for attempt in range(MAX_PARTIAL_RETRIES + 1):
            if not remaining_segments:
                break

            retry_chunk = TranslationChunk(
                start_index=remaining_segments[0].index,
                context_before=remaining_context_before,
                main_segments=remaining_segments,
                context_after=chunk.context_after,
                use_sections=chunk.use_sections or len(remaining_context_before) > 0,
            )
            content = self._request_translation(prompt, build_chunk_user_message(retry_chunk))
            remaining_ids = [line.index for line in remaining_segments]
            remaining_texts = [line.text for line in remaining_segments]

            # Try full parse first
            try:
                parsed = parse_chunk_output(
                    content, remaining_ids, remaining_texts, self._parse_json_array_content,
                )
                # Full success — fill in all remaining results
                for seg, translated in zip(remaining_segments, parsed):
                    pos = next(i for i, s in enumerate(chunk.main_segments) if s.index == seg.index)
                    results[pos] = translated
                remaining_segments = []
                break
            except PipelineError:
                pass

            # Full parse failed — try ordered partial parse
            pr = parse_numbered_lines_ordered(content, remaining_ids)
            if pr.matched:
                for seg_idx, translated in pr.matched.items():
                    pos = next(i for i, s in enumerate(chunk.main_segments) if s.index == seg_idx)
                    results[pos] = translated

                if pr.first_failed_position is not None:
                    # Keep matched prefix, retry from the failure point
                    kept = remaining_segments[:pr.first_failed_position]
                    remaining_context_before = kept[-CONTEXT_SIZE:] if kept else remaining_context_before
                    remaining_segments = remaining_segments[pr.first_failed_position:]
                    logger.warning(
                        "分块部分翻译成功 %d/%d，重试剩余 %d 条 (第 %d 次)",
                        len(pr.matched), len(remaining_ids),
                        len(remaining_segments), attempt + 1,
                    )
                    continue
                else:
                    remaining_segments = []
                    break

            # Nothing matched at all on this attempt
            if attempt < MAX_PARTIAL_RETRIES:
                logger.warning(
                    "分块翻译完全失败，重试整块 (第 %d 次)", attempt + 1,
                )
                continue
            else:
                raise PipelineError(
                    f"分块翻译经过 {MAX_PARTIAL_RETRIES + 1} 次尝试仍无法解析"
                )

        # Fill any remaining None with source text as last resort
        final: list[str] = []
        for i, val in enumerate(results):
            if val is None:
                logger.warning("翻译缺失行 %d，回退为原文", chunk.main_segments[i].index)
                final.append(texts[i])
            else:
                final.append(val)
        return final

    def _resolve_base_url(self) -> str:
        return self.client.resolved_base_url()

    def _request_translation(self, prompt: str, user_content: str) -> str:
        try:
            return self.client.complete(
                [
                    LLMMessage(role="system", content=prompt),
                    LLMMessage(role="user", content=user_content),
                ]
            )
        except LLMRateLimitError as exc:
            raise TranslationRateLimitError(str(exc)) from exc
        except LLMError as exc:
            raise PipelineError(str(exc)) from exc

    def _build_prompt(self, target_language: str, content_type: str = "general", custom_prompt: str = "") -> str:
        style_prompt = custom_prompt.strip() or TRANSLATION_PRESETS.get(content_type, TRANSLATION_PRESETS["general"])
        return f"{style_prompt}\n\n{FORMAT_INSTRUCTION.format(target_language=target_language)}"

    def _parse_json_array_content(self, content: str) -> list[Any]:
        candidates = [
            content.strip(),
            strip_code_fence(content),
            self._extract_json_array(content),
        ]
        seen: set[str] = set()
        for candidate in candidates:
            normalized = candidate.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            try:
                parsed = json.loads(normalized)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, list):
                return parsed
        raise PipelineError(f"真实翻译 provider 未返回 JSON 数组，原始响应: {content[:200]}")

    def _strip_code_fence(self, content: str) -> str:
        return strip_code_fence(content)

    def _extract_json_array(self, content: str) -> str:
        start = content.find("[")
        end = content.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return ""
        return content[start : end + 1]


def debug_translation_request(
    llm_type: str,
    api_base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: int,
    target_language: str,
    texts: list[str],
    content_type: str = "general",
    custom_prompt: str = "",
) -> dict[str, Any]:
    provider = LLMTranslationProvider(
        llm_type=llm_type,
        api_base_url=api_base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout_seconds,
    )
    chunk = TranslationChunk(
        start_index=0,
        context_before=[],
        main_segments=[ChunkLine(index=index, text=text) for index, text in enumerate(texts)],
        context_after=[],
        use_sections=False,
    )
    prompt = provider._build_prompt(target_language, content_type, custom_prompt)
    content = provider._request_translation(prompt, build_chunk_user_message(chunk))
    parsed = parse_chunk_output(content, [line.index for line in chunk.main_segments], texts, provider._parse_json_array_content)
    return {
        "llm_type": llm_type,
        "base_url": provider._resolve_base_url(),
        "model": model,
        "target_language": target_language,
        "texts": texts,
        "raw_content": content,
        "parsed": [str(item).strip() for item in parsed],
    }


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def get_intermediates_dir(source_path: Path) -> Path:
    return source_path.parent / ".subpipeline" / source_path.stem


def _intermediate_filenames() -> tuple[str, ...]:
    return ("audio.wav", "asr_result.json", "aligned_segments.json", "processed_segments.json", "translations.json")


def ensure_intermediates_dir(context: TaskContext) -> Path:
    if context.intermediates_dir is not None:
        return context.intermediates_dir
    target_dir = get_intermediates_dir(Path(context.file_path))
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        context.intermediates_dir = target_dir
        context.using_fallback_intermediates = False
    except OSError:
        context.work_dir.mkdir(parents=True, exist_ok=True)
        context.intermediates_dir = context.work_dir
        context.using_fallback_intermediates = True
    return context.intermediates_dir


def resolve_intermediates_dir(context: TaskContext) -> Path:
    if context.intermediates_dir is not None:
        return context.intermediates_dir
    target_dir = get_intermediates_dir(Path(context.file_path))
    if target_dir.exists():
        context.intermediates_dir = target_dir
        context.using_fallback_intermediates = False
        return target_dir
    context.intermediates_dir = context.work_dir
    context.using_fallback_intermediates = True
    return context.work_dir


def get_intermediate_path(context: TaskContext, filename: str, create: bool = False) -> Path:
    base_dir = ensure_intermediates_dir(context) if create else resolve_intermediates_dir(context)
    return base_dir / filename


def cleanup_intermediates(source_path: Path) -> None:
    shutil.rmtree(get_intermediates_dir(source_path), ignore_errors=True)


def cleanup_work_dir_intermediates(work_dir: Path) -> None:
    for filename in _intermediate_filenames():
        path = work_dir / filename
        if path.exists():
            path.unlink()


def _write_json(path: Path, payload: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_ffmpeg(command: list[str], timeout_message: str, failure_message: str) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=7200)
    except subprocess.TimeoutExpired as exc:
        raise PipelineError(timeout_message) from exc
    if result.returncode != 0:
        raise PipelineError(result.stderr.strip() or failure_message)
    return result


def extract_audio(context: TaskContext) -> Path:
    whisper_config = context.config_snapshot["whisper"]
    source_path = Path(context.file_path)
    audio_format = str(whisper_config["audio_format"]).strip().lower()
    audio_path = get_intermediate_path(context, f"audio.{audio_format}", create=True)
    ensure_parent(audio_path)
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise PipelineError("ffmpeg 未安装，无法执行真实音频提取")
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(whisper_config["sample_rate"]),
        str(audio_path),
    ]
    _run_ffmpeg(command, "音频提取超时，FFmpeg 执行超过 7200 秒", "ffmpeg 执行失败")
    return audio_path


def save_asr_result(context: TaskContext, payload: dict[str, Any]) -> Path:
    path = get_intermediate_path(context, "asr_result.json", create=True)
    _write_json(path, payload)
    return path


def load_asr_result(context: TaskContext) -> dict[str, Any]:
    path = get_intermediate_path(context, "asr_result.json")
    if not path.exists():
        raise PipelineError("缺少 asr_result.json，无法继续执行")
    payload = _read_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("segments"), list):
        raise PipelineError("asr_result.json 内容无效，无法继续执行")
    return payload


def save_aligned_segments(context: TaskContext, payload: list[dict[str, Any]]) -> Path:
    path = get_intermediate_path(context, "aligned_segments.json", create=True)
    _write_json(path, payload)
    return path


def load_aligned_segments(context: TaskContext) -> list[dict[str, Any]]:
    path = get_intermediate_path(context, "aligned_segments.json")
    if not path.exists():
        raise PipelineError("缺少 aligned_segments.json，无法继续执行")
    payload = _read_json(path)
    if not isinstance(payload, list):
        raise PipelineError("aligned_segments.json 内容无效，无法继续执行")
    return payload


def _resolve_align_provider(config_snapshot: dict[str, Any]) -> str:
    whisper_config = config_snapshot.get("whisper", {})
    return str(whisper_config.get("align_provider", whisper_config.get("align_method", "auto"))).strip().lower() or "auto"


def _has_qwen_forced_aligner_model() -> bool:
    model_dir = get_models_root() / "qwen3-forced-aligner"
    return model_dir.exists() and any(model_dir.iterdir())


def align_segments(
    context: TaskContext,
    asr_result: dict[str, Any],
    audio_path: Path,
    model_cache: WhisperModelCache | None = None,
    database: Any = None,
) -> list[dict[str, Any]]:
    original_segments = asr_result.get("segments", [])
    normalized_segments = [
        {
            "start": float(segment.get("start", 0.0)),
            "end": float(segment.get("end", segment.get("start", 0.0))),
            "text": str(segment.get("text", "")).strip(),
        }
        for segment in original_segments
    ]
    align_provider = _resolve_align_provider(context.config_snapshot)
    asr_provider = normalize_provider_name(
        asr_result.get("provider")
        or context.config_snapshot["whisper"].get("provider")
        or infer_provider_from_model_name(str(context.config_snapshot["whisper"].get("model_name", "")), DEFAULT_PROVIDER)
    )
    language = str(asr_result.get("language", "")).strip() or None

    if align_provider == "none":
        if database is not None:
            database.log(context.task_id, "align_segments", "INFO", "已跳过时间轴对齐，直接使用 ASR 时间戳")
        return normalized_segments

    selected_provider = align_provider
    if align_provider == "auto":
        if asr_provider == "whisperx":
            selected_provider = "whisperx"
        elif _has_qwen_forced_aligner_model():
            selected_provider = "qwen-forced"
        else:
            if database is not None:
                database.log(
                    context.task_id,
                    "align_segments",
                    "WARNING",
                    "建议下载 qwen3-forced-aligner 以提升时间戳精度，当前使用内置 timestamps 继续",
                )
            return normalized_segments

    if selected_provider == "whisperx":
        return WhisperXAligner(model_cache).align(normalized_segments, audio_path, language, context.config_snapshot["whisper"]["device"])
    if selected_provider == "qwen-forced":
        return QwenForcedAligner().align(normalized_segments, audio_path, language, context.config_snapshot["whisper"]["device"])
    raise PipelineError(f"不支持的对齐 Provider: {selected_provider}")


def process_text_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Step 1: Clean segments (remove repetition loops, merge fragments, split long segments, etc.)
    cleaned = clean_segments(segments)

    # Step 2: Normalize whitespace and add trailing punctuation
    processed: list[dict[str, Any]] = []
    for segment in cleaned:
        text = " ".join(str(segment["text"]).split())
        if text and text[-1] not in ".!?。！？":
            text = f"{text}."
        processed.append(
            {
                "start": float(segment["start"]),
                "end": float(segment["end"]),
                "text": text,
            }
        )
    return processed


def save_processed_segments(context: TaskContext, payload: list[dict[str, Any]]) -> Path:
    path = get_intermediate_path(context, "processed_segments.json", create=True)
    _write_json(path, payload)
    return path


def load_processed_segments(context: TaskContext) -> list[dict[str, Any]]:
    path = get_intermediate_path(context, "processed_segments.json")
    if not path.exists():
        raise PipelineError("缺少 processed_segments.json，无法继续执行")
    payload = _read_json(path)
    if not isinstance(payload, list):
        raise PipelineError("processed_segments.json 内容无效，无法继续执行")
    return payload


def get_translation_provider(config_snapshot: dict[str, Any]) -> TranslationProvider:
    translation = config_snapshot["translation"]
    return LLMTranslationProvider(
        llm_type=str(translation.get("llm_type", "openai-compatible")).strip(),
        api_base_url=str(translation["api_base_url"]).strip(),
        api_key=str(translation["api_key"]).strip(),
        model=str(translation["model"]).strip(),
        timeout_seconds=int(translation["timeout_seconds"]),
    )


def translate_segments(
    context: TaskContext,
    segments: list[dict[str, Any]],
    progress_callback=None,
) -> dict[str, list[str]]:
    translation_config = context.config_snapshot["translation"]
    if not translation_config["enabled"]:
        return {}
    provider = get_translation_provider(context.config_snapshot)
    translations: dict[str, list[str]] = {}
    max_retries = max(int(translation_config["max_retries"]), 1)
    target_languages = [str(language) for language in translation_config["target_languages"]]
    chunks = build_chunks(segments, CHUNK_SIZE, CONTEXT_SIZE)
    total_chunks = len(chunks) * len(target_languages)
    completed_chunks = 0
    progress_lock = threading.Lock()
    content_type = str(translation_config.get("content_type", "general") or "general")
    custom_prompt = str(translation_config.get("custom_prompt", "") or "")

    def on_chunk_complete() -> None:
        nonlocal completed_chunks
        if progress_callback is None or total_chunks <= 0:
            return
        with progress_lock:
            completed_chunks += 1
            progress_callback(completed_chunks, total_chunks)

    translator = ChunkedTranslator(provider, content_type, custom_prompt, on_chunk_complete)
    for language in target_languages:
        last_error: Exception | None = None
        for _ in range(max_retries):
            try:
                translations[language] = translator.translate_language(segments, language)
                last_error = None
                break
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise PipelineError(str(last_error))
    return translations


def save_translations(context: TaskContext, payload: dict[str, list[str]]) -> Path:
    path = get_intermediate_path(context, "translations.json", create=True)
    _write_json(path, payload)
    return path


def load_translations(context: TaskContext) -> dict[str, list[str]]:
    path = get_intermediate_path(context, "translations.json")
    if not path.exists():
        raise PipelineError("缺少 translations.json，无法继续执行")
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise PipelineError("translations.json 内容无效，无法继续执行")
    normalized: dict[str, list[str]] = {}
    for language, values in payload.items():
        if not isinstance(values, list):
            raise PipelineError("translations.json 内容无效，无法继续执行")
        normalized[str(language)] = [str(value) for value in values]
    return normalized


def format_srt_time(seconds: float) -> str:
    total_milliseconds = int(round(seconds * 1000))
    milliseconds = total_milliseconds % 1000
    total_seconds = total_milliseconds // 1000
    minutes, seconds_value = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds_value:02},{milliseconds:03}"


def get_subtitle_target_dir(context: TaskContext) -> Path:
    file_config = context.config_snapshot["file"]
    source_path = Path(context.file_path)
    output_to_source_dir = bool(file_config.get("output_to_source_dir", True))
    if output_to_source_dir:
        return source_path.parent
    return Path(os.environ.get("SUBPIPELINE_OUTPUT_DIR", "/output"))


def build_subtitle_tracks(context: TaskContext, translations: dict[str, list[str]]) -> list[dict[str, Any]]:
    subtitle_config = context.config_snapshot["subtitle"]
    source_path = Path(context.file_path)
    target_dir = get_subtitle_target_dir(context)
    template = str(subtitle_config["filename_template"])
    tracks: list[dict[str, Any]] = []
    if subtitle_config["bilingual"] and translations and subtitle_config["bilingual_mode"] == "merge":
        language = next(iter(translations))
        tracks.append(
            {
                "language": language,
                "path": target_dir / template.format(stem=source_path.stem, lang="bilingual"),
                "translated_lines": translations.get(language),
            }
        )
        return tracks
    if not translations:
        tracks.append(
            {
                "language": str(subtitle_config.get("source_language", "source")),
                "path": target_dir / template.format(stem=source_path.stem, lang="source"),
                "translated_lines": None,
            }
        )
        return tracks
    for language, translated_lines in translations.items():
        if subtitle_config["bilingual_mode"] == "merge":
            tracks.append(
                {
                    "language": language,
                    "path": target_dir / template.format(stem=source_path.stem, lang=language),
                    "translated_lines": translated_lines,
                }
            )
        else:
            # separate mode: only target language, replace source text
            tracks.append(
                {
                    "language": language,
                    "path": target_dir / template.format(stem=source_path.stem, lang=language),
                    "translated_lines": translated_lines,
                    "replace_source": True,
                }
            )
    return tracks


def render_srt(
    context: TaskContext,
    segments: list[dict[str, Any]],
    translations: dict[str, list[str]],
) -> list[str]:
    target_dir = get_subtitle_target_dir(context)
    target_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    for track in build_subtitle_tracks(context, translations):
        output_path = Path(track["path"])
        content = build_srt_content(segments, track["translated_lines"], replace_source=track.get("replace_source", False))
        ensure_parent(output_path)
        output_path.write_text(content, encoding="utf-8")
        outputs.append(str(output_path))
    return outputs


def build_srt_content(segments: list[dict[str, Any]], translated_lines: list[str] | None, replace_source: bool = False) -> str:
    blocks: list[str] = []
    for index, segment in enumerate(segments, start=1):
        if replace_source and translated_lines:
            lines = [translated_lines[index - 1]]
        else:
            lines = [segment["text"]]
            if translated_lines:
                lines.append(translated_lines[index - 1])
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{format_srt_time(float(segment['start']))} --> {format_srt_time(float(segment['end']))}",
                    *lines,
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"


def build_result_payload(
    context: TaskContext,
    audio_path: Path,
    subtitle_paths: list[str],
    translations: dict[str, list[str]],
) -> dict[str, Any]:
    return {
        "audio_path": str(audio_path),
        "subtitle_paths": subtitle_paths,
        "device": context.config_snapshot["whisper"]["device"],
        "translations": list(translations.keys()),
        "file_path_key": str(Path(context.file_path).expanduser().resolve()).lower(),
    }


def write_stage_artifacts(context: TaskContext, payload: dict[str, Any]) -> None:
    artifact_path = context.work_dir / "artifacts.json"
    ensure_parent(artifact_path)
    artifact_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_stage_artifacts(context: TaskContext) -> dict[str, Any]:
    artifact_path = context.work_dir / "artifacts.json"
    if not artifact_path.exists():
        raise PipelineError("缺少 artifacts.json，无法继续执行")
    payload = _read_json(artifact_path)
    if not isinstance(payload, dict):
        raise PipelineError("artifacts.json 内容无效，无法继续执行")
    return payload


def resolve_audio_path(context: TaskContext) -> Path:
    source_dir_audio = get_intermediate_path(context, "audio.wav")
    if source_dir_audio.exists():
        return source_dir_audio
    audio_format = str(context.config_snapshot["whisper"]["audio_format"]).strip().lower()
    fallback_audio = get_intermediate_path(context, f"audio.{audio_format}")
    if fallback_audio.exists():
        return fallback_audio
    raise PipelineError("缺少音频中间产物，无法继续执行")


def _sanitize_language_code(value: str) -> str:
    normalized = value.replace("_", "-").strip()
    return normalized or "und"


def _resolve_mux_output_path(context: TaskContext) -> Path:
    mux_config = context.config_snapshot["mux"]
    source_path = Path(context.file_path)
    output_to_source_dir = bool(context.config_snapshot["file"].get("output_to_source_dir", True))
    target_dir = source_path.parent if output_to_source_dir else Path(os.environ.get("SUBPIPELINE_OUTPUT_DIR", "/output"))
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = str(mux_config["filename_template"]).format(stem=source_path.stem)
    output_path = target_dir / filename
    if output_path.suffix.lower() != ".mkv":
        output_path = output_path.with_suffix(".mkv")
    return output_path


def mux_subtitle(context: TaskContext, subtitle_paths: list[str]) -> str:
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise PipelineError("ffmpeg 未安装，无法执行字幕封装")
    source_path = Path(context.file_path)
    expected_languages: dict[str, str] = {}
    translations = load_translations(context) if context.config_snapshot["translation"]["enabled"] else {}
    for track in build_subtitle_tracks(context, translations):
        expected_languages[str(track["path"])] = _sanitize_language_code(str(track["language"]))
    command = [ffmpeg_path, "-y", "-i", str(source_path)]
    for subtitle_path in subtitle_paths:
        command.extend(["-i", subtitle_path])
    command.extend(["-map", "0:v", "-map", "0:a"])
    for index in range(len(subtitle_paths)):
        command.extend(["-map", str(index + 1)])
    command.extend(["-c", "copy", "-c:s", "srt"])
    for index, subtitle_path in enumerate(subtitle_paths):
        command.extend(
            [
                f"-metadata:s:s:{index}",
                f"language={expected_languages.get(subtitle_path, 'und')}",
            ]
        )
    output_path = _resolve_mux_output_path(context)
    command.append(str(output_path))
    _run_ffmpeg(command, "字幕封装超时，FFmpeg 执行超过 7200 秒", "ffmpeg 字幕封装失败")
    return str(output_path)


def _required_resume_files(task: dict[str, Any], context: TaskContext) -> list[tuple[str, Path]]:
    stage = normalize_stage_name(str(task["stage"]))
    translation_enabled = bool(context.config_snapshot["translation"]["enabled"])
    audio_format = str(context.config_snapshot["whisper"]["audio_format"]).strip().lower()
    files: list[tuple[str, Path]] = []
    if stage in {"run_asr", "align_segments", "text_process", "translate", "subtitle_render", "output_finalize", "mux"}:
        files.append((f"audio.{audio_format}", get_intermediate_path(context, f"audio.{audio_format}")))
    if stage in {"align_segments", "text_process", "translate", "subtitle_render", "output_finalize", "mux"}:
        files.append(("asr_result.json", get_intermediate_path(context, "asr_result.json")))
    if stage in {"text_process", "translate", "subtitle_render", "output_finalize", "mux"}:
        files.append(("aligned_segments.json", get_intermediate_path(context, "aligned_segments.json")))
    if stage in {"translate", "subtitle_render", "output_finalize", "mux"}:
        files.append(("processed_segments.json", get_intermediate_path(context, "processed_segments.json")))
    if translation_enabled and stage in {"subtitle_render", "output_finalize", "mux"}:
        files.append(("translations.json", get_intermediate_path(context, "translations.json")))
    if stage in {"output_finalize", "mux"}:
        translations: dict[str, list[str]] = {}
        if translation_enabled:
            translations_path = get_intermediate_path(context, "translations.json")
            if translations_path.exists():
                payload = _read_json(translations_path)
                if isinstance(payload, dict):
                    translations = {
                        str(language): [str(value) for value in values]
                        for language, values in payload.items()
                        if isinstance(values, list)
                    }
        for track in build_subtitle_tracks(context, translations):
            files.append((Path(track["path"]).name, Path(track["path"])))
    if stage == "mux":
        files.append(("artifacts.json", context.work_dir / "artifacts.json"))
    return files


def _infer_resume_stage(current_stage: str, context: TaskContext) -> str:
    stage = normalize_stage_name(current_stage)
    audio_format = str(context.config_snapshot["whisper"]["audio_format"]).strip().lower()
    audio_exists = get_intermediate_path(context, f"audio.{audio_format}").exists()
    asr_exists = get_intermediate_path(context, "asr_result.json").exists()
    aligned_exists = get_intermediate_path(context, "aligned_segments.json").exists()
    processed_exists = get_intermediate_path(context, "processed_segments.json").exists()
    translations_exists = get_intermediate_path(context, "translations.json").exists()
    artifacts_exist = (context.work_dir / "artifacts.json").exists()

    if stage in {"run_asr", "align_segments", "text_process", "translate", "subtitle_render", "output_finalize", "mux"} and not audio_exists:
        return "extract_audio"
    if stage in {"align_segments", "text_process", "translate", "subtitle_render", "output_finalize", "mux"} and not asr_exists:
        return "run_asr"
    if stage in {"text_process", "translate", "subtitle_render", "output_finalize", "mux"} and not aligned_exists:
        return "align_segments"
    if stage in {"translate", "subtitle_render", "output_finalize", "mux"} and not processed_exists:
        return "text_process"
    if bool(context.config_snapshot["translation"]["enabled"]) and stage in {"subtitle_render", "output_finalize", "mux"} and not translations_exists:
        return "translate"
    if stage in {"output_finalize", "mux"} and not artifacts_exist and stage == "mux":
        return "output_finalize"
    return stage


def check_resume_feasibility(task: dict[str, Any]) -> dict[str, Any]:
    snapshot = task.get("config_snapshot")
    if not snapshot:
        return {"can_resume": False, "missing": ["config_snapshot"]}
    work_dir = Path(snapshot["processing"]["work_dir"]) / str(task["id"])
    context = TaskContext(
        task_id=int(task["id"]),
        file_path=str(task["file_path"]),
        config_snapshot=snapshot,
        work_dir=work_dir,
    )
    resume_stage = _infer_resume_stage(str(task["stage"]), context)
    missing: list[str] = []
    files = _required_resume_files({"stage": resume_stage}, context)
    for name, path in files:
        if not path.exists():
            missing.append(name)
            continue
        if path.suffix.lower() == ".json":
            try:
                _read_json(path)
            except Exception:
                missing.append(name)
    return {"can_resume": not missing, "missing": missing, "resume_stage": resume_stage}
