# Re-export from parent middleware for app-internal imports
import sys
from pathlib import Path

# Add parent directory to path so we can import from the root-level middleware
_parent_middleware = Path(__file__).resolve().parent.parent.parent / "middleware"
if str(_parent_middleware.parent) not in sys.path:
    sys.path.insert(0, str(_parent_middleware.parent))

from middleware.token_counter import TokenCounter

__all__ = ["TokenCounter"]
