import importlib.util
import sys
import types
from pathlib import Path

import pytest


def test_allow_missing_custom_py_converts_entry(monkeypatch, tmp_path):
    project_root = Path(__file__).resolve().parents[3]
    compat_path = project_root / "models" / "speaker_identification" / "hf_compat.py"
    spec = importlib.util.spec_from_file_location("hf_compat_under_test", compat_path)
    assert spec is not None and spec.loader is not None
    compat = importlib.util.module_from_spec(spec)
    sys.modules["hf_compat_under_test"] = compat
    spec.loader.exec_module(compat)

    class DummyEntry(Exception):
        pass

    compat.EntryNotFoundError = DummyEntry  # type: ignore[attr-defined]

    fetch_mod = types.SimpleNamespace()
    calls = []

    def failing_fetch(*args, **kwargs):
        calls.append(kwargs.get("filename"))
        raise DummyEntry("missing custom.py")

    fetch_mod.fetch = failing_fetch
    sys.modules["speechbrain.utils.fetching"] = fetch_mod
    sys.modules["speechbrain.utils"] = types.SimpleNamespace(fetching=fetch_mod)
    sys.modules["speechbrain"] = types.SimpleNamespace(utils=sys.modules["speechbrain.utils"])

    with pytest.raises(ValueError):
        with compat.allow_missing_custom_py():
            fetch_mod.fetch(filename="custom.py", savedir=tmp_path)

    assert calls == ["custom.py"]
    sys.modules.pop("hf_compat_under_test", None)
    sys.modules.pop("speechbrain.utils.fetching", None)
    sys.modules.pop("speechbrain.utils", None)
    sys.modules.pop("speechbrain", None)
