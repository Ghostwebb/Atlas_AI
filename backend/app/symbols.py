"""Symbol format validation for US equity tickers."""

import re

# 1 to 5 letters, optionally followed by a single dot and 1-2 letters
# (e.g. "BRK.B"). Enough for Phase 1; extend when real data arrives.
_SYMBOL_PATTERN = re.compile(r"^[A-Z]{1,5}(\.[A-Z]{1,2})?$")


def normalize_symbol(raw: str) -> str:
    """Strip whitespace and uppercase a symbol. Does not validate it."""
    return raw.strip().upper()


def is_valid_format(symbol: str) -> bool:
    """Return True if the (already normalized) symbol has a valid ticker shape."""
    return bool(_SYMBOL_PATTERN.fullmatch(symbol))
