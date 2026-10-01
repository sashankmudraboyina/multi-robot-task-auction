"""
Gate & Trust module: Plausibility checks, strike counters, and Byzantine quarantine.
"""
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from .models import RobotManifest, Vector2D
from .crypto import verify_manifest_signature


@dataclass
class GateResult:
    accepted: bool
    reason: str


class GateTrust:
    """
    Evaluates incoming peer manifests against physical and logical invariants.
    Maintains strike records for faulty or malicious peers.
    """
    def __init__(
        self,
        v_max: float = 5.0,
        speed_tolerance: float = 1.25,
        max_strikes: int = 3,
        warehouse_bounds: Tuple[float, float, float, float] = (-10.0, -10.0, 150.0, 150.0)
    ):
        self.v_max = v_max
        self.speed_tolerance = speed_tolerance
        self.max_strikes = max_strikes
        self.warehouse_bounds = warehouse_bounds  # (min_x, min_y, max_x, max_y)

        # Peer history: robot_id -> (last_manifest, strike_count, is_quarantined)
        self.history: Dict[int, RobotManifest] = {}
        self.strikes: Dict[int, int] = {}
        self.quarantined: Dict[int, bool] = {}

    def is_quarantined(self, robot_id: int) -> bool:
        return self.quarantined.get(robot_id, False)

    def record_strike(self, robot_id: int, reason: str) -> None:
        curr = self.strikes.get(robot_id, 0) + 1
        self.strikes[robot_id] = curr
        if curr >= self.max_strikes:
            self.quarantined[robot_id] = True

    def evaluate_manifest(self, m: RobotManifest) -> GateResult:
        """
        Runs the 6 plausibility checks against the manifest.
        """
        # If already quarantined, immediately reject
        if self.is_quarantined(m.robot_id):
            return GateResult(accepted=False, reason="Robot is quarantined")

        # Check 1: Signature check (if present)
        if m.signature and not verify_manifest_signature(m.to_dict(), m.signature):
            self.record_strike(m.robot_id, "Invalid signature")
            return GateResult(accepted=False, reason="Cryptographic signature invalid")

        # Check 2: Physical warehouse bounds
        min_x, min_y, max_x, max_y = self.warehouse_bounds
        if not (min_x <= m.pose.x <= max_x and min_y <= m.pose.y <= max_y):
            self.record_strike(m.robot_id, "Out of warehouse bounds")
            return GateResult(accepted=False, reason=f"Pose ({m.pose.x}, {m.pose.y}) outside bounds")

        # Check 3: Cargo validity
        if m.cargo_count < 0 or m.cargo_count > m.cargo_capacity:
            self.record_strike(m.robot_id, "Illegal cargo count")
            return GateResult(accepted=False, reason=f"Illegal cargo count: {m.cargo_count}")

        # Check 4: History-based checks (if previous manifest exists)
        if m.robot_id in self.history:
            prev = self.history[m.robot_id]

            # 4a: Sequence monotonicity
            if m.seq <= prev.seq:
                return GateResult(accepted=False, reason="Duplicate or out-of-order sequence number")

            dt = max(0.001, m.timestamp - prev.timestamp)

            # 4b: Physical speed limit check (teleportation detector)
            dist = prev.pose.distance_to(m.pose)
            max_allowed_dist = (self.v_max * self.speed_tolerance) * dt + 0.5  # margin
            if dist > max_allowed_dist:
                self.record_strike(m.robot_id, f"Speed violation: {dist/dt:.2f} m/s")
                return GateResult(
                    accepted=False,
                    reason=f"Plausibility check failed: speed {dist/dt:.1f} m/s exceeds max limit"
                )

            # 4c: Battery spontaneous creation check (cannot recharge while moving)
            if m.battery > prev.battery + 0.1 and dist > 1.0:
                self.record_strike(m.robot_id, "Spontaneous recharge while moving")
                return GateResult(accepted=False, reason="Impossible battery increase during locomotion")

        # Manifest accepted: update history
        self.history[m.robot_id] = m
        return GateResult(accepted=True, reason="Accepted")
