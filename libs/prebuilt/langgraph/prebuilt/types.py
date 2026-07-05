from dataclasses import dataclass, field
from typing import Any, Literal, Tuple, Optional


@dataclass
class Interrupt:
    """Information about a graph suspension boundary that occurred inside an active node."""
    value: Any
    id: str = field(default_factory=lambda: f"int_{uuid.uuid4().hex[:12]}")
    # Additive field to discriminate between human intervention and programmatic data fulfillment
    kind: Literal["human", "fetch"] = "human" 


@dataclass
class PregelTask:
    """Represents a scheduled state node task inside the Pregel runtime execution engine."""
    id: str
    name: str
    path: Tuple[str, ...]
    error: Optional[BaseException] = None
    interrupts: Tuple[Interrupt, ...] = field(default_factory=tuple)
    state: Optional[Any] = None
    result: Optional[Any] = None

    @property
    def fetches(self) -> Tuple[Interrupt, ...]:
        """Exposes only the programmatic service-to-service data dependency constraints."""
        return tuple(i for i in self.interrupts if i.kind == "fetch")

    @property
    def human_interrupts(self) -> Tuple[Interrupt, ...]:
        """Exposes standard human-in-the-loop escalation tasks."""
        return tuple(i for i in self.interrupts if i.kind == "human")

import uuid

class GraphInterrupt(Exception):
    """Signals to the core Pregel driver loop to suspend execution."""
    def __init__(self, interrupts: Tuple[Interrupt, ...]):
        self.interrupts = interrupts
        super().__init__("Graph execution suspended.")


def fetch(request_payload: Any) -> Any:
    """Convenience function that pauses execution for service-to-service dependency fulfillment.
    
    Thinly wraps the core interrupt signaling loop while hardcoding kind='fetch' 
    so upstream tools and LangGraph Server can route it cleanly.
    """
    interrupt_id = f"fch_{uuid.uuid4().hex[:12]}"
    new_fetch_interrupt = Interrupt(
        value=request_payload,
        id=interrupt_id,
        kind="fetch"
    )
    
    # Standard pregel interception mechanism
    raise GraphInterrupt((new_fetch_interrupt,))