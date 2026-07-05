import pytest
from unittest.mock import MagicMock
from langgraph.prebuilt.run_context import AssistantContextBoundGraph

def test_assistant_context_binding_resolution():
    """Validates that assistant-level context merges cleanly into run-scoped configurations."""
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {"status": "success"}
    
    assistant_metadata = {
        "server_runtime_id": "srv_992x",
        "billing_tier": "enterprise"
    }
    
    # Bind context at the graph/assistant level
    bound_graph = AssistantContextBoundGraph(mock_graph, context=assistant_metadata)
    
    # Execute an invoke run with additional run-scoped parameters
    bound_graph.invoke(
        {"messages": []}, 
        config={"configurable": {"thread_id": "1"}, "context": {"trace_id": "trc_111"}}
    )
    
    # Assert that the underlying invoke received the cleanly merged context dictionary
    called_config = mock_graph.invoke.call_args[1]["config"]
    assert "context" in called_config
    assert called_config["context"]["server_runtime_id"] == "srv_992x"
    assert called_config["context"]["billing_tier"] == "enterprise"
    assert called_config["context"]["trace_id"] == "trc_111"