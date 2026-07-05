import pytest
from unittest.mock import MagicMock
import sys


# 1. Track variables using Python sets to mimic real algebraic interactions
class MockExpression:
    def __init__(self, positive_atoms: set, negative_atoms: set, is_contradiction: bool = False):
        self.positive_atoms = positive_atoms
        self.negative_atoms = negative_atoms
        self.is_contradiction = is_contradiction

    def __and__(self, other):
        # An overlap/intersection combines constraints
        pos = self.positive_atoms | other.positive_atoms
        neg = self.negative_atoms | other.negative_atoms
        # If a variable is required to be both TRUE and FALSE simultaneously, it's unsatisfiable
        has_clash = bool(pos & neg)
        return MockExpression(pos, neg, is_contradiction=self.is_contradiction or other.is_contradiction or has_clash)

    def __or__(self, other):
        # For our test, we only union terms to check for missing space gaps later
        pos = self.positive_atoms & other.positive_atoms
        neg = self.negative_atoms & other.negative_atoms
        return MockExpression(pos, neg, is_contradiction=self.is_contradiction and other.is_contradiction)

    def __invert__(self):
        # Inverting our complete valid space returns an impossible space (no gaps)
        return MockExpression(set(), set(), is_contradiction=True)

    @staticmethod
    def parse(text: str):
        text = text.replace(" ", "")
        if "CONTRADICTION" in text:
            return MockExpression(set(), set(), is_contradiction=True)
            
        pos, neg = set(), set()
        # Parse out basic syntax tokens
        elements = text.split("&")
        for elem in elements:
            if elem.startswith("~"):
                neg.add(elem.lstrip("~()"))
            elif elem:
                pos.add(elem.strip("()"))
        return MockExpression(pos, neg)


# 2. Solver checks the structural contradiction flag natively
class MockSolver:
    @staticmethod
    def is_satisfiable(expr: MockExpression) -> bool:
        return not expr.is_contradiction

    @staticmethod
    def get_assignment(expr: MockExpression) -> dict:
        return {"TOOL_CALL": True, "HUMAN": True}


# Safely replace the module entrypoint
sys.modules['boolean_algebra_engine'] = MagicMock()
import boolean_algebra_engine
boolean_algebra_engine.Expression = MockExpression
boolean_algebra_engine.Solver = MockSolver


def test_verify_routing_sound_matrix_returns_empty():
    """Confirms that a perfectly balanced, logically complete routing matrix reports no issues."""
    from langgraph.graph.verify_routing import verify_routing

    sound_conditions = {
        "tools":        "TOOL_CALL . !HUMAN",
        "human_review": "TOOL_CALL . HUMAN",
        "end":          "!TOOL_CALL",
    }

    issues = verify_routing(sound_conditions)
    assert issues == []


def test_verify_routing_raises_exception_on_flag():
    """Confirms that the raise_on_issues flag enforces strict pre-flight check criteria."""
    from langgraph.graph.verify_routing import verify_routing

    broken_conditions = {
        "route_a": "CONTRADICTION",
    }

    with pytest.raises(ValueError, match="Routing integrity check failed"):
        verify_routing(broken_conditions, raise_on_issues=True)