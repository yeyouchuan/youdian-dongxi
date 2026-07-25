# SmartCushion → A1Z Reminder Service

本目录提供智能坐垫事件到 A1Z 机器人任务之间的本地开发入口。目前已经实现：

- 与固件一致的 `zuodian/posture`、`zuodian/radar` MQTT 模拟发布端；
- 常驻订阅 `zuodian/#` 的 receiver、连续入座状态机和自动机器人任务触发；
- 仅绑定 loopback 的 aMQTT 开发 broker（TCP `1883`、WebSocket `9001`）；
- `localhost:3000` MQTT 测试层、场景直接触发层和 HTTP API；
- 持续追加、可通过 API 轮询的 workflow/action step log；
- 每 3 秒从 Mark 刷新的 USB VID:PID、稳定设备链接、CAN、相机、daemon socket 和 DGX relay 状态；
- daemon 控制线程、急停和电机错误码门禁（例如 J4 欠压 `0x9` 会阻止 dispatch）；
- `exterior_right`（Mark 固定外部相机）与 `wrist`（DaBai 夹爪随动相机）双视角
  帧存储和动作边界原子观测；不再访问 Mac 摄像头；
- G0.5 每 16 steps 停稳后由 GPT-5.6 做结构化验收和有预算的安全纠偏；
- 默认不移动真机的 `shadow` executor；
- 显式启用后通过 SSH 在 Mark 上运行 headless client 的 executor。

当前 receiver 状态和 job queue 都在内存中，服务重启后会清空。OpenAI 视觉验收
已经实现，但只有在真机模式设置 `OPENAI_API_KEY` 后才启用；数据库持久化、跨进程
任务队列和真机抓取成功率验收仍未完成，不能把当前实现当作无人值守生产服务。

## 立即运行 Web 控制台

从本目录运行：

```bash
uv run cushion-web
```

打开：

```text
http://127.0.0.1:3000
```

默认模式为 `shadow`。它会连接 `MQTT_HOST:MQTT_PORT`（默认
`127.0.0.1:1883`），但机器人任务不会访问 DGX，也不会移动 A1Z。

连接现场 Broker 的原生 MQTT TCP listener，并把测试阈值设为一分钟：

```bash
MQTT_HOST=<BROKER_LAN_IP> \
MQTT_PORT=1883 \
MQTT_TRANSPORT=tcp \
CUSHION_SEATED_THRESHOLD_SECONDS=60 \
uv run cushion-web
```

如果现场只开放与 iOS 相同的 WebSocket listener，也可以改用：

```bash
MQTT_HOST=<BROKER_LAN_IP> \
MQTT_PORT=9001 \
MQTT_TRANSPORT=websockets \
CUSHION_SEATED_THRESHOLD_SECONDS=60 \
uv run cushion-web
```

`8000` 是静态 HTTP 看板，不是 MQTT listener，不能填写为 `MQTT_PORT`。

页面分为两层：

1. 上层 MQTT 测试按钮把允许列表中的测试包真正发布到 Broker，再由本服务的
   subscriber 从 `zuodian/#` 收回；
2. 下层场景按钮绕过坐垫判定，直接创建机器人 Job，供机械臂单独调试。

“发布入座样本”会开始真实的本地计时；持续收到非 `AWAY` 姿态满 60 秒才触发。
“模拟连续在座 60 秒”会发布带 `simulated=true` 和
`effective_seated_seconds=60` 的测试包，适合不等待一分钟的完整链路演示。
“发布离座样本”会重置当前连续入座会话。

CLI 触发：

```bash
curl -sS -X POST \
  http://127.0.0.1:3000/api/scenarios/seated_60m_non_contact_reminder/trigger
```

响应中的 `id` 是 job ID：

```bash
curl -sS http://127.0.0.1:3000/api/jobs/JOB_ID
curl -sS 'http://127.0.0.1:3000/api/jobs/JOB_ID/events?after=0'
```

其他接口：

```text
GET  /api/status
GET  /api/readiness
GET  /api/hardware
GET  /api/cameras/status
GET  /api/cameras/{exterior_right|wrist}/frame
POST /api/cameras/{exterior_right|wrist}/frame
POST /api/cameras/capture-two-view
GET  /api/mqtt/status
GET  /api/mqtt/events?after={sequence}
POST /api/mqtt/test/occupied
POST /api/mqtt/test/continuous-seated
POST /api/mqtt/test/away
POST /api/mqtt/test/radar
GET  /api/scenarios
POST /api/scenarios/{scenario_id}/trigger
GET  /api/jobs/{job_id}
GET  /api/jobs/{job_id}/events?after={sequence}
```

服务一次只允许一个 active robot job。API 只能选择 [`scenarios.py`](src/cushion_reminder/scenarios.py) 里版本控制的场景，不能上传任意 prompt 或 shell command。

## MQTT receiver 与自动触发

主数据流：

```text
坐垫 FSR ─┐
雷达板 ───┼─ Wi-Fi ─ MQTT Broker ─ zuodian/# subscriber ─ 连续入座状态机
iOS App ──┘                                              │
Web 测试按钮 ─ MQTT publish ─────────────────────────────┘
                                                        │ 60 s
                                                        ▼
                                allowlisted person-reminder scenario
                                                        │
                    Mark camera → DGX G0.5 → safe daemon → A1Z
```

判定规则：

- `UPRIGHT`、`LEAN_L`、`LEAN_R`、`EDGE`、`OTHER` 均表示有人入座；
- `AWAY` 表示离座，立即清空累计时间和本次会话的触发标记；
- 连续入座达到 `CUSHION_SEATED_THRESHOLD_SECONDS` 后，每次入座会话只触发一次；
- 雷达数据只更新 `heart_med`、`breath_med` 等页面状态，不直接触发动作；
- 自动动作使用 `locate_person_non_contact_gesture`：识别人、朝其方向明显移动并做
  指向提醒，但保持非接触安全距离；
- MQTT 断线时 paho client 自动退避重连，页面显示“重连中”。

接口返回的 MQTT event log 会记录原始 topic、入座累计值、阈值命中和创建出的 robot
job ID。浏览器收到 job ID 后会自动切换到下方动作日志，继续展示每一个 A1Z action
step。

## TestFlight / iPhone 连接

1. 安装 TestFlight `1.0.0 (11)`；
2. iPhone、坐垫和 Broker 电脑连接同一个 Wi-Fi，例如 `ADVX-Players`；
3. App 打开“设置 → 智能坐垫连接”，填写
   `ws://<BROKER_LAN_IP>:9001`；
4. 保存后前往“健康 → 坐垫实时数据”，点击“连接坐垫数据源”；
5. 首次出现本地网络权限请求时选择允许；
6. Broker IP 改变时，在 App 设置和本服务的 `MQTT_HOST` 中同时更新地址。

Broker 侧确认硬件发布：

```bash
mosquitto_sub -h <BROKER_LAN_IP> -p 1883 -t 'zuodian/#' -v
```

至少应看到 `zuodian/radar`；做姿态联动前还必须确认 FSR 姿态板已经上电并持续发布
`zuodian/posture`。

## 真机模式

真机模式的实际主数据流是：

```text
Web/API -> local service -> SSH mark -> headless client
         -> mark:127.0.0.1:8765 relay -> DGX G0.5
         -> action chunk -> Mark safety checks -> /tmp/a1z.sock -> A1Z
```

启动前必须满足：

- `ssh mark` 使用 BatchMode 可以免交互连接；
- Mark 上 `/tmp/a1z.sock` 存在且只运行一个 safe daemon；
- Mark 到 DGX 的 `127.0.0.1:8765` relay 已连接；
- CAN、温度、反馈、daemon control thread、急停、电机错误码和相机 preflight 通过；
- 场景声明的 camera profile 和 Mark config 文件存在；
- 人和非测试物体离开机械臂运动空间。

推荐在 Mac 上用一个命令启动 LAN Broker、DGX→Mark relay 和 Web 服务：

```bash
./scripts/start-live-demo.sh
```

安全停止并准备断电：

```bash
./scripts/stop-live-demo.sh
```

脚本让本机 subscriber 始终连接 `127.0.0.1:1883`，避免 Mac 的 DHCP 地址变化后
Web 服务自己也断线；同时把当前 `en0` 地址打印为 TestFlight 的
`ws://<CURRENT_IP>:9001` 和 ESP32 的 TCP Broker 地址。LAN Broker 为现场演示方便，
在 `0.0.0.0:1883/9001` 开放匿名访问，只能在可信私有 Wi‑Fi 使用。

也可以手动显式启动：

```bash
ROBOT_EXECUTION_MODE=ssh-mark \
MARK_SSH_HOST=mark \
ALLOW_MOUNTED_AS_EXTERIOR=1 \
MQTT_HOST=127.0.0.1 \
MQTT_PORT=1883 \
MQTT_TRANSPORT=tcp \
CUSHION_SEATED_THRESHOLD_SECONDS=60 \
uv run cushion-web
```

`ssh-mark` adapter 不会自动启动 safe daemon，也不会把 API 参数拼进远程 shell。若 `/tmp/a1z.sock` 缺失，它会拒绝执行。

控制台在所有模式下都强制只绑定 loopback；不能用 `--host 0.0.0.0` 暴露硬件拓扑或匿名运动接口。远程 headless client 同时受远端 175 秒 timeout 和 safe daemon watchdog 约束。

页面的硬件区来自只读 `ssh mark` probe，显示：

- `/tmp/a1z.sock` 和 `127.0.0.1:8765`；
- `can0` 的 UP/ERROR-ACTIVE/bitrate；
- `/dev/video*`、`/dev/ttyUSB*`、`/dev/ttyACM*`；
- `/dev/v4l/by-id`、`/dev/serial/by-id` 稳定链接；
- `lsusb` 的 Bus/Device 与 VID:PID；
- 系统提供 `usbip port` 时的 attach 状态。

USB 重新 attach 后，优先使用稳定的 `by-id` 链接判断相机身份；`Bus 001 Device 003` 之类的 Device number 和 `/dev/videoN` 都可能变化。

事件日志按 `[1/6]` 到 `[6/6]` 展示触发、坐垫事件、RobotIntent、preflight、DGX/Mark dispatch 和完成状态。headless 输出中的每一条 `step=N hz=...` 会被转换为 `A1Z action step N`，在机械臂运动期间持续刷新。

同一份 probe 也是 live job 的强制门禁。每次动作前都会重新检查 daemon socket、DGX relay、CAN `UP/ERROR-ACTIVE/1 Mbps` 和至少一个 camera node；任一项失败都会写入 job log 并阻止 SSH dispatch。

当前场景按目录选择相机配置：

| 场景 | Camera profile | Mark config |
| --- | --- | --- |
| 久坐非接触提醒 | `wrist_single` | `config.mark-execute.yaml` |
| 泡棉靶、识别人、轻质抓取 | `two_view` | `config.mark-execute-two-view.yaml` |

`two_view` 的合同是：

```text
exterior_right <- Mark 笔记本 RGB 0408:30c3，固定在夹爪对侧
wrist          <- DaBai 2bc5:0557，固定在夹爪上并随夹爪运动，显示时旋转 180°
```

Windows RGB 与 DaBai 不能可靠地持续并发 streaming。`SshMarkObservationAdapter`
动态查找 Windows BUSID，只在设备缺失时 attach 一次并保持；action boundary 仅单拍
并原子写入 `/tmp/a1z-vision/exterior-right.jpg`，再抓 DaBai，避免反复 USB/IP
attach/detach 干扰 CAN 反馈。抓取场景每次
只执行一个 16-step G0.5 chunk，然后重新取得双视角并评价；
不再开放式执行 96 steps 后只看退出码。

控制台的“抓取并显示两路帧”调用：

```http
POST /api/cameras/capture-two-view
```

它依次单拍 Mark Windows RGB 和 DaBai，返回同一动作边界的两帧摘要并在页面显示。
这里的 `ready=true` 只表示两张 JPEG 新鲜完整，不表示两路都看到了目标和夹爪。

G0.5 checkpoint 仍要求 `exterior/wrist_left/wrist_right` 三个 tensor。双视角配置将
Mark 外部相机映射到 `exterior`，DaBai 映射到 `wrist_right`，并把不存在的
`wrist_left` 显式零填充；零填充槽不会提交给 GPT，也不能算作安全视觉证据。

`mounted_as_exterior` 和 `config.mark-execute-exterior.yaml` 仍保留为单相机诊断模式，
不用于证明抓取成功。

当前禁止真人接触。`seated_60m_non_contact_reminder` 只做非接触提醒；`approach_foam_target` 在接触前停止。要允许接触固定靶，必须先增加独立力/行程停止和相应验收测试。

## 确定性回中立位

Web 控制台的“回到中立位”按钮调用：

```http
POST /api/commands/return-neutral
```

该命令不经过 G0.5 或 DGX，固定通过 Mark 上的 `a1zctl` 以 `0.15` 速度把
J1/J2/J3/J5/J6 移动到 `[0, 60, -60, 0, 0]°`；J4 由 safe daemon 保持当前锁定值，
不应把页面上的六轴模板误读为 J4 一定回到 0°。它和场景任务共用单任务互斥锁，并在执行前检查
`/tmp/a1z.sock`、CAN `UP/ERROR-ACTIVE/1 Mbps`。API 返回的 Job 可继续通过
`/api/jobs/{id}` 和 `/api/jobs/{id}/events` 监控。

同一区域的“J3 降温零位”按钮调用：

```http
POST /api/commands/return-zero
```

它通过同一套互斥锁、safe daemon 和 CAN preflight，把五个可控关节
J1/J2/J3/J5/J6 固定移动到 `[0, 0, 0, 0, 0]°`，用于解除 J3 在 `-60°`
附近长期保持产生的负载。发送给 `a1zctl` 的六轴模板是
`[0, 0, 0, 0, 0, 0]°`，其中 J4 仍由 safe daemon 保持当前锁定角度。

## 2026-07-24 四场景真机回归

修复前只有久坐提醒成功；另外三个场景都在 DGX dispatch 前被 `exterior_camera_ready=false` 拒绝。根因是场景要求真实双摄，但当前可用部署只有一台 DaBai，且仓库已经另有单相机 exterior 诊断配置。

改为场景选择 camera profile 后，四个场景均完成真实 Mark→DGX→A1Z 控制流程：

| 场景 | Job | Config | 结果 |
| --- | --- | --- | --- |
| 久坐非接触提醒 | `b24e2a3d93ac4d8083e4a37d45457863` | `config.mark-execute.yaml` | 64 steps，成功 |
| 接近固定泡棉靶 | `fce2821b8f66463ab94c36ee67f0f50e` | `config.mark-execute-exterior.yaml` | 64 steps，成功 |
| 识别人并做非接触手势 | `092fd7968fbf499cb88b16163546a472` | `config.mark-execute-exterior.yaml` | 64 steps，成功 |
| 抓取轻质测试物体 | `9bc69dfac0e54330a3b70798a0711913` | `config.mark-execute-exterior.yaml` | 96 steps，成功 |

这里的“成功”只表示硬件 preflight、DGX action generation、A1Z action stream 和进程退出全部正常。它不证明实际接近了正确目标、手势方向正确或物体被抓起；语义成功需要 [OpenAI 动作验收闭环](../docs/openai-action-evaluator-workflow.md)。

## 2026-07-25 双视角真机状态

- Windows RGB 与 DaBai 均能从 WSL 取得非黑帧；
- Mac 摄像头因自动取景会移动，已从代码、UI 和安全证据中完全移除；
- Mark RGB 是固定外部视角，部署时放在夹爪对侧并同时覆盖目标、夹爪和接近路径；
- DaBai 固定在夹爪上并随关节运动，画面底部是夹爪尖端；不能按固定外部相机解释；
- G0.5 真机动作把一个白色拳头模型从横放改变为竖立，证明发生了实际物体交互；
- 早期测试中指定的张开手腕部没有被正确抓起；随后已完成一次可复现的真机抓取：
  TCP 从约 `z=0.332 m` 以最多 20 mm 的 waypoint 下降到约
  `z=0.213 m`，夹爪闭合到 `0.05`，再举回
  `[0,60,-60,0,0,0]°` 附近。外部与腕部画面均确认白色模型离开桌面并持续夹持；
- 原多视角 direct mapping 仍以早期 base pose 为 SO101 proprioception 中心。从
  `[0,60,-60,0,0,0]°` 启动时，16-step 批次几乎只合夹爪。双视角配置现已改为
  中立位锚点；真机复测 J2 从约 60° 移到 69.6°、夹爪保持约 91% 打开，证明首帧
  observation 已恢复到训练分布附近，但目标仍未被接近；
- 持续双 UVC 流会让 `0408:30c3` 从 USB/IP 断开，已改为动作边界单拍；
- J4 曾报告 `error_code=0x9 (under voltage)` 并触发 daemon Emergency Stop。硬件
  probe 现在会读取 control thread、estop 和 error codes，在该状态下 fail closed。
- 新增的 `move_tool_delta` 用官方 URDF 做 position-only IK，每个 base-frame 路径点
  每轴最多 20 mm、合成最多 30 mm、关节变化最多 8°。一次真实 10 mm 上移测试中，
  J4 漂移 3.65°且实测 TCP 反向移动约 6.8 mm；这证明“IK 可解”不等于“硬件执行
  正确”。daemon 现额外要求实测 TCP 方向/误差和锁定轴漂移通过，失败即保持当前位置，
  不允许 GPT 继续下一个路径点。
- 所有新动作入口（G0.5 stream、确定性 joint move、GPT Cartesian move）现在共用
  电机健康门：只允许 error code `0/1`，MOS 达到 `70°C` 或 rotor 达到 `90°C`
  即拒绝新动作但继续保持。Web/HTTP hardware preflight 使用相同阈值，避免热机状态
  仍被前端误判为可执行。
- `actuator_tools.py` 定义了 GPT-5.6 的结构化纠偏计划：最多四步，只允许
  `move_tool_delta` 和 `set_gripper`。无动作场景选择允许目标与夹爪在至少一路画面
  同时清晰可见，但两路新鲜画面都必须用于检查人体和矛盾证据；结构化 actuator plan
  仍要求完整标定。workflow 在 G0.5 第一次动作前先用无动作 `SceneAssessment`
  从三个手模型和小卡片中固定一个目标；G0.5、评价器和 actuator plan 必须一直引用
  同一目标，任何换目标计划都会被拒绝。G0.5 失败后每次只执行计划中的第一步，立即
  重新单拍两路并评价，剩余旧步骤全部丢弃。
- 设置 `OPENAI_API_KEY` 即启用无动作场景选择、动作后视觉评价和 G0.5 有限重试；
  真机 GPT Actuator 默认关闭，只有同时设置 `ENABLE_GPT_ACTUATOR_TOOLS=1` 和有效
  `A1Z_CAMERA_GEOMETRY` 才允许结构化 Cartesian/Gripper 直接纠偏。
  `A1Z_CAMERA_GEOMETRY` 必须是 JSON：包含 `calibration_id`、坐标系 `a1z_base`，以及
  `exterior_right`、`wrist` 两路内参和刚体外参。exterior 的 `parent_frame`
  必须是 `a1z_base`；wrist 的
  `parent_frame` 必须是 `arm_link6`。规划前 actuator state 会调用 daemon
  `tool_pose`，把当前 `base_from_tool` 与 `arm_link6_from_camera` 动态合成
  `base_from_camera`。每路还必须给出 `width/height/fx/fy/cx/cy`，重投影误差不得
  超过 5 px。字段缺失、矩阵非正交或标定无效都会 fail closed。
- `GET /api/status` 的 `gpt_actuator_correction_ready`、
  `camera_geometry_ready`、`camera_geometry_error` 可以区分“有 OpenAI key”和
  “具备真机视觉纠偏全部条件”。当前双视角外参尚未标定，因此 actuator 门禁保持
  关闭。

重新做真机抓取前必须让 Mark 外部相机和 DaBai 同时看到夹爪与桌面目标，并排除
电源欠压。无需额外人工确认，但自动硬件门禁或画面中的人体进入运动区仍会停止执行。

抓取真机流程已迁移到个人 Codex skill `$a1z-visual-grasp`。它由 Codex 逐步读取
固定侧视与腕部相机、执行小范围纠偏，并在闭合和举升前后直接审核画面；Web 服务不再
提供重复的一键自动抓取入口。侧视用于深度、桌面间隙和离桌验证，腕视只用于横向对准
及夹持确认。

该流程需要 J4 参与 IK。Mark daemon 应这样启动：

```bash
nohup env PYTHONPATH=. ~/GALAXEA-A1Z/.venv/bin/python \
  -m a1z_g05.safe_server \
  --a1z-dir ~/GALAXEA-A1Z \
  --can can0 --control-hz 50 --min-hz 40 --watchdog-s 0.35 \
  --unlock-j4 --j4-kp 12 \
  >> ~/.local/state/a1z/server.log 2>&1 </dev/null &
```

默认不带 `--unlock-j4` 时仍锁定 J4，一键深度完成器会拒绝执行。现场经验是：

- 腕部相机适合目标身份和横向对准，不能单独判断桌面深度；
- 外部相机负责确认夹爪高度和目标是否真正离桌；
- 先前 J4 `Kp=10` 且硬锁定会让 J4 在负载下持续漂移，并使所有 Cartesian Z
  waypoint 被 `locked J4 drifted` 拒绝；
- 解锁 J4、设置 `Kp=15` 后，20 mm 下降请求实测可达到约 17–21 mm；
- 夹住后不要要求 J4 在负载下精确到 0°；举起姿态允许 J4 最多约 10°误差，
  其余轴最多约 5°误差。

## MQTT 模拟器

一条命令启动本地 broker 和发布端：

```bash
./scripts/start-local-simulator.sh
```

指定姿态或故障模式：

```bash
./scripts/start-local-simulator.sh --pose AWAY --duration 20
./scripts/start-local-simulator.sh --radar-stale-after 10
uv run cushion-simulator --stdout --duration 3
```

模拟器合同：

| Topic | 节奏 | 内容 |
| --- | --- | --- |
| `zuodian/posture` | 500 ms | `s1/s3/s4/s5/s6/pose` |
| `zuodian/radar` | 新帧每 1 s | `heart/heart_med/breath/breath_med/dist/seq` |
| `zuodian/radar` | 无新帧每 5 s | 重播最后 payload，`seq` 不变 |

开发 broker 只绑定 `127.0.0.1` 且匿名开放。它不适合跨机器或生产部署。

## 测试

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
```

相关设计：

- [断电与次日恢复手册](../docs/cushion-a1z-overnight-runbook.md)
- [本地 HTTP / MQTT 接口](../docs/cushion-a1z-api.md)
- [MQTT 坐垫提醒服务化计划](../docs/mqtt-cushion-reminder-service-plan.md)
- [OpenAI 动作验收与纠偏闭环](../docs/openai-action-evaluator-workflow.md)
- [G0.5 → A1Z 技术方案摘要](../docs/g05-a1z-technical-summary.md)
