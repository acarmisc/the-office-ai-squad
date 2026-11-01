"""Serve the fake LLM: ``python -m deploy.fake_llm`` (PORT, default 4000)."""

from __future__ import annotations

import os

import uvicorn

from deploy.fake_llm.server import create_app

_DEFAULT_PORT = 4000


def main() -> None:
    port = int(os.environ.get("PORT", str(_DEFAULT_PORT)))
    uvicorn.run(create_app(), host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
