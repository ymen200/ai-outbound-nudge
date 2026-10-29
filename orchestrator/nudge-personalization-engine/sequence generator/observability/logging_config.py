import logging
import json
from datetime import datetime
import os

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.now().isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "name": record.name,
            "lineno": record.lineno,
            "funcName": record.funcName,
            "pathname": record.pathname,
            "process": record.process,
            "thread": record.thread,
        }
        if hasattr(record, 'correlation_id'):
            log_record['correlation_id'] = record.correlation_id
        if record.exc_info:
            log_record['exc_info'] = self.formatException(record.exc_info)
        if record.stack_info:
            log_record['stack_info'] = self.formatStack(record.stack_info)

        # Add any extra attributes from the log record
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'levelname', 'levelno', 'pathname', 'filename',
                           'lineno', 'funcName', 'created', 'asctime', 'msecs', 'relativeCreated',
                           'thread', 'threadName', 'processName', 'process', 'exc_info', 'exc_text',
                           'stack_info', 'args', 'kwargs', 'correlation_id'] and not key.startswith('_'):
                log_record[key] = value

        return json.dumps(log_record, default=str)

def setup_logging():
    logger = logging.getLogger("outreach_sequencer")
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

    # Prevent duplicate handlers if called multiple times
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = JsonFormatter()
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger

logger = setup_logging()

__all__ = ["logger"]
