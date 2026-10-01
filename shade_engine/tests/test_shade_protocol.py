"""
Unit and integration test suite for the SHADE protocol engine.
"""
import unittest
import time
from shade.models import Vector2D, RobotManifest, Task, TaskState, ClaimRecord
from shade.crypto import compute_manifest_signature, verify_manifest_signature
from shade.gate_trust import GateTrust
from shade.bid_evaluator import BidEvaluator
from shade.claim_manager import ClaimManager
from shade.lease_monitor import LeaseMonitor
from shade.ledger import LedgerReplica
from shade.agent import ShadeAgent


class TestShadeProtocol(unittest.TestCase):

    def setUp(self):
        self.evaluator = BidEvaluator()
        self.claim_manager = ClaimManager(theta=0.25, bid_width_w=1.2, tau_live=2.0)
        self.now = 1000.0

    def test_cryptographic_signatures(self):
        m = RobotManifest(robot_id=1, seq=1, timestamp=self.now, pose=Vector2D(10, 10))
        sig = compute_manifest_signature(m.to_dict())
        self.assertTrue(verify_manifest_signature(m.to_dict(), sig))
        # Tampered manifest
        m_tampered = m.to_dict()
        m_tampered["battery"] = 20.0
        self.assertFalse(verify_manifest_signature(m_tampered, sig))

    def test_gate_plausibility_and_quarantine(self):
        gate = GateTrust(v_max=5.0, max_strikes=3)
        m1 = RobotManifest(robot_id=1, seq=1, timestamp=self.now, pose=Vector2D(10, 10))
        res1 = gate.evaluate_manifest(m1)
        self.assertTrue(res1.accepted)

        # Illegal speed violation (jump 100m in 1s -> 100m/s > 5m/s)
        m2 = RobotManifest(robot_id=1, seq=2, timestamp=self.now + 1.0, pose=Vector2D(110, 10))
        res2 = gate.evaluate_manifest(m2)
        self.assertFalse(res2.accepted)
        self.assertEqual(gate.strikes[1], 1)

        # Trigger quarantine with 3 strikes
        gate.record_strike(1, "Test strike 2")
        gate.record_strike(1, "Test strike 3")
        self.assertTrue(gate.is_quarantined(1))

        # Rejected once quarantined
        m3 = RobotManifest(robot_id=1, seq=3, timestamp=self.now + 2.0, pose=Vector2D(10, 10))
        self.assertFalse(gate.evaluate_manifest(m3).accepted)

    def test_bid_evaluation_and_ghost_bounds(self):
        t = Task(task_id=1, target_pos=Vector2D(30, 10), creation_time=self.now, deadline=self.now + 60.0)
        m = RobotManifest(robot_id=1, seq=1, timestamp=self.now, pose=Vector2D(10, 10), battery=90.0)

        bid, eligible, reason = self.evaluator.compute_live_bid(m, t, self.now)
        self.assertTrue(eligible)
        self.assertGreater(bid, 0.0)

        # Ghost upper-bound extrapolation
        ghost_bid = self.evaluator.compute_ghost_bid(m, t, self.now + 2.0)
        # Closer optimistic projection gives a higher or equal bid
        self.assertGreaterEqual(ghost_bid, bid)

    def test_regret_bounded_claiming_and_patience(self):
        t = Task(
            task_id=1,
            target_pos=Vector2D(20, 20),
            creation_time=self.now,
            deadline=self.now + 40.0,
            priority=1.0
        )

        # Robot 0 is close (distance ~14m)
        m0 = RobotManifest(robot_id=0, seq=1, timestamp=self.now, pose=Vector2D(10, 10), is_online=True)
        # Robot 1 is farther away (distance ~56m)
        m1 = RobotManifest(robot_id=1, seq=1, timestamp=self.now, pose=Vector2D(60, 60), is_online=True)

        fleet = {0: m0, 1: m1}

        # Close robot R0 evaluates claim at t = 0
        can_claim_0, _ = self.claim_manager.evaluate_task_claiming(t, 0, fleet, self.evaluator, self.now)
        self.assertTrue(can_claim_0)
        self.assertEqual(t.winning_robot_id, 0)

    def test_progress_ratchet_lease_and_stall_revocation(self):
        monitor = LeaseMonitor(lease_duration=4.0, rho_min=0.30, check_interval=1.0)
        t = Task(task_id=1, target_pos=Vector2D(30, 0), creation_time=self.now, deadline=self.now + 60.0)
        m = RobotManifest(robot_id=0, seq=1, timestamp=self.now, pose=Vector2D(0, 0))

        # Grant lease
        monitor.grant_lease(task_id=1, robot_id=0, epoch=1, initial_cost=30.0, now=self.now)

        # Simulate robot moving forward (0 -> 5m) at t = now + 1.0s
        m.pose = Vector2D(5.0, 0)
        valid, needs_takeover, _ = monitor.verify_progress(t, m, self.now + 1.0)
        self.assertTrue(valid)
        self.assertFalse(needs_takeover)

        # Simulate robot stalling (does not move at all between 1.0s and 6.0s)
        now_stalled = self.now + 6.0  # past lease expiry (lease_duration is 4.0s)
        valid, needs_takeover, reason = monitor.verify_progress(t, m, now_stalled)
        self.assertFalse(valid)
        self.assertTrue(needs_takeover)
        self.assertIn("Lease expired", reason)

    def test_finish_line_yield_rule(self):
        now = self.now
        # Robot A is at distance 5m to target
        agA = ShadeAgent(robot_id=1, initial_pose=Vector2D(5, 0), max_speed=5.0)
        # Robot B is at distance 20m to target
        agB = ShadeAgent(robot_id=2, initial_pose=Vector2D(20, 0), max_speed=5.0)

        task = Task(task_id=1, target_pos=Vector2D(0, 0), creation_time=now, deadline=now + 60.0)
        agA.ledger.add_task(task)
        agB.ledger.add_task(task)

        # Both hold task after a simulated healed partition
        agA.held_task_id = 1
        agA.remaining_cost = 5.0

        agB.held_task_id = 1
        agB.remaining_cost = 20.0

        # Feed each other's manifests
        mA = agA.build_my_manifest(now)
        mB = agB.build_my_manifest(now)
        agA.fleet_manifests[2] = mB
        agB.fleet_manifests[1] = mA

        # Check finish-line rules
        agA.check_finish_line_conflicts(now)
        agB.check_finish_line_conflicts(now)

        # Robot A (closer, 5m) must KEEP task
        self.assertEqual(agA.held_task_id, 1)
        # Robot B (farther, 20m) must YIELD task
        self.assertEqual(agB.held_task_id, -1)

    def test_neural_bidder_deterministic_inference(self):
        from shade.neural_bidder import NeuralBidder
        nb1 = NeuralBidder()
        nb2 = NeuralBidder()

        # Two independent nodes with identical inputs must produce exact identical scores
        score1 = nb1.forward(
            distance=15.0, battery=85.0, travel_time=3.0, time_slack=40.0,
            cargo_count=0, cargo_capacity=2, priority=1.5, uncertainty_sigma=0.05
        )
        score2 = nb2.forward(
            distance=15.0, battery=85.0, travel_time=3.0, time_slack=40.0,
            cargo_count=0, cargo_capacity=2, priority=1.5, uncertainty_sigma=0.05
        )
        self.assertEqual(score1, score2)
        self.assertGreater(score1, 0.1)
        self.assertLessEqual(score1, 1.0)

        # Distance penalty: farther robot must get a lower score
        score_far = nb1.forward(
            distance=80.0, battery=85.0, travel_time=16.0, time_slack=40.0,
            cargo_count=0, cargo_capacity=2, priority=1.5, uncertainty_sigma=0.05
        )
        self.assertLess(score_far, score1)


if __name__ == "__main__":
    unittest.main()
