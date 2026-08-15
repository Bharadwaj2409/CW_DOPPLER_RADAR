#!/usr/bin/env python3
"""
LAN web dashboard for the Doppler RADAR GUI.

The desktop PyQt5 application remains the main RADAR/UDP process.
This module exposes a lightweight HTTP API and a mobile-friendly
web dashboard on the same machine.

Default:
    http://<RADAR-PC-IP>:5000
"""

import threading
import time

from flask import Flask, jsonify, render_template_string


HTML = r"""
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Doppler RADAR</title>
<style>
    * { box-sizing: border-box; }
    body {
        margin: 0;
        background: #050b08;
        color: #b8ffd8;
        font-family: Arial, sans-serif;
        overflow-x: hidden;
    }
    header {
        padding: 14px 16px;
        border-bottom: 1px solid #14513a;
        background: #07130e;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    h1 { margin: 0; font-size: 20px; letter-spacing: 1px; }
    #status { font-size: 12px; }
    .online { color: #35ff91; }
    .offline { color: #ff5555; }

    .wrap {
        max-width: 900px;
        margin: auto;
        padding: 12px;
    }

    .radar-card {
        background: #07130e;
        border: 1px solid #14513a;
        border-radius: 12px;
        padding: 10px;
    }

    canvas {
        display: block;
        width: 100%;
        max-width: 760px;
        aspect-ratio: 1 / 1;
        margin: auto;
        background: #060c0a;
        border-radius: 10px;
    }

    .summary {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 8px;
        margin-top: 10px;
    }

    .stat, .target {
        background: #07130e;
        border: 1px solid #14513a;
        border-radius: 10px;
        padding: 10px;
    }

    .stat b {
        display: block;
        font-size: 20px;
        margin-top: 4px;
    }

    .targets {
        margin-top: 10px;
        display: grid;
        gap: 8px;
    }

    .target {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
        gap: 8px;
    }

    .target .title {
        grid-column: 1 / -1;
        color: #35ff91;
        font-weight: bold;
    }

    .label {
        color: #6f9f86;
        font-size: 11px;
        text-transform: uppercase;
    }

    .value { font-size: 15px; margin-top: 3px; }

    @media (max-width: 600px) {
        .summary { grid-template-columns: 1fr 1fr 1fr; }
        .target { grid-template-columns: 1fr 1fr; }
        h1 { font-size: 17px; }
    }
</style>
</head>

<body>
<header>
    <h1>● DOPPLER RADAR</h1>
    <div id="status" class="offline">CONNECTING</div>
</header>

<div class="wrap">
    <div class="radar-card">
        <canvas id="radar" width="700" height="700"></canvas>
    </div>

    <div class="summary">
        <div class="stat">
            <div class="label">Targets</div>
            <b id="count">0</b>
        </div>
        <div class="stat">
            <div class="label">Threshold</div>
            <b id="threshold">--</b>
        </div>
        <div class="stat">
            <div class="label">Link</div>
            <b id="link">--</b>
        </div>
    </div>

    <div class="targets" id="targets"></div>
</div>

<script>
const canvas = document.getElementById("radar");
const ctx = canvas.getContext("2d");

let state = {
    targets: [],
    sweep_angle: 45,
    start_angle: 45,
    end_angle: 135,
    connected: false,
    threshold: -50,
    max_targets: 5
};

function resizeCanvas() {
    const dpr = window.devicePixelRatio || 1;
    const css = Math.min(window.innerWidth - 24, 700);
    canvas.style.width = css + "px";
    canvas.style.height = css + "px";
    canvas.width = Math.floor(css * dpr);
    canvas.height = Math.floor(css * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
window.addEventListener("resize", resizeCanvas);
resizeCanvas();

function drawRadar() {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    const cx = w / 2;
    const cy = h / 2;
    const r = Math.min(w, h) * 0.42;

    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "#060c0a";
    ctx.fillRect(0, 0, w, h);

    // Range rings
    ctx.strokeStyle = "rgba(0,255,120,0.22)";
    ctx.lineWidth = 1;
    for (let i = 1; i <= 4; i++) {
        ctx.beginPath();
        ctx.arc(cx, cy, r * i / 4, 0, Math.PI * 2);
        ctx.stroke();
    }

    // Sector
    const a0 = -state.start_angle * Math.PI / 180;
    const a1 = -state.end_angle * Math.PI / 180;

    ctx.strokeStyle = "rgba(0,255,120,0.65)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(cx, cy, r, a0, a1, true);
    ctx.stroke();

    // Sweep
    const sa = -state.sweep_angle * Math.PI / 180;
    ctx.strokeStyle = "rgba(0,255,120,0.9)";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + r * Math.cos(sa), cy + r * Math.sin(sa));
    ctx.stroke();

    // Origin
    ctx.fillStyle = "#35ff91";
    ctx.beginPath();
    ctx.arc(cx, cy, 4, 0, Math.PI * 2);
    ctx.fill();

    // Targets
    for (const t of state.targets) {
        const rr = r * Math.max(0.06, Math.min(0.98, t.radius_frac));
        const a = -t.angle * Math.PI / 180;
        const x = cx + rr * Math.cos(a);
        const y = cy + rr * Math.sin(a);

        ctx.fillStyle = "rgba(255,40,40,0.95)";
        ctx.beginPath();
        ctx.arc(x, y, 8, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = "#ffd0d0";
        ctx.font = "12px monospace";
        ctx.fillText(
            `${t.velocity >= 0 ? "+" : ""}${t.velocity.toFixed(2)} m/s`,
            x + 12, y - 6
        );
    }

    requestAnimationFrame(drawRadar);
}

function updateTargets() {
    const box = document.getElementById("targets");
    box.innerHTML = "";

    for (let i = 0; i < state.targets.length; i++) {
        const t = state.targets[i];
        const direction = t.velocity >= 0 ? "APPROACHING" : "RECEDING";

        const div = document.createElement("div");
        div.className = "target";
        div.innerHTML = `
            <div class="title">TARGET ${i + 1} — ${direction}</div>
            <div><div class="label">Velocity</div><div class="value">${t.velocity >= 0 ? "+" : ""}${t.velocity.toFixed(3)} m/s</div></div>
            <div><div class="label">Doppler</div><div class="value">${t.doppler_hz.toFixed(2)} Hz</div></div>
            <div><div class="label">Signal</div><div class="value">${t.signal.toFixed(2)} dBFS</div></div>
        `;
        box.appendChild(div);
    }
}

async function poll() {
    try {
        const response = await fetch("/api/state", {cache: "no-store"});
        if (!response.ok) throw new Error("HTTP " + response.status);

        state = await response.json();

        document.getElementById("count").textContent =
            `${state.targets.length}/${state.max_targets}`;
        document.getElementById("threshold").textContent =
            state.threshold.toFixed(1) + " dBFS";

        const status = document.getElementById("status");
        const link = document.getElementById("link");

        if (state.connected) {
            status.textContent = "RADAR ONLINE";
            status.className = "online";
            link.textContent = "ONLINE";
        } else {
            status.textContent = "RADAR IDLE";
            status.className = "offline";
            link.textContent = "IDLE";
        }

        updateTargets();
    } catch (e) {
        document.getElementById("status").textContent = "SERVER OFFLINE";
        document.getElementById("status").className = "offline";
        document.getElementById("link").textContent = "OFFLINE";
    }
}

drawRadar();
setInterval(poll, 150);
poll();
</script>
</body>
</html>
"""


class RadarWebServer:
    def __init__(self, radar_widget, host="0.0.0.0", port=5000):
        self.radar = radar_widget
        self.host = host
        self.port = port
        self._thread = None
        self._server = None
        self._lock = threading.Lock()

        self.app = Flask(
            "radar_web_server",
            static_folder=None,
            template_folder=None,
        )

        @self.app.get("/")
        def index():
            return render_template_string(HTML)

        @self.app.get("/api/state")
        def api_state():
            return jsonify(self.snapshot())

        @self.app.get("/health")
        def health():
            return jsonify({"status": "ok"})

    def snapshot(self):
        # Copy only simple values from the Qt widget. This avoids exposing
        # Qt objects to the Flask thread.
        with self._lock:
            targets = []
            for t in list(self.radar.targets):
                targets.append({
                    "angle": float(t["angle"]),
                    "radius_frac": float(t["radius_frac"]),
                    "velocity": float(t["velocity"]),
                    "doppler_hz": float(t["doppler_hz"]),
                    "signal": float(t["signal"]),
                })

            return {
                "connected": bool(self.radar.connected),
                "threshold": float(self.radar.threshold_dbfs),
                "start_angle": float(self.radar.start_angle),
                "end_angle": float(self.radar.end_angle),
                "sweep_angle": float(self.radar.sweep_angle),
                "velocity_scale": float(self.radar.velocity_scale),
                "max_targets": int(self.radar.MAX_TARGETS),
                "targets": targets,
                "timestamp": time.time(),
            }

    def start(self):
        def run():
            # Disable Flask's reloader; this is embedded inside the PyQt app.
            self.app.run(
                host=self.host,
                port=self.port,
                debug=False,
                threaded=True,
                use_reloader=False,
            )

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self):
        # The embedded Flask development server runs as a daemon thread.
        # The main process exit will terminate it cleanly.
        self._thread = None
