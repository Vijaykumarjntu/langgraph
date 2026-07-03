from __future__ import annotations
import json
import base64
import hmac
import hashlib
import re
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
        binary_path: str = "perseus",secret_key: str = "secure_fallback_key_change_me",
        max_payload_bytes: int = 5 * 1024 * 1024
    ) -> None:
        super().__init__(serde=serde)
        self._given_binary_path = binary_path
        self._resolved_binary_path: Optional[str] = None
        self._process: Optional[subprocess.Popen] = None
        self.secret_key = secret_key.encode("utf-8")
        self.max_payload_bytes = max_payload_bytes  # 5MB Threshold Bound
        # Regex to intercept common adversarial injection payloads or hidden instructions
        self.poison_pattern = re.compile(
            r"(ignore previous instructions|system prompt override|assistant state:|\[system\])", 
            re.IGNORECASE
        )

    def _generate_signature(self, payload_str: str) -> str:
        """Generates an HMAC-SHA256 signature for a given text string."""
        return hmac.new(self.secret_key, payload_str.encode("utf-8"), hashlib.sha256).hexdigest()

    def _verify_payload(self, payload_str: str, signature: Optional[str]) -> bool:
        """Safely verifies the signature to mitigate timing attacks."""
        if not signature:
            return False
        expected = self._generate_signature(payload_str)
        return hmac.compare_digest(expected, signature)

    def _validate_structural_integrity(self, checkpoint: Any) -> None:
        """Enforces OWASP ASI06 state structural validation rules."""
        if not isinstance(checkpoint, dict):
            raise ValueError("[OWASP SECURITY VIOLATION] Malformed checkpoint structure: Must be a dictionary.")
        
        # Verify required LangGraph base primitives
        required_keys = {"v", "ts", "id", "channel_values"}
        missing_keys = required_keys - checkpoint.keys()
        if missing_keys:
            raise ValueError(f"[OWASP SECURITY VIOLATION] Poisoned schema: Missing core keys {missing_keys}")

        # Deep content sanitization on agent state values
        channel_values = checkpoint.get("channel_values", {})
        if not isinstance(channel_values, dict):
            raise ValueError("[OWASP SECURITY VIOLATION] Poisoned channel state structure.")

        for key, value in channel_values.items():
            # Check for prompt injection strings hiding in memory variables
            if isinstance(value, str) and self.poison_pattern.search(value):
                raise ValueError(f"[OWASP SECURITY VIOLATION] Prompt injection vector detected in memory channel: '{key}'")

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

        chk_raw = res["checkpoint"]
        meta_raw = res.get("metadata", "")
        
        # 1. Size Threshold Validation (DoS Prevention)
        if len(chk_raw) > self.max_payload_bytes or len(meta_raw) > self.max_payload_bytes:
            raise ValueError("[OWASP SECURITY VIOLATION] Payload limit exceeded. Dropping request to prevent DoS.")

        # --- VALIDATION GUARD: ANTI-POISONING ---
        if not self._verify_payload(chk_raw, res.get("checkpoint_sig")) or \
           not self._verify_payload(meta_raw, res.get("metadata_sig")):
            raise ValueError("[SECURITY ALARM] Checkpoint or Metadata signature verification failed! Possible poisoning attack detected.")
        # ----------------------------------------

        # Decode base64 strings back to the original binary bytes
        checkpoint_bytes = base64.b64decode(res["checkpoint"]) if isinstance(res["checkpoint"], str) else res["checkpoint"]
        metadata_bytes = base64.b64decode(res.get("metadata", "")) if isinstance(res.get("metadata"), str) else res.get("metadata", b"")

        # Reconstruct using the type string ("json" or "msgpack") and raw bytes
        checkpoint = self.serde.loads_typed((res.get("checkpoint_type", "msgpack"), checkpoint_bytes))
        metadata = self.serde.loads_typed((res.get("metadata_type", "msgpack"), metadata_bytes))
        # checkpoint = self.serde.loads(checkpoint_bytes)

        # 3. Structural and Semantic Memory Validation
        self._validate_structural_integrity(checkpoint)
        
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
            chk_raw = entry["checkpoint"]
            meta_raw = entry.get("metadata", "")
            print("now we are inside the list function and printing the checkpoint and metadata raw values:")
            print(f"Checkpoint raw: {chk_raw}")
            print(f"Metadata raw: {meta_raw}")
            # --- VALIDATION GUARD: ANTI-POISONING ---
            if not self._verify_payload(chk_raw, entry.get("checkpoint_sig")) or \
               not self._verify_payload(meta_raw, entry.get("metadata_sig")):
                raise ValueError("[SECURITY ALARM] Historical Checkpoint corruption or signature failure encountered.")
            # ----------------------------------------

            chk_bytes = base64.b64decode(entry["checkpoint"]) if isinstance(entry["checkpoint"], str) else entry["checkpoint"]
            meta_bytes = base64.b64decode(entry.get("metadata", "")) if isinstance(entry.get("metadata"), str) else entry.get("metadata", b"")
            yield CheckpointTuple(
                config={"configurable": {"thread_id": entry["thread_id"], "checkpoint_id": entry["checkpoint_id"]}},
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

        # dumps_typed returns a tuple: (type_string, binary_bytes)
        chk_type, chk_bytes = self.serde.dumps_typed(checkpoint)
        meta_type, meta_bytes = self.serde.dumps_typed(metadata)

        chk_b64 = base64.b64encode(chk_bytes).decode("ascii")
        meta_b64 = base64.b64encode(meta_bytes).decode("ascii")

        payload = {
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_id,
            "checkpoint": chk_b64,
            "checkpoint_sig": self._generate_signature(chk_b64),
            "checkpoint_type": chk_type,
            "metadata": meta_b64,
            "metadata_sig": self._generate_signature(meta_b64),
            "metadata_type": meta_type,
            "parent_id": config["configurable"].get("parent_id"),
        }
        self._call_perseus("context/save", payload)
        return {"configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}}