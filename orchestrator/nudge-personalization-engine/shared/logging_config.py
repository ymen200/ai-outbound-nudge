"""Structured logging configuration shared across all modules."""

import logging
import sys
from typing import Optional


def setup_logging(service_name: str, debug: bool = False) -> logging.Logger:
    """
    Configure structured logging for a service.
    
    Args:
        service_name: Name of the service (e.g., "message_generator", "sequence_generator")
        debug: If True, set level to DEBUG; otherwise INFO
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(service_name)
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    
    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()
    
    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG if debug else logging.INFO)
    
    # Format: TIMESTAMP | LEVEL | SERVICE_NAME | MESSAGE
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    
    return logger
