"""
Data models and message structures for the SHADE protocol.
"""
from dataclasses import dataclass, field
from enum import Enum
import math
import time
from typing import Dict, List, Optional, Tuple, Set


@dataclass
class Vector2D:
    x: float = 0.0
    y: float = 0.0

    def distance_to(self, other: "Vector2D") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def to_dict(self) -> Dict[str, float]:
        return {"x": round(self.x, 3), "y": round(self.y, 3)}

    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> "Vector2D":
        return cls(x=float(data.get("x", 0.0)), y=float(data.get("y", 0.0)))


class TaskState(str, Enum):
    OPEN = "OPEN"
    PATIENCE_WAITING = "PATIENCE_WAITING"
    CLAIMED = "CLAIMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


@dataclass
class RobotManifest:
    """
    Public signed state manifest broadcast periodically or upon prediction drift.
    """
    robot_id: int
    seq: int
    timestamp: float
    pose: Vector2D
    battery: float = 100.0  # 0.0 - 100.0%
    cargo_count: int = 0
    cargo_capacity: int = 2
    capabilities: List[str] = field(default_factory=lambda: ["pick", "transport"])
    held_task_id: int = -1
    lease_epoch: int = 0
    remaining_cost: float = 0.0
    signature: str = ""

    # Local evaluation flags (not serialized over wire)
    is_online: bool = True
    is_stalled: bool = False
    is_quarantined: bool = False
    strikes: int = 0

    def to_dict(self) -> Dict:
        return {
            "robot_id": self.robot_id,
            "seq": self.seq,
            "timestamp": round(self.timestamp, 4),
            "pose": self.pose.to_dict(),
            "battery": round(self.battery, 2),
            "cargo_count": self.cargo_count,
            "cargo_capacity": self.cargo_capacity,
            "capabilities": self.capabilities,
            "held_task_id": self.held_task_id,
            "lease_epoch": self.lease_epoch,
            "remaining_cost": round(self.remaining_cost, 3),
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "RobotManifest":
        return cls(
            robot_id=int(data["robot_id"]),
            seq=int(data["seq"]),
            timestamp=float(data["timestamp"]),
            pose=Vector2D.from_dict(data["pose"]),
            battery=float(data.get("battery", 100.0)),
            cargo_count=int(data.get("cargo_count", 0)),
            cargo_capacity=int(data.get("cargo_capacity", 2)),
            capabilities=list(data.get("capabilities", ["pick", "transport"])),
            held_task_id=int(data.get("held_task_id", -1)),
            lease_epoch=int(data.get("lease_epoch", 0)),
            remaining_cost=float(data.get("remaining_cost", 0.0)),
            signature=str(data.get("signature", "")),
        )


@dataclass
class Task:
    task_id: int
    target_pos: Vector2D
    creation_time: float
    deadline: float
    priority: float = 1.0
    required_caps: List[str] = field(default_factory=lambda: ["pick"])
    quantity: int = 1
    state: TaskState = TaskState.OPEN

    # Lease & Ownership tracking
    winning_robot_id: int = -1
    lease_epoch: int = 0
    lease_expiry: float = 0.0
    claim_time: float = 0.0

    # Auction metrics for transparency
    winning_bid: float = 0.0
    highest_ghost_bid: float = 0.0
    best_ghost_id: int = -1
    current_regret: float = 0.0
    current_tolerance: float = 0.0
    patience_delay: float = 0.0
    succession_ranks: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "target_pos": self.target_pos.to_dict(),
            "creation_time": round(self.creation_time, 3),
            "deadline": round(self.deadline, 3),
            "priority": round(self.priority, 2),
            "required_caps": self.required_caps,
            "quantity": self.quantity,
            "state": self.state.value,
            "winning_robot_id": self.winning_robot_id,
            "lease_epoch": self.lease_epoch,
            "lease_expiry": round(self.lease_expiry, 3),
            "claim_time": round(self.claim_time, 3),
            "winning_bid": round(self.winning_bid, 3),
            "highest_ghost_bid": round(self.highest_ghost_bid, 3),
            "best_ghost_id": self.best_ghost_id,
            "current_regret": round(self.current_regret, 3),
            "current_tolerance": round(self.current_tolerance, 3),
            "succession_ranks": self.succession_ranks,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Task":
        return cls(
            task_id=int(data["task_id"]),
            target_pos=Vector2D.from_dict(data["target_pos"]),
            creation_time=float(data["creation_time"]),
            deadline=float(data["deadline"]),
            priority=float(data.get("priority", 1.0)),
            required_caps=list(data.get("required_caps", ["pick"])),
            quantity=int(data.get("quantity", 1)),
            state=TaskState(data.get("state", TaskState.OPEN.value)),
            winning_robot_id=int(data.get("winning_robot_id", -1)),
            lease_epoch=int(data.get("lease_epoch", 0)),
            lease_expiry=float(data.get("lease_expiry", 0.0)),
            claim_time=float(data.get("claim_time", 0.0)),
            winning_bid=float(data.get("winning_bid", 0.0)),
            highest_ghost_bid=float(data.get("highest_ghost_bid", 0.0)),
            best_ghost_id=int(data.get("best_ghost_id", -1)),
            current_regret=float(data.get("current_regret", 0.0)),
            current_tolerance=float(data.get("current_tolerance", 0.0)),
            succession_ranks=list(data.get("succession_ranks", [])),
        )


@dataclass(frozen=True)
class ClaimRecord:
    task_id: int
    epoch: int
    robot_id: int
    timestamp: float

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "epoch": self.epoch,
            "robot_id": self.robot_id,
            "timestamp": round(self.timestamp, 3),
        }


@dataclass(frozen=True)
class YieldRecord:
    task_id: int
    robot_id: int
    timestamp: float

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "robot_id": self.robot_id,
            "timestamp": round(self.timestamp, 3),
        }
