"""
Ledger: Grow-only set (G-Set) CRDT for distributed tasks, claims, yields, and completions.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from .models import Task, TaskState, ClaimRecord, YieldRecord


class LedgerReplica:
    """
    Decentralized CRDT ledger maintaining monotonic sets of tasks, claims, yields, and completions.
    Any two replicas can merge state deterministically without coordination.
    """
    def __init__(self):
        self.tasks: Dict[int, Task] = {}
        self.claims: Set[ClaimRecord] = set()
        self.yields: Set[YieldRecord] = set()
        self.completed_tasks: Set[int] = set()

    def add_task(self, task: Task) -> bool:
        if task.task_id not in self.tasks:
            self.tasks[task.task_id] = task
            return True
        return False

    def add_claim(self, claim: ClaimRecord) -> bool:
        if claim not in self.claims:
            self.claims.add(claim)
            # Update local task representation
            if claim.task_id in self.tasks:
                t = self.tasks[claim.task_id]
                if claim.epoch >= t.lease_epoch:
                    t.winning_robot_id = claim.robot_id
                    t.lease_epoch = claim.epoch
                    t.state = TaskState.CLAIMED
            return True
        return False

    def add_yield(self, yld: YieldRecord) -> bool:
        if yld not in self.yields:
            self.yields.add(yld)
            return True
        return False

    def mark_completed(self, task_id: int) -> bool:
        if task_id not in self.completed_tasks:
            self.completed_tasks.add(task_id)
            if task_id in self.tasks:
                self.tasks[task_id].state = TaskState.COMPLETED
            return True
        return False

    def get_open_tasks(self) -> List[Task]:
        return [
            t for t_id, t in self.tasks.items()
            if t_id not in self.completed_tasks and t.state in (TaskState.OPEN, TaskState.PATIENCE_WAITING)
        ]

    def export_digest(self) -> Dict:
        """
        Exports state for synchronization over gossip or network channels.
        """
        return {
            "tasks": [t.to_dict() for t in self.tasks.values()],
            "claims": [c.to_dict() for c in self.claims],
            "yields": [y.to_dict() for y in self.yields],
            "completed": list(self.completed_tasks),
        }

    def merge_digest(self, digest: Dict) -> None:
        """
        Merges incoming remote CRDT state monotonically.
        """
        for t_dict in digest.get("tasks", []):
            task = Task.from_dict(t_dict)
            if task.task_id not in self.tasks:
                self.tasks[task.task_id] = task

        for c_dict in digest.get("claims", []):
            c = ClaimRecord(
                task_id=int(c_dict["task_id"]),
                epoch=int(c_dict["epoch"]),
                robot_id=int(c_dict["robot_id"]),
                timestamp=float(c_dict["timestamp"]),
            )
            self.add_claim(c)

        for y_dict in digest.get("yields", []):
            y = YieldRecord(
                task_id=int(y_dict["task_id"]),
                robot_id=int(y_dict["robot_id"]),
                timestamp=float(y_dict["timestamp"]),
            )
            self.add_yield(y)

        for comp_id in digest.get("completed", []):
            self.mark_completed(int(comp_id))
