from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import openai
from openai import OpenAI


class PipelineError(RuntimeError):
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


class TranslationProvider:
    def translate_batch(self, texts: list[str], target_language: str) -> list[str]:
        raise NotImplementedError


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
        if not texts:
            return []
        if not self.api_key:
            raise PipelineError("translation.api_key 未配置，无法调用真实翻译 provider")
        prompt = self._build_prompt(target_language)
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(texts, ensure_ascii=False)},
                ],
            )
        except openai.AuthenticationError as exc:
            raise PipelineError("翻译服务鉴权失败，请检查 API Key") from exc
        except openai.RateLimitError as exc:
            raise PipelineError("翻译服务触发限流，请稍后重试") from exc
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
        translated = self._parse_json_array_content(content)
        if not isinstance(translated, list) or len(translated) != len(texts):
            raise PipelineError("真实翻译 provider 返回结果数量与输入不一致")
        return [str(item).strip() for item in translated]

    def _resolve_base_url(self) -> str:
        if self.api_base_url.endswith("/v1"):
            return self.api_base_url
        return f"{self.api_base_url}/v1"

    def _build_prompt(self, target_language: str) -> str:
        return (
            f"Translate each input string to {target_language}. "
            "Return a JSON array of translated strings only. "
            "Keep the same order and array length. Do not include markdown or code fences."
        )

    def _parse_json_array_content(self, content: str) -> list[Any]:
        candidates = [
            content.strip(),
            self._strip_code_fence(content),
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
        stripped = content.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped)
            stripped = re.sub(r"\s*```$", "", stripped)
        return stripped.strip()

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
) -> dict[str, Any]:
    provider = OpenAICompatibleTranslationProvider(
        api_base_url=api_base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout_seconds,
    )
    prompt = provider._build_prompt(target_language)
    response = provider.client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(texts, ensure_ascii=False)},
        ],
    )
    content = response.choices[0].message.content
    if not isinstance(content, str):
        raise PipelineError("真实翻译 provider 未返回文本内容")
    parsed = provider._parse_json_array_content(content)
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


def translate_segments(context: TaskContext, segments: list[dict[str, Any]]) -> dict[str, list[str]]:
    translation_config = context.config_snapshot["translation"]
    if not translation_config["enabled"]:
        return {}
    provider = get_translation_provider(context.config_snapshot)
    source_texts = [segment["text"] for segment in segments]
    translations: dict[str, list[str]] = {}
    max_retries = max(int(translation_config["max_retries"]), 1)
    for language in translation_config["target_languages"]:
        last_error: Exception | None = None
        for _ in range(max_retries):
            try:
                translations[language] = provider.translate_batch(source_texts, language)
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
