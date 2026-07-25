# MQTT 智能坐垫 → A1Z 提醒服务化计划

更新日期：2026-07-24

目标：把现有 G0.5→A1Z 真机链路包装成一个长期运行、可恢复、可审计的内部服务。MQTT 智能坐垫只发布事实；确定性规则判断是否需要提醒；机器人执行模块只接受允许列表中的 `RobotIntent`，不接受 MQTT 传入的任意 shell command 或 prompt。

## 当前实现

[`cushion-reminder-service/`](../cushion-reminder-service/) 已经提供：

- 与当前固件合同一致的 posture/radar MQTT 模拟发布端；
- 仅绑定 `127.0.0.1` 的开发 broker；
- `localhost:3000` 场景触发页面和 HTTP API；
- 生成“连续在座 3600 秒”事件的 shadow workflow；
- 通过固定场景目录调用 Mark headless client 的可选 `ssh-mark` adapter。

当前默认仍是 `shadow`。常驻 `zuodian/#` receiver、连续入座状态机、
MQTT→allowlisted RobotIntent、Mark executor 和 GPT-5.6 三视角验收已经实现并有测试；
SQLite session/workflow persistence、生产 MQTT ACL/TLS 和真机三有效视角验收尚未实现。

## 产品规则

生产默认规则：

- 连续有效在座达到 60 分钟，触发一次提醒；
- 短暂 telemetry 丢包不重置计时；
- 连续离座达到 3 分钟才结束本次 sitting session；
- 同一 session 默认只提醒一次；
- 提醒失败可按明确策略重试一次，但不得形成无限重试；
- `demo_mode` 可以把 60 分钟压缩成 10–15 秒，但事件和日志必须标明 `demo_mode=true`。

“戳一下真人”不进入允许列表。第一版提醒动作是非接触手势或语音；如果要验证接触，只能接触固定泡棉靶，并增加独立力/行程停止。

推荐的 G0.5 task：

```text
Perform a small non-contact reminder gesture toward the seated person.
Keep a safe distance, do not touch the person, then stop.
```

不要使用：

```text
poke that person slightly
```

因为 RGB-only G0.5 没有接触力合同，也不能保证 `slightly` 对应安全速度或安全力。

## 架构

```text
Smart Cushion
    │ MQTT QoS 1
    ▼
MQTT broker
    ▼
MqttReceiver adapter
    ▼
ReminderOrchestrator module
  validate -> dedupe -> sessionize -> 60-minute rule -> cooldown
    │                         │
    │                         └── EventStore adapter (SQLite)
    ▼
RobotIntent
    ▼
ManipulationWorkflow module
  preflight -> observe -> allowlisted subtask -> execute -> evaluate -> bounded retry
    ├── G0.5 policy adapter (DGX)
    ├── OpenAI vision evaluator (action-chunk boundary only)
    └── A1Z safe daemon adapter (mark)
    ▼
MQTT result/status + structured audit log
```

### Module interfaces

`ReminderOrchestrator` 是核心深 module。调用者只需要提交一个规范化 sample：

```python
outcomes = orchestrator.ingest(sample)
```

它内部隐藏乱序、去重、连续在座 session、离座 debounce、阈值、cooldown 和持久化恢复。测试与生产都从同一 interface 验证行为。

需要的 seam 与 adapter：

| Seam | 生产 adapter | 测试 adapter |
| --- | --- | --- |
| MQTT transport | `paho-mqtt`/`asyncio-mqtt` | in-memory message adapter |
| Event persistence | SQLite | in-memory SQLite |
| Robot execution | local Mark executor | fake executor |
| Action evaluation | OpenAI Responses adapter | fixture/fake evaluator |
| Clock | monotonic/wall clock | deterministic fake clock |

不要为每个小函数创建对外 interface。MQTT 解码、坐垫状态机和触发规则应集中在 `ReminderOrchestrator` 内，保持 locality。

## 当前硬件 MQTT 合同

固件当前发布两个 legacy topic。receiver 应在入口把它们规范化，固件不需要为了服务端内部 schema 立即重烧。

### `zuodian/posture`

每 500 ms 一条：

```json
{"s1":208,"s3":85,"s4":175,"s5":127,"s6":0,"pose":"UPRIGHT"}
```

`pose` 为 `AWAY | UPRIGHT | LEAN_L | LEAN_R | EDGE | OTHER`。连续在座判断使用 `pose != "AWAY"`；原始 FSR 值用于审计和后续置信度计算。

### `zuodian/radar`

有新帧时每秒一条：

```json
{"heart":97.0,"heart_med":110.0,"breath":16.0,"breath_med":17.0,"dist":68.9,"seq":88}
```

- `heart`、`breath` 只用于调试；
- 产品逻辑使用 60 秒滑动中值 `heart_med`、`breath_med`；
- `dist` 用于判断单目标是否仍锁在预期的 `0.6–1.2 m` 区间；
- `seq` 只有雷达新帧时递增；
- 无新帧时每 5 秒重播最后 payload，因此 `seq` 不变必须标记为 stale，不能算新观测。

已知硬件约束：

- 雷达必须立起并正对胸口；
- 单目标可能重锁到旁人，Demo 波束前后不要站其他人；
- broker IP 当前写死在固件里，换网需重烧，后续改固定 IP/mDNS；
- 充电宝需要小电流模式。

本仓库模拟器复现上述 topic、字段和 cadence：

```bash
cd robot-arm/cushion-reminder-service
./scripts/start-local-simulator.sh
```

## 规范化 v1 MQTT 合同

建议 topic：

```text
smartcushion/v1/{device_id}/telemetry
smartcushion/v1/{device_id}/presence
smartcushion/v1/{device_id}/events
smartcushion/v1/{device_id}/commands
smartcushion/v1/{device_id}/results
robot/a1z/{robot_id}/status
robot/a1z/{robot_id}/results
```

ACL：

- 坐垫设备只能 publish 自己的 `telemetry/presence`；
- orchestrator 可以 subscribe telemetry，并 publish events/commands；
- robot executor 只能 subscribe 指定 robot command topic，并 publish status/results；
- broker 禁止坐垫直接 publish robot command；
- production 使用 TLS、每设备独立凭据和证书/密码轮换。

telemetry 建议 JSON：

```json
{
  "schema_version": 1,
  "event_id": "01J3...",
  "device_id": "cushion-001",
  "sequence": 18442,
  "observed_at": "2026-07-24T13:00:00.000Z",
  "occupancy": "occupied",
  "posture": "upright",
  "confidence": 0.97,
  "pressure_zones": [0.18, 0.22, 0.31, 0.29],
  "firmware_version": "0.4.0",
  "demo_mode": false
}
```

要求：

- QoS 1，因此 consumer 必须幂等；
- telemetry 不 retained，presence/LWT 可以 retained；
- `event_id` 全局唯一，`sequence` 对单设备单调递增；
- 同时保存 device `observed_at` 和 receiver `received_at`；
- 拒绝未来时间、过旧消息、非法枚举和越界 confidence；
- 乱序消息可以写审计日志，但不得把 session 时间倒退；
- broker reconnect 后不根据一条 retained `occupied` 直接补算一小时。

## 连续在座判定

建议状态：

```text
UNKNOWN
  ├─ valid occupied ─> OCCUPIED_PENDING
  └─ valid away ─────> AWAY

OCCUPIED_PENDING
  ├─ debounce passed ─> SEATED
  └─ away ────────────> AWAY

SEATED
  ├─ seated >= 60 min ─> REMINDER_DUE
  ├─ short away ───────> SEATED (grace)
  └─ away >= 3 min ────> AWAY / close session

REMINDER_DUE
  ├─ executor accepted ─> REMINDING
  └─ unsafe/unavailable ─> DEFERRED

REMINDING
  ├─ success ──────────> REMINDED
  └─ failure ──────────> DEFERRED or one bounded retry

REMINDED
  └─ away >= 3 min ────> AWAY / next session may remind
```

计算连续时间必须基于已持久化 session：

```text
effective_seated = now - session.started_at - confirmed_away_intervals
```

不能简单累计每条 MQTT sample 的 interval，因为重复、掉线和乱序会造成多算。

## RobotIntent 合同

MQTT 或规则模块不能发送任意 prompt。它只能选择受版本控制的 intent：

```json
{
  "schema_version": 1,
  "intent_id": "01J3...",
  "type": "non_contact_stand_reminder",
  "device_id": "cushion-001",
  "robot_id": "a1z-mark",
  "session_id": "01J3...",
  "issued_at": "2026-07-24T14:00:00.000Z",
  "expires_at": "2026-07-24T14:00:30.000Z",
  "reason": "continuous_seated_60m",
  "demo_mode": false,
  "prompt_template_version": "stand-reminder-v1",
  "max_steps": 64
}
```

第一版允许列表：

| Intent | 执行 |
| --- | --- |
| `non_contact_stand_reminder` | 非接触挥手/指向，保持距离 |
| `return_neutral` | 确定性 `a1zctl move`，不走 G0.5 |
| `open_gripper` | 确定性 gripper command |
| `stop_inference` | 停止当前 headless client，不停止保持 daemon |

未来仅在固定泡棉靶通过力传感器验证后，才考虑加入 `touch_fixture`。不得加入 `touch_person`。

## Robot executor

阶段一可以包装现有命令，但必须传 argv，禁止把 MQTT 内容拼进 shell：

```python
argv = [
    python,
    "-m",
    "a1z_g05.headless",
    "--config",
    "config.mark-execute.yaml",
    "--task",
    ALLOWLISTED_PROMPTS[intent.prompt_template_version],
    "--max-steps",
    str(intent.max_steps),
]
```

执行前：

1. intent 未过期且未执行过；
2. 当前没有其他 robot job；
3. `/tmp/a1z.sock` 健康；
4. CAN 为 `UP/ERROR-ACTIVE` 且无 bus-off；
5. motor 温度和 error code 通过；
6. 相机帧新鲜；
7. DGX policy WebSocket 握手成功；
8. 人体接触 intent 被拒绝；
9. 机械臂在允许的启动姿态窗口内。

执行后发布：

```json
{
  "intent_id": "01J3...",
  "status": "succeeded",
  "started_at": "2026-07-24T14:00:01.000Z",
  "completed_at": "2026-07-24T14:00:24.000Z",
  "steps": 64,
  "final_joints_deg": [0.3, 59.4, -59.5, 1.0, 0.6, -0.5],
  "gripper": 1.0,
  "error_code": null
}
```

进程超时或 inference 失败时，executor 只终止 headless client，让 safe daemon watchdog 保持；不能自动调用 `a1zctl stop`。

一次 headless 进程正常退出只说明动作已经发送完，不代表语义任务成功。抓取和复杂交互必须经过动作块后的 OpenAI evaluator，检查位置、目标和抓取状态，再决定成功、有限重试或 abort。详细合同见 [OpenAI 动作验收与纠偏闭环](openai-action-evaluator-workflow.md)。

## 建议目录

```text
robot-arm/cushion-reminder-service/
├── README.md
├── pyproject.toml
├── src/cushion_reminder/
│   ├── contracts.py
│   ├── orchestrator.py
│   ├── mqtt_adapter.py
│   ├── event_store.py
│   ├── robot_executor.py
│   ├── manipulation_workflow.py
│   ├── openai_evaluator.py
│   ├── prompt_catalog.py
│   └── main.py
├── config/
│   ├── development.yaml
│   └── production.example.yaml
├── systemd/
│   ├── cushion-reminder.service
│   └── cushion-reminder.env.example
└── tests/
    ├── test_orchestrator.py
    ├── test_mqtt_contract.py
    ├── test_recovery.py
    └── test_robot_executor.py
```

先部署为 Mark 上的一个进程。只有 broker ingestion 与 robot execution 需要独立扩缩或独立故障域时，再拆成多个进程；不要一开始就引入不必要的网络 seam。

## 实施计划

### Phase 0：合同与回放

- 固定 topic、JSON schema、posture/occupancy 枚举；
- 维护本地 MQTT simulator 和 `localhost:3000` 场景触发 API；
- 实现 sample validation、幂等和 SQLite schema；
- 用录制 JSONL 和 fake clock 验证 60 分钟规则；
- 验证重复、乱序、断线、短暂离座、跨进程重启。

验收：同一 session 无论消息重复多少次只生成一个 intent。

### Phase 1：MQTT receiver

- 连接 development broker；
- TLS/ACL/LWT；
- QoS 1 subscribe 与 reconnect；
- 把原始消息和规范化 sample 写入 event store；
- publish receiver health。

验收：broker 重启和网络断开后恢复，不丢失已确认 session，不重复提醒。

### Phase 2：shadow robot executor

- 生成 `RobotIntent`，但只运行 `config.mark-shadow.yaml`；
- 记录 prompt、模型 action、拒绝原因和延迟；
- 加单 job 锁、过期、超时、cooldown。

验收：20 次加速 session replay 产生确定数量的 shadow job。

### Phase 3：确定性非接触提醒

- 第一版 production intent 使用预验证手势或受限 G0.5 非接触 prompt；
- 所有真实任务先 preflight；
- 完成后确定性回中立位；
- publish structured `MotionResult`。

验收：10 次连续运行，无真人接触、无软限位/温度/CAN 错误，全部能回中立位。

### Phase 4：双摄像头 G0.5

- Windows USB/IP 绑定固定 exterior camera；
- 以设备序列号而不是易变 `/dev/videoN` 识别；
- exterior→`exterior`，DaBai→`wrist_right`；
- wrist_left 补黑；
- 对比单/双摄像头任务成功率。

验收：同一固定轻质物体至少 20 次抓放，报告成功率和失败类型。

### Phase 4.5：OpenAI 视觉验收闭环

- 保存每个动作块前后的 exterior/wrist burst、关节和夹爪状态；
- 使用图像输入和 strict structured output 判断 position/target/grasp；
- evaluator 反馈只能选择允许列表中的下一子任务；
- 最多 3 次纠偏、一次 reobserve，总 action steps 和 wall clock 有上限；
- evaluator timeout、证据不足、安全故障或连续无改善时 abort；
- 建立人工标注的真/假成功验证集，重点测 false-success。

验收：固定测试集上错误成功判断低于预定阈值；真机每次重试都有完整 audit record；任何 evaluator 输出都不能绕过 joint/CAN/温度/相机安全检查。

### Phase 5：运维包装

- systemd 自动启动 receiver/orchestrator；
- safe daemon 仍保留独立生命周期和单实例锁；
- Prometheus/JSON health、结构化日志和日志轮转；
- readiness 只有在 MQTT、SQLite、camera、CAN、daemon、policy 全部健康时为 true；
- 版本化 prompt catalog、配置和数据库 migration；
- 故障注入：broker、DGX、camera、CAN、daemon、进程重启。

## 必测场景

- 重复 QoS 1 delivery；
- device sequence 回退；
- 设备时钟漂移；
- 59:59 离座、60:00 触发边界；
- 2:59 和 3:00 离座 reset 边界；
- broker 断开 10 分钟后恢复；
- orchestrator 在 59 分钟时重启；
- robot 正忙时第二个坐垫触发；
- intent 到达时 camera/DGX/CAN 不健康；
- headless 超时、模型返回越限、daemon watchdog；
- Windows/WSL 重启后的 USB/IP 和 encoder turn recovery；
- J2 温度超过 preflight 阈值；
- 任意包含真人接触语义的 intent 被拒绝。
- evaluator 夹错物体、空夹、遮挡、陈旧帧和 `insufficient_evidence`；
- evaluator API timeout/refusal/非法 schema；
- retry budget、no-progress 和总 wall-clock 边界。
