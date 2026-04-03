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
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--target-language", default="zh-CN")
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--text", action="append", dest="texts")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    texts = args.texts or ["hello world.", "second line."]
    try:
        result = debug_translation_request(
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
