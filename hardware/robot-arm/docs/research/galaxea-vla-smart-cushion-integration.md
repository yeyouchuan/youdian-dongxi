# Galaxea G0.5 VLA 与 A1Z 智能坐垫联动调研

核查日期：2026-07-23（Asia/Shanghai）

核查范围：OpenGalaxea 官方 [G0.5 技术页](https://opengalaxea.github.io/G05/) 与
[OpenGalaxea/GalaxeaVLA](https://github.com/OpenGalaxea/GalaxeaVLA) 官方仓库。
仓库代码核查基于提交
[`b34966f387dd2ae0f003143b81494afd9213e613`](https://github.com/OpenGalaxea/GalaxeaVLA/tree/b34966f387dd2ae0f003143b81494afd9213e613)。
本文不连接 CAN、串口或真实机械臂，也不把任何模型输出发送给硬件。

## 结论摘要

1. **G0.5 不能直接控制当前 A1Z/G1Z。** 官方真实机器人入口只覆盖 R1 Lite、R1 Pro、SO-100/101 和 DROID/Franka；本次核查的仓库中没有 A1Z/G1Z 的 client、数据配置、`eval_embodiment` 或部署说明。A1Z 虽然也是六轴单臂，但不能把 R1 Lite 的一侧六轴输出直接转发到 CAN。
2. **G0.5 更适合后期“看懂目标并抓放”，不适合作为首版人物检测器或安全控制器。** 官方模型能生成 `BBox`、`Trace` 等推理字段，且重点能力覆盖 pick/place；但仓库没有把它包装成有确定延迟和召回保证的人体安全检测接口。
3. **当前单路夹爪前 USB 摄像头不是官方 R1 输入的即插即用替代。** 官方 R1 Lite 客户端使用头部、左腕、右腕三路 RGB；A1Z 需要自建 UVC 采集、相机槽映射、时间同步、训练配置和数据统计。
4. **Apple Silicon Mac 不适合作为 G0.5 policy server。** 官方只测试 Linux、CUDA 12.8、PyTorch 2.7.1 和原生 CUDA 扩展；推理要求 NVIDIA GPU 大于 8 GB。Mac 适合做坐垫事件、USB 相机、确定性状态机和安全执行网关，模型放在 RTX Linux 主机。
5. **黑客松首版应选择“看到人 → 非接触提醒动作”，然后是固定道具抓放。** “拍一下/锤一下真人”风险和验证难度最高，且 G0.5 没有官方力觉闭环输入；如果要展示接触，只接触固定泡棉靶，并用外部力传感器验收。
6. **推荐架构是分层而非端到端直控：** 坐垫决定何时提醒，独立视觉管线决定是否有人及安全区域，G0.5 只给语义目标/候选动作，经过限位、速度、碰撞、人体距离和安全回位网关后，才允许执行预验证轨迹。

## 1. G0.5 实际提供什么

G0.5 是以 Qwen3.5-2B 为初始化的自回归 Vision-Language-Action 模型。输入包括多视角
RGB、机器人 embodiment 标识、自然语言任务和本体状态；同一 Transformer 解码器先生成可选
推理 token，再生成动作 token。动作由 ActionCodec 解码成连续控制，按 chunk 执行，并基于新观测
闭环重规划。[官方 G0.5 概览](https://github.com/OpenGalaxea/GalaxeaVLA#-g05-overview)

官方把不同机器人动作映射到统一 27 维布局：

```text
left_control(9)
| left_gripper(1)
| right_control(9)
| right_gripper(1)
| lower_body(7)
```

动作组经过残差向量量化 tokenizer 转成离散动作 token；只有活跃动作组需要生成。官网说明预训练
混合了 14 种机器人 embodiment，并用 5 秒窗口内的 6 帧视觉历史训练。
[G0.5 技术页](https://opengalaxea.github.io/G05/)；
[ActionCodec 说明](https://github.com/OpenGalaxea/GalaxeaVLA#-g05-overview)

“14 种 embodiment 的预训练”不等于“任意机器人可零样本直控”。部署仍需要与具体机器人的
观测字段、动作字段、单位、归一化统计和控制接口一致的 adapter。官方仓库当前给出的真实机器人
部署面如下：

| 平台 | 官方部署入口 | 模型/控制说明 |
| --- | --- | --- |
| R1 Lite | `experiments/r1lite` | ROS2 客户端，`g05-base` 零样本部署 |
| R1 Pro | `experiments/r1pro` | ROS2 多帧客户端，`g05-base` 零样本部署 |
| SO-100/101 | `experiments/so100` | LeRobot 客户端，专用 `g05-so101` checkpoint |
| DROID / Franka | `experiments/droid` + 独立 Franka client | 专用 `g05-droid` checkpoint |
| LIBERO | 仿真评测 | 专用 `g05-libero` checkpoint |
| RoboTwin 2.0 | 仿真评测 | 专用 `g05-robotwin20` checkpoint |
| **A1Z/G1Z** | **没有** | **没有官方 client、config、checkpoint 或部署声明** |

来源：[官方真实机器人部署入口](https://github.com/OpenGalaxea/GalaxeaVLA#inference-on-real-robots)；
[官方训练入口](https://github.com/OpenGalaxea/GalaxeaVLA#fine-tuning-base-models-on-galaxea-robots)。

### 1.1 视觉与语言能力的边界

G0.5 的推理 span 可含 `Subtask`、`BBox`、`Trace` 和 `ActionHint`，分别表达任务分解、物体
框选、二维夹爪轨迹和帧级动作提示。这让它适合从语言中选择物体、解释下一子任务，并为操作提供
语义线索。[官方 G0.5 概览](https://github.com/OpenGalaxea/GalaxeaVLA#-g05-overview)

但这并不构成一个独立的“人是否在危险区”检测器：

- 官方 server 接口的最终用途是动作预测，不提供人物检测的精度、召回、最坏延迟或失效安全合同；
- `BBox` 是生成式推理字段，不应作为急停或人体距离的唯一输入；
- 官方输入是 RGB 和机器人本体状态，没有深度、力/力矩或触觉字段作为通用必选输入；
- 摄像头遮挡、绑带松动、腕部快速运动和单目尺度歧义都可能让人物距离判断失真。

因此人物存在、人体关键点、相机帧新鲜度和安全距离必须由独立、可测的感知管线提供；G0.5
可以做语义复核，但不能拥有安全否决权。

### 1.2 官方所证明的操作能力

官方技术页展示的强项是桌面操作：DROID/Franka 零样本评测覆盖物体放置、按颜色选择、小孔插入、
柔性物体操作、空间位移和多步顺序任务；R1 Lite/R1 Pro 的真实机器人微调覆盖毛巾/纸箱等操作。
“Pick up Anything & Place Anywhere”来自 **50 小时 R1 Lite 桌面数据的后训练**，场景含
5–20 个物体。[G0.5 技术页](https://opengalaxea.github.io/G05/)

这支持“G0.5 适合成为后期抓放策略候选”，但不能推出当前 A1Z、单腕相机和当前夹爪安装能够
获得同样的零样本成功率。机器人形态、相机位置、夹爪几何和动作统计均发生了变化。

## 2. 摄像头输入与当前 USB 相机的差异

官方 R1 Lite 客户端订阅三路 ROS2 `CompressedImage`：

- `head_rgb`
- `left_wrist_rgb`
- `right_wrist_rgb`

客户端将压缩图像解码为 RGB，并发送 `(C,H,W) uint8` 数组。
[R1 Lite ROS2 话题配置](https://github.com/OpenGalaxea/GalaxeaVLA/blob/main/experiments/r1lite/core/communication/robot_topics.py)；
[R1 Lite 图像转换与观测采集](https://github.com/OpenGalaxea/GalaxeaVLA/blob/main/experiments/r1lite/core/communication/ros2_bridge.py)

R1 Lite 数据配置声明三路原始图像均为 `3×720×1280`，训练/推理预处理为 `3×224×224`。
同一配置还声明左右六轴手臂、左右单维夹爪状态和动作。
[R1 Lite 数据配置](https://github.com/OpenGalaxea/GalaxeaVLA/blob/main/configs/data/r1lite.yaml)

当前夹爪前侧单路 USB 摄像头可以成为 A1Z 自定义客户端的 `wrist_rgb`，但至少要补：

1. UVC 相机枚举与序列号锁定，避免重启后设备索引变化；
2. RGB/BGR、分辨率、曝光、畸变和时间戳的明确约定；
3. 相机到 TCP/基座的外参标定；
4. 帧新鲜度、冻结帧、拔线和低曝光检测；
5. A1Z 数据配置中的相机槽定义，以及与采集数据一致的 normalization stats；
6. 若模型仍期望多相机，对缺失视角做经过训练验证的 camera dropout/zero padding。

SO-100 官方客户端确实允许把实物相机映射到模型槽，并对缺失相机补零；但这只是该 checkpoint
和训练增强下的兼容机制，不能自动保证 R1/A1Z checkpoint 在单相机输入下仍可靠。
[SO-100/101 部署说明](https://github.com/OpenGalaxea/GalaxeaVLA/blob/main/experiments/so100/README.md)

## 3. 动作表示、推理和训练工作流

### 3.1 官方 client/server 协议

真实机器人采用 server/client 分离：

```text
robot-side client
  images: {camera: CHW uint8}
  state: {body_part: float32[D]}
  task: natural-language string
  embodiment_type: string
        │ WebSocket + msgpack
        ▼
Linux/CUDA policy server
  preprocess → G0.5 inference → postprocess
        │
        ▼
action: {body_part: float32[T,D]} in physical units
```

客户端不做归一化；server 根据 checkpoint 的 processor 和 `dataset_stats.json` 完成坐标变换、
合并/拆分和归一化。官方 R1 Lite 示例以 15 Hz 控制，server 每次推理缓存并执行 16 个动作步，
再从新观测重规划。[R1 Lite 协议](https://github.com/OpenGalaxea/GalaxeaVLA/blob/main/experiments/r1lite/README.md)；
[R1 Lite 运行配置](https://github.com/OpenGalaxea/GalaxeaVLA/blob/main/experiments/r1lite/config.toml)

R1 Lite 的训练配置把左右臂动作各表示为 6 维关节量、夹爪各 1 维，并对手臂使用
`RelativeJointTransform`。server 后处理后再返回物理单位的分部动作。
[R1 Lite 数据配置](https://github.com/OpenGalaxea/GalaxeaVLA/blob/main/configs/data/r1lite.yaml)；
[相对关节动作变换](https://github.com/OpenGalaxea/GalaxeaVLA/blob/main/src/g05/data_processor/transforms/relative_action.py)

### 3.2 A1Z 不能直接复用 R1 Lite 左臂输出

两者表面上都是“六轴手臂 + 一维夹爪”，但仍有以下未解决差异：

- 关节顺序、零位、正方向和限位可能不同；
- R1 Lite 数据分布来自双臂/躯干/底盘 embodiment，A1Z 是桌面单臂；
- 相机视角、TCP、夹爪形状和开度单位不同；
- checkpoint 的 `dataset_stats.json` 不代表 A1Z 的状态/动作统计；
- R1 客户端发布 ROS2 motion target，当前 A1Z 使用自定义 macOS HHS CAN 传输；
- 官方客户端没有当前项目的 J4 `±1.309 rad`、人体 keep-out 和先回安全位再失能约束。

因此禁止将 G0.5 返回的某个 6D action 数组直接当作 A1Z 六关节目标。

### 3.3 如果后续为 A1Z 适配 G0.5

官方自有数据微调流程使用 LeRobot 数据集：创建/修改 `configs/task/` 与 `configs/data/`，
提供本地数据路径，从 base checkpoint 运行 `scripts/run/finetune.sh`。
[官方微调说明](https://github.com/OpenGalaxea/GalaxeaVLA#fine-tuning-base-models-on-galaxea-robots)；
[配置快速指南](https://github.com/OpenGalaxea/GalaxeaVLA/blob/main/configs/QUICK_START.md)

A1Z 至少需要新增：

- `galaxea_a1z_g1z` embodiment id；
- 单臂六轴、夹爪和相机的 `shape_meta`；
- ActionCodec 中单臂动作组的 merge/padding 规则；
- A1Z 专属 joint/state/action normalization stats；
- 同步的 LeRobot episode：RGB、六轴反馈、夹爪开度、自然语言任务、动作目标、成功/失败标签；
- A1Z WebSocket client 与现有安全控制器之间的 adapter；
- 仿真/回放评测入口，以及真实硬件前的 shadow mode。

官方没有给出 A1Z 微调配方、最低数据量或成功率保证。第一批数据应只含固定桌面、固定道具、
低速预验证轨迹；不要从人体接触示范开始。

## 4. 运行环境与 Apple Silicon 风险

官方测试环境为：

- Linux；
- Python `>=3.10.16,<3.11`；
- CUDA 12.8；
- PyTorch 2.7.1 CUDA wheel；
- `flash-attn-4`、`flash-linear-attention` 等原生 CUDA 扩展；
- 推理显存大于 8 GB，推荐 RTX 3090/4090；
- full fine-tuning 显存大于 70 GB，示例为 A100 80 GB/H20 96 GB。

[官方 GPU 与安装要求](https://github.com/OpenGalaxea/GalaxeaVLA#gpu-requirements)

每个 G0.5 checkpoint 约 11 GB，共享 ActionCodec tokenizer 约 484 MB；包含列出的完整
checkpoint 集约 55 GB。[官方 checkpoint 布局](https://github.com/OpenGalaxea/GalaxeaVLA#model-checkpoints)

Apple Silicon 没有官方 MPS/Metal 推理路径，CUDA 扩展也不能在 Mac 上运行。推荐部署：

```text
Mac / A1Z 桌面端                         RTX Linux
──────────────────                      ───────────────
坐垫事件
USB 相机与独立人物检测
状态机、安全监控
A1Z 反馈与动作网关       ← WebSocket →  G0.5 policy server
轨迹回放/日志
```

这是依据官方 client/server 架构做出的项目方案，不是官方 A1Z 支持声明。Mac 端应能在远端
GPU 或网络不可用时完全绕过 VLA，用本地状态机完成比赛主流程。

官方 R1 客户端还要求 Python 3.10 + ROS2 Humble，`rclpy` 由
`/opt/ros/humble` 注入。[R1 Lite 客户端环境](https://github.com/OpenGalaxea/GalaxeaVLA/blob/main/experiments/r1lite/README.md)
当前 A1Z Mac 控制栈不应为了复用该客户端而强行引入 ROS2；实现一个只负责 numpy/msgpack/WebSocket
协议的薄客户端更清晰。

## 5. 四类比赛能力的复杂度与可验证性

评分：1 最低/最容易，5 最高/最困难。

| 能力 | 实现复杂度 | 人身风险 | 可验证性 | G0.5 适配度 | 建议 |
| --- | ---: | ---: | ---: | ---: | --- |
| 人物出现检测 | 2 | 1 | 5 | 2 | 用独立 detector/pose；VLA 只做语义复核 |
| 非接触提醒手势 | 2 | 1 | 5 | 2 | **比赛首版主动作**，使用预验证关节轨迹 |
| 轻触固定泡棉靶 | 4 | 3 | 4 | 2 | 仅固定假人/泡棉和外部力传感器；不触碰真人 |
| 固定道具抓取/放置 | 4 | 2 | 4 | 4 | **第二阶段主动作**；先固定物体，再引入 VLA |
| 拍/锤真人 | 5 | 5 | 1 | 1 | 不进入比赛主流程 |

### 5.1 人物检测

坐垫负责回答“是否在座/离座多久”，摄像头负责回答“机器人工作区是否有人、目标用户是否出现”。
首版可用可重复的传统 detector/pose 模型，输出置信度、框、关键点和时间戳；连续若干帧确认后才
触发状态迁移。G0.5 的 `BBox` 可在 shadow mode 中记录并对比，但不用于急停。

验收可以直接量化：预录视频的 precision/recall、人物进入到状态改变的 p95 延迟、遮挡/拔线后
进入 `VISION_LOST` 的时间。

### 5.2 非接触提醒

最合适的第一版动作是“抬头看向用户 → 小幅挥手/点头 → 回 HOME_SAFE”。它不需要精确目标
三维位置，也不需要夹持和接触。轨迹应由仿真生成并逐点通过 A1Z 限位、速度、碰撞和线缆检查，
然后以固定版本发布。

坐垫事件只选择动作，不生成关节目标：

```text
AWAY_TOO_LONG + PERSON_VISIBLE + AREA_CLEAR
    → LOOK_UP
    → REMINDER_GESTURE
    → HOME_SAFE
```

### 5.3 轻触/拍一下

G0.5 官方通用输入没有力/力矩或触觉闭环合同，因此不能仅凭 RGB 判断接触力。真人软组织位置也会
移动，腕部单目相机在接近阶段更容易失去全局安全视野。

如果必须展示“拍一下”，把目标改成固定的泡棉按钮或带力传感器的假肩：

- 固定目标位姿，预先示教接触前 waypoint；
- 接触速度和最大行程双重限制；
- 外部传感器给出接触阈值和硬件独立停止；
- 达到阈值立即沿原路径退回；
- 至少记录峰值力、冲量、末端位移和退出原因。

这可以验证接触控制，但不应被描述为已经验证了“拍真人”。

### 5.4 物体抓放

这是 G0.5 与比赛叙事最匹配的复杂能力，但应分级：

1. 固定位置、单一大号轻质道具，确定性 IK + 固定 waypoint；
2. 同一桌面内若干已知位置，传统检测选目标；
3. 多个已知道具，VLM/VLA 根据语言选择；
4. 未知摆放与闭环抓取；
5. 多步“取物 → 递送 → 放回”。

比赛建议停在 2 或 3。道具用海绵球、空纸盒或大号拉伸卡，避开玻璃、液体、尖锐和高价值物品。
“递送”应送到固定托盘，不把夹爪伸向人的手或面部。

## 6. 推荐的智能坐垫联动产品架构

```text
Smart Cushion
occupancy / posture / away duration
           │
           ▼
Deterministic Demo Orchestrator
IDLE → WAITING → PERSON_SEEN → REMIND → OFFER_OBJECT → RETURN
           │                    ▲
           │ intent             │ result / failure
           ▼                    │
Perception Layer ──────── Optional G0.5 Server
person/pose/safety ROI       target grounding / subtask proposal
           │                    │
           └────────┬───────────┘
                    ▼
Safety Governor
freshness / limits / velocity / acceleration / collision /
human keep-out / J4 ±1.309 rad / timeout / HOME_SAFE return
                    │
                    ▼
Trajectory Library or constrained IK
                    │
                    ▼
A1Z Hardware Adapter
```

关键产品原则：

- 坐垫事件具有触发权，但没有运动控制权；
- 独立安全感知具有否决权；
- VLA 只能提出 intent 或候选 action，不能绕过 safety governor；
- 首版硬件只执行有版本号、已仿真和已实机低速验证的轨迹；
- 正常结束先回运行待机位 `HOME_SAFE`，再在控制仍有效时用 60 帧五次
  minimum-jerk 归到全零位；实测确认后保持使能，人工托住并确认，才允许
  失能，最后断 24V；
- 急停、通信中断或越限时不盲目自动回位，应保持/停止并由现场人员处理；
- VLA 断线、超时或 OOD 时回退到确定性状态机，不让比赛主流程依赖网络。

## 7. 推荐黑客松 Demo 与里程碑

### Demo 主线

1. 用户坐上坐垫，坐垫建立连续在座计时；
2. `demo_mode` 将“连续坐太久未起身”压缩为可演示时长，并在界面明确标记；
3. USB 相机连续确认人物仍在交互区；
4. 机械臂执行非接触 `LOOK_UP + WAVE`；
5. 用户仍未起身时，机械臂从固定位置夹起拉伸卡/海绵球，放到固定提醒托盘；
6. 坐垫检测到一次达到重置阈值的离座，或用户确认完成拉伸；
7. 机械臂先回 `HOME_SAFE`，Dashboard 显示完整事件链。

这条故事同时体现坐垫、视觉、机器人、夹爪和数据闭环，又不需要触碰真人。

### 实施顺序

**Phase 0：纯回放**

- 坐垫模拟事件 → 状态机 → Dashboard；
- 摄像头录像回放 → person/vision-lost；
- MuJoCo 执行 `LOOK_UP`、`WAVE`、`PICK_PROP`、`PLACE_TRAY`、`HOME_SAFE`。

**Phase 1：真实相机、仿真机器人**

- 锁定 USB 相机序列号与格式；
- 标定相机并测试帧新鲜度；
- 录制人物进入、遮挡、拔线、多人和背景干扰用例；
- G0.5 只做离线/shadow 推理，不影响状态机。

**Phase 2：真实 A1Z、确定性动作**

- 分别验证每个预设姿态和轨迹；
- 验证 J4 `±1.309 rad`、全轴限位、非目标轴漂移和安全回位；
- 先做非接触提醒，再做固定道具抓放；
- 每次正常测试先回安全基准位，再失能，最后断电。

**Phase 3：远端 G0.5 语义接入**

- RTX Linux 启动 policy server；
- Mac 发送相机、本体状态、任务和自定义 embodiment；
- 首先只记录模型输出，与确定性轨迹做离线对比；
- 只有通过回放、仿真和 shadow 评估后，才允许 VLA 选择预验证动作 ID。

**Phase 4：A1Z VLA 后训练**

- 采集固定道具抓放的同步 LeRobot 数据；
- 建立 A1Z config、stats、checkpoint 与仿真评测；
- VLA 生成的连续轨迹仍必须经过 action gateway；
- 不以人体接触作为训练或比赛验收任务。

## 8. 阶段验收标准

首版非接触 Demo：

- 离线回放连续 20 次状态序列一致；
- 人物确认需要连续帧，单帧误检不触发；
- 摄像头拔线/冻结在 300 ms 内阻止新动作；
- 机器人全程不进入人体 keep-out 区；
- 正常流程 10 次均返回 `HOME_SAFE`；
- 每次记录 cushion event、vision event、intent、轨迹版本、关节反馈、最小距离和退出原因。

固定道具抓放：

- 固定初始位连续 20 次抓取/放置；
- 道具未被识别或位姿超出容差时不运动；
- 夹持失败进入 `RETREAT`，不继续递送；
- 道具只放到固定托盘，不递到人手；
- VLA shadow 输出与最终执行动作分开保存，能追溯每次否决原因。

接触泡棉靶：

- 与真人测试完全隔离；
- 独立测力、硬限制速度和行程；
- 峰值力与停止延迟有明确阈值；
- 任一传感器或通信失效均不启动接触段。

## 9. 许可与产品化

官方仓库说明，2026-06-16 及之后的 G0.5 材料采用 G0.5 Community License，只允许研究、
教育、个人使用和评估等非商业用途；生产部署、向第三方提供服务或产品化需要单独商业许可。
[官方许可说明](https://github.com/OpenGalaxea/GalaxeaVLA#what-you-can-do-under-the-g05-community-license)

黑客松原型通常更接近研究/评估，但如果智能坐垫进入商业产品路线，应在架构锁定和数据投入前
向 Galaxea 确认商业授权；不要默认开源仓库即允许商业集成。

## 最终建议

最终比赛动作优先级：

1. **必须完成：** 坐垫触发 + 人物确认 + 非接触提醒动作 + 安全回位；
2. **推荐完成：** 固定轻质道具抓取并放到固定托盘；
3. **可选加分：** G0.5 在远端 GPU 上做目标/语言 grounding，先 shadow、后只选择动作 ID；
4. **赛后研发：** A1Z 专属数据采集、embodiment adapter 和后训练；
5. **不做：** VLA 直接输出 CAN 指令，或让机器人拍/锤真人。

这一路线把最可验证的联动作为比赛主线，同时保留 G0.5 的亮点：它可以在后续阶段把“拿哪个物品、
放到哪里、下一步做什么”从硬编码升级为视觉语言条件下的闭环操作。
