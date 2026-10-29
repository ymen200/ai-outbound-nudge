import json
import logging
import hashlib

import redis

logger = logging.getLogger(__name__)


class RedisCache:
    """
    Redis-backed cache with graceful degradation.
    If Redis is unreachable at init time, the cache becomes a silent no-op
    so the pipeline can still start (without caching) instead of hard-crashing.
    """

    def __init__(self, host: str = "localhost", port: int = 6379):
        self._host = host
        self._port = port
        self.client = None  # Lazy: connected on first real use

    # ------------------------------------------------------------------
    # Lazy connection helper
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> bool:
        """Attempt to connect on first use. Returns True if connected."""
        if self.client is not None:
            return True
        try:
            self.client = redis.Redis(
                host=self._host, port=self._port, decode_responses=True
            )
            self.client.ping()  # Force a real connection to surface errors early
            return True
        except Exception as exc:
            logger.warning(
                "Redis unavailable (host=%s port=%s): %s — cache disabled for this session.",
                self._host, self._port, exc,
            )
            self.client = None
            return False

    # ------------------------------------------------------------------
    # Semantic (embedding-style) helpers — fall back to hash-based KV
    # ------------------------------------------------------------------

    def get_semantic(self, text: str):
        """Fallback to a standard hash lookup."""
        if not self._ensure_connected():
            return None
        key = self.make_key("semantic", text)
        return self._raw_get(key)

    def set_semantic(self, text: str, embedding, metadata=None):
        """Store embedding using a standard key-value pair."""
        if not self._ensure_connected():
            return
        try:
            key = self.make_key("semantic", text)
            if hasattr(embedding, "tolist"):
                embedding = embedding.tolist()
            self.client.set(key, json.dumps(embedding), ex=86400)
        except Exception as exc:
            logger.warning("Cache set_semantic failed: %s", exc)

    # ------------------------------------------------------------------
    # Standard methods
    # ------------------------------------------------------------------

    def key(self, prefix: str, *args) -> str:
        """Public alias for make_key (used by callers throughout the codebase)."""
        return self.make_key(prefix, *args)

    def get(self, key: str):
        if not self._ensure_connected():
            return None
        return self._raw_get(key)

    def set(self, key: str, value, ttl: int = 3600):
        if not self._ensure_connected():
            return
        try:
            self.client.set(key, json.dumps(value), ex=ttl)
        except Exception as exc:
            logger.warning("Cache set failed key=%s: %s", key, exc)

    def make_key(self, prefix: str, *args) -> str:
        raw = ":".join(str(a).lower().strip() for a in args)
        return hashlib.md5(f"{prefix}:{raw}".encode()).hexdigest()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _raw_get(self, key: str):
        """Execute a GET against Redis, returning None on any failure."""
        try:
            value = self.client.get(key)
            return json.loads(value) if value else None
        except Exception as exc:
            logger.warning("Cache get failed key=%s: %s", key, exc)
            return None