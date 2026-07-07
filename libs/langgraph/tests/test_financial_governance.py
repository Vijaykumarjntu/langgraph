import pytest
from langgraph.utils.governance import FinancialControlGate


def test_gate_allows_valid_transaction():
    gate = FinancialControlGate(daily_ceiling=500.0, max_tx_per_minute=3, allowed_recipients=["0xMerxexEscrow"])
    
    state = {
        "transaction_amount": 50.0,
        "recipient_address": "0xMerxexEscrow",
        "daily_spend_accumulator": 100.0,
        "recent_transaction_timestamps": [],
        "gate_verdict": "ALLOW"
    }
    
    result = gate(state)
    assert result["gate_verdict"] == "ALLOW"
    assert result["daily_spend_accumulator"] == 150.0


def test_gate_denies_poisoned_recipient():
    gate = FinancialControlGate(daily_ceiling=500.0, max_tx_per_minute=3, allowed_recipients=["0xMerxexEscrow"])
    
    state = {
        "transaction_amount": 50.0,
        "recipient_address": "0xMaliciousInjectionTarget",
        "daily_spend_accumulator": 0.0,
        "recent_transaction_timestamps": [],
        "gate_verdict": "ALLOW"
    }
    
    result = gate(state)
    assert result["gate_verdict"] == "DENY"