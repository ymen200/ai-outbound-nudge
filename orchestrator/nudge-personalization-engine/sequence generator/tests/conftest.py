"""Pytest configuration for the sequence generator test suite.

Loads the project .env file so that environment-dependent tests (e.g. Gemini
retry/fallback tests) have a non-empty GOOGLE_API_KEY without requiring the
developer to export it manually.

Also registers the 'sequence_generator' package via importlib so that tests
can use 'from sequence_generator.graph.builder import ...' even though the
directory name contains a space.
"""

import os
import sys
import importlib
import importlib.util
from pathlib import Path

from dotenv import load_dotenv


# Load sequence generator/.env relative to this test directory
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH, override=False)


# Tests that mock the Gemini API still need a non-empty key because the code
# checks GOOGLE_API_KEY before making the request. If .env is missing the key,
# fall back to a dummy value so the mocked request path is exercised.
if not os.getenv("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = "dummy_key_for_tests"


# Add the sequence generator directory to sys.path so that
# relative imports within the package resolve correctly.
seq_gen_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if seq_gen_dir not in sys.path:
    sys.path.insert(0, seq_gen_dir)


# Register 'sequence_generator' as an importable package via importlib.
# The directory name contains a space, so Python can't import it directly.
# This mirrors the package registration in scripts/api_server.py.
def _load_pkg_module(pkg_name: str, pkg_dir: Path):
    init_file = pkg_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text("# auto-generated for package registration\n")
    spec = importlib.util.spec_from_file_location(
        pkg_name, str(init_file),
        submodule_search_locations=[str(pkg_dir)]
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[pkg_name] = mod
    spec.loader.exec_module(mod)
    return mod


_seq_gen_pkg_dir = Path(seq_gen_dir)
if "sequence_generator" not in sys.modules:
    _load_pkg_module("sequence_generator", _seq_gen_pkg_dir)

for _subpkg in ["config", "models", "graph", "graph.nodes", "tools",
                "observability", "temporal", "middleware"]:
    _subpkg_path = _seq_gen_pkg_dir / _subpkg.replace(".", "/")
    if _subpkg_path.is_dir():
        _full_name = f"sequence_generator.{_subpkg}"
        if _full_name not in sys.modules:
            _init = _subpkg_path / "__init__.py"
            if not _init.exists():
                _init.write_text("")
            try:
                _spec = importlib.util.spec_from_file_location(
                    _full_name, str(_init),
                    submodule_search_locations=[str(_subpkg_path)]
                )
                if _spec and _spec.loader:
                    _mod = importlib.util.module_from_spec(_spec)
                    sys.modules[_full_name] = _mod
                    _spec.loader.exec_module(_mod)
            except Exception:
                pass


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "integration: marks tests that call real external APIs (slow, deselect with -k 'not integration')"
    )
