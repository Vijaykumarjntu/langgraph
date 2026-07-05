from typing import Any, Dict, Optional, Mapping
from langchain_core.runnables import RunnableConfig

class AssistantContextBoundGraph:
    """A public wrapper that attaches persistent, run-scoped assistant context 
    directly to a compiled graph instance.
    
    This eliminates the need for hosting servers to sneak non-Runtime instances 
    into the private `__pregel_runtime` configuration slots.
    """
    
    def __init__(self, compiled_graph: Any, context: Optional[Mapping[str, Any]] = None):
        self.graph = compiled_graph
        # Expose store parity if attached to the underlying graph object
        self.store = getattr(compiled_graph, "store", None)
        # Bind the persistent assistant/graph-level context dictionary
        self._bound_context = dict(context) if context else {}

    @property
    def bound_context(self) -> Dict[str, Any]:
        """Public getter to inspect the assistant-level context assigned to this graph."""
        return self._bound_context

    def _prepare_config(self, config: Optional[RunnableConfig]) -> RunnableConfig:
        """Merges graph-bound context into the execution config safely."""
        runtime_config = dict(config) if config else {}
        
        # Pull or initialize standard context tracking keys publicly
        current_context = runtime_config.get("context", {})
        if not isinstance(current_context, dict):
            current_context = {}
            
        # Merge graph-bound context values. Explicit invoke-level context overrides 
        # graph-bound values if there's a key collision.
        merged_context = {**self._bound_context, **current_context}
        
        runtime_config["context"] = merged_context
        return runtime_config

    def invoke(self, input_payload: Any, config: Optional[RunnableConfig] = None, **kwargs: Any) -> Any:
        """Executes the graph workflow, injecting the public bound context."""
        secured_config = self._prepare_config(config)
        return self.graph.invoke(input_payload, config=secured_config, **kwargs)

    async def ainvoke(self, input_payload: Any, config: Optional[RunnableConfig] = None, **kwargs: Any) -> Any:
        """Asynchronously executes the graph workflow, injecting the public bound context."""
        secured_config = self._prepare_config(config)
        return await self.graph.ainvoke(input_payload, config=secured_config, **kwargs)

    def stream(self, input_payload: Any, config: Optional[RunnableConfig] = None, **kwargs: Any) -> Any:
        """Streams graph execution updates, injecting the public bound context."""
        secured_config = self._prepare_config(config)
        return self.graph.stream(input_payload, config=secured_config, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Delegates all other standard pregel attributes and inspection APIs to the underlying graph."""
        return getattr(self.graph, name)