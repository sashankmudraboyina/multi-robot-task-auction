"""
ShadeAgent: Autonomous decentralized robot node executing the full SHADE loop.
"""
import time
from typing import Dict, List, Optional, Tuple
from .models import RobotManifest, Task, TaskState, Vector2D, ClaimRecord, YieldRecord
from .crypto import compute_manifest_signature
from .gate_trust import GateTrust
from .bid_evaluator import BidEvaluator
from .claim_manager import ClaimManager
from .lease_monitor import LeaseMonitor
from .ledger import LedgerReplica


class ShadeAgent:
    """
    Self-contained decentralized agent running on each autonomous warehouse robot.
    """
    def __init__(
        self,
        robot_id: int,
        initial_pose: Vector2D,
        battery: float = 100.0,
        cargo_capacity: int = 2,
        capabilities: Optional[List[str]] = None,
        theta: float = 0.25,
        lease_duration: float = 6.0,
        rho_min: float = 0.30,
        tau_live: float = 3.0,
        max_speed: float = 5.0,
    ):
        self.robot_id = robot_id
        self.pose = initial_pose
        self.battery = battery
        self.cargo_capacity = cargo_capacity
        self.cargo_count = 0
        self.capabilities = capabilities or ["pick", "transport"]

        self.seq = 0
        self.held_task_id = -1
        self.lease_epoch = 0
        self.remaining_cost = 0.0

        # Physical simulation / health
        self.is_online = True
        self.is_stalled = False
        self.max_speed = max_speed

        # Core SHADE Modules
        self.gate_trust = GateTrust(v_max=max_speed)
        self.bid_evaluator = BidEvaluator(max_speed=max_speed)
        self.claim_manager = ClaimManager(theta=theta, tau_live=tau_live)
        self.lease_monitor = LeaseMonitor(lease_duration=lease_duration, rho_min=rho_min)
        self.ledger = LedgerReplica()

        # Fleet directory (peer robot manifests)
        self.fleet_manifests: Dict[int, RobotManifest] = {}

        # Publication tracking
        self.last_published_time = 0.0
        self.last_published_pose = Vector2D(initial_pose.x, initial_pose.y)
        self.publish_floor_interval = 1.0  # 1 Hz floor
        self.publish_drift_dist = 0.5  # 0.5m dead-reckoning drift threshold

        # Telemetry event log
        self.event_log: List[Dict] = []

    def log(self, category: str, message: str) -> None:
        entry = {
            "time": round(time.time(), 3),
            "robot_id": self.robot_id,
            "category": category,
            "message": message,
        }
        self.event_log.append(entry)
        if len(self.event_log) > 50:
            self.event_log.pop(0)

    def build_my_manifest(self, now: float) -> RobotManifest:
        self.seq += 1
        m = RobotManifest(
            robot_id=self.robot_id,
            seq=self.seq,
            timestamp=now,
            pose=Vector2D(self.pose.x, self.pose.y),
            battery=self.battery,
            cargo_count=self.cargo_count,
            cargo_capacity=self.cargo_capacity,
            capabilities=list(self.capabilities),
            held_task_id=self.held_task_id,
            lease_epoch=self.lease_epoch,
            remaining_cost=self.remaining_cost,
            is_online=self.is_online,
            is_stalled=self.is_stalled,
        )
        m.signature = compute_manifest_signature(m.to_dict())
        return m

    def should_publish_manifest(self, now: float) -> bool:
        if now - self.last_published_time >= self.publish_floor_interval:
            return True
        drift = self.pose.distance_to(self.last_published_pose)
        if drift >= self.publish_drift_dist:
            return True
        return False

    def handle_incoming_manifest(self, m: RobotManifest) -> bool:
        """
        Receives and validates a manifest from a peer robot.
        """
        if m.robot_id == self.robot_id:
            return True

        res = self.gate_trust.evaluate_manifest(m)
        if not res.accepted:
            self.log("GATE_REJECT", f"Rejected R{m.robot_id}: {res.reason}")
            return False

        # Accepted: update view
        self.fleet_manifests[m.robot_id] = m
        return True

    def tick(self, now: float, dt: float) -> Optional[RobotManifest]:
        """
        Main agent loop (runs at 10 Hz).
        Returns a newly signed manifest if published during this tick.
        """
        # 1. Update our own manifest in our local fleet view
        my_m = self.build_my_manifest(now)
        self.fleet_manifests[self.robot_id] = my_m

        published_manifest: Optional[RobotManifest] = None
        if self.should_publish_manifest(now):
            self.last_published_time = now
            self.last_published_pose = Vector2D(self.pose.x, self.pose.y)
            published_manifest = my_m

        # 2. Progress and lease monitoring for active task
        if self.held_task_id != -1:
            task = self.ledger.tasks.get(self.held_task_id)
            if task:
                self.remaining_cost = self.pose.distance_to(task.target_pos)
                my_m.remaining_cost = self.remaining_cost

                # Physical simulation step: move towards destination if not stalled
                if not self.is_stalled and self.remaining_cost > 0.1:
                    step = min(self.remaining_cost, self.max_speed * dt)
                    dx = (task.target_pos.x - self.pose.x) / self.remaining_cost
                    dy = (task.target_pos.y - self.pose.y) / self.remaining_cost
                    self.pose.x += dx * step
                    self.pose.y += dy * step
                    self.battery = max(5.0, self.battery - 0.05 * dt)
                    self.remaining_cost = self.pose.distance_to(task.target_pos)

                valid, needs_takeover, reason = self.lease_monitor.verify_progress(task, my_m, now)
                if not valid:
                    self.log("LEASE_FAIL", f"Lost lease on T{task.task_id}: {reason}")
                    self.held_task_id = -1
                    self.lease_epoch = 0
                elif task.state == TaskState.COMPLETED:
                    self.log("COMPLETED", f"Arrived and completed T{task.task_id}!")
                    self.ledger.mark_completed(task.task_id)
                    self.held_task_id = -1
                    self.lease_epoch = 0

        # 3. Contest resolution (Finish-Line Rule upon partition healing)
        self.check_finish_line_conflicts(now)

        # 4. Open tasks auction and claim evaluation
        if self.held_task_id == -1 and not self.is_stalled and self.battery >= 15.0:
            open_tasks = self.ledger.get_open_tasks()
            for task in open_tasks:
                can_claim, reason = self.claim_manager.evaluate_task_claiming(
                    task=task,
                    my_id=self.robot_id,
                    fleet_manifests=self.fleet_manifests,
                    evaluator=self.bid_evaluator,
                    current_time=now,
                    quarantined_ids={rid for rid, qu in self.gate_trust.quarantined.items() if qu}
                )

                if can_claim:
                    # Claim authorized under Progress-Ratchet Lease!
                    self.held_task_id = task.task_id
                    self.lease_epoch = task.lease_epoch + 1
                    init_cost = self.pose.distance_to(task.target_pos)
                    self.remaining_cost = init_cost

                    self.lease_monitor.grant_lease(
                        task_id=task.task_id,
                        robot_id=self.robot_id,
                        epoch=self.lease_epoch,
                        initial_cost=init_cost,
                        now=now
                    )

                    claim_rec = ClaimRecord(
                        task_id=task.task_id,
                        epoch=self.lease_epoch,
                        robot_id=self.robot_id,
                        timestamp=now
                    )
                    self.ledger.add_claim(claim_rec)
                    self.log("CLAIM", f"Claimed T{task.task_id} (Bid {task.winning_bid:.2f}, Regret {task.current_regret:.2f})")
                    break

        return published_manifest

    def check_finish_line_conflicts(self, now: float) -> None:
        """
        Finish-Line Yield Rule: If partition heals and another robot holds our task,
        the one physically closer to completion keeps it.
        """
        if self.held_task_id == -1:
            return

        task = self.ledger.tasks.get(self.held_task_id)
        if not task:
            return

        for r_id, m in self.fleet_manifests.items():
            if r_id != self.robot_id and m.held_task_id == self.held_task_id:
                # Contested task detected!
                c_me = self.remaining_cost
                c_other = m.remaining_cost
                margin = 0.5

                if c_other < c_me - margin or (abs(c_other - c_me) <= margin and r_id < self.robot_id):
                    # I yield!
                    self.log("YIELD", f"Finish-Line Rule: Yielding T{self.held_task_id} to closer R{r_id} ({c_other:.1f}m vs my {c_me:.1f}m)")
                    self.ledger.add_yield(YieldRecord(task_id=self.held_task_id, robot_id=self.robot_id, timestamp=now))
                    self.lease_monitor.revoke_lease(self.held_task_id)
                    self.held_task_id = -1
                    self.lease_epoch = 0
                    break
