"""
SHADE: Shadow-Hedged Auction with Decaying Estimates
Decentralized, fault-tolerant multi-robot task allocation protocol.
"""
from .models import Vector2D, RobotManifest, Task, TaskState, ClaimRecord, YieldRecord
from .crypto import compute_manifest_signature, verify_manifest_signature
from .gate_trust import GateTrust, GateResult
from .neural_bidder import NeuralBidder
from .bid_evaluator import BidEvaluator
from .claim_manager import ClaimManager
from .lease_monitor import LeaseMonitor
from .ledger import LedgerReplica
from .agent import ShadeAgent

__all__ = [
    "Vector2D",
    "RobotManifest",
    "Task",
    "TaskState",
    "ClaimRecord",
    "YieldRecord",
    "compute_manifest_signature",
    "verify_manifest_signature",
    "GateTrust",
    "GateResult",
    "NeuralBidder",
    "BidEvaluator",
    "ClaimManager",
    "LeaseMonitor",
    "LedgerReplica",
    "ShadeAgent",
]
