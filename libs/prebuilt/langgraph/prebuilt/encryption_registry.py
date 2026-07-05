import inspect
from typing import Any, Callable, Dict, Optional, Tuple


class CryptographicContextError(Exception):
    """Raised when an encryption context handler fails parameter or structural signature 
    inspections at registration time.
    """
    pass


class EncryptionContextManager:
    """Manages secure run-scoped context mappings with strict registration-time arity 
    and asynchronous interface validation.
    """
    
    def __init__(self):
        self._context_handlers: Dict[str, Callable] = {}

    def register_context_handler(self, context_key: str, handler_fn: Callable) -> None:
        """Registers an encryption context generation handler.
        
        Validates the handler immediately to ensure it matches the required (user, ctx) 
        signature boundaries and runs asynchronously.
        """
        # 1. Enforce that context handlers operate non-blockingly via asyncio
        if not inspect.iscoroutinefunction(handler_fn):
            raise CryptographicContextError(
                f"Registration rejected for context key '{context_key}': "
                f"Handler must be an asynchronous coroutine function (async def)."
            )

        # 2. Extract signature configuration metrics
        sig = inspect.signature(handler_fn)
        params = list(sig.parameters.values())
        
        # Count non-default parameters
        required_params = [
            p for p in params 
            if p.default == inspect.Parameter.empty and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.POSITIONAL_ONLY)
        ]

        # Enforce strict context arity matching the explicit (user, ctx) contract
        if len(required_params) != 2:
            raise CryptographicContextError(
                f"Registration rejected for context key '{context_key}': "
                f"Handler has wrong arity. Expected exactly 2 positional arguments (user, ctx), "
                f"got {len(required_params)} parameters."
            )

        # 3. Safe registration admission after signature clearing
        self._context_handlers[context_key] = handler_fn

    def get_context_handler(self, context_key: str) -> Optional[Callable]:
        """Retrieves a fully validated context handler."""
        return self._context_handlers.get(context_key)