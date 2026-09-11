"""Local entrypoint: ``python -m app``.

On Windows uvicorn defaults to the Proactor event loop, which psycopg's async mode
(the LangGraph checkpointer) cannot use, so the server runs on a selector loop here.
Containers run plain ``uvicorn app.main:app`` on Linux.
"""

from __future__ import annotations

import asyncio
import sys

import uvicorn

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    server = uvicorn.Server(
        uvicorn.Config("app.main:app", host="0.0.0.0", port=settings.port, log_level=settings.log_level.lower())
    )
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())


if __name__ == "__main__":
    main()
