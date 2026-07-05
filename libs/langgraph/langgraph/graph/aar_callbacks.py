from typing import Any, Dict, List, Optional
from langchain_core.callbacks import BaseCallbackHandler
from langgraph.graph.aar_protocol import AAREngine


class AARCallbackHandler(BaseCallbackHandler):
    """Automated framework hook that captures and signs state changes at node boundaries."""
    def __init__(self, aar_engine: AAREngine):
        self.engine = aar_engine
        self.emitted_receipts: List[Dict[str, Any]] = []
        self._last_signature: Optional[str] = None

    def on_chain_start(
        self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs: Any
    ) -> None:
        self._current_input = inputs

    def on_chain_end(self, outputs: Dict[str, Any], **kwargs: Any) -> None:
        # Detect if we are crossing an execution node bound
        agent_name = kwargs.get("name", "langgraph-node")
        
        receipt = self.engine.generate_receipt(
            agent_node=agent_name,
            action="execute_node_transition",
            node_input=self._current_input,
            node_output=outputs,
            parent_signature=self._last_signature
        )
        
        self._last_signature = receipt["signature"]
        self.emitted_receipts.append(receipt)