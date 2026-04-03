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

import openai
from openai import OpenAI

logger = logging.getLogger(__name__)

CHUNK_SIZE = 50
CONTEXT_SIZE = 10
MAX_CHUNK_WORKERS = 3
MAX_CHUNK_RETRIES = 5

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
    return re.sub(r"^\s*\d+\|", "", line, count=1).strip()


def parse_numbered_lines(
    raw_output: str,
    expected_ids: list[int],
    source_texts: list[str] | None = None,
) -> list[str] | None:
    matches: dict[int, str] = {}
    expected = set(expected_ids)
    for line in strip_code_fence(raw_output).splitlines():
        normalized = line.strip()
        if not normalized or "|" not in normalized:
            continue
        prefix, value = normalized.split("|", 1)
        if not prefix.strip().isdigit():
            continue
        index = int(prefix.strip())
        if index in expected and index not in matches:
            matches[index] = value.strip()
    if len(matches) == len(expected_ids):
        return [matches[index] for index in expected_ids]
    if source_texts is not None and expected_ids:
        matched_ratio = len(matches) / len(expected_ids)
        if matched_ratio >= 0.8:
            missing = [index for index in expected_ids if index not in matches]
            logger.warning("分块翻译部分匹配，缺失编号将回退原文: %s", missing)
            return [matches.get(index, source_texts[position]) for position, index in enumerate(expected_ids)]
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
    raise PipelineError("真实翻译 provider 返回结果数量与输入不一致")


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
        if isinstance(self.provider, OpenAICompatibleTranslationProvider):
            return self.provider.translate_chunk(chunk, target_language, self.content_type, self.custom_prompt)
        return self.provider.translate_batch([line.text for line in chunk.main_segments], target_language)


class OpenAICompatibleTranslationProvider(TranslationProvider):
    def __init__(self, api_base_url: str, api_key: str, model: str, timeout_seconds: int):
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.client = OpenAI(
            api_key=self.api_key or "missing-api-key",
            base_url=self._resolve_base_url(),
            timeout=float(self.timeout_seconds),
            max_retries=0,
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
        if not self.api_key:
            raise PipelineError("translation.api_key 未配置，无法调用真实翻译 provider")
        prompt = self._build_prompt(target_language, content_type, custom_prompt)
        content = self._request_translation(prompt, build_chunk_user_message(chunk))
        return parse_chunk_output(
            content,
            [line.index for line in chunk.main_segments],
            texts,
            self._parse_json_array_content,
        )

    def _resolve_base_url(self) -> str:
        if self.api_base_url.endswith("/v1"):
            return self.api_base_url
        return f"{self.api_base_url}/v1"

    def _request_translation(self, prompt: str, user_content: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_content},
                ],
            )
        except openai.AuthenticationError as exc:
            raise PipelineError("翻译服务鉴权失败，请检查 API Key") from exc
        except openai.RateLimitError as exc:
            raise TranslationRateLimitError("翻译服务触发限流，请稍后重试") from exc
        except openai.BadRequestError as exc:
            raise PipelineError(f"翻译请求参数无效: {exc}") from exc
        except openai.APIConnectionError as exc:
            raise PipelineError("翻译服务连接失败，请检查 API 地址、网络或服务状态") from exc
        except openai.APIStatusError as exc:
            raise PipelineError(f"翻译服务返回异常状态 {exc.status_code}") from exc
        except openai.APIError as exc:
            raise PipelineError(f"翻译服务调用失败: {exc}") from exc
        try:
            content = response.choices[0].message.content
        except (KeyError, IndexError, TypeError) as exc:
            raise PipelineError("真实翻译 provider 返回格式无效") from exc
        if not isinstance(content, str):
            raise PipelineError("真实翻译 provider 未返回文本内容")
        return content

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
    api_base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: int,
    target_language: str,
    texts: list[str],
    content_type: str = "general",
    custom_prompt: str = "",
) -> dict[str, Any]:
    provider = OpenAICompatibleTranslationProvider(
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
    return ("audio.wav", "asr_result.json", "processed_segments.json", "translations.json")


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
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise PipelineError(result.stderr.strip() or "ffmpeg 执行失败")
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


def run_asr(context: TaskContext, audio_path: Path) -> dict[str, Any]:
    try:
        import whisperx  # type: ignore
    except ImportError as exc:
        raise PipelineError("whisperx 未安装，无法执行真实识别") from exc
    whisper_config = context.config_snapshot["whisper"]
    models_root = Path(os.environ.get("SUBPIPELINE_MODELS_DIR", "/models"))
    local_model_dir = models_root / str(whisper_config["model_name"])
    model_reference = str(local_model_dir) if local_model_dir.exists() else whisper_config["model_name"]
    model = whisperx.load_model(
        model_reference,
        whisper_config["device"],
        download_root=str(models_root),
    )
    result = model.transcribe(str(audio_path))
    align_model, metadata = whisperx.load_align_model(
        language_code=result.get("language", "en"),
        device=whisper_config["device"],
    )
    aligned = whisperx.align(result["segments"], align_model, metadata, str(audio_path), whisper_config["device"])
    return {
        "segments": [
            {
                "start": float(segment["start"]),
                "end": float(segment["end"]),
                "text": str(segment["text"]).strip(),
            }
            for segment in aligned["segments"]
        ],
        "device": whisper_config["device"],
        "audio_path": str(audio_path),
    }


def process_text_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    processed: list[dict[str, Any]] = []
    for segment in segments:
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
    return OpenAICompatibleTranslationProvider(
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
    output_dir = str(file_config["output_dir"]).strip()
    return source_path.parent if not output_dir else Path(output_dir)


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
        tracks.append(
            {
                "language": language,
                "path": target_dir / template.format(stem=source_path.stem, lang=language),
                "translated_lines": translated_lines if subtitle_config["bilingual_mode"] == "merge" else None,
            }
        )
    if subtitle_config["bilingual_mode"] == "separate":
        tracks.append(
            {
                "language": str(subtitle_config.get("source_language", "source")),
                "path": target_dir / template.format(stem=source_path.stem, lang="source"),
                "translated_lines": None,
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
        content = build_srt_content(segments, track["translated_lines"])
        ensure_parent(output_path)
        output_path.write_text(content, encoding="utf-8")
        outputs.append(str(output_path))
    return outputs


def build_srt_content(segments: list[dict[str, Any]], translated_lines: list[str] | None) -> str:
    blocks: list[str] = []
    for index, segment in enumerate(segments, start=1):
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
    output_dir = str(mux_config["output_dir"]).strip()
    target_dir = source_path.parent if not output_dir else Path(output_dir)
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
    command.extend(["-map", "0"])
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
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise PipelineError(result.stderr.strip() or "ffmpeg 字幕封装失败")
    return str(output_path)


def _required_resume_files(task: dict[str, Any], context: TaskContext) -> list[tuple[str, Path]]:
    stage = str(task["stage"])
    translation_enabled = bool(context.config_snapshot["translation"]["enabled"])
    audio_format = str(context.config_snapshot["whisper"]["audio_format"]).strip().lower()
    files: list[tuple[str, Path]] = []
    if stage in {"asr", "text_process", "translate", "subtitle_render", "output_finalize", "mux"}:
        files.append((f"audio.{audio_format}", get_intermediate_path(context, f"audio.{audio_format}")))
    if stage in {"text_process", "translate", "subtitle_render", "output_finalize", "mux"}:
        files.append(("asr_result.json", get_intermediate_path(context, "asr_result.json")))
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
    missing: list[str] = []
    files = _required_resume_files(task, context)
    for name, path in files:
        if not path.exists():
            missing.append(name)
            continue
        if path.suffix.lower() == ".json":
            try:
                _read_json(path)
            except Exception:
                missing.append(name)
    return {"can_resume": not missing, "missing": missing}
