import logging
import sys

_LOG_FORMAT = (
    '{"time": "%(asctime)s", "level": "%(levelname)s", '
    '"logger": "%(name)s", "message": "%(message)s"}'
)


def configure_logging(level: str = "info") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))

    root.handlers.clear()
    root.addHandler(handler)

    # Quiet noisy third-party loggers at INFO by default.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
