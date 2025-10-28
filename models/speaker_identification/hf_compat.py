from __future__ import annotations

import contextlib
from typing import Iterator, Optional

try:
    from huggingface_hub.utils import EntryNotFoundError
except Exception:
    EntryNotFoundError = None  # type: ignore[assignment]


def _resolve_filename(args: tuple, kwargs: dict) -> Optional[str]:
    filename = kwargs.get("filename")
    if filename:
        return str(filename)
    if args:
        return str(args[0])
    return None


@contextlib.contextmanager
def allow_missing_custom_py() -> Iterator[None]:
    """
    Temporarily convert huggingface_hub EntryNotFoundError for custom.py into
    ValueError so that speechbrain 1.0.x keeps treating the file as optional.
    """
    if EntryNotFoundError is None:
        yield
        return

    try:
        from speechbrain.utils import fetching as sb_fetching  # type: ignore
    except Exception:
        yield
        return

    original_fetch = getattr(sb_fetching, "fetch", None)
    if original_fetch is None:
        yield
        return

    def fetch_wrapper(*args, **kwargs):
        filename = _resolve_filename(args, kwargs)
        try:
            return original_fetch(*args, **kwargs)
        except EntryNotFoundError as err:  # type: ignore[misc]
            if filename and filename.endswith("custom.py"):
                raise ValueError("speechbrain optional custom.py missing") from err
            raise

    sb_fetching.fetch = fetch_wrapper  # type: ignore[assignment]
    try:
        yield
    finally:
        sb_fetching.fetch = original_fetch  # type: ignore[assignment]
