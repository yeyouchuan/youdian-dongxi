# SmartCushion → A1Z 本地接口

Base URL：

```text
http://127.0.0.1:3000
```

接口仅用于本机演示，没有用户认证。服务强制绑定 loopback，不能通过
`0.0.0.0` 对外暴露机器人动作入口。

## Readiness 和状态

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/api/readiness` | MQTT 与 Mark 真机门禁的统一结果 |
| `GET` | `/api/status` | 服务模式和 camera profile 开关 |
| `GET` | `/api/hardware` | Mark daemon、relay、CAN、USB、camera |
| `GET` | `/api/mqtt/status` | Broker、transport、坐姿、雷达和阈值状态 |
| `GET` | `/api/mqtt/events?after=N` | 增量读取 MQTT/触发日志 |

`/api/readiness` 关键字段：

```json
{
  "ready": true,
  "blockers": [],
  "mqtt": {
    "host": "127.0.0.1",
    "port": 1883,
    "transport": "tcp",
    "connected": true
  },
  "hardware": {
    "healthy": true,
    "failures": []
  }
}
```

调用方必须在真机动作前检查 `ready == true`。

顶层 `ready` 只代表 MQTT、Mark daemon、CAN、DGX relay 和至少一台相机等基础链路。
具体功能必须检查 `capabilities`：

```json
{
  "capabilities": {
    "base_motion": {"ready": true, "blockers": []},
    "mqtt_non_contact_reminder": {"ready": true, "blockers": []},
    "two_view_grasp": {
      "ready": false,
      "blockers": [
        "GPT-5.6 visual evaluator is not configured",
        "two-view camera observation is not ready"
      ]
    }
  }
}
```

不得用顶层 `ready` 代替 `capabilities.two_view_grasp.ready`。

`/api/status` 还返回：

```json
{
  "gpt_visual_evaluator_ready": false,
  "gpt_actuator_correction_ready": false,
  "camera_geometry_ready": false,
  "camera_geometry_error": null,
  "two_view_camera_ready": false,
  "camera_observation_mode": "action-boundary",
  "required_camera_views": ["exterior_right", "wrist"],
  "max_camera_age_seconds": 8.0
}
```

`gpt_visual_evaluator_ready=false` 时 live grasp 会 fail closed。真机 GPT
Move/Gripper 纠偏还必须同时满足 `gpt_actuator_correction_ready=true` 和
`camera_geometry_ready=true`。仅设置 `OPENAI_API_KEY` 会启用无动作场景选择、
动作后评价和 G0.5 有限重试，但不会开启 GPT Cartesian/Gripper 直接工具。

`camera_geometry_ready` 要求 Mark 外部相机的 base-frame 内外参、DaBai 的
`arm_link6_from_camera` 安装外参，以及两路 `width/height/fx/fy/cx/cy`。腕部
`base_from_camera` 不接受静态配置；每次 GPT actuator plan 前通过 Mark daemon
`tool_pose` 读取当前 `base_from_tool` 后动态合成。

## 双视角接口

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/api/cameras/status` | 两路帧是否存在、帧龄、来源、方向和 SHA-256 |
| `GET` | `/api/cameras/{view}/frame` | 读取仍在 freshness window 内的 JPEG |
| `POST` | `/api/cameras/{view}/frame` | 上传 `image/jpeg` |
| `POST` | `/api/cameras/capture-two-view` | 动作边界依次单拍并返回两路摘要 |

`view` 在真实工作流中只能是 `exterior_right | wrist`。上传可带：

```text
X-Captured-At: 2026-07-25T08:00:00Z
X-Camera-Source: mark-webcam-0408:30c3-boundary
X-Orientation-Degrees: 180
```

抓取真机工作流不依赖 Windows 相机的常驻发布器。每个 16-step action chunk 前后，
adapter 只在 Mark RGB 缺失时 attach 一次并保持连接；每个边界依次单拍 Mark RGB
和 DaBai，生成同一双视角 observation bundle。服务不会请求或上传 Mac 摄像头画面。

## MQTT 测试接口

| Method | Path | 发布内容 |
| --- | --- | --- |
| `POST` | `/api/mqtt/test/occupied` | 一条 `UPRIGHT` 入座样本 |
| `POST` | `/api/mqtt/test/continuous-seated` | 模拟已连续入座 60 秒 |
| `POST` | `/api/mqtt/test/away` | `AWAY`，重置入座 session |
| `POST` | `/api/mqtt/test/radar` | 模拟过滤后的心率/呼吸数据 |

测试包会先真正发布到 Broker，再由本服务订阅 `zuodian/#` 收回，不是直接调用
Robot API。

## 场景和任务

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/api/scenarios` | 返回版本控制的允许场景 |
| `POST` | `/api/scenarios/{scenario_id}/trigger` | 绕过坐垫判定，直接创建场景 Job |
| `POST` | `/api/commands/return-neutral` | 确定性回到 `[0,60,-60,0,0,0]°` |
| `GET` | `/api/jobs/{job_id}` | Job 状态 |
| `GET` | `/api/jobs/{job_id}/events?after=N` | 增量读取动作事件 |

服务一次只运行一个机器人 Job。Job 的终态是 `succeeded` 或 `failed`。

## MQTT Broker 接口

| Port | Protocol | Client |
| --- | --- | --- |
| `1883` | MQTT TCP | ESP32、Paho subscriber、`mosquitto_sub` |
| `9001` | MQTT over WebSocket | TestFlight/iOS |
| `8000` | HTTP | 静态看板，不是 MQTT |

Topics：

```text
zuodian/posture
zuodian/radar
```

真实 `posture` payload 至少包含字符串 `pose`；允许值：

```text
UPRIGHT, LEAN_L, LEAN_R, EDGE, OTHER, AWAY
```

真实 `radar` payload 使用 `heart_med`、`breath_med`、`dist` 和 `seq` 作为主要
消费字段。
