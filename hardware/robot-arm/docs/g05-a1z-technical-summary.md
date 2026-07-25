# G0.5 → Galaxea A1Z 技术方案摘要

更新日期：2026-07-25

本文记录当前已经跑通的 G0.5 推理、SO100→A1Z 映射、双主机部署和真机安全执行方案。它描述的是本仓库的实测实现，不代表 OpenGalaxea 官方已经发布 A1Z embodiment。

## 当前状态

已经验证：

- DGX Spark（GB10、128 GB unified memory）运行 G0.5 SO101 checkpoint；
- `mark` WSL 控制 Galaxea A1Z、夹爪和腕部 DaBai DC1 相机；
- Mac 通过 SSH command proxy 和 reverse SSH 将 DGX `8765` 暴露为 `mark:127.0.0.1:8765`；
- G0.5 action chunk 能通过 WebSocket 返回并以 15 Hz 送入安全执行链；
- A1Z safe daemon 以 50 Hz 控制，最低安全频率 40 Hz，stream watchdog 为 350 ms；
- 相机固定旋转 180° 后输入模型；
- 五个 SO100 手臂轴和夹爪已映射到 A1Z，A1Z J4 由 daemon 独立保持；
- 限位、单步变化、反馈超时、温度、CAN、单 daemon 和断电编码器回绕保护已验证；
- 真机完成过接近目标、闭合夹爪、回中立位和约 30° 的确定性关节运动。

新增但尚未完成现场验收：

- `exterior_right`（Mark RGB 固定外部视角）与 `wrist`（夹爪随动 DaBai）双视角
  代码链路已经接入；Mac 相机因自动取景会移动，已从架构移除；
- 针对 A1Z 数据的微调；
- OpenAI 动作后结构化验收和有限纠偏代码已完成；API key 由仓库外的 0600
  runtime env 注入，不写入 Git。真机 actuator correction 仍要求有效相机标定；
- 可靠的开放词汇抓取成功率验证；
- 人体接触的力/触觉闭环。当前系统不得用来戳、拍或推真人。

## 主数据流

```text
DaBai wrist camera ─┐
A1Z joint feedback ─┼─ mark/WSL ─ WebSocket ─ Mac relay ─ SSH ─ DGX G0.5
task prompt ─────────┘                                      │
                                                           │ action chunk
                                                           ▼
A1Z motors ◀─ 50 Hz safe daemon ◀─ limit/step/watchdog ◀─ SO100→A1Z mapping
```

完整步骤：

1. `mark` 的 `CameraWorker` 从 DaBai 的 `/dev/v4l/by-id/...CC1N16200WR-video-index0`
   读取 640×480 MJPEG、5 FPS 图像并旋转 180°。
2. client 从 `/tmp/a1z.sock` 读取六轴位置、速度、力矩、温度、错误码和夹爪状态。
3. `A1ZSo100Mapping` 把 A1Z 本体状态转换成 SO100 模型坐标。
4. client 组装 `images`、`state.right_arm`、`task`、`embodiment_type=so100` 和 `frequency=15`。
5. observation 通过 `mark:127.0.0.1:8765` 的 reverse SSH 进入 Mac，再通过 command-mode SSH 到 DGX policy server。
6. G0.5 每次生成 16 步 action chunk；client 在每个 chunk 边界发送新图像和本体状态。
7. 模型动作转换回 A1Z 目标，经过有限值、软限位、最大 overshoot 和最大单步角度检查。
8. safe daemon 再次检查 stream jump、锁定轴、控制频率、反馈新鲜度、温度和电机错误。
9. 通过检查后，daemon 以 50 Hz 向 CAN `can0` 下发位置、速度、PD 和重力补偿。
10. client 结束或网络丢失时，350 ms watchdog 退出 stream 状态并保持测得位置；它不会自动停止 daemon，因为 A1Z 没有刹车，失能会下落。

复杂任务现在由服务在每个 16-step action chunk 后增加低频语义验收：

```text
执行前双相机观测 -> DGX G0.5 动作 -> Mark 安全执行
    -> 停稳后双相机观测 -> OpenAI 判断位置/目标/抓取
    -> success / allowlisted correction / abort
```

OpenAI 不进入实时控制环，也不直接生成关节角。它只返回结构化 verdict 和有限的下一子任务；最多有限次数重试，现有 client/daemon 安全检查始终拥有最终否决权。设计见 [OpenAI 动作验收与纠偏闭环](openai-action-evaluator-workflow.md)。

## SO100 五轴到 A1Z 六轴

这里不是“把五轴压缩成一个轴”。实际映射为：

| SO100 模型输出 | A1Z 目标 |
| --- | --- |
| arm 0 | J1 |
| arm 1 | J2，反向 |
| arm 2 | J3 |
| arm 3 | J5 |
| arm 4 | J6 |
| gripper | A1Z gripper |
| 无对应输出 | J4，由 safe daemon 保持 |

当前 direct mapping：

```yaml
arm_joint_indices: [0, 1, 2, 4, 5]
signs:  [1, -1, 1, 1, 1]
scales: [2, 2, 2, 3, 2]
offsets: [3.44501, 151.34757, 169.43454, -162.80379, 48.56067]
```

上面这组 offset 仍用于原有单相机配置，它把早期实测的 A1Z base pose
对齐到 SO101 proprioception 分布中心。双视角工作流固定从
`[0, 60, -60, 0, 0, 0]°` 中立位启动，因此
`config.mark-execute-two-view.yaml` 使用单独的中立位锚点：

```yaml
offsets: [3.12501, 244.34757, 241.49454, 55.89621, -12.25933]
```

2026-07-25 真机对照：旧 offset 从中立位启动时，16-step 批次的六轴几乎
不动、夹爪从全开误合到约 9%；改用中立位锚点后，首批 J2 从约 60° 移到
69.6°，夹爪保持约 91% 打开。这证明旧配置的首帧本体状态处于 checkpoint
训练分布之外；新 offset 恢复了有效动作，但它仍只是 joint-space affine
retargeting，不能替代 A1Z/SO100 的 FK/IK、TCP 与相机外参标定。

数学形式：

```text
model_deg[i] = offset[i] + sign[i] * scale[i] * a1z_deg[joint_index[i]]
a1z_deg[joint_index[i]] =
    (model_deg[i] - offset[i]) / (sign[i] * scale[i])
```

offset 以 SO101 checkpoint 的 proprioception 分布中心为锚点，避免把模型送到训练分布之外。J4 被排除是一个明确的安全折衷：模型无法生成完整六轴姿态，J4 的目标由 daemon 所有，client 不能覆盖。

## 摄像头合同

官方 SO100 部署使用：

- `exterior`：第三人称工作区视角；
- `wrist_right`：腕部视角；
- `wrist_left`：没有物理相机时可以补黑帧。

当前只有腕部 DaBai DC1：

```text
config.mark-execute.yaml
  real wrist camera -> wrist_right
  black frame       -> exterior, wrist_left
```

这能执行动作，但抓取最后几厘米时目标会离开腕部视野，而且关键的 `exterior` 是黑帧。实测把同一画面临时送入 `exterior` 后，目标接近明显改善：

```text
config.mark-execute-exterior.yaml
  real mounted camera -> exterior
  black frame         -> wrist_left, wrist_right
```

该文件仅用于单相机诊断。当前双视角配置为：

```text
Mark laptop RGB     -> exterior
arm-mounted DaBai   -> wrist_right
no physical camera  -> wrist_left (zero tensor only)
```

Mark 的 Windows RGB 和 DaBai 都通过 USB/IP。持续并发 UVC streaming 会让
`0408:30c3` 复合设备掉线，因此工作流只在设备缺失时 attach 一次并保持连接；
action boundary 只依次单拍 Windows RGB 和 DaBai。反复 attach/detach 会造成 CAN
反馈抖动，禁止在机械臂使能期间使用。图像以稳定文件形式交给下一次 G0.5 chunk。

## 部署节点

### DGX Spark

职责：

- G0.5 inference；
- checkpoint、ActionCodec 和 processor；
- 后续 A1Z 数据微调。

入口：

```bash
cd ~/hardware/robot-arm/a1z-g05-client
bash scripts/start_policy_dgx.sh
```

### Mac relay

职责：

- 同时可达 `dgx` 和 Tailscale `mark`；
- 将 DGX policy 私有转发到 Mark loopback；
- 不开放公网 policy 端口。

入口：

```bash
cd robot-arm/a1z-g05-client
bash scripts/relay_policy_to_mark.sh
```

### mark / WSL

职责：

- USB/IP 摄像头和 USB-CAN；
- A1Z safe daemon；
- observation 采集、SO100/A1Z 映射和真机执行。

入口：

```bash
cd ~/hardware/robot-arm/a1z-g05-client
bash scripts/start_a1z_safe_server.sh
bash scripts/preflight_mark.sh --operator-checked
```

执行一次任务：

```bash
PYTHONPATH=. ~/GALAXEA-A1Z/.venv/bin/python -m a1z_g05.headless \
  --config config.mark-execute.yaml \
  --task "Move toward the visible object, grasp it, lift it, and stop." \
  --max-steps 64
```

确定性回中立位优先使用：

```bash
~/GALAXEA-A1Z/.venv/bin/python ~/GALAXEA-A1Z/tools/a1zctl \
  move 0,60,-60,0,0,0 --speed 0.15
```

自然语言 prompt 不适合表达精确关节姿态；精确姿态、恢复和停机必须走确定性控制。

## 安全链

安全检查分两层。

Client：

- 相机缺失或帧龄超过 500 ms 时拒绝 inference；
- action 必须维度正确且全部有限；
- A1Z 软限位和最多 5° 小幅 projection；
- 每 tick 最大 2°；
- J4 锁定；
- task 步数有上限。

Safe daemon：

- 文件锁保证只有一个 CAN 控制 daemon；
- 完整六轴反馈到齐前不启用保持；
- 50 Hz 控制频率，连续低于 40 Hz 急停；
- 350 ms stream watchdog；
- 每次 stream 最大 3° jump；
- 电机温度、错误码、反馈超时和 CAN 状态检查；
- J4 使用 daemon-owned command；
- watchdog 对可动轴保持测量值，但保留锁定 J4 的 server command，避免长推理边界把
  重力漂移棘轮式固化；
- GPT 纠偏只可调用 base-frame `move_tool_delta` 小步工具：单轴 ≤20 mm、合成
  ≤30 mm、IK 关节变化 ≤8°；动作结束后必须用 FK 复算实测 TCP，方向/误差或 J4
  漂移不合格即返回失败；
- 断电后多圈编码器以固定 `2π` offset 解包，并对反馈与电机命令双向应用。

`a1zctl stop` 会停止 daemon 并可能导致无刹车机械臂失去保持。只有在机械臂已被支撑或急停风险更低时使用。

## 已知限制

1. SO101 checkpoint 不是 A1Z 专用 checkpoint，direct mapping 只是可运行适配，不等于完整 embodiment 训练。
2. 单腕相机不足以可靠评估抓取和抬升；第二路 exterior 是下一优先级。
3. J4 不受模型控制，不能通过 prompt 指定完整六轴姿态。
4. 语言模型可能忽略“保持夹爪张开”等否定约束；分阶段 task 和确定性夹爪命令更可靠。
5. G0.5 没有当前方案可用的力/触觉输入，禁止把开放式 prompt 用于真人接触。
6. USB/IP attach 在 Windows/WSL 重启或 USB reset 后可能失效，启动服务前必须重新 preflight。
7. 现场曾出现 J4 `error_code=0x9 (under voltage)`。daemon 会 Emergency Stop，
   Web hardware probe 也会读取 control thread、estop 和 error codes 并阻止新动作；
   该问题必须检查电源和接头，不能用提高软件刚度规避。
8. 2026-07-25 真机 10 mm 上移试验中，position-only IK 收敛，但 USB/IP 50 Hz
   执行时 J4 漂移 3.65°、TCP 实测反向约 6.8 mm。因此当前禁止把笛卡尔工具接入
   自动抓取，直至锁定轴跟踪和 DaBai 视角修复后重新验收。

## 关键文件

| 文件 | 用途 |
| --- | --- |
| `a1z-g05-client/a1z_g05/headless.py` | 单任务无界面执行入口 |
| `a1z-g05-client/a1z_g05/controller.py` | observation/action 闭环、client 安全检查 |
| `a1z-g05-client/a1z_g05/mapping.py` | SO100↔A1Z direct mapping |
| `a1z-g05-client/a1z_g05/safe_server.py` | 50 Hz daemon、watchdog、锁定轴和 stream 检查 |
| `a1z-g05-client/a1z_g05/camera.py` | UVC 采集和固定方向修正 |
| `a1z-g05-client/a1z_g05/g05_client.py` | msgpack WebSocket 协议 |
| `a1z-g05-client/config.mark-shadow.yaml` | 真机观测但不写动作 |
| `a1z-g05-client/config.mark-execute.yaml` | 当前腕部相机执行配置 |
| `a1z-g05-client/config.mark-execute-exterior.yaml` | 单相机 exterior A/B 诊断配置 |
| `GALAXEA-A1Z/a1z/robots/arm_robot.py` | 官方驱动分支及断电 encoder turn recovery |

## 相关文档

- [本地 MQTT/场景触发服务](../cushion-reminder-service/README.md)
- [MQTT 坐垫提醒服务化计划](mqtt-cushion-reminder-service-plan.md)
- [OpenAI 动作验收与纠偏闭环](openai-action-evaluator-workflow.md)
- [智能坐垫 × A1Z Demo 设计](smart-cushion-a1z-hackathon-demo.md)
- [G0.5/A1Z 源码兼容性调研](research/galaxea-vla-smart-cushion-integration.md)
- [A1Z bring-up](a1z-macos-bringup.md)
