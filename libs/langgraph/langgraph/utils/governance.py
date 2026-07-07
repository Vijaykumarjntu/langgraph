import time
from typing import Any, Dict, List, Literal, TypedDict


class FinancialState(TypedDict):
    transaction_amount: float
    recipient_address: str
    daily_spend_accumulator: float
    recent_transaction_timestamps: List[float]
    gate_verdict: Literal["ALLOW", "REFER", "DENY"]


class FinancialControlGate:
    """Deterministic validation guardrail to prevent budget exhaustion and address spoofing."""
    
    def __init__(self, daily_ceiling: float, max_tx_per_minute: int, allowed_recipients: List[str]):
        self.daily_ceiling = daily_ceiling
        self.max_tx_per_minute = max_tx_per_minute
        self.allowed_recipients = allowed_recipients

    def __call__(self, state: FinancialState) -> Dict[str, Any]:
        current_time = time.time()
        
        # 1. Recipient Address Poisoning Guardrail
        if state["recipient_address"] not in self.allowed_recipients:
            return {"gate_verdict": "DENY"}
            
        # 2. Daily Cumulative Budget Ceiling Check
        if state["daily_spend_accumulator"] + state["transaction_amount"] > self.daily_ceiling:
            return {"gate_verdict": "REFER"}  # Escalate to human review branch
            
        # 3. Micro-transaction Loop/Rate Velocity Throttling
        one_minute_ago = current_time - 60.0
        active_timestamps = [t for t in state["recent_transaction_timestamps"] if t > one_minute_ago]
        
        if len(active_timestamps) >= self.max_tx_per_minute:
            return {"gate_verdict": "DENY"}
            
        return {
            "gate_verdict": "ALLOW",
            "daily_spend_accumulator": state["daily_spend_accumulator"] + state["transaction_amount"],
            "recent_transaction_timestamps": active_timestamps + [current_time]
        }