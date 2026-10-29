import logging
import time
from functools import wraps


logger = logging.getLogger(__name__)


def retry_on_rate_limit(max_attempts=4, base_delay=1.0, max_delay=12.0):
    """Retry API calls that fail with a provider rate-limit error."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = base_delay
            last_error = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    message = str(exc).lower()
                    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                    is_rate_limited = status_code == 429 or "429" in message or "too many requests" in message

                    if not is_rate_limited or attempt == max_attempts:
                        raise

                    last_error = exc
                    logger.warning(
                        "Rate limit hit in %s; retrying attempt %s/%s in %.1fs",
                        func.__name__,
                        attempt + 1,
                        max_attempts,
                        delay,
                    )
                    time.sleep(delay)
                    delay = min(delay * 2, max_delay)

            raise last_error

        return wrapper

    return decorator
