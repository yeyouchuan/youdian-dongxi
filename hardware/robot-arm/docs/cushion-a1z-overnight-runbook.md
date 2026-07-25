# SmartCushion → G0.5 → A1Z 断电与次日恢复手册

更新日期：2026-07-25

这份手册用于现场 Mac、DGX Spark、Mark/WSL 和 A1Z 在整套断电或断网后恢复。
机器人动作接口只绑定 Mac 的 `127.0.0.1:3000`，不应暴露到局域网。

## 今晚安全停止

在 Mac 上运行：

```bash
cd ~/Documents/Github/hardware/robot-arm/cushion-reminder-service
./scripts/stop-live-demo.sh
```

脚本严格按下面的顺序执行：

1. 通过 `ssh mark` 调用 `a1zctl stop`；
2. 停止 Web、MQTT Broker 和 DGX→Mark relay；
3. 输出可以断开 A1Z 控制器电源的确认。

只有看到 `Demo services stopped` 后才关闭机械臂控制器电源。A1Z 没有机械刹车，
失能或断电时需要保证手臂已有支撑且不会自由下落。

## 明天启动顺序

### 1. 网络和电源

1. Mac、iPhone、坐垫和 Windows/Mark 接入同一个可信 Wi-Fi；
2. 打开 A1Z 控制器电源；
3. 确认 Mac 能运行 `ssh mark` 和 `ssh dgx`；
4. 获取 Mac 当前地址：

```bash
ipconfig getifaddr en0
```

不要继续使用前一天缓存的 `10.x.x.x` 地址。Mac 本地 subscriber 固定连接
`127.0.0.1:1883`，只有 TestFlight 和 ESP32 需要当前 LAN IP。

### 2. Windows USB/IP

在 Windows 管理员 PowerShell 中先查看当天的 BUSID：

```powershell
usbipd list
```

至少 attach：

```powershell
# CAN: VID:PID a8fa:8598
usbipd attach --wsl --busid <CAN_BUSID>

# DaBai: VID:PID 2bc5:0557
usbipd attach --wsl --busid <DABAI_BUSID>
```

BUSID 和 `/dev/videoN` 都可能变化，不要硬编码昨天的编号。DaBai 的稳定身份是
`2bc5:0557`，序列号是 `CC1N16200WR`。

Mark 笔记本 RGB 的 VID:PID 是 `0408:30c3`。双视角抓取 adapter 会从
`usbipd list` 动态解析它当天的 BUSID；缺失时 attach 一次并保持，动作边界只单拍；
不要同时运行持续 Windows RGB publisher 和 DaBai G0.5 stream。Windows IR interface
在 USB/IP 下会让整个复合 UVC 设备复位，不要打开。

### 3. Mark safe daemon

```bash
tailscale ssh mark
cd ~/hardware/robot-arm/a1z-g05-client
nohup bash scripts/start_a1z_safe_server.sh \
  >> ~/.local/state/a1z/server-launch.log 2>&1 </dev/null &
```

验证：

```bash
test -S /tmp/a1z.sock
~/GALAXEA-A1Z/.venv/bin/python ~/GALAXEA-A1Z/tools/a1zctl status
ip -details link show can0
lsusb
ls -l /dev/video* /dev/v4l/by-id/*
```

### 4. DGX policy

```bash
ssh dgx
ss -lnt | grep ':8765'
pgrep -af serve_policy
```

如果 G0.5 没有运行，按
[A1Z G0.5 client README](../a1z-g05-client/README.md) 的 DGX 部分恢复 checkpoint
服务。

### 5. Mac 一键启动

```bash
cd ~/Documents/Github/hardware/robot-arm/cushion-reminder-service
screen -dmS cushion-live bash -lc \
  'cd ~/Documents/Github/hardware/robot-arm/cushion-reminder-service && exec ./scripts/start-live-demo.sh'
```

这个 session 会启动或复用：

- LAN MQTT Broker：TCP `1883`、WebSocket `9001`；
- Mac→Mark→DGX policy relay；
- `http://127.0.0.1:3000` 真机控制服务。

查看日志：

```bash
screen -r cushion-live
```

退出查看但保持运行：按 `Ctrl-A`，再按 `D`。

### 6. Readiness 门禁

```bash
curl -sS http://127.0.0.1:3000/api/readiness | python3 -m json.tool
```

只有 `"ready": true` 才能触发真机。常见 blocker：

- `MQTT subscriber is disconnected`：检查本地 `1883`；
- `A1Z safe daemon socket ... missing`：重启 Mark safe daemon；
- `DGX policy relay ... missing`：恢复 Mac relay；
- `camera /dev/video* missing`：重新执行 Windows `usbipd attach`；
- CAN blocker：确认 `UP`、`ERROR-ACTIVE`、`1000000`。
- `A1Z safe daemon control thread is not healthy` / `emergency-stopped`：读取
  `~/.local/state/a1z/server.log`，不要绕过；
- `A1Z motor error codes are unsafe`：现场曾见 J4 `0x9 (under voltage)`，检查
  控制器电源、电源线和接头，不能通过提高 PD 刚度继续运行。

双视角抓取还要求：

```bash
test -n "$OPENAI_API_KEY"
curl -sS http://127.0.0.1:3000/api/status | python3 -m json.tool
curl -sS http://127.0.0.1:3000/api/cameras/status | python3 -m json.tool
```

`gpt_visual_evaluator_ready` 和 `two_view_camera_ready` 都必须为 `true`。Mark
`exterior_right` 必须固定在夹爪对侧并同时覆盖目标、夹爪和接近路径；DaBai 固定
在夹爪上且随夹爪运动，画面底部应能看到夹爪尖端和目标。仅有“非黑帧”不能算
双视角语义就绪。Mac 摄像头不属于当前架构，不要启用或上传。

### 7. TestFlight 和真实坐垫

TestFlight 设置：

```text
ws://<MAC_CURRENT_LAN_IP>:9001
```

ESP32 固件使用同一个 IP、TCP `1883`。固件当前写死 Broker IP；如果 Mac DHCP
地址变化，需要修改 `MQTT_HOST` 后重新烧录。

检查真实消息：

```bash
mosquitto_sub -h 127.0.0.1 -p 1883 -t 'zuodian/#' -v
```

### 8. 最小冒烟测试

先重置入座 session：

```bash
curl -sS -X POST http://127.0.0.1:3000/api/mqtt/test/away
curl -sS -X POST http://127.0.0.1:3000/api/mqtt/test/radar
```

确认 readiness 后，再执行完整 MQTT→G0.5→A1Z 测试：

```bash
curl -sS -X POST \
  http://127.0.0.1:3000/api/mqtt/test/continuous-seated
```

在 Web 页面观察 MQTT log 和 `[1/6]` 到 `[6/6]` 的机器人事件。进程
`succeeded` 只证明控制链路完成，不证明视觉语义动作正确。

## 紧急停止

只要 Mark 仍可连接：

```bash
ssh mark \
  '~/GALAXEA-A1Z/.venv/bin/python ~/GALAXEA-A1Z/tools/a1zctl stop'
```

如果 Mac 服务仍在：

```bash
cd ~/Documents/Github/hardware/robot-arm/cushion-reminder-service
./scripts/stop-live-demo.sh
```
