import functools
import inspect
from typing import Any, Dict, List, Literal, Set, Tuple, Callable


class SemanticConflictError(Exception):
    """Raised when parallel executing nodes violate task-level invariants at dispatch time."""
    pass


def node(writes: List[str]):
    """Decorator to declare semantic write intents directly on graph nodes.
    
    Supports key syntax operators:
    - 'key' (exclusive write lockout)
    - 'key.append' (additive, shared ok)
    - 'key.read_then_write' (strict state isolation barrier)
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        # Attach intent metadata explicitly onto the target execution payload
        setattr(wrapper, "__write_intents__", writes)
        return wrapper
    return decorator


class SemanticSuperstepAdmission:
    """Evaluates task-level write invariants before admitting scheduled branches 
    into the active Pregel execution loop frame.
    """
    def __init__(self, policy: Literal["refuse", "queue", "warn"] = "refuse"):
        self.policy = policy
        self.in_flight_intent_set: Dict[str, str] = {}  # channel -> node_name

    def admit_batch(self, pending_tasks: List[Callable]) -> Tuple[List[Callable], List[Dict[str, Any]]]:
        """Scans pending sends, evaluates collisions against the active policy, 
        and filters what can run in the current superstep vs what gets deferred.
        """
        admitted_tasks: List[Callable] = []
        deferred_tasks: List[Callable] = []
        conflict_logs: List[Dict[str, Any]] = []

        for task in pending_tasks:
            node_name = getattr(task, "__name__", str(task))
            intents = getattr(task, "__write_intents__", [])
            has_conflict = False
            conflicting_channel = None
            owner_node = None

            for intent in intents:
                # 1. Parse channel-key semantic syntax rules
                if intent.endswith(".append"):
                    # Additive intents skip exclusive collision tracking
                    continue
                
                base_channel = intent.split(".")[0]
                
                # 2. Check for active ownership conflicts
                if base_channel in self.in_flight_intent_set:
                    has_conflict = True
                    conflicting_channel = base_channel
                    owner_node = self.in_flight_intent_set[base_channel]
                    break

            if has_conflict:
                log_entry = {
                    "node": node_name,
                    "conflicting_channel": conflicting_channel,
                    "held_by": owner_node,
                    "action": self.policy
                }
                conflict_logs.append(log_entry)

                if self.policy == "refuse":
                    raise SemanticConflictError(
                        f"Admission refused! Parallel Node '{node_name}' conflicts with '{owner_node}' "
                        f"on state channel '{conflicting_channel}'."
                    )
                elif self.policy == "queue":
                    deferred_tasks.append(task)
                    continue
                elif self.policy == "warn":
                    # Log the overlap and fall through to admit anyway
                    pass

            # Claim the channels for the duration of this superstep block
            for intent in intents:
                base_channel = intent.split(".")[0]
                if not intent.endswith(".append"):
                    self.in_flight_intent_set[base_channel] = node_name
                    
            admitted_tasks.append(task)

        return admitted_tasks, conflict_logs

    def auto_release(self) -> None:
        """Flushes all entries cleanly at superstep completion boundaries."""
        self.in_flight_intent_set.clear()