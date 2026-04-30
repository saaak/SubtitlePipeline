from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.pipeline import PipelineError, debug_translation_request


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm-type", default="openai-compatible")
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--target-language", default="zh-CN")
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--text", action="append", dest="texts")
    parser.add_argument("--subpipeline-dir")
    parser.add_argument("--segments-file")
    return parser


def load_texts(args: argparse.Namespace) -> list[str]:
    segments_path: Path | None = None
    if args.segments_file:
        segments_path = Path(args.segments_file)
    elif args.subpipeline_dir:
        segments_path = Path(args.subpipeline_dir) / "processed_segments.json"
    if segments_path is None:
        return args.texts or ["hello world.", "second line."]
    if not segments_path.exists():
        raise PipelineError(f"未找到真实数据文件: {segments_path}")
    payload = json.loads(segments_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise PipelineError(f"真实数据文件格式无效: {segments_path}")
    texts = [str(item.get("text", "")).strip() for item in payload]
    texts = [text for text in texts if text]
    if not texts:
        raise PipelineError(f"真实数据文件中没有可用文本: {segments_path}")
    return texts


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        texts = load_texts(args)
        result = debug_translation_request(
            llm_type=args.llm_type,
            api_base_url=args.api_base_url,
            api_key=args.api_key,
            model=args.model,
            timeout_seconds=args.timeout_seconds,
            target_language=args.target_language,
            texts=texts,
        )
    except PipelineError as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "success": True,
                **result,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
