# 系统架构

本文描述黑客松开源版本的边界。它把移动端健康日报、坐垫实时数据和机器人提醒
放在同一仓库中，但每一层仍可独立运行。

## 数据流

```text
┌──────────────────────── 感知层 ────────────────────────┐
│ ESP32 + FSR × 5             XIAO C6 + mmWave radar    │
│ posture + raw ADC           heart / breath / distance │
└───────────────┬──────────────────────┬─────────────────┘
                └──────── MQTT ────────┘
                            │
            ┌───────────────┴────────────────┐
            │                                │
            ▼                                ▼
┌──────────────────────┐          ┌────────────────────────┐
│ Expo / React Native  │          │ Cushion Reminder       │
│ iPhone App           │          │ Service                │
│                      │          │                        │
│ · 本地日报与趋势      │          │ · 连续久坐状态机        │
│ · HealthKit 只读同步  │          │ · RobotIntent 白名单    │
│ · SQLCipher 本地镜像  │          │ · 硬件 readiness 门禁   │
└──────────────────────┘          └───────────┬────────────┘
                                              │ SSH dispatch
                                              ▼
                                 ┌────────────────────────┐
                                 │ DGX Spark              │
                                 │ Galaxea G0.5 SO101 VLA │
                                 └───────────┬────────────┘
                                             │ WebSocket + msgpack
                                             ▼
                                 ┌────────────────────────┐
                                 │ Mark / WSL             │
                                 │ camera + safe daemon   │
                                 └───────────┬────────────┘
                                             │ SocketCAN
                                             ▼
                                         Galaxea A1Z
```

## 组件职责

### iPhone App

根目录的 `src/` 使用 Expo SDK 57、React Native、TypeScript、Expo Router、
HealthKit、Expo SQLite/SQLCipher 和 MQTT.js。它负责展示与本地数据处理，不向
机器人发送任意自然语言指令。

### MQTT 协议

坐垫发布 `zuodian/posture`，毫米波雷达发布 `zuodian/radar`。App 和提醒服务
分别消费同一数据源。协议、合法范围和失效语义见
[MQTT 协议](MQTT_PROTOCOL.md)与
[实时数据领域规范](CUSHION_REALTIME_DATA_SPEC.md)。

### Cushion Reminder Service

`hardware/robot-arm/cushion-reminder-service/` 是 FastAPI + paho-mqtt 服务。
它把连续久坐事件转换成允许列表中的 `RobotIntent`，并在 dispatch 前重新检查
相机、CAN、daemon socket 和 DGX relay。默认 shadow mode 只记录决策。

### G0.5 与 A1Z

DGX Spark 运行 GalaxeaVLA G0.5 SO101 checkpoint。Mark/WSL 采集相机和关节状态，
通过 WebSocket/msgpack 请求 16-step action chunk，再将 SO100 的五轴加夹爪输出
映射到 A1Z J1/J2/J3/J5/J6；J4 由安全 daemon 保持。

安全 daemon 独占 CAN，以 50 Hz 运行，并设置 40 Hz 频率下限、350 ms stream
watchdog、关节限位、动作增量限制、电机故障和温度门禁。完整设计见
[G0.5 → A1Z 技术总结](../hardware/robot-arm/docs/g05-a1z-technical-summary.md)。

## 信任边界

- MQTT 演示 Broker 只应在受控局域网中运行；公网必须使用 `wss://` 和认证。
- App 不信任传感器输入，会独立检查类型、范围、序号和新鲜度。
- 提醒服务不允许 MQTT payload 直接成为模型 prompt 或 shell 参数。
- DGX 只生成候选 action；最终限位、频率与硬件故障判断在 Mark 端执行。
- OpenAI 视觉评价是动作边界的辅助判断，不能绕过确定性硬件门禁。

## 可独立复现的层级

1. **App UI**：`npm run web`，无需硬件。
2. **MQTT 状态机**：本地 broker + simulator，默认不连接机器人。
3. **A1Z 离线检查**：运行 Python 测试、轨迹审计和仿真。
4. **真机链路**：需要 DGX、checkpoint、两路相机、Mark/WSL、CAN 和现场操作员。

硬件层不是“一键运行”的消费级功能。任何真机复现都必须从
[`hardware/robot-arm/README.md`](../hardware/robot-arm/README.md)的安全规则开始。
