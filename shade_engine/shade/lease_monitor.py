"""
Lease Monitor: Progress-ratchet verification, stall/Byzantine detection, and succession takeover.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from .models import RobotManifest, Task, TaskState


@dataclass
class LeaseState:
    task_id: int
    robot_id: int
    epoch: int
    lease_until: float
    last_recorded_cost: float
    last_check_time: float
    ratchet_failing: bool = False


class LeaseMonitor:
    """
    Monitors active task leases. Enforces physical progress ratchets without consensus voting.
    """
    def __init__(
        self,
        lease_duration: float = 6.0,
        rho_min: float = 0.30,  # Minimum required cost reduction rate in m/s
        check_interval: float = 1.0,
    ):
        self.lease_duration = lease_duration
        self.rho_min = rho_min
        self.check_interval = check_interval
        self.leases: Dict[int, LeaseState] = {}  # task_id -> LeaseState

    def grant_lease(self, task_id: int, robot_id: int, epoch: int, initial_cost: float, now: float) -> LeaseState:
        ls = LeaseState(
            task_id=task_id,
            robot_id=robot_id,
            epoch=epoch,
            lease_until=now + self.lease_duration,
            last_recorded_cost=initial_cost,
            last_check_time=now,
            ratchet_failing=False,
        )
        self.leases[task_id] = ls
        return ls

    def revoke_lease(self, task_id: int) -> Optional[LeaseState]:
        return self.leases.pop(task_id, None)

    def verify_progress(
        self,
        task: Task,
        manifest: RobotManifest,
        now: float
    ) -> Tuple[bool, bool, str]:
        """
        Verifies progress on the active lease.
        Returns: (lease_valid, needs_takeover, reason)
        """
        if task.task_id not in self.leases:
            return (False, True, "No active lease registered")

        ls = self.leases[task.task_id]

        # Check if arrived at destination
        current_dist = manifest.pose.distance_to(task.target_pos)
        if current_dist < 1.5:
            # Arrival verified!
            task.state = TaskState.COMPLETED
            self.revoke_lease(task.task_id)
            return (True, False, "Task successfully reached destination")

        # Periodic Ratchet Check
        dt = now - ls.last_check_time
        if dt >= self.check_interval:
            cost_reduction = ls.last_recorded_cost - current_dist
            min_expected_reduction = self.rho_min * dt

            # Ratchet condition
            if cost_reduction >= min_expected_reduction and not manifest.is_stalled:
                # Progress verified! Renew lease
                ls.lease_until = now + self.lease_duration
                ls.last_recorded_cost = current_dist
                ls.last_check_time = now
                ls.ratchet_failing = False
                task.lease_expiry = ls.lease_until
                return (True, False, f"Progress verified (-{cost_reduction:.2f}m in {dt:.1f}s). Lease renewed.")
            else:
                # Ratchet check failed: stall detected
                ls.ratchet_failing = True
                # Clock continues ticking down without renewal

        # Check for lease expiration
        if now > ls.lease_until:
            # Lease expired! Revoke claim and trigger succession
            self.revoke_lease(task.task_id)
            return (False, True, f"Lease expired for robot {ls.robot_id}! No verifiable progress.")

        return (True, False, f"Lease active ({ls.lease_until - now:.1f}s remaining)")
