from __future__ import annotations

import json
import base64
# ... other existing imports (typing, langgraph, etc.)
import logging
import shutil
import subprocess
from collections.abc import Iterator
from typing import Any, Optional

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    SerializerProtocol,
)

logger = logging.getLogger(__name__)


class PerseusCheckpointer(BaseCheckpointSaver):
    """Perseus-backed live context engine checkpointer for tracking real-time graph states."""

    def __init__(
        self, 
        serde: Optional[SerializerProtocol] = None,
        binary_path: str = "perseus"
    ) -> None:
        super().__init__(serde=serde)
        self._given_binary_path = binary_path
        self._resolved_binary_path: Optional[str] = None
        self._process: Optional[subprocess.Popen] = None

    def _resolve_binary(self) -> str:
        if self._resolved_binary_path:
            return self._resolved_binary_path
        resolved = shutil.which(self._given_binary_path)
        if resolved:
            self._resolved_binary_path = resolved
            return resolved
        raise FileNotFoundError(f"Perseus engine binary '{self._given_binary_path}' not found on PATH.")

    def start(self) -> None:
        """Spawns the Perseus live context engine stream."""
        if not self._process or self._process.poll() is not None:
            binary = self._resolve_binary()
            self._process = subprocess.Popen(
                [binary, "stream-context"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )

    def _call_perseus(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.start()
        frame = {"jsonrpc": "2.0", "method": action, "params": payload, "id": 1}
        try:
            self._process.stdin.write(json.dumps(frame) + "\n")
            self._process.stdin.flush()
            line = self._process.stdout.readline()
            if not line:
                raise RuntimeError("Perseus background context stream died.")
            res = json.loads(line)
            if "error" in res:
                raise RuntimeError(f"Perseus Engine Error: {res['error']}")
            return res.get("result", {})
        except Exception as e:
            logger.error(f"Perseus tracking error: {e}")
            raise e

    def get_tuple(self, config: dict[str, Any]) -> Optional[CheckpointTuple]:
        """Fetches a specific live graph state tuple from the context engine."""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"].get("checkpoint_id")

        res = self._call_perseus("context/get", {"thread_id": thread_id, "checkpoint_id": checkpoint_id})
        if not res or "checkpoint" not in res:
            return None

        # Deserialize payloads safely back into LangGraph objects
        # checkpoint = self.serde.loads(res["checkpoint"])
        # metadata = self.serde.loads(res.get("metadata", "{}"))
        # checkpoint = self.serde.loads(res["checkpoint"].encode("utf-8") if isinstance(res["checkpoint"], str) else res["checkpoint"])
        # metadata = self.serde.loads(res.get("metadata", "{}").encode("utf-8") if isinstance(res.get("metadata"), str) else res.get("metadata", b"{}"))
        # parent_config = {"configurable": {"thread_id": thread_id, "checkpoint_id": res.get("parent_id")}} if res.get("parent_id") else None

        # Convert the textual JSON-RPC strings back to bytes for the serializer
        checkpoint_bytes = res["checkpoint"].encode("utf-8") if isinstance(res["checkpoint"], str) else res["checkpoint"]
        metadata_bytes = res.get("metadata", "{}").encode("utf-8") if isinstance(res.get("metadata"), str) else res.get("metadata", b"{}")

        # Decode base64 strings back to the original binary bytes
        checkpoint_bytes = base64.b64decode(res["checkpoint"]) if isinstance(res["checkpoint"], str) else res["checkpoint"]
        metadata_bytes = base64.b64decode(res.get("metadata", "")) if isinstance(res.get("metadata"), str) else res.get("metadata", b"")

        # Reconstruct using the type string ("json" or "msgpack") and raw bytes
        checkpoint = self.serde.loads_typed((res.get("checkpoint_type", "msgpack"), checkpoint_bytes))
        metadata = self.serde.loads_typed((res.get("metadata_type", "msgpack"), metadata_bytes))
        # checkpoint = self.serde.loads(checkpoint_bytes)
        # metadata = self.serde.loads(metadata_bytes)
        # loads_typed expects (type_string, bytes). Pass ("json", bytes) as fallback
        # checkpoint = self.serde.loads_typed(("json", checkpoint_bytes))
        # metadata = self.serde.loads_typed(("json", metadata_bytes))
        parent_config = {"configurable": {"thread_id": thread_id, "checkpoint_id": res.get("parent_id")}} if res.get("parent_id") else None

        return CheckpointTuple(
            config=config,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
        )

    def list(
        self,
        config: Optional[dict[str, Any]],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        """Lists historical active context ticks along the live timeline."""
        thread_id = config["configurable"]["thread_id"] if config else None
        payload = {"thread_id": thread_id, "limit": limit}
        if before:
            payload["before_id"] = before["configurable"].get("checkpoint_id")

        res = self._call_perseus("context/list", payload)
        for entry in res.get("checkpoints", []):
            # chk_bytes = entry["checkpoint"].encode("utf-8") if isinstance(entry["checkpoint"], str) else entry["checkpoint"]
            # meta_bytes = entry.get("metadata", "{}").encode("utf-8") if isinstance(entry.get("metadata"), str) else entry.get("metadata", b"{}")

            chk_bytes = base64.b64decode(entry["checkpoint"]) if isinstance(entry["checkpoint"], str) else entry["checkpoint"]
            meta_bytes = base64.b64decode(entry.get("metadata", "")) if isinstance(entry.get("metadata"), str) else entry.get("metadata", b"")
            yield CheckpointTuple(
                config={"configurable": {"thread_id": entry["thread_id"], "checkpoint_id": entry["checkpoint_id"]}},
                # checkpoint=self.serde.loads(entry["checkpoint"]),
                # metadata=self.serde.loads(entry.get("metadata", "{}")),
                # checkpoint=self.serde.loads(chk_bytes),
                # metadata=self.serde.loads(meta_bytes),  
                # checkpoint=self.serde.loads_typed(("json", chk_bytes)),
                # metadata=self.serde.loads_typed(("json", meta_bytes)),
                checkpoint=self.serde.loads_typed((entry.get("checkpoint_type", "msgpack"), chk_bytes)),
                metadata=self.serde.loads_typed((entry.get("metadata_type", "msgpack"), meta_bytes)),
                parent_config={"configurable": {"thread_id": entry["thread_id"], "checkpoint_id": entry.get("parent_id")}} if entry.get("parent_id") else None,
            )

    def put(
        self,
        config: dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict[str, Any],
    ) -> dict[str, Any]:
        """Commits an atomic execution tick snapshot into the context tracking space."""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"]["checkpoint_id"]

        # payload = {
        #     "thread_id": thread_id,
        #     "checkpoint_id": checkpoint_id,
        #     # "checkpoint": self.serde.dumps(checkpoint),
        #     # "metadata": self.serde.dumps(metadata),
        #     "checkpoint": self.serde.dumps(checkpoint).decode("utf-8"),
        #     "metadata": self.serde.dumps(metadata).decode("utf-8"),
        #     "parent_id": config["configurable"].get("parent_id"),
        # }

        # dumps_typed returns a tuple: (type_string, bytes)
        # We grab the bytes payload at index [1] and decode it
        # checkpoint_payload = self.serde.dumps_typed(checkpoint)[1].decode("utf-8")
        # metadata_payload = self.serde.dumps_typed(metadata)[1].decode("utf-8")
        # Decode the serialized binary data to plain strings for standard I/O framing

        # dumps_typed returns a tuple: (type_string, binary_bytes)
        chk_type, chk_bytes = self.serde.dumps_typed(checkpoint)
        meta_type, meta_bytes = self.serde.dumps_typed(metadata)
        payload = {
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_id,
            # "checkpoint": self.serde.dumps(checkpoint).decode("utf-8"),
            # "metadata": self.serde.dumps(metadata).decode("utf-8"),
            "checkpoint": base64.b64encode(chk_bytes).decode("ascii"),
            "checkpoint_type": chk_type,
            "metadata": base64.b64encode(meta_bytes).decode("ascii"),
            "metadata_type": meta_type,
            # "checkpoint": checkpoint_payload,
            # "metadata": metadata_payload,
            "parent_id": config["configurable"].get("parent_id"),
        }
        self._call_perseus("context/save", payload)
        return {"configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}}