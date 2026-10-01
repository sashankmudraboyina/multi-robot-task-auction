"""
REST API and Web Dashboard using standard library http.server (zero external dependencies).
"""
import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from typing import Optional
from .agent import ShadeAgent
from .models import Task, Vector2D, TaskState


HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
    <title>SHADE Node Telemetry</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        :root {
            --bg: #101216;
            --panel: #181b22;
            --border: #282f3d;
            --text-main: #e6edf3;
            --text-muted: #8b949e;
            --accent: #d97706;
            --accent-hover: #b45309;
            --success-bg: #143823;
            --success-text: #4ade80;
            --warning-bg: #4a2800;
            --warning-text: #fbbf24;
            --danger-bg: #451a1a;
            --danger-text: #f87171;
        }
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg);
            color: var(--text-main);
            margin: 0;
            padding: 24px;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            border-bottom: 1px solid var(--border);
            padding-bottom: 12px;
            margin-bottom: 20px;
        }
        h1 {
            margin: 0;
            font-size: 20px;
            letter-spacing: 0.5px;
            text-transform: uppercase;
            font-weight: 700;
            color: var(--accent);
        }
        .header-sub { font-size: 12px; color: var(--text-muted); font-family: ui-monospace, monospace; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; margin-bottom: 20px; }
        .card {
            background: var(--panel);
            border-radius: 6px;
            padding: 18px;
            border: 1px solid var(--border);
        }
        h2 {
            margin-top: 0;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
            border-bottom: 1px solid var(--border);
            padding-bottom: 8px;
            margin-bottom: 14px;
        }
        .data-row {
            display: flex;
            justify-content: space-between;
            padding: 6px 0;
            font-size: 13px;
            border-bottom: 1px solid #1f242e;
        }
        .data-label { color: var(--text-muted); }
        .data-val { font-family: ui-monospace, monospace; font-weight: 600; color: var(--text-main); }
        .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.5px;
            text-transform: uppercase;
            font-family: ui-monospace, monospace;
        }
        .badge-green { background: var(--success-bg); color: var(--success-text); border: 1px solid #1c5230; }
        .badge-red { background: var(--danger-bg); color: var(--danger-text); border: 1px solid #632525; }
        .badge-yellow { background: var(--warning-bg); color: var(--warning-text); border: 1px solid #663a00; }
        button {
            background: #252b36;
            color: var(--text-main);
            border: 1px solid var(--border);
            padding: 8px 14px;
            border-radius: 4px;
            cursor: pointer;
            font-weight: 600;
            font-size: 12px;
            letter-spacing: 0.3px;
            margin-right: 8px;
            margin-top: 8px;
            transition: all 0.15s ease-in-out;
        }
        button:hover { background: #323b49; border-color: var(--accent); }
        button.btn-accent { background: var(--accent); color: #000; border-color: var(--accent); }
        button.btn-accent:hover { background: var(--accent-hover); }
        button.btn-danger { background: #3d1c1c; border-color: #632525; color: #fca5a5; }
        button.btn-danger:hover { background: #542222; }
        #eventLog {
            max-height: 280px;
            overflow-y: auto;
            font-family: ui-monospace, monospace;
            font-size: 12px;
        }
        .log-item {
            padding: 6px 0;
            border-bottom: 1px solid #1f242e;
            display: flex;
            gap: 10px;
        }
        .log-time { color: var(--text-muted); }
        .log-cat { color: var(--accent); font-weight: 600; }
    </style>
</head>
<body>
    <div class="header">
        <h1>SHADE Node Telemetry :: Robot <span id="robotId">...</span></h1>
        <div class="header-sub">PORT: <span id="portDisplay">LOCAL</span> | PROTOCOL: SHADE 1.0</div>
    </div>
    <div class="grid">
        <div class="card">
            <h2>Robot Telemetry</h2>
            <div class="data-row"><span class="data-label">Network Status</span><span id="onlineBadge" class="badge">ONLINE</span></div>
            <div class="data-row"><span class="data-label">Coordinates (X, Y)</span><span id="posCoords" class="data-val">(0.0, 0.0)</span></div>
            <div class="data-row"><span class="data-label">Battery Level</span><span id="batteryVal" class="data-val">100.0%</span></div>
            <div class="data-row"><span class="data-label">Assigned Task</span><span id="heldTaskVal" class="data-val">NONE</span></div>
            <div class="data-row"><span class="data-label">Distance to Goal</span><span id="costVal" class="data-val">0.00 m</span></div>
            <div class="data-row"><span class="data-label">Fault Strikes / Quarantine</span><span id="strikesVal" class="data-val">0</span></div>
        </div>
        <div class="card">
            <h2>Simulation Controls</h2>
            <button onclick="spawnTask()" class="btn-accent">Spawn Random Task</button>
            <button onclick="postAction('/faults/toggle_partition')">Toggle Network Partition</button>
            <button onclick="postAction('/faults/toggle_stall')" class="btn-danger">Toggle Motor Stall</button>
        </div>
    </div>
    <div class="card">
        <h2>Live Event Log</h2>
        <div id="eventLog"></div>
    </div>
    <script>
        async function fetchStatus() {
            try {
                const res = await fetch('/status');
                const data = await res.json();
                document.getElementById('robotId').innerText = "R" + data.robot_id;
                document.getElementById('posCoords').innerText = "(" + data.pose.x.toFixed(1) + ", " + data.pose.y.toFixed(1) + ")";
                document.getElementById('batteryVal').innerText = data.battery.toFixed(1) + "%";
                document.getElementById('heldTaskVal').innerText = data.held_task_id !== -1 ? "TASK T" + data.held_task_id : "IDLE";
                document.getElementById('costVal').innerText = data.remaining_cost.toFixed(2) + " m";
                document.getElementById('strikesVal').innerText = data.strikes + (data.is_quarantined ? " [QUARANTINED]" : "");
                
                const badge = document.getElementById('onlineBadge');
                if (data.is_stalled) {
                    badge.innerText = "STALLED"; badge.className = "badge badge-red";
                } else if (!data.is_online) {
                    badge.innerText = "PARTITIONED"; badge.className = "badge badge-yellow";
                } else {
                    badge.innerText = "ONLINE"; badge.className = "badge badge-green";
                }

                const logDiv = document.getElementById('eventLog');
                logDiv.innerHTML = data.event_log.slice(-12).reverse().map(e => 
                    `<div class="log-item">
                        <span class="log-time">${new Date(e.time * 1000).toLocaleTimeString()}</span>
                        <span class="log-cat">[${e.category}]</span>
                        <span>${e.message}</span>
                    </div>`
                ).join('');
            } catch (err) { console.error(err); }
        }
        async function postAction(url) {
            await fetch(url, { method: 'POST' });
            fetchStatus();
        }
        async function spawnTask() {
            const rx = Math.floor(Math.random() * 80) + 10;
            const ry = Math.floor(Math.random() * 80) + 10;
            await fetch('/tasks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ x: rx, y: ry, priority: 1.5 })
            });
            fetchStatus();
        }
        setInterval(fetchStatus, 1000);
        fetchStatus();
    </script>
</body>
</html>
"""


class ShadeApiServer:
    """
    Spawns a background HTTP API server for telemetry and control.
    """
    def __init__(self, agent: ShadeAgent, host: str = "0.0.0.0", port: int = 8080):
        self.agent = agent
        self.host = host
        self.port = port
        self.httpd: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        agent_ref = self.agent

        class RequestHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Suppress standard logging to stdout

            def do_GET(self):
                if self.path == "/health":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "robot_id": agent_ref.robot_id}).encode())
                elif self.path == "/status":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    data = {
                        "robot_id": agent_ref.robot_id,
                        "pose": agent_ref.pose.to_dict(),
                        "battery": agent_ref.battery,
                        "held_task_id": agent_ref.held_task_id,
                        "remaining_cost": agent_ref.remaining_cost,
                        "is_online": agent_ref.is_online,
                        "is_stalled": agent_ref.is_stalled,
                        "is_quarantined": agent_ref.gate_trust.is_quarantined(agent_ref.robot_id),
                        "strikes": agent_ref.gate_trust.strikes.get(agent_ref.robot_id, 0),
                        "event_log": agent_ref.event_log,
                    }
                    self.wfile.write(json.dumps(data).encode())
                elif self.path == "/" or self.path == "/dashboard":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(HTML_DASHBOARD.encode())
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else ""

                if self.path == "/faults/toggle_partition":
                    agent_ref.is_online = not agent_ref.is_online
                    agent_ref.log("FAULT", f"Partition toggled: is_online={agent_ref.is_online}")
                    self.send_response(200)
                    self.end_headers()
                elif self.path == "/faults/toggle_stall":
                    agent_ref.is_stalled = not agent_ref.is_stalled
                    agent_ref.log("FAULT", f"Stall toggled: is_stalled={agent_ref.is_stalled}")
                    self.send_response(200)
                    self.end_headers()
                elif self.path == "/tasks":
                    try:
                        p = json.loads(body) if body else {}
                        tx = float(p.get("x", 40.0))
                        ty = float(p.get("y", 40.0))
                        pri = float(p.get("priority", 1.0))
                        tid = len(agent_ref.ledger.tasks) + 1
                        now = time.time()
                        task = Task(
                            task_id=tid,
                            target_pos=Vector2D(tx, ty),
                            creation_time=now,
                            deadline=now + 60.0,
                            priority=pri,
                        )
                        agent_ref.ledger.add_task(task)
                        agent_ref.log("TASK_ADD", f"Created Task T{tid} at ({tx}, {ty})")
                        self.send_response(201)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps(task.to_dict()).encode())
                    except Exception as ex:
                        self.send_response(400)
                        self.end_headers()
                        self.wfile.write(str(ex).encode())
                else:
                    self.send_response(404)
                    self.end_headers()

        self.httpd = HTTPServer((self.host, self.port), RequestHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
