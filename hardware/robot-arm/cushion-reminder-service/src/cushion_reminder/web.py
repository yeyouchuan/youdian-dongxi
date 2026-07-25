"""Local scenario trigger API and monitoring console."""

from __future__ import annotations

import argparse
import os
import threading
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from .actuator_tools import (
    CameraGeometry,
    OpenAICorrectionPlanner,
    SshMarkActuatorTools,
)
from .camera_capture import SshMarkObservationAdapter
from .execution import (
    NeutralPoseExecutor,
    RobotExecutor,
    ShadowNeutralPoseExecutor,
    ShadowRobotExecutor,
    SshMarkNeutralPoseExecutor,
    SshMarkRobotExecutor,
)
from .hardware import HardwareProbe, SshMarkHardwareProbe
from .jobs import JobManager
from .manipulation_workflow import ManipulationWorkflow
from .manual_control import (
    ManualControl,
    ShadowManualControl,
    SshMarkManualControl,
)
from .mqtt_bridge import CushionMqttBridge, MqttBridge, PostureDecision
from .openai_evaluator import OpenAIVisionEvaluator
from .readiness import build_readiness
from .scenarios import SCENARIOS, get_scenario
from .vision import CameraView, FrameStore, parse_captured_at


class ManualJogRequest(BaseModel):
    control: str
    direction: int


class ManualSetRequest(BaseModel):
    control: str
    value: float


_INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>SmartCushion → A1Z 场景控制台</title>
  <style>
    :root { color-scheme: dark; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    body { max-width: 1100px; margin: 32px auto; padding: 0 20px; background:#101418; color:#e7edf3; }
    h1 { font: 700 28px system-ui; margin-bottom: 4px; }
    .sub { color:#94a3b8; margin-bottom: 24px; }
    #mode { color:#fbbf24; }
    .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(270px,1fr)); gap:12px; }
    .card { border:1px solid #334155; border-radius:10px; padding:16px; background:#17202a; }
    .card h2 { font:600 17px system-ui; margin:0 0 8px; }
    .card p { min-height:54px; color:#b6c2cf; font:14px/1.5 system-ui; }
    button { background:#2563eb; color:white; border:0; border-radius:7px; padding:9px 13px; cursor:pointer; }
    button.neutral { background:#d97706; font-weight:700; }
    button:disabled { opacity:.45; cursor:not-allowed; }
    pre { min-height:320px; max-height:55vh; overflow:auto; padding:16px; background:#050708;
          border:1px solid #334155; border-radius:10px; white-space:pre-wrap; }
    .warning { color:#fbbf24; }
    #hardware { min-height:120px; max-height:260px; }
    #mqtt-log { min-height:150px; max-height:280px; }
    #mqtt-status { color:#cbd5e1; font:14px/1.6 system-ui; margin-bottom:12px; }
    .mqtt-actions { display:flex; flex-wrap:wrap; gap:8px; }
    .mqtt-actions button { background:#0f766e; }
    .manual-panel { margin-top:28px; border-color:#475569; }
    .manual-head { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }
    .manual-head p { min-height:0; margin:4px 0 14px; }
    .manual-state { color:#93c5fd; font:13px/1.5 ui-monospace,monospace; text-align:right; }
    .joint-controls { display:grid; grid-template-columns:repeat(3,minmax(180px,1fr)); gap:10px; }
    .joint-control { display:grid; grid-template-columns:44px 1fr 44px 54px; align-items:center;
                     gap:8px; padding:10px; border:1px solid #334155; border-radius:9px;
                     background:#101820; }
    .joint-control button { padding:8px 0; font-size:17px; background:#475569; }
    .joint-control button:first-child { background:#7c3aed; }
    .joint-info { text-align:center; font:600 14px system-ui; }
    .joint-value { width:100%; box-sizing:border-box; margin-top:4px; padding:5px 6px;
                   border:1px solid #475569; border-radius:5px; outline:none;
                   background:#0b1118; color:#93c5fd; text-align:center;
                   font:12px/1.4 ui-monospace,monospace; }
    .joint-value:focus { border-color:#60a5fa; box-shadow:0 0 0 2px #2563eb33; }
    .joint-control button.apply { background:#2563eb; font:600 12px system-ui; }
    #manual-message { min-height:20px; margin:12px 0 0; color:#94a3b8; font:13px/1.5 system-ui; }
    #manual-message.error { color:#fca5a5; }
    .camera-panel { display:grid; grid-template-columns:minmax(260px,1fr) minmax(320px,2fr);
                    gap:14px; align-items:start; }
    #camera-status { min-height:180px; max-height:260px; margin:0; }
    .camera-actions { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
    .camera-actions button { background:#0369a1; }
    .camera-previews { display:grid; grid-template-columns:repeat(2,minmax(0,1fr));
                       gap:8px; grid-column:1/-1; }
    .camera-preview { margin:0; padding:8px; border:1px solid #334155;
                      border-radius:8px; background:#0b1118; }
    .camera-preview img { display:block; width:100%; aspect-ratio:4/3;
                          object-fit:contain; background:#050708; }
    .camera-preview figcaption { margin-top:6px; color:#94a3b8;
                                 font:12px/1.4 system-ui; }
    #preview-wrist { transform:rotate(180deg); }
    @media (max-width:720px) {
      .joint-controls { grid-template-columns:1fr; }
      .manual-head { display:block; }
      .manual-state { text-align:left; margin-bottom:12px; }
      .camera-panel { grid-template-columns:1fr; }
      .camera-previews { grid-template-columns:1fr; }
    }
  </style>
</head>
<body>
  <h1>SmartCushion → A1Z 场景控制台</h1>
  <div class="sub">执行模式：<strong id="mode">loading</strong> · 一次只运行一个机器人任务</div>
  <div class="warning">真人场景仅允许非接触动作；当前系统没有力/触觉安全闭环。</div>
  <h2>MQTT 坐垫事件</h2>
  <div class="card">
    <div id="mqtt-status">正在连接 Broker…</div>
    <div class="mqtt-actions">
      <button id="mqtt-occupied">发布入座样本</button>
      <button id="mqtt-continuous">模拟连续在座 60 秒</button>
      <button id="mqtt-away">发布离座样本</button>
      <button id="mqtt-radar">发布雷达样本</button>
    </div>
  </div>
  <pre id="mqtt-log">等待 zuodian/# 事件…</pre>
  <h2>双视角视觉验收</h2>
  <div class="card camera-panel">
    <div>
      <div class="camera-actions">
        <button id="capture-two-views">抓取并显示两路帧</button>
      </div>
      <p>exterior_right=Mark 笔记本固定外部视角；wrist=夹爪随动 DaBai（180°）。</p>
    </div>
    <pre id="camera-status">正在读取两路相机状态…</pre>
    <div class="camera-previews">
      <figure class="camera-preview">
        <img id="preview-exterior-right" alt="Mark 固定外部相机最新帧">
        <figcaption>exterior_right · Mark 笔记本 · 夹爪对侧</figcaption>
      </figure>
      <figure class="camera-preview">
        <img id="preview-wrist" alt="DaBai 夹爪随动相机最新帧">
        <figcaption>wrist · DaBai · 随夹爪运动 · 页面旋转 180°</figcaption>
      </figure>
    </div>
  </div>
  <h2>Mark USB / CAN / Camera</h2>
  <pre id="hardware">正在读取 Mark 硬件接口…</pre>
  <h2>确定性控制</h2>
  <div class="card">
    <h2>回到中立位</h2>
    <p>不经过模型，将 J1/J2/J3/J5/J6 移动到 0°, 60°, -60°, 0°, 0°；J4 保持锁定。</p>
    <button id="return-neutral" class="neutral">回到中立位</button>
  </div>
  <div class="card">
    <h2>J3 降温零位</h2>
    <p>不经过模型，将 J1/J2/J3/J5/J6 全部移动到 0°，释放 J3 持续负载；J4 保持锁定。</p>
    <button id="return-zero" class="neutral">移动到 0°, 0°, 0°, 0°, 0°</button>
  </div>
  <h2>预设场景</h2>
  <div id="scenarios" class="grid"></div>
  <h2>事件日志</h2>
  <pre id="log">等待触发…</pre>
  <section class="card manual-panel">
    <div class="manual-head">
      <div>
        <h2>API 操控测试</h2>
        <p>可直接输入目标值并设置，也可用箭头步进 2°；J4 由安全守护程序锁定。</p>
      </div>
      <div id="manual-state" class="manual-state">正在读取关节状态…</div>
    </div>
    <div id="joint-controls" class="joint-controls"></div>
    <div id="manual-message">五轴：J1 / J2 / J3 / J5 / J6 · Gripper 每次调整 10%</div>
  </section>
<script>
let currentJob = null, lastSequence = 0, pollTimer = null;
let mqttLastSequence = 0;
let manualBusy = false;
const log = document.querySelector('#log');
const hardware = document.querySelector('#hardware');
const cameraStatus = document.querySelector('#camera-status');
const mqttLog = document.querySelector('#mqtt-log');
const mqttStatus = document.querySelector('#mqtt-status');
const mqttTestUrls = {
  occupied: '/api/mqtt/test/occupied',
  continuous: '/api/mqtt/test/continuous-seated',
  away: '/api/mqtt/test/away',
  radar: '/api/mqtt/test/radar'
};
function appendMqtt(event) {
  const data = event.data ? ` ${JSON.stringify(event.data)}` : '';
  mqttLog.textContent += `\\n[${event.at}] ${event.level.toUpperCase()} ${event.message}${data}`;
  mqttLog.scrollTop = mqttLog.scrollHeight;
}
async function refreshMqtt() {
  try {
    const state = await fetch('/api/mqtt/status').then(r => r.json());
    const connection = state.connected ? '已连接' : '重连中';
    const posture = state.pose || '-';
    const heart = state.last_radar?.heart_med ?? '-';
    const breath = state.last_radar?.breath_med ?? '-';
    mqttStatus.textContent =
      `Broker ${state.transport || 'tcp'}://${state.host}:${state.port} · ${connection} · ` +
      `topic=${state.topic_filter} · ` +
      `pose=${posture} occupied=${state.occupied} seated=${state.seated_seconds}s / ` +
      `${state.threshold_seconds}s · heart_med=${heart} breath_med=${breath}`;
    const events = await fetch(`/api/mqtt/events?after=${mqttLastSequence}`).then(r => r.json());
    for (const event of events) {
      appendMqtt(event);
      mqttLastSequence = event.sequence;
      if (event.message === 'Robot reminder job created' && event.data?.id) {
        void watchJob(event.data.id);
      }
    }
  } catch (error) {
    mqttStatus.textContent = `MQTT status failed: ${error}`;
  }
}
async function publishMqtt(kind) {
  const response = await fetch(mqttTestUrls[kind], {method:'POST'});
  const body = await response.json();
  if (!response.ok) {
    appendMqtt({
      at:new Date().toISOString(), level:'error',
      message:body.detail || 'MQTT test publish failed', data:null
    });
  }
  await refreshMqtt();
}
async function refreshHardware() {
  try {
    const state = await fetch('/api/hardware').then(r => r.json());
    const lines = [
      `probe=${state.probed_at}`,
      `host=${state.host} healthy=${state.healthy}`,
      `a1z_socket=${state.a1z_socket} policy_relay_8765=${state.policy_relay}`,
      '',
      '[CAN]', ...(state.can || []),
      '',
      '[DEVICE NODES]', ...(state.device_nodes || []),
      '',
      '[DEVICE → VID:PID / SERIAL]', ...(state.device_details || []),
      '',
      '[STABLE LINKS]', ...(state.stable_links || []),
      '',
      '[USB VID:PID]', ...(state.usb_devices || []),
      '',
      '[USB/IP]', ...(state.usbip || [])
    ];
    if (state.error) lines.push('', `ERROR ${state.error}`);
    hardware.textContent = lines.join('\\n');
  } catch (error) {
    hardware.textContent = `hardware probe failed: ${error}`;
  }
}
async function refreshCameraStatus() {
  try {
    const state = await fetch('/api/cameras/status').then(r => r.json());
    const lines = [
      `ready=${state.ready} max_age=${state.max_age_seconds}s`,
      `checked=${state.checked_at}`,
      ''
    ];
    for (const view of state.required_views) {
      const item = state.views[view];
      const frame = item.frame;
      lines.push(
        `${view}: present=${item.present} fresh=${item.fresh}` +
        (frame ? ` age=${frame.age_seconds}s source=${frame.source}` : '')
      );
      if (frame) lines.push(`  bytes=${frame.bytes} sha256=${frame.sha256.slice(0,12)}`);
    }
    cameraStatus.textContent = lines.join('\\n');
  } catch (error) {
    cameraStatus.textContent = `camera status failed: ${error}`;
  }
}
function refreshCameraPreviews() {
  const stamp = Date.now();
  for (const view of ['exterior-right', 'wrist']) {
    document.querySelector(`#preview-${view}`).src =
      `/api/cameras/${view.replaceAll('-', '_')}/frame?t=${stamp}`;
  }
}
async function captureTwoViews() {
  const button = document.querySelector('#capture-two-views');
  button.disabled = true;
  cameraStatus.textContent = '正在边界抓取 Mark 右视角和 DaBai 腕部视角…';
  try {
    const response = await fetch('/api/cameras/capture-two-view', {method:'POST'});
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || '两路相机抓取失败');
    await refreshCameraStatus();
    refreshCameraPreviews();
  } catch (error) {
    cameraStatus.textContent = `Two-view capture failed: ${error}`;
  } finally {
    button.disabled = false;
  }
}
function append(event) {
  const data = event.data ? ` ${JSON.stringify(event.data)}` : '';
  log.textContent += `\\n[${event.at}] ${event.level.toUpperCase()} ${event.message}${data}`;
  log.scrollTop = log.scrollHeight;
}
const manualControls = [
  {id:'j1', label:'轴 1', jointIndex:0, min:-120, max:120},
  {id:'j2', label:'轴 2', jointIndex:1, min:0, max:180},
  {id:'j3', label:'轴 3', jointIndex:2, min:-180, max:0},
  {id:'j5', label:'轴 4', jointIndex:4, min:-85, max:85},
  {id:'j6', label:'轴 5', jointIndex:5, min:-115, max:115},
  {id:'gripper', label:'Gripper', jointIndex:null, min:0, max:100}
];
function renderManual(state) {
  for (const control of manualControls) {
    const value = control.id === 'gripper'
      ? Math.round(state.gripper * 100)
      : Number(state.joints_degrees[control.jointIndex]).toFixed(1);
    document.querySelector(`#manual-${control.id} .joint-value`).value = value;
  }
  document.querySelector('#manual-state').textContent =
    `${state.mode} · 步进 ${state.joint_step_degrees}° / ${Math.round(state.gripper_step * 100)}%`;
}
function setManualMessage(message, isError=false) {
  const target = document.querySelector('#manual-message');
  target.textContent = message;
  target.classList.toggle('error', isError);
}
async function refreshManual() {
  try {
    const response = await fetch('/api/manual-control');
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || '读取失败');
    renderManual(body);
  } catch (error) {
    setManualMessage(`状态读取失败：${error}`, true);
  }
}
async function jogManual(control, direction) {
  if (manualBusy) return;
  manualBusy = true;
  document.querySelectorAll('.joint-control button').forEach(b => b.disabled = true);
  setManualMessage(`正在控制 ${control.toUpperCase()}…`);
  try {
    const response = await fetch('/api/manual-control/jog', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({control, direction})
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || '控制失败');
    renderManual(body);
    setManualMessage(`${control.toUpperCase()} 指令已接受`);
  } catch (error) {
    setManualMessage(`控制失败：${error}`, true);
  } finally {
    manualBusy = false;
    document.querySelectorAll('.joint-control button').forEach(b => b.disabled = false);
  }
}
async function setManual(control) {
  if (manualBusy) return;
  const input = document.querySelector(`#manual-${control} .joint-value`);
  const shownValue = Number(input.value);
  if (!Number.isFinite(shownValue)) {
    setManualMessage(`${control.toUpperCase()} 请输入有效数字`, true);
    input.focus();
    return;
  }
  const value = control === 'gripper' ? shownValue / 100 : shownValue;
  manualBusy = true;
  document.querySelectorAll('.joint-control button, .joint-value')
    .forEach(element => element.disabled = true);
  setManualMessage(`正在设置 ${control.toUpperCase()}…`);
  try {
    const response = await fetch('/api/manual-control/set', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({control, value})
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || '设置失败');
    renderManual(body);
    setManualMessage(`${control.toUpperCase()} 已设置`);
  } catch (error) {
    setManualMessage(`设置失败：${error}`, true);
  } finally {
    manualBusy = false;
    document.querySelectorAll('.joint-control button, .joint-value')
      .forEach(element => element.disabled = false);
  }
}
async function refreshJob() {
  if (!currentJob) return;
  const events = await fetch(`/api/jobs/${currentJob}/events?after=${lastSequence}`).then(r => r.json());
  for (const event of events) { append(event); lastSequence = event.sequence; }
  const job = await fetch(`/api/jobs/${currentJob}`).then(r => r.json());
  if (job.status === 'succeeded' || job.status === 'failed') {
    append({at:new Date().toISOString(), level:'status', message:`job=${job.status}`, data:null});
    clearInterval(pollTimer); pollTimer = null;
    document.querySelectorAll('button').forEach(b => b.disabled = false);
  }
}
async function watchJob(jobId) {
  if (pollTimer) clearInterval(pollTimer);
  currentJob = jobId;
  lastSequence = 0;
  log.textContent = '';
  document.querySelectorAll('button').forEach(b => b.disabled = true);
  pollTimer = setInterval(refreshJob, 500);
  await refreshJob();
}
async function triggerRequest(url) {
  document.querySelectorAll('button').forEach(b => b.disabled = true);
  log.textContent = '';
  lastSequence = 0;
  const response = await fetch(url, {method:'POST'});
  const body = await response.json();
  if (!response.ok) {
    log.textContent = `ERROR ${body.detail}`;
    document.querySelectorAll('button').forEach(b => b.disabled = false);
    return;
  }
  await watchJob(body.id);
}
async function trigger(id) {
  return triggerRequest(`/api/scenarios/${id}/trigger`);
}
async function load() {
  const status = await fetch('/api/status').then(r => r.json());
  document.querySelector('#mode').textContent = status.execution_mode;
  const scenarios = await fetch('/api/scenarios').then(r => r.json());
  const root = document.querySelector('#scenarios');
  for (const scenario of scenarios) {
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `<h2>${scenario.title}</h2><p>${scenario.description}</p>
      <button>触发场景</button>`;
    card.querySelector('button').onclick = () => trigger(scenario.id);
    root.appendChild(card);
  }
  document.querySelector('#return-neutral').onclick =
    () => triggerRequest('/api/commands/return-neutral');
  document.querySelector('#return-zero').onclick =
    () => triggerRequest('/api/commands/return-zero');
  document.querySelector('#mqtt-occupied').onclick = () => publishMqtt('occupied');
  document.querySelector('#mqtt-continuous').onclick = () => publishMqtt('continuous');
  document.querySelector('#mqtt-away').onclick = () => publishMqtt('away');
  document.querySelector('#mqtt-radar').onclick = () => publishMqtt('radar');
  document.querySelector('#capture-two-views').onclick = captureTwoViews;
  const manualRoot = document.querySelector('#joint-controls');
  for (const control of manualControls) {
    const item = document.createElement('div');
    item.className = 'joint-control';
    item.id = `manual-${control.id}`;
    const unit = control.id === 'gripper' ? '%' : '°';
    const step = control.id === 'gripper' ? 1 : 0.1;
    const bounds = `min="${control.min}" max="${control.max}" step="${step}"`;
    item.innerHTML = `<button title="减小">↓</button>
      <label class="joint-info">${control.label} (${unit})
        <input class="joint-value" type="number" ${bounds} value="0">
      </label>
      <button title="增大">↑</button>
      <button class="apply" title="设置目标值">设置</button>`;
    const buttons = item.querySelectorAll('button');
    buttons[0].onclick = () => jogManual(control.id, -1);
    buttons[1].onclick = () => jogManual(control.id, 1);
    buttons[2].onclick = () => setManual(control.id);
    item.querySelector('.joint-value').onkeydown = event => {
      if (event.key === 'Enter') setManual(control.id);
    };
    manualRoot.appendChild(item);
  }
  await refreshManual();
  async function hardwareLoop() {
    await refreshHardware();
    setTimeout(hardwareLoop, 3000);
  }
  hardwareLoop();
  async function mqttLoop() {
    await refreshMqtt();
    setTimeout(mqttLoop, 1000);
  }
  mqttLoop();
  async function cameraLoop() {
    await refreshCameraStatus();
    setTimeout(cameraLoop, 1000);
  }
  cameraLoop();
}
load();
</script>
</body>
</html>"""


def executor_from_environment() -> RobotExecutor:
    mode = os.environ.get("ROBOT_EXECUTION_MODE", "shadow")
    if mode == "shadow":
        return ShadowRobotExecutor()
    if mode == "ssh-mark":
        return SshMarkRobotExecutor(host=os.environ.get("MARK_SSH_HOST", "mark"))
    raise RuntimeError("ROBOT_EXECUTION_MODE must be 'shadow' or 'ssh-mark'")


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def env_positive_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    value = default if raw is None else float(raw)
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


def create_app(
    *,
    executor: RobotExecutor | None = None,
    neutral_executor: NeutralPoseExecutor | None = None,
    mqtt_bridge: MqttBridge | None = None,
    exterior_camera_ready: bool | None = None,
    hardware_probe: HardwareProbe | None = None,
    manual_controller: ManualControl | None = None,
    frame_store: FrameStore | None = None,
    manipulation_workflow: ManipulationWorkflow | None = None,
) -> FastAPI:
    camera_ready = (
        env_flag("EXTERIOR_CAMERA_READY")
        if exterior_camera_ready is None
        else exterior_camera_ready
    )
    mounted_as_exterior_ready = env_flag("ALLOW_MOUNTED_AS_EXTERIOR")
    probe = hardware_probe or SshMarkHardwareProbe(host=os.environ.get("MARK_SSH_HOST", "mark"))
    selected_executor = executor or executor_from_environment()
    selected_frames = frame_store or FrameStore()
    max_camera_age_seconds = env_positive_float("VISION_MAX_FRAME_AGE_SECONDS", 3.0)
    camera_capture_lock = threading.Lock()
    preview_observer = (
        SshMarkObservationAdapter(
            frame_store=selected_frames,
            host=os.environ.get("MARK_SSH_HOST", "mark"),
            max_age_seconds=max_camera_age_seconds,
        )
        if selected_executor.mode == "ssh-mark"
        else None
    )
    selected_workflow = manipulation_workflow
    camera_geometry_raw = os.environ.get("A1Z_CAMERA_GEOMETRY", "").strip()
    camera_geometry: CameraGeometry | None = None
    camera_geometry_error: str | None = None
    if camera_geometry_raw:
        try:
            camera_geometry = CameraGeometry.model_validate_json(camera_geometry_raw)
        except ValueError as exc:
            first_line = str(exc).splitlines()[0]
            camera_geometry_error = f"camera geometry invalid: {first_line}"
    auto_actuator_ready = bool(
        os.environ.get("OPENAI_API_KEY")
        and env_flag("ENABLE_GPT_ACTUATOR_TOOLS")
        and camera_geometry is not None
    )
    auto_visual_ready = bool(os.environ.get("OPENAI_API_KEY"))
    if (
        selected_workflow is None
        and selected_executor.mode == "ssh-mark"
        and auto_visual_ready
    ):
        assert preview_observer is not None
        planner = (
            OpenAICorrectionPlanner(camera_geometry=camera_geometry)
            if auto_actuator_ready
            else None
        )
        selected_workflow = ManipulationWorkflow(
            executor=selected_executor,
            observer=preview_observer,
            evaluator=OpenAIVisionEvaluator(),
            scene_assessor=planner or OpenAICorrectionPlanner(),
            planner=planner,
            actuators=(
                SshMarkActuatorTools(host=os.environ.get("MARK_SSH_HOST", "mark"))
                if planner is not None
                else None
            ),
        )
    actuator_correction_ready = bool(
        selected_workflow is not None
        and (manipulation_workflow is not None or auto_actuator_ready)
    )
    if neutral_executor is None:
        neutral_executor = (
            ShadowNeutralPoseExecutor()
            if selected_executor.mode == "shadow"
            else SshMarkNeutralPoseExecutor(host=os.environ.get("MARK_SSH_HOST", "mark"))
        )
    manager = JobManager(
        selected_executor,
        neutral_executor,
        exterior_camera_ready=camera_ready,
        mounted_as_exterior_ready=mounted_as_exterior_ready,
        hardware_probe=probe,
        camera_readiness=lambda: bool(
            selected_frames.status(max_age_seconds=max_camera_age_seconds)["ready"]
        ),
        manipulation_workflow=selected_workflow,
    )
    selected_manual = manual_controller or (
        ShadowManualControl()
        if selected_executor.mode == "shadow"
        else SshMarkManualControl(host=os.environ.get("MARK_SSH_HOST", "mark"))
    )

    def trigger_mqtt_reminder(decision: PostureDecision) -> dict[str, object]:
        scenario = get_scenario("locate_person_non_contact_gesture")
        return manager.trigger(
            scenario,
            trigger_event={
                "topic": "zuodian/posture",
                "source": "mqtt-subscriber",
                **decision.as_dict(),
            },
        ).summary()

    selected_mqtt = mqtt_bridge or CushionMqttBridge(
        host=os.environ.get("MQTT_HOST", "127.0.0.1"),
        port=int(os.environ.get("MQTT_PORT", "1883")),
        transport=os.environ.get("MQTT_TRANSPORT", "tcp"),
        threshold_seconds=env_positive_float("CUSHION_SEATED_THRESHOLD_SECONDS", 60.0),
        on_threshold=trigger_mqtt_reminder,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        del application
        selected_mqtt.start()
        try:
            yield
        finally:
            selected_mqtt.stop()

    app = FastAPI(
        title="SmartCushion → A1Z scenario trigger",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.job_manager = manager
    app.state.mqtt_bridge = selected_mqtt
    app.state.manual_controller = selected_manual
    app.state.frame_store = selected_frames

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _INDEX_HTML

    @app.get("/api/status")
    def status() -> dict[str, object]:
        camera_state = selected_frames.status(
            max_age_seconds=max_camera_age_seconds
        )
        return {
            "service": "cushion-reminder",
            "execution_mode": manager.mode,
            "human_contact_enabled": False,
            "gpt_visual_evaluator_ready": selected_workflow is not None,
            "gpt_actuator_correction_ready": actuator_correction_ready,
            "camera_geometry_ready": camera_geometry is not None,
            "camera_geometry_error": camera_geometry_error,
            "two_view_camera_ready": camera_state["ready"],
            "camera_observation_mode": "action-boundary",
            "required_camera_views": camera_state["required_views"],
            "max_camera_age_seconds": max_camera_age_seconds,
            "exterior_camera_ready": manager.exterior_camera_ready,
            "mounted_as_exterior_ready": manager.mounted_as_exterior_ready,
        }

    @app.get("/api/scenarios")
    def scenarios() -> list[dict[str, object]]:
        return [scenario.as_dict() for scenario in SCENARIOS.values()]

    @app.get("/api/hardware")
    def hardware() -> dict[str, object]:
        return probe.snapshot()

    @app.get("/api/cameras/status")
    def camera_status() -> dict[str, object]:
        return selected_frames.status(max_age_seconds=max_camera_age_seconds)

    @app.post("/api/cameras/capture-two-view")
    def capture_two_view() -> dict[str, object]:
        if preview_observer is None:
            raise HTTPException(
                status_code=409,
                detail="Two-view Mark capture requires ssh-mark execution mode",
            )
        if not camera_capture_lock.acquire(blocking=False):
            raise HTTPException(
                status_code=409,
                detail="A two-view camera capture is already running",
            )
        try:
            observation = preview_observer.observe(
                phase="manual-preview",
                log=lambda _level, _message, _data: None,
            )
            return {
                "ready": True,
                "captured_at": observation.captured_at.isoformat(),
                "frames": observation.summaries(),
            }
        except (RuntimeError, TimeoutError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        finally:
            camera_capture_lock.release()

    @app.get("/api/cameras/{view}/frame")
    def latest_camera_frame(view: str) -> Response:
        try:
            frame = selected_frames.latest(
                CameraView(view),
                max_age_seconds=max_camera_age_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Response(
            content=frame.jpeg,
            media_type="image/jpeg",
            headers={
                "X-Captured-At": frame.captured_at.isoformat(),
                "X-Camera-Source": frame.source,
                "X-Orientation-Degrees": str(frame.orientation_degrees),
            },
        )

    @app.post("/api/cameras/{view}/frame", status_code=202)
    async def camera_frame(view: str, request: Request) -> dict[str, object]:
        if request.headers.get("content-type", "").split(";", 1)[0] != "image/jpeg":
            raise HTTPException(status_code=415, detail="Camera frame must use image/jpeg")
        try:
            selected_view = CameraView(view)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=f"Unsupported camera view: {view}") from exc
        try:
            captured_at = parse_captured_at(request.headers.get("x-captured-at"))
            orientation = int(request.headers.get("x-orientation-degrees", "0"))
            frame = selected_frames.put(
                selected_view,
                await request.body(),
                captured_at=captured_at,
                source=request.headers.get("x-camera-source", "http-upload"),
                orientation_degrees=orientation,
            )
            return frame.summary()
        except (ValueError, OverflowError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/readiness")
    def readiness() -> dict[str, object]:
        result = build_readiness(selected_mqtt, probe)
        base_ready = bool(result["ready"])
        camera_state = selected_frames.status(
            max_age_seconds=max_camera_age_seconds
        )
        grasp_blockers: list[str] = list(result["blockers"])
        if selected_workflow is None:
            if not os.environ.get("OPENAI_API_KEY"):
                grasp_blockers.append("OPENAI_API_KEY is not configured")
            grasp_blockers.append("GPT-5.6 manipulation workflow is not configured")
        if not camera_state["ready"]:
            grasp_blockers.append("two-view camera observation is not ready")
        actuator_blockers: list[str] = list(result["blockers"])
        if not os.environ.get("OPENAI_API_KEY"):
            actuator_blockers.append("OPENAI_API_KEY is not configured")
        if not env_flag("ENABLE_GPT_ACTUATOR_TOOLS"):
            actuator_blockers.append("GPT actuator tools are not explicitly enabled")
        if camera_geometry_error:
            actuator_blockers.append(camera_geometry_error)
        elif camera_geometry is None:
            actuator_blockers.append(
                "calibrated A1Z camera geometry is not configured"
            )
        if not actuator_correction_ready:
            actuator_blockers.append("GPT actuator correction is not configured")
        result["capabilities"] = {
            "base_motion": {
                "ready": base_ready,
                "blockers": list(result["blockers"]),
            },
            "mqtt_non_contact_reminder": {
                "ready": base_ready,
                "blockers": list(result["blockers"]),
            },
            "two_view_grasp": {
                "ready": not grasp_blockers,
                "blockers": grasp_blockers,
            },
            "gpt_actuator_correction": {
                "ready": not actuator_blockers,
                "blockers": actuator_blockers,
            },
        }
        return result

    @app.get("/api/mqtt/status")
    def mqtt_status() -> dict[str, object]:
        return selected_mqtt.status()

    @app.get("/api/mqtt/events")
    def mqtt_events(after: int = 0) -> list[dict[str, object]]:
        return selected_mqtt.events_after(max(0, after))

    @app.post("/api/mqtt/test/{kind}", status_code=202)
    def mqtt_test(kind: str) -> dict[str, object]:
        try:
            return selected_mqtt.publish_test_event(kind)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/scenarios/{scenario_id}/trigger", status_code=202)
    def trigger(scenario_id: str) -> dict[str, object]:
        try:
            scenario = get_scenario(scenario_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            return manager.trigger(scenario).summary()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/commands/return-neutral", status_code=202)
    def return_neutral() -> dict[str, object]:
        try:
            return manager.trigger_return_neutral().summary()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/commands/return-zero", status_code=202)
    def return_zero() -> dict[str, object]:
        try:
            return manager.trigger_return_zero().summary()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/manual-control")
    def manual_state() -> dict[str, object]:
        try:
            return selected_manual.state()
        except (RuntimeError, TimeoutError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/manual-control/jog")
    def manual_jog(request: ManualJogRequest) -> dict[str, object]:
        try:
            manager.ensure_idle()
            return selected_manual.jog(request.control, request.direction)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/manual-control/set")
    def manual_set(request: ManualSetRequest) -> dict[str, object]:
        try:
            manager.ensure_idle()
            return selected_manual.set_value(request.control, request.value)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str) -> dict[str, object]:
        try:
            return manager.get(job_id).summary()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/jobs/{job_id}/events")
    def events(job_id: str, after: int = 0) -> list[dict[str, object]]:
        try:
            return manager.events_after(job_id, max(0, after))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return app


app = create_app()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=3000, type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("The hardware console must bind to a loopback host")
    uvicorn.run("cushion_reminder.web:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
