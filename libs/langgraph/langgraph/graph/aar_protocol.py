import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid


class AAREngine:
    def __init__(self, private_key_bytes: Optional[bytes] = None):
        """Initializes the cryptographic signing boundary.
        Requires `pip install pynacl` for pure Ed25519 operations.
        """
        try:
            import nacl.signing
        except ImportError as e:
            raise ImportError(
                "The AAR implementation requires the `pynacl` library. "
                "Please install it using: pip install pynacl"
            ) from e

        if private_key_bytes:
            self.signing_key = nacl.signing.SigningKey(private_key_bytes)
        else:
            self.signing_key = nacl.signing.SigningKey.generate()
        
        self.verify_key = self.signing_key.verify_key

    @staticmethod
    def compute_sha256(data: Any) -> str:
        """Generates a PII-free SHA-256 fingerprint from deterministic state values."""
        serialized = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        return f"sha256-{hashlib.sha256(serialized).hexdigest()}"

    def generate_receipt(
        self, 
        agent_node: str, 
        action: str, 
        node_input: Any, 
        node_output: Any,
        parent_signature: Optional[str] = None
    ) -> Dict[str, Any]:
        """Constructs an offline-verifiable, PII-free cryptographic action token."""
        import nacl.encoding

        input_hash = self.compute_sha256(node_input)
        output_hash = self.compute_sha256(node_output)
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Basic AAR manifest payload layout mapping spec
        receipt_body = {
            "receiptId": str(uuid.uuid4()),
            "agent": agent_node,
            "action": action,
            "inputHash": input_hash,
            "outputHash": output_hash,
            "timestamp": timestamp
        }

        # Composable chaining via Session Continuity Certificates (SCC) if a parent exists
        if parent_signature:
            receipt_body["parentCertificate"] = parent_signature

        # Canonicalize the manifest dictionary keys to ensure deterministic validation text
        canonical_bytes = json.dumps(receipt_body, sort_keys=True).encode("utf-8")
        
        # Compute the detached Ed25519 cryptographic signature over the binary channel
        detached_sig = self.signing_key.sign(canonical_bytes).signature
        receipt_body["signature"] = detached_sig.hex()

        return receipt_body

    @staticmethod
    def verify_receipt(receipt: Dict[str, Any], verify_key_hex: bytes) -> bool:
        """Statically verifies an asymmetric receipt payload entirely offline."""
        import nacl.signing
        import nacl.exceptions

        try:
            v_key = nacl.signing.VerifyKey(verify_key_hex)
            working_copy = receipt.copy()
            signature_hex = working_copy.pop("signature")
            
            # Reconstruct the deterministic canonical verification array
            canonical_bytes = json.dumps(working_copy, sort_keys=True).encode("utf-8")
            
            v_key.verify(canonical_bytes, bytes.fromhex(signature_hex))
            return True
        except (nacl.exceptions.BadSignatureError, KeyError, ValueError):
            return False