"""Read-only status dashboard for the A1Z × G0.5 deployment."""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

DEFAULT_STATE = Path.home() / ".local/state/g05/status.json"
POLICY_PORT = 8765

PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>A1Z × G0.5 Monitor</title>
<style>
:root{color-scheme:dark;--bg:#071018;--panel:#0d1b27;--line:#21384a;--text:#eaf6ff;--muted:#87a5b8;--ok:#38d996;--warn:#ffc857;--bad:#ff6577;--accent:#5cc8ff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% 0,#12334b 0,transparent 35%),var(--bg);font:15px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--text)}
main{max-width:1180px;margin:auto;padding:28px}header{display:flex;justify-content:space-between;align-items:end;gap:20px;margin-bottom:22px}h1{margin:0;font-size:clamp(24px,4vw,42px);letter-spacing:-.05em}#stamp{color:var(--muted)}
.hero{display:grid;grid-template-columns:1.5fr 1fr;gap:14px;margin-bottom:14px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.card{background:linear-gradient(145deg,#102333dd,#0a1721ee);border:1px solid var(--line);border-radius:14px;padding:17px;box-shadow:0 18px 60px #0005}.label{color:var(--muted);text-transform:uppercase;letter-spacing:.12em;font-size:11px}.value{font-size:21px;margin-top:8px;overflow-wrap:anywhere}.detail{color:var(--muted);font-size:13px;margin-top:7px;white-space:pre-wrap}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:8px;background:var(--warn);box-shadow:0 0 14px currentColor}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
pre{margin:8px 0 0;max-height:240px;overflow:auto;color:#b9d8ea;font-size:12px}footer{margin-top:18px;color:var(--muted);font-size:12px}
@media(max-width:820px){.hero,.grid{grid-template-columns:1fr}header{align-items:start;flex-direction:column}}
</style></head>
<body><main>
<header><div><div class="label">Live robotics telemetry</div><h1>A1Z × G0.5</h1></div><div id="stamp">connecting…</div></header>
<section class="hero"><div class="card"><div class="label">Deployment phase</div><div class="value" id="phase">—</div><div class="detail" id="message"></div></div><div class="card"><div class="label">Overall</div><div class="value" id="overall">—</div><div class="detail" id="uptime"></div></div></section>
<section class="grid" id="cards"></section>
<section class="card" style="margin-top:14px"><div class="label">Latest action output</div><pre id="action">No model action received yet.</pre></section>
<section class="card" style="margin-top:14px"><div class="label">Last error / event</div><pre id="event">None</pre></section>
<footer>Read-only monitor · refreshes every second · no motion controls exposed</footer>
</main>
<script>
const esc=v=>String(v??"—").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));
function status(v){const s=String(v??"unknown").toLowerCase();return s==="ready"||s==="online"||s==="connected"||s==="available"||s==="running"?"ok":s==="error"||s==="offline"||s==="missing"?"bad":"warn"}
function card(label,value,detail){return `<article class="card"><div class="label">${esc(label)}</div><div class="value ${status(value)}"><span class="dot"></span>${esc(value)}</div><div class="detail">${esc(detail)}</div></article>`}
async function tick(){try{const r=await fetch("/api/status",{cache:"no-store"}),d=await r.json();phase.textContent=d.phase||"unknown";message.textContent=d.message||"";stamp.textContent=new Date(d.timestamp*1000).toLocaleString();overall.innerHTML=`<span class="dot"></span>${esc(d.overall)}`;overall.className=`value ${status(d.overall)}`;uptime.textContent=`monitor ${d.monitor_uptime_s}s`;
cards.innerHTML=card("CUDA / GPU",d.gpu.status,`${d.gpu.name}\\nVRAM ${d.gpu.used_mb}/${d.gpu.total_mb} MiB · ${d.gpu.utilization}%`) + card("G0.5 policy",d.policy.status,`ws://127.0.0.1:${d.policy.port}\\n${d.policy.detail}`) + card("Camera",d.camera.status,d.camera.detail) + card("CAN / HHS",d.can.status,d.can.detail) + card("Dependency install",d.install.status,d.install.detail) + card("Proxy",d.proxy.status,d.proxy.detail);
action.textContent=JSON.stringify(d.last_action??null,null,2);event.textContent=d.last_event||d.last_error||"None"}catch(e){stamp.textContent="monitor unreachable";overall.textContent=String(e)}}tick();setInterval(tick,1000);
</script></body></html>"""


def _tcp_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def _run(command: list[str], timeout: float = 1.5) -> str:
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _gpu() -> dict[str, Any]:
    binary = shutil.which("nvidia-smi") or "/usr/lib/wsl/lib/nvidia-smi"
    output = _run(
        [
            binary,
            "--query-gpu=name,memory.used,memory.total,utilization.gpu",
            "--format=csv,noheader,nounits",
        ]
    )
    if not output:
        return {"status": "missing", "name": "NVIDIA GPU unavailable", "used_mb": 0, "total_mb": 0, "utilization": 0}
    fields = [field.strip() for field in output.splitlines()[0].split(",")]
    return {
        "status": "available",
        "name": fields[0],
        "used_mb": int(fields[1]),
        "total_mb": int(fields[2]),
        "utilization": int(fields[3]),
    }


def _read_state(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def collect(state_path: Path, started: float) -> dict[str, Any]:
    state = _read_state(state_path)
    video_devices = sorted(str(path) for path in Path("/dev").glob("video*"))
    usb = _run(["lsusb"])
    uv_process = _run(["pgrep", "-af", "uv sync"])
    policy_online = _tcp_open("127.0.0.1", POLICY_PORT)
    proxy_online = _tcp_open("127.0.0.1", 7897)
    state.update(
        {
            "timestamp": time.time(),
            "monitor_uptime_s": int(time.monotonic() - started),
            "overall": state.get("overall", "starting"),
            "phase": state.get("phase", "environment setup"),
            "message": state.get("message", "Preparing G0.5 runtime and hardware inputs."),
            "gpu": _gpu(),
            "policy": {
                "status": "online" if policy_online else state.get("policy_status", "offline"),
                "port": POLICY_PORT,
                "detail": state.get("policy_detail", "Waiting for checkpoint load."),
            },
            "camera": {
                "status": state.get("camera_status", "connected" if video_devices else "missing"),
                "detail": state.get("camera_detail", ", ".join(video_devices) or "No /dev/video device in WSL."),
            },
            "can": {
                "status": state.get("can_status", "connected" if "a8fa:8598" in usb.lower() else "missing"),
                "detail": state.get("can_detail", "HHS a8fa:8598" if "a8fa:8598" in usb.lower() else "HHS USB-CANFD not visible in WSL."),
            },
            "install": {
                "status": "running" if uv_process else state.get("install_status", "idle"),
                "detail": uv_process or state.get("install_detail", "No dependency installer running."),
            },
            "proxy": {
                "status": "online" if proxy_online else "offline",
                "detail": "Mihomo JP/US automatic pool on 127.0.0.1:7897",
            },
            "last_action": state.get("last_action"),
            "last_event": state.get("last_event", ""),
            "last_error": state.get("last_error", ""),
        }
    )
    return state


class Handler(BaseHTTPRequestHandler):
    state_path = DEFAULT_STATE
    started = time.monotonic()

    def do_GET(self) -> None:
        if self.path == "/api/status":
            body = json.dumps(collect(self.state_path, self.started), ensure_ascii=False).encode()
            content_type = "application/json; charset=utf-8"
        elif self.path == "/health":
            body = b"ok\n"
            content_type = "text/plain; charset=utf-8"
        elif self.path == "/":
            body = PAGE.encode()
            content_type = "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE)
    args = parser.parse_args()
    Handler.state_path = args.state_file.expanduser()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"G0.5 monitor listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
