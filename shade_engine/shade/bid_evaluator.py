"""
Bid Evaluator: Deterministic multi-variable implicit bidding and optimistic ghost extrapolation.
"""
import math
from typing import Dict, Optional, Tuple
from .models import RobotManifest, Task, Vector2D
from .neural_bidder import NeuralBidder


class BidEvaluator:
    """
    Computes bids deterministically from signed manifests without per-task message broadcasts.
    Supports both calibrated linear multi-attribute scoring and Decision-Focused Neural Network inference.
    """
    def __init__(
        self,
        w_dist: float = 0.30,
        w_batt: float = 0.25,
        w_eta: float = 0.25,
        w_fit: float = 0.20,
        lambda_uncertainty: float = 0.30,
        max_speed: float = 5.0,
        d_max: float = 120.0,
        min_battery: float = 15.0,
        use_neural: bool = True,
    ):
        self.w_dist = w_dist
        self.w_batt = w_batt
        self.w_eta = w_eta
        self.w_fit = w_fit
        self.lambda_uncertainty = lambda_uncertainty
        self.max_speed = max_speed
        self.d_max = d_max
        self.min_battery = min_battery
        self.use_neural = use_neural
        self.neural_bidder = NeuralBidder()

    def compute_live_bid(
        self,
        manifest: RobotManifest,
        task: Task,
        current_time: float,
        is_quarantined: bool = False
    ) -> Tuple[float, bool, str]:
        """
        Computes the multi-variable implicit bid for a live robot.
        Returns: (bid_score, is_eligible, gate_reason)
        """
        # Capability check
        for cap in task.required_caps:
            if cap not in manifest.capabilities:
                return (0.0, False, f"Missing capability: {cap}")

        # Eligibility Gates
        if is_quarantined or manifest.is_quarantined:
            return (0.0, False, "Robot is quarantined")
        if manifest.is_stalled:
            return (0.0, False, "Robot is stalled")
        if manifest.battery < self.min_battery:
            return (0.0, False, f"Low battery ({manifest.battery:.1f}%)")
        if manifest.cargo_count >= manifest.cargo_capacity:
            return (0.0, False, "Cargo capacity full")
        if manifest.held_task_id != -1 and manifest.held_task_id != task.task_id:
            return (0.0, False, "Robot already holding another task")

        # Metric components
        dist = manifest.pose.distance_to(task.target_pos)
        travel_time = dist / max(0.5, self.max_speed)
        time_slack = max(1.0, task.deadline - current_time)

        if self.use_neural:
            bid = self.neural_bidder.forward(
                distance=dist,
                battery=manifest.battery,
                travel_time=travel_time,
                time_slack=time_slack,
                cargo_count=manifest.cargo_count,
                cargo_capacity=manifest.cargo_capacity,
                priority=task.priority,
                uncertainty_sigma=0.05,
                d_max=self.d_max,
            )
            return (bid, True, "Eligible (Neural)")

        s_dist = max(0.0, min(1.0, 1.0 - (dist / self.d_max)))
        s_batt = max(0.0, min(1.0, manifest.battery / 100.0))
        s_eta = max(0.0, min(1.0, 1.0 - (travel_time / time_slack)))
        s_fit = 1.0  # Full capability match

        sigma = 0.05  # Standard small network jitter uncertainty penalty
        raw_bid = (
            self.w_dist * s_dist +
            self.w_batt * s_batt +
            self.w_eta * s_eta +
            self.w_fit * s_fit
        ) - (self.lambda_uncertainty * sigma)

        bid = max(0.01, min(1.0, raw_bid))
        return (round(bid, 4), True, "Eligible (Linear)")

    def compute_ghost_bid(
        self,
        manifest: RobotManifest,
        task: Task,
        current_time: float
    ) -> float:
        """
        Computes the optimistic upper-bound bid for a silent peer.
        Assumes peer moved directly towards the task at v_max with unchanged battery and zero uncertainty.
        """
        # Capability check
        for cap in task.required_caps:
            if cap not in manifest.capabilities:
                return 0.0

        if manifest.is_quarantined or manifest.battery < self.min_battery:
            return 0.0

        age = max(0.0, current_time - manifest.timestamp)
        last_dist = manifest.pose.distance_to(task.target_pos)
        # Optimistic physical extrapolation: closest it could possibly be
        opt_dist = max(0.0, last_dist - (self.max_speed * age))
        travel_time = opt_dist / max(0.5, self.max_speed)
        time_slack = max(1.0, task.deadline - current_time)

        if self.use_neural:
            return self.neural_bidder.forward(
                distance=opt_dist,
                battery=manifest.battery,
                travel_time=travel_time,
                time_slack=time_slack,
                cargo_count=manifest.cargo_count,
                cargo_capacity=manifest.cargo_capacity,
                priority=task.priority,
                uncertainty_sigma=0.0,
                d_max=self.d_max,
            )

        s_dist = max(0.0, min(1.0, 1.0 - (opt_dist / self.d_max)))
        s_batt = max(0.0, min(1.0, manifest.battery / 100.0))
        s_eta = max(0.0, min(1.0, 1.0 - (travel_time / time_slack)))
        s_fit = 1.0

        sigma = 0.0  # Zero uncertainty for optimistic upper bound
        raw_bid = (
            self.w_dist * s_dist +
            self.w_batt * s_batt +
            self.w_eta * s_eta +
            self.w_fit * s_fit
        ) - (self.lambda_uncertainty * sigma)

        return round(max(0.01, min(1.0, raw_bid)), 4)
