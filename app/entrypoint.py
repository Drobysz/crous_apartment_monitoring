"""Run polling locally or the internal HTTP service in webhook deployments."""

import asyncio

import uvicorn

from app.bot.runner import main as polling_main
from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    if settings.run_mode == "webhook":
        uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
    else:
        asyncio.run(polling_main())


if __name__ == "__main__":
    main()
