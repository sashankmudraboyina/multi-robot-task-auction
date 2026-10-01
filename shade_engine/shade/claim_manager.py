"""
Claim Manager: Regret-bounded claiming, decaying patience tolerance, and succession ranks.
"""
import math
from typing import Dict, List, Optional, Tuple
from .models import RobotManifest, Task, TaskState
from .bid_evaluator import BidEvaluator


class ClaimManager:
    """
    Implements the regret-bounded claim rule with decaying patience tolerance.
    """
    def __init__(
        self,
        theta: float = 0.25,
        bid_width_w: float = 1.2,
        stagger_delta: float = 0.2,
        tau_live: float = 3.0,
    ):
        self.theta = theta
        self.bid_width_w = bid_width_w
        self.stagger_delta = stagger_delta
        self.tau_live = tau_live

    def evaluate_task_claiming(
        self,
        task: Task,
        my_id: int,
        fleet_manifests: Dict[int, RobotManifest],
        evaluator: BidEvaluator,
        current_time: float,
        quarantined_ids: Optional[set] = None
    ) -> Tuple[bool, str]:
        """
        Evaluates whether my_id is permitted to claim the open task under SHADE rules.
        Returns: (can_claim, reason)
        """
        if task.state in (TaskState.CLAIMED, TaskState.COMPLETED, TaskState.CANCELLED):
            return (False, f"Task already {task.state.value}")

        if quarantined_ids is None:
            quarantined_ids = set()

        # Step 1: Separate live robots from silent ghost peers
        live_bids: List[Tuple[int, float]] = []
        ghost_bids: List[Tuple[int, float]] = []

        for r_id, m in fleet_manifests.items():
            if r_id in quarantined_ids:
                continue

            is_ghost = (not m.is_online) or ((current_time - m.timestamp) > self.tau_live)

            if not is_ghost:
                bid, eligible, _ = evaluator.compute_live_bid(m, task, current_time, r_id in quarantined_ids)
                if eligible and bid > 0.0:
                    live_bids.append((r_id, bid))
            else:
                g_bid = evaluator.compute_ghost_bid(m, task, current_time)
                if g_bid > 0.0:
                    ghost_bids.append((r_id, g_bid))

        # Sort live robots descending by bid; tie-break deterministically by robot_id
        live_bids.sort(key=lambda x: (-x[1], x[0]))
        task.succession_ranks = [r[0] for r in live_bids]

        # Check if my_id is in the ranked list
        my_rank_idx = -1
        my_bid = 0.0
        for idx, (r_id, bid) in enumerate(live_bids):
            if r_id == my_id:
                my_rank_idx = idx
                my_bid = bid
                break

        if my_rank_idx == -1:
            return (False, "Robot not eligible or gated out for this task")

        # Step 2: Staggered timer check
        # Rank 0 acts immediately at t_open; Rank 1 waits delta; Rank 2 waits 2*delta
        required_time = task.creation_time + (my_rank_idx * self.stagger_delta)
        if current_time < required_time:
            wait_rem = required_time - current_time
            return (False, f"Waiting succession stagger: {wait_rem:.2f}s remaining (Rank {my_rank_idx})")

        # Step 3: Compute Regret against best ghost
        best_ghost_bid = 0.0
        best_ghost_id = -1
        if ghost_bids:
            ghost_bids.sort(key=lambda x: -x[1])
            best_ghost_id, best_ghost_bid = ghost_bids[0]

        regret = max(0.0, best_ghost_bid - my_bid)

        # Step 4: Compute Decaying Patience Tolerance
        total_duration = max(5.0, task.deadline - task.creation_time)
        patience_window = max(2.0, (self.theta * total_duration) / max(0.1, task.priority))
        age = max(0.0, current_time - task.creation_time)
        tolerance = self.bid_width_w * min(1.0, age / patience_window)

        # Update telemetry metrics on task
        task.winning_robot_id = live_bids[0][0]
        task.winning_bid = live_bids[0][1]
        task.highest_ghost_bid = best_ghost_bid
        task.best_ghost_id = best_ghost_id
        task.current_regret = regret
        task.current_tolerance = tolerance

        # Step 5: Check Regret Bound
        if regret <= tolerance:
            # Regret is bounded! Authorize claim
            task.state = TaskState.CLAIMED
            task.winning_robot_id = my_id
            task.winning_bid = my_bid
            task.claim_time = current_time
            return (True, f"Regret {regret:.3f} <= Tolerance {tolerance:.3f}. Claim authorized.")
        else:
            task.state = TaskState.PATIENCE_WAITING
            deficit = regret - tolerance
            return (False, f"Regret {regret:.3f} > Tolerance {tolerance:.3f} (deficit {deficit:.3f}). Patience hold.")
