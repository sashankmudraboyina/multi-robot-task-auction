"""
Cryptographic signing and verification for SHADE manifests and tasks.
Uses HMAC-SHA256 by default (zero external dependencies) with fallback capability.
"""
import hashlib
import hmac
import json
from typing import Dict, Any


DEFAULT_SECRET_KEY = b"shade-fleet-shared-secret-salt-2026"


def compute_manifest_signature(manifest_dict: Dict[str, Any], secret_key: bytes = DEFAULT_SECRET_KEY) -> str:
    """
    Computes an HMAC-SHA256 digest over the deterministic serialized manifest state.
    """
    # Exclude signature itself
    content = {
        "robot_id": manifest_dict["robot_id"],
        "seq": manifest_dict["seq"],
        "timestamp": manifest_dict["timestamp"],
        "pose": manifest_dict["pose"],
        "battery": manifest_dict["battery"],
        "cargo_count": manifest_dict.get("cargo_count", 0),
        "cargo_capacity": manifest_dict.get("cargo_capacity", 2),
        "held_task_id": manifest_dict.get("held_task_id", -1),
        "lease_epoch": manifest_dict.get("lease_epoch", 0),
        "remaining_cost": manifest_dict.get("remaining_cost", 0.0),
    }
    serialized = json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(secret_key, serialized, hashlib.sha256).hexdigest()[:16]


def verify_manifest_signature(manifest_dict: Dict[str, Any], signature: str, secret_key: bytes = DEFAULT_SECRET_KEY) -> bool:
    """
    Verifies that the signature matches the manifest content.
    """
    if not signature:
        return False
    expected = compute_manifest_signature(manifest_dict, secret_key)
    return hmac.compare_digest(expected, signature)
