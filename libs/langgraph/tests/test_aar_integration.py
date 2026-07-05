import pytest
from langgraph.graph.aar_protocol import AAREngine
from langgraph.graph.aar_callbacks import AARCallbackHandler


def test_asymmetric_aar_chaining_and_tampering():
    engine = AAREngine()
    handler = AARCallbackHandler(engine)

    mock_input = {"query_balance": "acc_901"}
    mock_output = {"status": "SUCCESS", "cleared_funds": 12500.0}

    # Simulate node execution callback cycle
    handler.on_chain_start({}, mock_input, name="ledger-node")
    handler.on_chain_end(mock_output, name="ledger-node")

    assert len(handler.emitted_receipts) == 1
    receipt = handler.emitted_receipts[0]

    # Verify formatting constraints match the spec exactly
    assert "receiptId" in receipt
    assert receipt["inputHash"].startswith("sha256-")
    assert receipt["outputHash"].startswith("sha256-")
    assert receipt["timestamp"].endswith("Z")

    # Offline validation passes cleanly with public key validation
    pub_key = engine.verify_key.encode()
    assert AAREngine.verify_receipt(receipt, pub_key) is True

    # Confirm tampering causes immediate failure
    tampered_receipt = receipt.copy()
    tampered_receipt["outputHash"] = "sha256-FORGED_HASH_MUTATION"
    assert AAREngine.verify_receipt(tampered_receipt, pub_key) is False


def test_session_continuity_certificate_chaining():
    engine = AAREngine()
    handler = AARCallbackHandler(engine)

    # First Node execution bound block
    handler.on_chain_start({}, {"step": 1}, name="node-1")
    handler.on_chain_end({"data": "alpha"}, name="node-1")

    # Second Dependent Node execution bound block
    handler.on_chain_start({}, {"step": 2}, name="node-2")
    handler.on_chain_end({"data": "beta"}, name="node-2")

    assert len(handler.emitted_receipts) == 2
    r1 = handler.emitted_receipts[0]
    r2 = handler.emitted_receipts[1]

    # Confirm correct pedigree tracking sequence
    assert r2["parentCertificate"] == r1["signature"]