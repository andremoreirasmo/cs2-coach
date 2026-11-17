"""Modo sem janela (só serviço): python -m coach.main. Para o app com janela use coach.app."""
from __future__ import annotations

import uvicorn

from .config import settings
from .server import create_app
from .services import Services, setup_logging


def main() -> None:
    setup_logging()
    s = Services()
    s.start()
    uvicorn.run(create_app(s.tracker, busy=s.busy, on_demo=s.analyzer.submit, progress=s.analyzer.progress), host="127.0.0.1", port=settings.gsi_port, log_level="warning")


if __name__ == "__main__":
    main()
