from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


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


class TranslationProvider:
    def translate_batch(self, texts: list[str], target_language: str) -> list[str]:
        raise NotImplementedError


class MockTranslationProvider(TranslationProvider):
    def __init__(self, prefix_template: str, fail_languages: list[str]):
        self.prefix_template = prefix_template
        self.fail_languages = set(fail_languages)

    def translate_batch(self, texts: list[str], target_language: str) -> list[str]:
        if target_language in self.fail_languages:
            raise PipelineError(f"mock translation failed for {target_language}")
        prefix = self.prefix_template.format(lang=target_language)
        return [f"{prefix}{text}" for text in texts]


class EchoTranslationProvider(TranslationProvider):
    def translate_batch(self, texts: list[str], target_language: str) -> list[str]:
        return [f"{text} ({target_language})" for text in texts]


class OpenAICompatibleTranslationProvider(TranslationProvider):
    def __init__(self, api_base_url: str, api_key: str, model: str, timeout_seconds: int):
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def translate_batch(self, texts: list[str], target_language: str) -> list[str]:
        if not self.api_key:
            raise PipelineError("translation.api_key 未配置，无法调用真实翻译 provider")
        endpoint = (
            f"{self.api_base_url}/chat/completions"
            if self.api_base_url.endswith("/v1")
            else f"{self.api_base_url}/v1/chat/completions"
        )
        prompt = (
            f"Translate each input string to {target_language}. "
            "Return a JSON array of translated strings only. "
            "Keep the same order and array length. Do not include markdown."
        )
        response = httpx.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "developer", "content": prompt},
                    {"role": "user", "content": json.dumps(texts, ensure_ascii=False)},
                ],
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise PipelineError("真实翻译 provider 返回格式无效") from exc
        if not isinstance(content, str):
            raise PipelineError("真实翻译 provider 未返回文本内容")
        try:
            translated = json.loads(content)
        except json.JSONDecodeError as exc:
            raise PipelineError("真实翻译 provider 未返回 JSON 数组") from exc
        if not isinstance(translated, list) or len(translated) != len(texts):
            raise PipelineError("真实翻译 provider 返回结果数量与输入不一致")
        return [str(item).strip() for item in translated]


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def extract_audio(context: TaskContext) -> Path:
    whisper_config = context.config_snapshot["whisper"]
    processing_config = context.config_snapshot["processing"]
    source_path = Path(context.file_path)
    audio_path = context.work_dir / f"{source_path.stem}.{whisper_config['audio_format']}"
    ensure_parent(audio_path)
    if processing_config["backend_mode"] == "mock":
        audio_path.write_bytes(source_path.name.encode("utf-8"))
        return audio_path
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


def run_asr(context: TaskContext, audio_path: Path) -> dict[str, Any]:
    processing_config = context.config_snapshot["processing"]
    source_path = Path(context.file_path)
    if processing_config["backend_mode"] == "mock":
        stem_text = source_path.stem.replace("_", " ").replace("-", " ").strip() or "sample video"
        first_text = f"{stem_text} segment one."
        second_text = f"{stem_text} segment two."
        return {
            "segments": [
                {"start": 0.0, "end": 2.5, "text": first_text},
                {"start": 2.5, "end": 5.0, "text": second_text},
            ],
            "device": context.config_snapshot["whisper"]["device"],
            "audio_path": str(audio_path),
        }
    try:
        import whisperx  # type: ignore
    except ImportError as exc:
        raise PipelineError("whisperx 未安装，无法执行真实识别") from exc
    whisper_config = context.config_snapshot["whisper"]
    model = whisperx.load_model(whisper_config["model_name"], whisper_config["device"])
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


def get_translation_provider(config_snapshot: dict[str, Any]) -> TranslationProvider:
    translation = config_snapshot["translation"]
    provider_name = translation["provider"]
    if provider_name == "mock":
        return MockTranslationProvider(
            prefix_template=translation["mock_prefix_template"],
            fail_languages=list(translation.get("fail_languages", [])),
        )
    if provider_name == "echo":
        return EchoTranslationProvider()
    if provider_name == "openai_compatible":
        return OpenAICompatibleTranslationProvider(
            api_base_url=str(translation["api_base_url"]).strip(),
            api_key=str(translation["api_key"]).strip(),
            model=str(translation["model"]).strip(),
            timeout_seconds=int(translation["timeout_seconds"]),
        )
    raise PipelineError(f"未知翻译 provider: {provider_name}")


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


def format_srt_time(seconds: float) -> str:
    total_milliseconds = int(round(seconds * 1000))
    milliseconds = total_milliseconds % 1000
    total_seconds = total_milliseconds // 1000
    minutes, seconds_value = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds_value:02},{milliseconds:03}"


def render_srt(
    context: TaskContext,
    segments: list[dict[str, Any]],
    translations: dict[str, list[str]],
) -> list[str]:
    subtitle_config = context.config_snapshot["subtitle"]
    file_config = context.config_snapshot["file"]
    source_path = Path(context.file_path)
    target_dir = source_path.parent if file_config["in_place"] else Path(file_config["output_dir"])
    target_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    if subtitle_config["bilingual"] and translations and subtitle_config["bilingual_mode"] == "merge":
        language = next(iter(translations))
        content = build_srt_content(segments, translations.get(language))
        output_path = target_dir / subtitle_config["filename_template"].format(stem=source_path.stem, lang="bilingual")
        ensure_parent(output_path)
        output_path.write_text(content, encoding="utf-8")
        outputs.append(str(output_path))
        return outputs
    if not translations:
        content = build_srt_content(segments, None)
        output_path = target_dir / subtitle_config["filename_template"].format(stem=source_path.stem, lang="source")
        ensure_parent(output_path)
        output_path.write_text(content, encoding="utf-8")
        outputs.append(str(output_path))
        return outputs
    for language, translated_lines in translations.items():
        merge_lines = translated_lines if subtitle_config["bilingual_mode"] == "merge" else None
        content = build_srt_content(segments, merge_lines)
        output_path = target_dir / subtitle_config["filename_template"].format(stem=source_path.stem, lang=language)
        ensure_parent(output_path)
        output_path.write_text(content, encoding="utf-8")
        outputs.append(str(output_path))
        if subtitle_config["bilingual_mode"] == "separate":
            source_output = target_dir / subtitle_config["filename_template"].format(stem=source_path.stem, lang="source")
            if str(source_output) not in outputs:
                source_output.write_text(build_srt_content(segments, None), encoding="utf-8")
                outputs.append(str(source_output))
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


def write_stage_artifacts(context: TaskContext, payload: dict[str, Any]) -> None:
    artifact_path = context.work_dir / "artifacts.json"
    ensure_parent(artifact_path)
    artifact_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
