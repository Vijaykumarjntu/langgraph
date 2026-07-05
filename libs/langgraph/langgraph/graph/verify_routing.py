from dataclasses import dataclass
from typing import Dict, List, Literal, Optional


@dataclass
class RoutingIssue:
    kind: Literal["contradiction", "overlap", "gap"]
    routes: List[str]
    message: str
    details: Dict[str, bool]


def verify_routing(
    conditions: Dict[str, str], 
    raise_on_issues: bool = False
) -> List[RoutingIssue]:
    """Deterministically validates conditional graph branching logic using boolean satisfiability."""
    try:
        from boolean_algebra_engine import Expression, Solver
    except ImportError as e:
        raise ImportError(
            "The `verify_routing` feature requires the `boolean-algebra-engine` library. "
            "Please install it using: pip install boolean-algebra-engine"
        ) from e

    issues: List[RoutingIssue] = []
    parsed_routes: Dict[str, Expression] = {}

    # Strict token parser mapping matching your precise token spec:
    # "TOOL_CALL . !HUMAN" -> Expression("TOOL_CALL") & ~Expression("HUMAN")
    for route_name, expr_str in conditions.items():
        try:
            # Clean spaces and translate symbols to algebraic engine syntax expectations
            normalized = expr_str.replace("!", " ~").replace(".", " & ")
            parsed_routes[route_name] = Expression.parse(normalized)
        except Exception as parse_err:
            if raise_on_issues:
                raise ValueError(f"Failed to parse algebraic rule for route '{route_name}': {expr_str}") from parse_err
            continue

    route_names = list(parsed_routes.keys())

    # 1. Contradictions Check
    for name, expr in parsed_routes.items():
        if not Solver.is_satisfiable(expr):
            issues.append(RoutingIssue(
                kind="contradiction",
                routes=[name],
                message=f"Route '{name}' contains a logical contradiction and can never be traversed.",
                details={}
            ))

    # 2. Overlaps Check
    for i in range(len(route_names)):
        for j in range(i + 1, len(route_names)):
            r1, r2 = route_names[i], route_names[j]
            overlap_expr = parsed_routes[r1] & parsed_routes[r2]
            
            if Solver.is_satisfiable(overlap_expr):
                issues.append(RoutingIssue(
                    kind="overlap",
                    routes=[r1, r2],
                    message=f"Ambiguous routing boundary: routes '{r1}' and '{r2}' can hold simultaneously.",
                    details=Solver.get_assignment(overlap_expr)
                ))

    # 3. Gaps Check
    if parsed_routes:
        combined_coverage = None
        for expr in parsed_routes.values():
            if combined_coverage is None:
                combined_coverage = expr
            else:
                combined_coverage = combined_coverage | expr
        
        gap_expr = ~combined_coverage
        if Solver.is_satisfiable(gap_expr):
            issues.append(RoutingIssue(
                kind="gap",
                routes=route_names,
                message="Unhandled states detected: certain variable assignments are not covered by any route.",
                details=Solver.get_assignment(gap_expr)
            ))

    if raise_on_issues and issues:
        raise ValueError(f"Routing integrity check failed! Detected {len(issues)} logic configuration structural flaws.")

    return issues