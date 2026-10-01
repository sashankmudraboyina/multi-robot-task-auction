"""
Unified SHADE Fleet Server & Real-Time Dashboard.
Runs all 5 decentralized robot agents and serves:
- Unified Fleet Dashboard & Interactive 2D Map on http://localhost:8000/
- Individual Robot Node Dashboards on http://localhost:8080/ to 8084/
"""
import json
import math
import os
import random
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, List, Optional
from shade.agent import ShadeAgent
from shade.models import Vector2D, Task, TaskState
from shade.api import ShadeApiServer


HTML_FLEET_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>SHADE Fleet Command</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        :root {
            --bg: #0d0f12;
            --panel: #15181e;
            --panel-sub: #101216;
            --border: #232731;
            --border-light: #2e3442;
            --text-main: #e6edf3;
            --text-muted: #8b949e;
            --accent: #d97706;
            --accent-hover: #b45309;
            --green: #10b981;
            --green-bg: #143823;
            --amber: #f59e0b;
            --amber-bg: #4a2800;
            --red: #ef4444;
            --red-bg: #451a1a;
            --purple: #c084fc;
            --purple-bg: #3b1d4a;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            padding: 20px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg);
            color: var(--text-main);
        }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 14px;
            margin-bottom: 18px;
            flex-wrap: wrap;
            gap: 12px;
        }
        .header-title-box h1 {
            margin: 0;
            font-size: 19px;
            letter-spacing: 0.5px;
            font-weight: 700;
            color: var(--accent);
            text-transform: uppercase;
        }
        .subtitle {
            color: var(--text-muted);
            font-size: 12px;
            margin-top: 3px;
            font-family: ui-monospace, monospace;
        }
        .controls { display: flex; gap: 8px; flex-wrap: wrap; }
        button {
            background: #1c2027;
            color: var(--text-main);
            border: 1px solid var(--border);
            padding: 7px 14px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.3px;
            text-transform: uppercase;
            transition: all 0.15s ease-in-out;
        }
        button:hover { background: #272d37; border-color: var(--accent); }
        button.btn-accent {
            background: var(--accent);
            color: #000;
            border-color: var(--accent);
            font-weight: 700;
        }
        button.btn-accent:hover { background: var(--accent-hover); }
        button.btn-warning { border-color: #5c3b0a; color: var(--amber); }
        button.btn-warning:hover { background: #291b07; border-color: var(--amber); }
        button.btn-danger { border-color: #5c1e1e; color: #fca5a5; }
        button.btn-danger:hover { background: #2e1313; border-color: var(--red); }

        .layout {
            display: grid;
            grid-template-columns: 1fr 390px;
            gap: 18px;
        }
        @media (max-width: 1100px) {
            .layout { grid-template-columns: 1fr; }
        }
        .card {
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 16px;
            margin-bottom: 18px;
        }
        .card-title {
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 0.5px;
            text-transform: uppercase;
            color: var(--text-muted);
            margin-top: 0;
            margin-bottom: 14px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 8px;
        }
        #canvasContainer {
            position: relative;
            width: 100%;
            height: 380px;
            background: var(--panel-sub);
            border-radius: 4px;
            overflow: hidden;
            border: 1px solid var(--border);
        }
        canvas { width: 100%; height: 100%; display: block; }
        
        .robots-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
        }
        .robot-tile {
            background: var(--panel-sub);
            border: 1px solid var(--border);
            border-radius: 4px;
            padding: 12px;
            position: relative;
        }
        .robot-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
        .robot-title { font-weight: 700; font-size: 14px; color: var(--accent); font-family: ui-monospace, monospace; }
        .badge {
            font-size: 10px;
            font-weight: 700;
            padding: 2px 7px;
            border-radius: 3px;
            text-transform: uppercase;
            font-family: ui-monospace, monospace;
            letter-spacing: 0.4px;
        }
        .badge-online { background: var(--green-bg); color: var(--green); border: 1px solid #1c5230; }
        .badge-ghost { background: var(--amber-bg); color: var(--amber); border: 1px solid #663a00; }
        .badge-stalled { background: var(--red-bg); color: var(--red); border: 1px solid #632525; }
        .badge-quarantine { background: var(--purple-bg); color: var(--purple); border: 1px solid #4a215d; }

        .stat-line { font-size: 12px; margin: 5px 0; color: var(--text-muted); display: flex; justify-content: space-between; }
        .stat-val { color: var(--text-main); font-weight: 600; font-family: ui-monospace, monospace; }
        
        .links-bar {
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
            font-size: 11px;
            font-family: ui-monospace, monospace;
        }
        .links-bar a {
            color: var(--accent);
            text-decoration: none;
            background: #1c2027;
            padding: 3px 6px;
            border-radius: 3px;
            border: 1px solid var(--border);
        }
        .links-bar a:hover { background: #272d37; border-color: var(--accent); }

        #eventList {
            height: 490px;
            overflow-y: auto;
            font-size: 12px;
            font-family: ui-monospace, monospace;
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .event-row {
            padding: 7px 10px;
            border-radius: 4px;
            background: var(--panel-sub);
            border-left: 3px solid var(--border);
            border-top: 1px solid #161a22;
            border-right: 1px solid #161a22;
            border-bottom: 1px solid #161a22;
        }
        .event-time { color: var(--text-muted); margin-right: 6px; }
        .event-cat { font-weight: 700; margin-right: 6px; }
    </style>
</head>
<body>
    <header>
        <div class="header-title-box">
            <h1>SHADE Fleet Telemetry Control</h1>
            <div class="subtitle">Decentralized Task Allocation & Progress-Ratchet Monitor</div>
        </div>
        <div class="controls">
            <button class="btn-accent" onclick="spawnTask()">Spawn Order</button>
            <button id="autoBtn" onclick="toggleAutoOrders()">Auto-Orders: OFF</button>
            <button class="btn-warning" onclick="togglePartition()">Isolate Peers (R3, R4)</button>
            <button class="btn-danger" onclick="toggleStallWinner()">Inject Motor Stall</button>
            <button onclick="resetFleet()">Reset Fleet</button>
        </div>
    </header>

    <div class="layout">
        <div>
            <div class="card">
                <div class="card-title">
                    <span>Warehouse Floor Plan (100m x 80m Grid)</span>
                    <span style="font-size: 11px; font-family: ui-monospace, monospace; color: var(--text-muted);">Coordinate Space: Metric</span>
                </div>
                <div id="canvasContainer">
                    <canvas id="mapCanvas"></canvas>
                </div>
            </div>

            <div class="card">
                <div class="card-title">
                    <span>Autonomous Fleet Units</span>
                    <div class="links-bar">
                        <span>Node Portals:</span>
                        <a href="http://localhost:8080" target="_blank">R0 (8080)</a>
                        <a href="http://localhost:8081" target="_blank">R1 (8081)</a>
                        <a href="http://localhost:8082" target="_blank">R2 (8082)</a>
                        <a href="http://localhost:8083" target="_blank">R3 (8083)</a>
                        <a href="http://localhost:8084" target="_blank">R4 (8084)</a>
                    </div>
                </div>
                <div class="robots-grid" id="robotsGrid"></div>
            </div>
        </div>

        <div>
            <div class="card">
                <div class="card-title">Protocol Audit Log</div>
                <div id="eventList"></div>
            </div>
        </div>
    </div>

    <script>
        const canvas = document.getElementById('mapCanvas');
        const ctx = canvas.getContext('2d');
        let fleetData = null;

        function resizeCanvas() {
            canvas.width = canvas.parentElement.clientWidth;
            canvas.height = canvas.parentElement.clientHeight;
        }
        window.addEventListener('resize', resizeCanvas);
        resizeCanvas();

        function worldToCanvas(x, y) {
            const pad = 30;
            const w = canvas.width - pad * 2;
            const h = canvas.height - pad * 2;
            const cx = pad + (x / 100.0) * w;
            const cy = canvas.height - (pad + (y / 80.0) * h);
            return [cx, cy];
        }

        function drawMap() {
            if (!fleetData) return;
            ctx.clearRect(0, 0, canvas.width, canvas.height);

            // Draw warehouse aisle grid
            ctx.strokeStyle = '#1e232c';
            ctx.lineWidth = 1;
            for (let x = 10; x <= 90; x += 15) {
                const [p1x, p1y] = worldToCanvas(x, 10);
                const [p2x, p2y] = worldToCanvas(x, 70);
                ctx.beginPath();
                ctx.moveTo(p1x, p1y);
                ctx.lineTo(p2x, p2y);
                ctx.stroke();
            }
            for (let y = 10; y <= 70; y += 15) {
                const [p1x, p1y] = worldToCanvas(10, y);
                const [p2x, p2y] = worldToCanvas(90, y);
                ctx.beginPath();
                ctx.moveTo(p1x, p1y);
                ctx.lineTo(p2x, p2y);
                ctx.stroke();
            }

            // Draw active tasks
            fleetData.tasks.forEach(t => {
                const [tx, ty] = worldToCanvas(t.target_pos.x, t.target_pos.y);
                ctx.fillStyle = t.state === 'CLAIMED' ? '#10b981' : (t.state === 'PATIENCE_WAITING' ? '#f59e0b' : '#64748b');
                ctx.beginPath();
                ctx.arc(tx, ty, 6, 0, Math.PI * 2);
                ctx.fill();
                ctx.strokeStyle = '#0d0f12';
                ctx.lineWidth = 2;
                ctx.stroke();

                ctx.fillStyle = '#94a3b8';
                ctx.font = '10px ui-monospace, monospace';
                ctx.fillText(`T${t.task_id}`, tx + 9, ty - 5);
            });

            // Draw robots
            fleetData.robots.forEach(r => {
                const [rx, ry] = worldToCanvas(r.pose.x, r.pose.y);

                // Draw path to target if holding task
                if (r.held_task_id !== -1) {
                    const task = fleetData.tasks.find(t => t.task_id === r.held_task_id);
                    if (task) {
                        const [tx, ty] = worldToCanvas(task.target_pos.x, task.target_pos.y);
                        ctx.strokeStyle = r.is_stalled ? '#ef4444' : '#10b981';
                        ctx.setLineDash([4, 4]);
                        ctx.beginPath();
                        ctx.moveTo(rx, ry);
                        ctx.lineTo(tx, ty);
                        ctx.stroke();
                        ctx.setLineDash([]);
                    }
                }

                // Robot body
                ctx.fillStyle = r.is_stalled ? '#ef4444' : (!r.is_online ? '#f59e0b' : '#d97706');
                ctx.beginPath();
                ctx.arc(rx, ry, 8, 0, Math.PI * 2);
                ctx.fill();
                ctx.strokeStyle = '#15181e';
                ctx.lineWidth = 2;
                ctx.stroke();

                // Robot label
                ctx.fillStyle = '#e6edf3';
                ctx.font = 'bold 10px ui-monospace, monospace';
                ctx.fillText(`R${r.robot_id}`, rx - 7, ry - 11);
            });
        }

        function updateRobotCards() {
            if (!fleetData) return;
            const grid = document.getElementById('robotsGrid');
            grid.innerHTML = fleetData.robots.map(r => {
                let badgeClass = 'badge-online';
                let badgeText = 'ONLINE';
                if (r.is_stalled) { badgeClass = 'badge-stalled'; badgeText = 'STALLED'; }
                else if (!r.is_online) { badgeClass = 'badge-ghost'; badgeText = 'GHOST'; }
                else if (r.is_quarantined) { badgeClass = 'badge-quarantine'; badgeText = 'QUARANTINE'; }

                const taskStr = r.held_task_id !== -1 ? `T${r.held_task_id}` : 'NONE';
                const distStr = r.held_task_id !== -1 ? `${r.remaining_cost.toFixed(1)} m` : '--';

                return `
                <div class="robot-tile">
                    <div class="robot-header">
                        <span class="robot-title">UNIT R${r.robot_id}</span>
                        <span class="badge ${badgeClass}">${badgeText}</span>
                    </div>
                    <div class="stat-line"><span>Pose:</span><span class="stat-val">(${r.pose.x.toFixed(1)}, ${r.pose.y.toFixed(1)})</span></div>
                    <div class="stat-line"><span>Battery:</span><span class="stat-val">${r.battery.toFixed(1)}%</span></div>
                    <div class="stat-line"><span>Assigned:</span><span class="stat-val">${taskStr}</span></div>
                    <div class="stat-line"><span>Rem. Cost:</span><span class="stat-val">${distStr}</span></div>
                    <div class="stat-line"><span>Strikes:</span><span class="stat-val">${r.strikes}</span></div>
                </div>`;
            }).join('');
        }

        function updateEventLog() {
            if (!fleetData) return;
            const container = document.getElementById('eventList');
            container.innerHTML = fleetData.events.slice(-25).reverse().map(e => {
                let borderCol = '#8b949e';
                let tagCol = '#d97706';
                if (e.category === 'RATCHET' || e.category === 'LEASE_FAIL' || e.category === 'FAULT') {
                    borderCol = '#ef4444'; tagCol = '#ef4444';
                } else if (e.category === 'CLAIM' || e.category === 'COMPLETED') {
                    borderCol = '#10b981'; tagCol = '#10b981';
                } else if (e.category === 'REGRET' || e.category === 'TAKEOVER' || e.category === 'PARTITION') {
                    borderCol = '#f59e0b'; tagCol = '#f59e0b';
                }

                return `
                <div class="event-row" style="border-left-color: ${borderCol};">
                    <span class="event-time">${new Date(e.time * 1000).toLocaleTimeString()}</span>
                    <strong class="event-cat" style="color: ${tagCol};">[R${e.robot_id} ${e.category}]</strong>
                    <span>${e.message}</span>
                </div>`;
            }).join('');
        }

        async function fetchFleet() {
            try {
                const res = await fetch('/api/fleet');
                fleetData = await res.json();
                drawMap();
                updateRobotCards();
                updateEventLog();
            } catch (err) { console.error(err); }
        }

        async function spawnTask() {
            await fetch('/api/spawn_task', { method: 'POST' });
            fetchFleet();
        }

        async function togglePartition() {
            await fetch('/api/toggle_partition', { method: 'POST' });
            fetchFleet();
        }

        async function toggleStallWinner() {
            await fetch('/api/toggle_stall_winner', { method: 'POST' });
            fetchFleet();
        }

        async function resetFleet() {
            await fetch('/api/reset', { method: 'POST' });
            fetchFleet();
        }

        let autoOrdersActive = false;
        async function toggleAutoOrders() {
            const res = await fetch('/api/toggle_auto_orders', { method: 'POST' });
            const data = await res.json();
            autoOrdersActive = data.auto_spawn;
            const btn = document.getElementById('autoBtn');
            btn.innerText = autoOrdersActive ? "Auto-Orders: ON" : "Auto-Orders: OFF";
            btn.style.borderColor = autoOrdersActive ? "var(--green)" : "var(--border)";
            btn.style.color = autoOrdersActive ? "var(--green)" : "var(--text-main)";
            fetchFleet();
        }

        setInterval(fetchFleet, 500);
        fetchFleet();
    </script>
</body>
</html>
"""


class FleetOrchestrator:
    def __init__(self, num_robots: int = 5):
        self.num_robots = num_robots
        self.agents: List[ShadeAgent] = []
        self.node_servers: List[ShadeApiServer] = []
        self.running = True
        self.all_events: List[Dict] = []
        self.auto_spawn = False
        self.last_auto_spawn_time = 0.0

        # Initialize agents
        for i in range(num_robots):
            pos = Vector2D(15.0 + (i * 18.0), 20.0 + (i % 2) * 20.0)
            ag = ShadeAgent(
                robot_id=i,
                initial_pose=pos,
                battery=88.0 + (i * 2.5),
                theta=0.25,
                lease_duration=6.0,
                rho_min=0.30,
            )
            self.agents.append(ag)

        # Pre-seed 3 tasks
        now = time.time()
        for tid in range(1, 4):
            t = Task(
                task_id=tid,
                target_pos=Vector2D(20.0 * tid, 55.0 + (tid * 5.0)),
                creation_time=now,
                deadline=now + 60.0,
                priority=1.0 + (tid * 0.5),
            )
            for ag in self.agents:
                ag.ledger.add_task(t)

    def start(self):
        # Start individual node servers on ports 8080 - 8084
        for i, ag in enumerate(self.agents):
            srv = ShadeApiServer(agent=ag, host="0.0.0.0", port=8080 + i)
            srv.start()
            self.node_servers.append(srv)

        # Background 10 Hz decentralized simulation thread
        self.sim_thread = threading.Thread(target=self._loop, daemon=True)
        self.sim_thread.start()

    def _loop(self):
        last_t = time.time()
        while self.running:
            now = time.time()
            dt = max(0.01, now - last_t)
            last_t = now

            published = []
            for ag in self.agents:
                m = ag.tick(now, dt)
                if m:
                    published.append(m)

            # Gossip exchange between online peers
            for m in published:
                sender = self.agents[m.robot_id]
                if sender.is_online:
                    for receiver in self.agents:
                        if receiver.is_online:
                            receiver.handle_incoming_manifest(m)

            # Collect events
            for ag in self.agents:
                while ag.event_log:
                    self.all_events.append(ag.event_log.pop(0))
            if len(self.all_events) > 80:
                self.all_events = self.all_events[-80:]

            # Auto-spawn orders if enabled
            if self.auto_spawn and now - self.last_auto_spawn_time > 3.0:
                open_tasks = [t for t in self.agents[0].ledger.tasks.values() if t.state in (TaskState.OPEN, TaskState.CLAIMED, TaskState.PATIENCE_WAITING)]
                if len(open_tasks) < 4:
                    self.spawn_random_task()
                    self.last_auto_spawn_time = now

            time.sleep(0.1)

    def reset_fleet(self):
        now = time.time()
        self.all_events.clear()
        for i, ag in enumerate(self.agents):
            ag.pose = Vector2D(15.0 + (i * 18.0), 20.0 + (i % 2) * 20.0)
            ag.battery = 100.0
            ag.held_task_id = -1
            ag.lease_epoch = 0
            ag.remaining_cost = 0.0
            ag.is_online = True
            ag.is_stalled = False
            ag.gate_trust.strikes.clear()
            ag.gate_trust.quarantined.clear()
            ag.lease_monitor.leases.clear()
            ag.ledger.tasks.clear()
            ag.ledger.claims.clear()
            ag.ledger.yields.clear()
            ag.ledger.completed_tasks.clear()
            ag.event_log.clear()

        # Pre-seed 3 fresh tasks
        for tid in range(1, 4):
            t = Task(
                task_id=tid,
                target_pos=Vector2D(20.0 * tid, 55.0 + (tid * 5.0)),
                creation_time=now,
                deadline=now + 60.0,
                priority=1.0 + (tid * 0.5),
            )
            for ag in self.agents:
                ag.ledger.add_task(t)

        self.agents[0].log("RESET", "Fleet simulation reset to clean initial state!")

    def spawn_random_task(self):
        tid = len(self.agents[0].ledger.tasks) + 1
        now = time.time()
        rx = random.uniform(15.0, 85.0)
        ry = random.uniform(25.0, 70.0)
        task = Task(
            task_id=tid,
            target_pos=Vector2D(rx, ry),
            creation_time=now,
            deadline=now + 60.0,
            priority=random.choice([1.0, 1.5, 2.0]),
        )
        for ag in self.agents:
            ag.ledger.add_task(task)
            ag.log("TASK_NEW", f"New Order T{tid} at ({rx:.1f}, {ry:.1f})")

    def toggle_partition(self):
        if len(self.agents) > 3:
            r3 = self.agents[3]
            r4 = self.agents[4] if len(self.agents) > 4 else None
            new_state = not r3.is_online
            r3.is_online = new_state
            if r4:
                r4.is_online = new_state
            cat = "HEAL" if new_state else "PARTITION"
            msg = "Network Healed! R3 & R4 reconnected." if new_state else "Network Partition: R3 & R4 disconnected (Ghosts)!"
            for ag in self.agents:
                ag.log(cat, msg)

    def toggle_stall_winner(self):
        # Find any agent currently holding a task
        active = [ag for ag in self.agents if ag.held_task_id != -1]
        if active:
            target = active[0]
            target.is_stalled = not target.is_stalled
            target.log("FAULT", f"Motor Stall toggled: is_stalled={target.is_stalled}")
        else:
            self.agents[0].log("FAULT", "No robot currently holds a task to stall")

    def get_fleet_telemetry(self) -> Dict:
        robots_data = []
        for ag in self.agents:
            robots_data.append({
                "robot_id": ag.robot_id,
                "pose": ag.pose.to_dict(),
                "battery": ag.battery,
                "held_task_id": ag.held_task_id,
                "remaining_cost": ag.remaining_cost,
                "is_online": ag.is_online,
                "is_stalled": ag.is_stalled,
                "is_quarantined": ag.gate_trust.is_quarantined(ag.robot_id),
                "strikes": ag.gate_trust.strikes.get(ag.robot_id, 0),
            })

        tasks_data = [t.to_dict() for t in self.agents[0].ledger.tasks.values()]

        return {
            "robots": robots_data,
            "tasks": tasks_data,
            "events": self.all_events,
        }


def run_fleet_dashboard():
    print("==================================================================")
    print("🚀 LAUNCHING SHADE DECENTRALIZED FLEET COMMAND & DASHBOARDS...")
    print("==================================================================")

    orchestrator = FleetOrchestrator(num_robots=5)
    orchestrator.start()

    class FleetHTTPHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            if self.path == "/" or self.path == "/dashboard":
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(HTML_FLEET_DASHBOARD.encode("utf-8"))
            elif self.path == "/api/fleet":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                data = orchestrator.get_fleet_telemetry()
                self.wfile.write(json.dumps(data).encode("utf-8"))
            elif self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok","fleet":5}')
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == "/api/spawn_task":
                orchestrator.spawn_random_task()
                self.send_response(200)
                self.end_headers()
            elif self.path == "/api/toggle_partition":
                orchestrator.toggle_partition()
                self.send_response(200)
                self.end_headers()
            elif self.path == "/api/toggle_stall_winner":
                orchestrator.toggle_stall_winner()
                self.send_response(200)
                self.end_headers()
            elif self.path == "/api/reset":
                orchestrator.reset_fleet()
                self.send_response(200)
                self.end_headers()
            elif self.path == "/api/toggle_auto_orders":
                orchestrator.auto_spawn = not orchestrator.auto_spawn
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"auto_spawn": orchestrator.auto_spawn}).encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()

    server = HTTPServer(("0.0.0.0", 8000), FleetHTTPHandler)
    print("✓ Unified Fleet Command Dashboard: http://localhost:8000/")
    print("✓ Individual Robot Dashboards:")
    for i in range(5):
        print(f"   • Robot {i}: http://localhost:{8080 + i}/")
    print("------------------------------------------------------------------")
    print("Server running live. Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Fleet Server...")
        orchestrator.running = False
        server.shutdown()


if __name__ == "__main__":
    run_fleet_dashboard()
