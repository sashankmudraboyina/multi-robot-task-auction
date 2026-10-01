# SHADE: Shadow-Hedged Auction with Decaying Estimates
**Portable & Containerized Decentralized Task Allocation Engine for Autonomous Robot Fleets**

---

## 📌 Overview

This package is a standalone, production-ready, and containerized implementation of the **SHADE** decentralized multi-robot task allocation protocol. It decouples the mathematical protocol from simulation runtimes (Unity / CoppeliaSim) and packages it as an autonomous microservice daemon that can be deployed on real Autonomous Mobile Robots (AMRs), edge devices, or cloud simulation clusters.

### Key Capabilities
- **Implicit Bidding ($O(N)$ Comms)**: Deterministic evaluation from signed state manifests without per-task message broadcasts.
- **Ghost Extrapolation**: Silent/partitioned peers continue bidding via optimistic reachability upper bounds.
- **Regret-Bounded Claiming**: Mathematical trade-off between optimality and latency with guaranteed starvation bounds.
- **Progress-Ratchet Leases**: Verifies physical distance reduction ($\Delta d \ge \rho_{\min} \cdot \Delta t$), revoking claims of stalled/Byzantine robots with zero quorum voting.
- **Succession Ranks**: Precomputed runner-up takeovers with sub-second failover.
- **Finish-Line Yield Rule**: Deterministic tie-breaker for healed network partitions.

---

## 📂 Package Architecture

```
shade_engine/
├── Dockerfile                  # Multi-stage, non-root, lightweight container image
├── docker-compose.yml          # Spawns a 5-robot containerized warehouse cluster
├── pyproject.toml / setup.py   # Pip packaging configuration
├── k8s/
│   └── deployment.yaml         # Kubernetes Deployment, Headless Service & ConfigMap
├── shade/
│   ├── models.py               # Vector2D, RobotManifest, Task, Claim, Yield dataclasses
│   ├── crypto.py               # HMAC-SHA256 signature signing and verification
│   ├── gate_trust.py           # Plausibility checks, speed limits, and quarantine strikes
│   ├── bid_evaluator.py        # Multi-attribute scoring and ghost bound calculation
│   ├── claim_manager.py        # Regret bounds, decaying patience, and succession ranks
│   ├── lease_monitor.py        # Progress ratchet verification and lease enforcement
│   ├── ledger.py               # Monotonic G-Set CRDT ledger replica
│   ├── network.py              # UDP broadcast/gossip and mesh networking
│   ├── api.py                  # HTTP REST API and Live Web Dashboard (zero-dependency)
│   └── agent.py                # Complete 10 Hz autonomous agent control loop
├── tests/
│   └── test_shade_protocol.py  # Unit and integration test suite
└── cli.py                      # Unified CLI entrypoint
```

---

## 🚀 Quick Start (Local Standalone)

The engine is engineered with **zero external dependencies** using Python 3 standard library:

### 1. Run Unit Tests
```bash
python3 shade_engine/tests/test_shade_protocol.py
```

### 2. Run Interactive Multi-Robot Fleet Simulation
Simulates 5 robots, task injection, network partition at $t=5\text{s}$, and partition healing at $t=15\text{s}$:
```bash
PYTHONPATH=shade_engine python3 shade_engine/cli.py sim --robots 5 --duration 25
```

### 3. Launch an Individual Robot Node
```bash
PYTHONPATH=shade_engine python3 shade_engine/cli.py node --robot-id 0 --port 8080 --x 10 --y 15
```
Open **`http://localhost:8080/`** in your browser to view the interactive Live Node Dashboard.

---

## 🐳 Containerized Deployment (Docker & Docker Compose)

### 1. Build the Docker Image
```bash
docker build -t shade-protocol:latest shade_engine/
```

### 2. Launch the 5-Robot Fleet Cluster
```bash
docker compose -f shade_engine/docker-compose.yml up -d
```

This starts 5 independent robot containers connected via a private virtual network (`shade-net`):
| Robot | Container Name | HTTP Dashboard | Gossip Port | Initial Pose |
| :--- | :--- | :--- | :--- | :--- |
| Robot 0 | `shade-robot-0` | `http://localhost:8080` | `9999/udp` | (10, 15) |
| Robot 1 | `shade-robot-1` | `http://localhost:8081` | `9999/udp` | (25, 15) |
| Robot 2 | `shade-robot-2` | `http://localhost:8082` | `9999/udp` | (40, 15) |
| Robot 3 | `shade-robot-3` | `http://localhost:8083` | `9999/udp` | (55, 15) |
| Robot 4 | `shade-robot-4` | `http://localhost:8084` | `9999/udp` | (70, 15) |

### 3. Inspect Cluster Health
```bash
docker compose -f shade_engine/docker-compose.yml ps
```

---

## ☸️ Cloud & Edge Cluster Deployment (Kubernetes)

Deploy on Kubernetes, K3s, or MicroK8s:
```bash
kubectl apply -f shade_engine/k8s/deployment.yaml
```

Features included:
* **Headless Service** (`shade-headless`) for peer-to-peer discovery over DNS.
* **ConfigMap** (`shade-config`) for dynamic runtime hyperparameters (`THETA`, `LEASE_DURATION`, `RHO_MIN`).
* **Liveness & Readiness Probes** checking `/health` on port 8080.

---

## 📡 REST API & Integration

Each container exposes an HTTP interface for AMR integration (ROS 2 / ROS / Navigation2):

### Check Node Telemetry
```bash
curl http://localhost:8080/status
```

### Submit a New Warehouse Task
```bash
curl -X POST http://localhost:8080/tasks \
  -H "Content-Type: application/json" \
  -d '{"x": 45.0, "y": 60.0, "priority": 1.5}'
```

### Simulate Network Partition (Disconnect Robot)
```bash
curl -X POST http://localhost:8080/faults/toggle_partition
```

### Simulate Motor Stall (Trigger Progress-Ratchet Revocation)
```bash
curl -X POST http://localhost:8080/faults/toggle_stall
```

---

## 🤖 ROS 2 AMR Integration Guide

To connect a physical AMR running ROS 2:
1. In your ROS 2 navigation node, subscribe to `/amcl_pose` or `/odom` and update the agent pose via `agent.pose = Vector2D(msg.x, msg.y)`.
2. When the agent logs a `CLAIM` event for `held_task_id`, dispatch the goal coordinates to the Nav2 `NavigateToPose` action client.
3. As the robot moves, `agent.tick(now, dt)` continuously validates the progress ratchet.
