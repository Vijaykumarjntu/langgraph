import pytest
import json
from langgraph.graph.canonicalization import canonicalize_graph_topology


def test_conditional_edge_priority_is_preserved():
    """Confirms that dictionary serialization preserves sequential branch order."""
    mock_nodes = {"agent_node": lambda s: s, "tools_node": lambda s: s}
    mock_static_edges = [("agent_node", "tools_node")]
    
    # Define an explicit priority routing structure (e.g., fallback evaluation order)
    priority_conditional_edges = {
        "agent_node": {
            "MATCH_FIRST_PRIORITY": "high_tier_handler",
            "MATCH_SECOND_PRIORITY": "mid_tier_handler",
            "DEFAULT_FALLBACK": "base_handler"
        }
    }

    serialized_1 = canonicalize_graph_topology(mock_nodes, mock_static_edges, priority_conditional_edges)
    
    # Simulate a deep network serialization trip (JSON round-tripping)
    json_string = json.dumps(serialized_1, indent=2)
    deserialized = json.loads(json_string)

    # Extract the reassembled route sequence
    extracted_branches = deserialized["conditional_edges"]["agent_node"]

    assert extracted_branches[0]["condition_key"] == "MATCH_FIRST_PRIORITY"
    assert extracted_branches[1]["condition_key"] == "MATCH_SECOND_PRIORITY"
    assert extracted_branches[2]["condition_key"] == "DEFAULT_FALLBACK"