"""Pytest bootstrap for the Tender Optimization test suite.

Two jobs, both done ONCE here so individual test files don't have to (and so
they can't disagree and corrupt shared state — see below):

1. **Import resolution.** Put the repo root on ``sys.path`` via an absolute,
   ``__file__``-based path so ``from components... / optimization... / config...
   / evals...`` resolve no matter what directory pytest is invoked from. This
   replaces the brittle per-file ``sys.path.insert(0, '.')`` (which only worked
   when pytest ran from the repo root).

2. **A single, consistent Streamlit stub.** Almost every module imports
   ``streamlit`` at import time and calls ``@st.cache_data(...)`` as a decorator,
   so a stub must exist *before* the first first-party import. Historically each
   test file installed its own — some with ``sys.modules['streamlit'] =
   MagicMock()`` (hard overwrite), some with ``setdefault`` (keep real if
   present). In a single pytest process whichever test imported first won, so a
   hard-overwrite file could replace the shared mock that ``setdefault`` files
   (and the eval harness, which holds a reference) relied on — making test
   *order* load-bearing. (Documented hazard: ``evals/harness.py`` notes that
   ``sys.modules['streamlit']`` "is not reliable cross-module".)

   We end that by installing ONE stub here, before collection, with the two
   behaviors the codebase actually needs:
     * ``cache_data`` / ``cache_resource`` as passthrough decorators (so
       ``@st.cache_data(ttl=...)`` at import time is a no-op wrapper), and
     * ``session_state`` as a real dict that ALSO supports attribute access
       (``ss.foo`` and ``ss["foo"]``), matching how both the app and the tests
       use it.
   Every other ``st.*`` call becomes a harmless MagicMock no-op, exactly as the
   prior hard-overwrite tests assumed.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

# ---- 1. repo root on sys.path (absolute, CWD-independent) ----
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---- 2. one consistent streamlit stub ----
class _SessionState(dict):
    """Dict that also supports attribute access, like ``st.session_state``.

    The app reads/writes session state both ways (``ss.key`` and ``ss['key']``),
    uses ``.get()``/``.setdefault()``/``in``/``pop()``, so a plain MagicMock
    (whose ``.get`` returns a truthy MagicMock) would silently misbehave. A real
    dict subclass with ``__getattr__``/``__setattr__`` gives correct semantics.
    """

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:  # mirror attribute-miss semantics
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        try:
            del self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _make_streamlit_stub() -> MagicMock:
    st = MagicMock(name="streamlit_stub")
    # @st.cache_data(...) and @st.cache_resource(...) -> passthrough decorators.
    st.cache_data = lambda *a, **k: (lambda f: f)
    st.cache_resource = lambda *a, **k: (lambda f: f)
    st.session_state = _SessionState()
    return st


# Force a single shared stub for the whole process, before any first-party
# import. Hard assignment (not setdefault) so we win regardless of whether real
# streamlit is installed in the interpreter — consistency is the point.
sys.modules["streamlit"] = _make_streamlit_stub()
