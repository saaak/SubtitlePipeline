from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("SUBPIPELINE_HOST", "0.0.0.0"),
        port=int(os.environ.get("SUBPIPELINE_PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    main()
