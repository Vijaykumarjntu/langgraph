from typing import Any, Dict, List, Tuple, Union


def canonicalize_graph_topology(
    nodes: Dict[str, Any], 
    edges: List[Tuple[str, str]], 
    conditional_edges: Dict[str, Dict[str, str]]
) -> Dict[str, Any]:
    """Ensures structural edge arrays and conditional routing rules preserve their order.
    
    Prevents dictionary sorting transformations from breaking execution priorities 
    during serialization cycles.
    """
    # 1. Sort nodes alphabetically to ensure consistent dictionary entry matching
    sorted_nodes = sorted(list(nodes.keys()))
    
    # 2. Sort simple edges systematically by (source, destination) coordinates
    sorted_static_edges = sorted(edges, key=lambda edge: (edge[0], edge[1]))
    
    # 3. Canonicalize conditional edges while strictly preserving internal router order
    canonical_conditional_map: Dict[str, List[Dict[str, str]]] = {}
    
    for source_node, path_map in conditional_edges.items():
        # Keep the array sequential priority exactly as configured by the builder
        ordered_branches: List[Dict[str, str]] = []
        for key, target in path_map.items():
            ordered_branches.append({"condition_key": key, "target_destination": target})
        
        canonical_conditional_map[source_node] = ordered_branches

    return {
        "nodes": sorted_nodes,
        "static_edges": sorted_static_edges,
        "conditional_edges": canonical_conditional_map
    }