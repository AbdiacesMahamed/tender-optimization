"""
Category normalization — the single source of truth for how a business
``Category`` value is matched, no matter which spelling shows up.

The problem this solves
-----------------------
GVT data is normalized on load (``components/data/processor.py``): the raw
labels ``Retail CD`` / ``FBA FCL`` / ``FBA LCL`` are collapsed into the bucket
``CD``, and ``Retail Transload`` into ``TL``. Constraint files, the chatbot, and
the rate sheet, however, may carry *either* spelling — a raw label, the bucket
code, or some casing/whitespace variant.

If one side compares the raw label against the other side's bucket code, the
match silently returns zero rows (a ``Category=CD`` rule matched nothing even
though the data was full of ``CD`` containers). The fix is to canonicalize
**both sides** of every comparison through :func:`canonical_category`, so all
equivalent spellings collapse to the same key before they are compared.

This module is intentionally dependency-light (stdlib only) so it can be shared
by the Streamlit-free layers (``optimization/*``, ``components/chatbot/*``) as
well as the dashboard.
"""
from __future__ import annotations

from typing import Optional

# Raw GVT label -> canonical bucket. MUST stay in sync with the normalization
# applied at data-load time (components/data/processor.CATEGORY_MAPPING).
# Add a row here whenever a new raw label needs to fold into an existing bucket.
RAW_TO_CANONICAL = {
    "FBA LCL": "CD",
    "RETAIL CD": "CD",
    "FBA FCL": "CD",
    "RETAIL TRANSLOAD": "TL",
}

# Shorthand a user may type in a constraint file -> canonical bucket. These are
# the codes that are NOT also raw labels (the raw labels above already resolve
# via RAW_TO_CANONICAL). Kept separate only for documentation; both maps are
# consulted by canonical_category.
SHORTHAND_TO_CANONICAL = {
    "CD": "CD",
    "TL": "TL",
    "ROBOTICS": "ROBOTICS",
    "AMAZON ROBOTICS": "ROBOTICS",
    "DEVICES": "DEVICES",
    "AMAZON DEVICES": "DEVICES",
}


def canonical_category(value) -> Optional[str]:
    """Fold any spelling of a category into its canonical bucket key.

    Case- and whitespace-insensitive. Returns ``None`` for blank/NaN input.
    Unknown values pass through as their upper-cased, stripped selves so a
    category this module has never heard of still matches itself on both sides
    (an unknown raw label compared against the same unknown raw label).

    Examples::

        canonical_category("CD")        -> "CD"
        canonical_category("Retail CD") -> "CD"
        canonical_category("fba fcl")   -> "CD"
        canonical_category("Robotics")  -> "ROBOTICS"
        canonical_category("Imports")   -> "IMPORTS"   (unknown -> itself)
        canonical_category("")          -> None
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    key = text.upper()
    if key in RAW_TO_CANONICAL:
        return RAW_TO_CANONICAL[key]
    if key in SHORTHAND_TO_CANONICAL:
        return SHORTHAND_TO_CANONICAL[key]
    return key


def category_matches(constraint_value, data_value) -> bool:
    """True if a constraint's Category value should match a data row's Category.

    Both sides are canonicalized first, so ``CD`` (constraint) matches a row
    whose Category is ``Retail CD``, ``FBA FCL``, or the already-normalized
    ``CD`` — and vice versa. A blank constraint value never restricts (handled
    by callers, which skip the filter entirely when the value is blank).
    """
    return canonical_category(constraint_value) == canonical_category(data_value)
