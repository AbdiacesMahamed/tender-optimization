"""Tests for config/peel_pile_thresholds.py — per-port/terminal peel-pile limits."""
import pytest

from config.peel_pile_thresholds import (
    peel_pile_threshold, min_threshold, DISABLED_THRESHOLD,
    PNW_DEFAULT_THRESHOLD,
)


class TestPNWTerminalLimits:
    @pytest.mark.parametrize("port", ["TIW", "SEA", "tiw", " sea "])
    @pytest.mark.parametrize("terminal,expected", [
        ("TRM-TWUT", 40),     # Washington United
        ("TRM-T004", 45),     # Husky (Tacoma Terminal 4)
        ("SSA-T18", 30),      # Terminal 18
        ("TERMINAL 5", 30),   # Terminal 5
    ])
    def test_known_terminals(self, port, terminal, expected):
        assert peel_pile_threshold(port, terminal) == expected

    def test_terminal_lookup_is_case_insensitive(self):
        assert peel_pile_threshold("TIW", "trm-twut") == 40
        assert peel_pile_threshold("SEA", " Terminal 5 ") == 30

    @pytest.mark.parametrize("terminal", ["TRM-TPCT", None, "", "SOME-NEW-DOCK"])
    def test_pct_and_unknown_terminals_use_pnw_default(self, terminal):
        # Pierce County (no own limit) and any blank/unknown terminal -> 80.
        assert peel_pile_threshold("TIW", terminal) == PNW_DEFAULT_THRESHOLD == 80


class TestOtherPorts:
    def test_oak_keeps_thirty(self):
        assert peel_pile_threshold("OAK") == 30
        assert peel_pile_threshold("oak", "any-terminal") == 30

    @pytest.mark.parametrize("port", ["LAX", "NYC", "BAL", "NFK", "CHI", "MKC", "MEM", None, ""])
    def test_unlisted_ports_disabled(self, port):
        assert peel_pile_threshold(port) == DISABLED_THRESHOLD
        # A terminal name never re-enables a disabled port.
        assert peel_pile_threshold(port, "TRM-TWUT") == DISABLED_THRESHOLD


def test_min_threshold_is_smallest_real_limit():
    # Smallest configured limit is 30 (T18/T5/OAK); never the disabled sentinel.
    assert min_threshold() == 30
    assert min_threshold() < DISABLED_THRESHOLD
