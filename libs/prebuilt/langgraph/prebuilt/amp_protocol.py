import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Union, Callable
from pydantic import BaseModel, Field


class AMPEnvelope(BaseModel):
    """Standardized cross-framework tracking metadata."""
    message_id: str = Field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:12]}")
    correlation_id: str = Field(default_factory=lambda: f"corr_{uuid.uuid4().hex[:12]}")
    sender: str = Field(..., description="The ID of the originating framework agent node.")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class AMPMessageEnvelope(BaseModel):
    """The uniform message envelope that translates between foreign frameworks and LangGraph."""
    envelope: AMPEnvelope
    payload: Dict[str, Any] = Field(..., description="The raw execution state payload.")


class AMPAgentHost:
    """Wraps any CompiledStateGraph to make it instantly AMP discoverable and interoperable."""
    
    def __init__(
        self, 
        agent_graph: Any, 
        agent_id: str, 
        description: str,
        input_validator: Optional[Callable[[str], str]] = None
    ):
        self.graph = agent_graph
        self.agent_id = agent_id
        self.description = description
        self.input_validator = input_validator

    def get_discovery_manifest(self) -> Dict[str, Any]:
        """Returns the public service schema so other frameworks (AutoGen, CrewAI) can discover it."""
        return {
            "amp_version": "1.0.0",
            "agent_id": self.agent_id,
            "description": self.description,
            "supported_roles": ["user", "system"],
            "content_type": "application/json"
        }

    def process_message(self, raw_amp_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Translates an external framework message, runs it through LangGraph, and maps it back."""
        # Parse and validate against the AMP standard format
        amp_msg = AMPMessageEnvelope.model_validate(raw_amp_payload)
        
        user_content = amp_msg.payload.get("content", "")
        
        # Optional: Intercept with our security hooks if provided
        if self.input_validator:
            user_content = self.input_validator(user_content)
            
        # Map to native LangGraph input state dictionaries
        langgraph_input = {
            "messages": [{"role": "user", "content": user_content}]
        }
        
        # Inject thread/correlation tracking natively into the execution runtime
        config = {"configurable": {"thread_id": amp_msg.envelope.correlation_id}}
        
        # Execute the Graph run loop
        graph_output = self.graph.invoke(langgraph_input, config=config)
        last_msg = graph_output["messages"][-1]
        
        # Extract response text content safely
        response_text = last_msg.content if hasattr(last_msg, 'content') else str(last_msg)
        
        # Repackage output back into the cross-framework message envelope standard
        response_envelope = AMPMessageEnvelope(
            envelope=AMPEnvelope(
                correlation_id=amp_msg.envelope.correlation_id,
                sender=self.agent_id
            ),
            payload={
                "role": "assistant",
                "content": response_text
            }
        )
        
        return response_envelope.model_dump()