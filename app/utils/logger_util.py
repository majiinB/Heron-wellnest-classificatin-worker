# python
import logging
import os
from typing import Optional

def _configure_logger(name: str = "nlp_worker") -> logging.Logger:
    env_mode = os.getenv("ENVIRONMENT", "development")
    logger = logging.getLogger(name)

    # Remove existing handlers to avoid duplicates
    if logger.handlers:
        logger.handlers.clear()

    logger.setLevel(logging.INFO)

    # Choose formatter based on environment
    if env_mode == "production":
        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s", "module": "%(name)s"}'
        )
    else:
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Try to add Google Cloud Logging handler in production if available
    if env_mode == "production":
        try:
            from google.cloud import logging as cloud_logging  # type: ignore
            from google.cloud.logging.handlers import CloudLoggingHandler  # type: ignore

            client = cloud_logging.Client()
            cloud_handler = CloudLoggingHandler(client)
            logger.addHandler(cloud_handler)
        except Exception as exc:
            logger.warning("Failed to initialize Google Cloud Logging: %s", exc)

    logger.propagate = False
    return logger

# Export a standard Logger instance (has .exception, .info, etc.)
logger = _configure_logger()