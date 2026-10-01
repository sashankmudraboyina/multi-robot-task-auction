"""
Command Line Interface (CLI) for running SHADE nodes or fleet simulations.
"""
import argparse
import sys
import time
from shade.agent import ShadeAgent
from shade.models import Vector2D, Task
from shade.network import GossipNode
from shade.api import ShadeApiServer


def run_node(args):
    print(f"🚀 Initializing SHADE Robot Node R{args.robot_id} on port {args.port}...")
    initial_pose = Vector2D(args.x, args.y)
    agent = ShadeAgent(
        robot_id=args.robot_id,
        initial_pose=initial_pose,
        battery=args.battery,
        theta=args.theta,
        lease_duration=args.lease,
    )

    gossip = GossipNode(port=args.gossip_port)
    gossip.on_manifest_received = agent.handle_incoming_manifest
    gossip.start()

    api_server = ShadeApiServer(agent=agent, host="0.0.0.0", port=args.port)
    api_server.start()

    print(f"✓ Node R{args.robot_id} active.")
    print(f"✓ Web Dashboard: http://localhost:{args.port}/")
    print(f"✓ UDP Gossip listening on port {args.gossip_port}")

    last_time = time.time()
    try:
        while True:
            now = time.time()
            dt = max(0.01, now - last_time)
            last_time = now

            manifest = agent.tick(now, dt)
            if manifest:
                gossip.broadcast_manifest(manifest)

            time.sleep(0.1)  # 10 Hz loop
    except KeyboardInterrupt:
        print("\nStopping SHADE Node...")
        gossip.stop()
        api_server.stop()
        sys.exit(0)


def run_sim(args):
    """
    Runs a self-contained multi-robot fleet simulation in terminal.
    """
    print(f"🚀 Starting multi-robot SHADE simulation with {args.robots} robots...")
    agents = []
    for i in range(args.robots):
        pos = Vector2D(10.0 + (i * 15.0), 20.0 + (i % 2) * 10.0)
        ag = ShadeAgent(robot_id=i, initial_pose=pos, battery=90.0 + (i * 2.0))
        agents.append(ag)

    # Inject a set of tasks
    now = time.time()
    for t_id in range(1, 4):
        target = Vector2D(25.0 * t_id, 45.0 + t_id * 5.0)
        task = Task(
            task_id=t_id,
            target_pos=target,
            creation_time=now,
            deadline=now + 40.0,
            priority=1.0 + (t_id * 0.5),
        )
        for ag in agents:
            ag.ledger.add_task(task)

    print(f"✓ 3 tasks injected across {args.robots} robots.")
    print("Beginning simulation loop (press Ctrl+C to terminate)...")

    start_sim_time = time.time()
    last_time = start_sim_time

    try:
        step = 0
        while time.time() - start_sim_time < args.duration:
            now = time.time()
            dt = max(0.01, now - last_time)
            last_time = now
            step += 1

            # Simulated network partition at t = 5s (disconnect R3 and R4)
            if step == 50 and len(agents) > 3:
                print("\n⚡ [SIMULATION EVENT] Injecting Network Partition: R3 & R4 disconnected!")
                agents[3].is_online = False
                if len(agents) > 4:
                    agents[4].is_online = False

            # Heal partition at t = 15s
            if step == 150 and len(agents) > 3:
                print("\n🌐 [SIMULATION EVENT] Network Healed! R3 & R4 reconnected.")
                agents[3].is_online = True
                if len(agents) > 4:
                    agents[4].is_online = True

            # Exchange manifests across online peers
            published_manifests = []
            for ag in agents:
                m = ag.tick(now, dt)
                if m:
                    published_manifests.append(m)

            for m in published_manifests:
                sender_ag = agents[m.robot_id]
                if sender_ag.is_online:
                    for receiver_ag in agents:
                        if receiver_ag.is_online:
                            receiver_ag.handle_incoming_manifest(m)

            # Print status every 2 seconds
            if step % 20 == 0:
                print(f"\n--- Simulation Time: {now - start_sim_time:.1f}s ---")
                for ag in agents:
                    status_str = "STALLED" if ag.is_stalled else ("GHOST/PARTITIONED" if not ag.is_online else "ONLINE")
                    task_str = f"Held: T{ag.held_task_id} (Rem: {ag.remaining_cost:.1f}m)" if ag.held_task_id != -1 else "Idle"
                    print(f"Robot R{ag.robot_id}: [{status_str}] Pos: ({ag.pose.x:.1f}, {ag.pose.y:.1f}) | {task_str} | Batt: {ag.battery:.1f}%")

            time.sleep(0.1)

    except KeyboardInterrupt:
        pass

    print("\n✓ Simulation completed successfully.")


def main():
    parser = argparse.ArgumentParser(description="SHADE Protocol CLI")
    subparsers = parser.add_subparsers(dest="command")

    # Node command
    node_p = subparsers.add_parser("node", help="Run a single SHADE agent node")
    node_p.add_argument("--robot-id", type=int, default=0)
    node_p.add_argument("--x", type=float, default=10.0)
    node_p.add_argument("--y", type=float, default=10.0)
    node_p.add_argument("--battery", type=float, default=100.0)
    node_p.add_argument("--theta", type=float, default=0.25)
    node_p.add_argument("--lease", type=float, default=6.0)
    node_p.add_argument("--port", type=int, default=8080)
    node_p.add_argument("--gossip-port", type=int, default=9999)

    # Sim command
    sim_p = subparsers.add_parser("sim", help="Run multi-agent fleet simulation")
    sim_p.add_argument("--robots", type=int, default=5)
    sim_p.add_argument("--duration", type=float, default=25.0)

    args = parser.parse_args()
    if args.command == "node":
        run_node(args)
    elif args.command == "sim":
        run_sim(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
