"""JBH (JB Hunt) Allocation Model.

A faithful implementation of the rules in
``Allocation_Model_Rules_Reference.docx``. The model is fully port-driven: all
LAX-specific parameters live in ``config/port_allocation_rules.py``, so adding
a new port is a config edit, not a code change.

Public entry points:
    run_allocation_model(milestone_df, port)  -> structured result dict  (pure)
    show_jbh_allocation_report()              -> Streamlit UI section
"""

from .model import run_allocation_model
from .eligibility import (
    normalize_columns, validate_columns, filter_eligible, apply_ssl_terminal_fallback,
)
from .scheduling import (
    vba_week_number, compute_expected_outgate, apply_vessel_tiering,
)
from .engine import (
    compute_weekly_target, compute_terminal_caps, allocate_terminal_week, allocate_week,
)
from .triggers import check_triggers

__all__ = [
    "run_allocation_model",
    "normalize_columns", "validate_columns", "filter_eligible", "apply_ssl_terminal_fallback",
    "vba_week_number", "compute_expected_outgate", "apply_vessel_tiering",
    "compute_weekly_target", "compute_terminal_caps", "allocate_terminal_week", "allocate_week",
    "check_triggers",
]
