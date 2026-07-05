import pytest
from langgraph.prebuilt.encryption_registry import EncryptionContextManager, CryptographicContextError


def test_valid_async_context_handler_succeeds():
    """Confirms a proper two-parameter async function passes registration seamlessly."""
    manager = EncryptionContextManager()
    
    async def valid_handler(user: str, ctx: dict):
        return {"derived_secret": f"sec_{user}"}

    manager.register_context_handler("vault_scope", valid_handler)
    assert manager.get_context_handler("vault_scope") is not None


def test_sync_context_handler_raises_error():
    """Confirms that registering a synchronous context function raises an immediate error."""
    manager = EncryptionContextManager()
    
    def invalid_sync_handler(user: str, ctx: dict):
        return {"secret": "insecure_blocking"}

    with pytest.raises(CryptographicContextError, match="must be an asynchronous coroutine function"):
        manager.register_context_handler("vault_scope", invalid_sync_handler)


def test_wrong_arity_context_handler_raises_error():
    """Confirms that any function missing or exceeding the required (user, ctx) parameters is caught."""
    manager = EncryptionContextManager()
    
    # Missing parameters completely
    async def empty_handler():
        return {}

    # Too many parameters
    async def overly_verbose_handler(user: str, ctx: dict, extra_param: str):
        return {}

    with pytest.raises(CryptographicContextError, match="wrong arity.*Expected exactly 2 positional arguments"):
        manager.register_context_handler("vault_scope", empty_handler)

    with pytest.raises(CryptographicContextError, match="wrong arity.*Expected exactly 2 positional arguments"):
        manager.register_context_handler("vault_scope", overly_verbose_handler)