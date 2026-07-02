from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any, Optional

from langgraph.store.base import (
    BaseStore,
    GetOp,
    Item,
    ListNamespacesOp,
    Op,
    PutOp,
    Result,
    SearchItem,
    SearchOp,
)

logger = logging.getLogger(__name__)

class MimirStore(BaseStore):
    """Mimir-backed store with built-in zero-dependency encrypted memory and hybrid search."""

    def __init__(self, db_path: str = "./mimir_memory.db", binary_path: str = "mimir") -> None:
        self.db_path = db_path
        self.binary_path = binary_path
        self._process: Optional[subprocess.Popen] = None

    def start(self) -> None:
        """Ensures the Mimir MCP server subprocess is active via stdio."""
        if not self._process or self._process.poll() is not None:
            self._process = subprocess.Popen(
                [self.binary_path, "serve", "--db", self.db_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True
            )

    def stop(self) -> None:
        """Gracefully shuts down the Mimir daemon subprocess."""
        if self._process:
            self._process.terminate()
            self._process.wait()
            self._process = None

    def _call_mimir_rpc(self, method: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Low-level JSON-RPC client to dispatch instructions over stdio."""
        self.start()
        
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": method,
                "arguments": arguments
            }
        }
        
        try:
            self._process.stdin.write(json.dumps(request) + "\n")
            self._process.stdin.flush()
            
            response_line = self._process.stdout.readline()
            if not response_line:
                raise RuntimeError("Mimir backend crashed or disconnected unexpectedly.")
                
            response = json.loads(response_line)
            if "error" in response:
                raise RuntimeError(f"Mimir RPC Engine returned an error: {response['error']}")
                
            # Mimir returns text tool outputs usually in a content array
            result = response.get("result", {})
            return result
        except Exception as e:
            logger.error(f"Failed communicating with Mimir backend: {e}")
            raise e

    def batch(self, ops: Iterable[Op]) -> list[Result]:
        """Execute atomic batch commands synchronously."""
        results: list[Result] = []
        for op in ops:
            results.append(self._execute_op(op))
        return results

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        """Execute atomic batch commands asynchronously using a thread pool runner."""
        loop = asyncio.get_running_loop()
        # Offload the blocking stdio operations to a worker pool safely
        return await loop.run_in_executor(None, self.batch, ops)

    def _execute_op(self, op: Op) -> Result:
        """Routes a LangGraph operation to the correct Mimir RPC call."""
        if isinstance(op, GetOp):
            return self._handle_get(op)
        elif isinstance(op, PutOp):
            return self._handle_put(op)
        elif isinstance(op, SearchOp):
            return self._handle_search(op)
        elif isinstance(op, ListNamespacesOp):
            return self._handle_list_namespaces(op)
        else:
            raise ValueError(f"Unknown operation type: {type(op)}")

    # --- Operation Handlers ---

    def _handle_get(self, op: GetOp) -> Optional[Item]:
        # Serialize the tuple namespace to a predictable string format for Mimir
        ns_str = ".".join(op.namespace)
        res = self._call_mimir_rpc("mimir_recall", {"namespace": ns_str, "key": op.key})
        
        # if not res or "item" Packs missing logic or data check: # (Placeholder logic depends on exact tools schema)
        #     return None

        if not res or "value" not in res:
            return None
            
        # Example conversion back to LangGraph Item
        return Item(
            namespace=op.namespace,
            key=op.key,
            value=res["value"],
            created_at=datetime.fromisoformat(res["created_at"]),
            updated_at=datetime.fromisoformat(res["updated_at"])
        )

    def _handle_put(self, op: PutOp) -> None:
        ns_str = ".".join(op.namespace)
        if op.value is None:
            # Delete execution path
            self._call_mimir_rpc("mimir_forget", {"namespace": ns_str, "key": op.key})
        else:
            # Store execution path
            self._call_mimir_rpc("mimir_remember", {
                "namespace": ns_str,
                "key": op.key,
                "value": op.value
            })
        return None

    def _handle_search(self, op: SearchOp) -> list[SearchItem]:
        ns_prefix = ".".join(op.namespace_prefix)
        # Pass queries directly down to Mimir's built-in vector/hybrid processing
        res = self._call_mimir_rpc("mimir_search", {
            "namespace_prefix": ns_prefix,
            "query": op.query,
            "limit": op.limit,
            "offset": op.offset,
            "filters": op.filter
        })
        
        search_items = []
        for match in res.get("matches", []):
            search_items.append(
                SearchItem(
                    namespace=tuple(match["namespace"].split(".")),
                    key=match["key"],
                    value=match["value"],
                    created_at=datetime.fromisoformat(match["created_at"]),
                    updated_at=datetime.fromisoformat(match["updated_at"]),
                    score=match.get("score")
                )
            )
        return search_items

    def _handle_list_namespaces(self, op: ListNamespacesOp) -> list[tuple[str, ...]]:
        res = self._call_mimir_rpc("mimir_list_namespaces", {
            "max_depth": op.max_depth,
            "limit": op.limit,
            "offset": op.offset
        })
        return [tuple(ns.split(".")) for ns in res.get("namespaces", [])]