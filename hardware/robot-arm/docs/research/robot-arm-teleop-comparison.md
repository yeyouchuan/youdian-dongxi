# A1Z、NERO、PiPER 机械臂与双臂遥操资料核查

核查日期：2026-07-23

## 口径

如果末端力方向与水平伸展半径垂直，且仅考察底座 J1 yaw 轴，可用理想静态关系 `F = T / L` 换算切向力。该值忽略机械臂自重、其他关节限制、减速器与热限制、控制限幅、结构刚度和安全系数，不是竖直承重力，也不是厂家保证的末端持续力。

## 参数与计算

| 机械臂 | 厂商公开的最长工作半径 | J1 机械扭矩 | 理想切向力 `T/L` | 结论 |
| --- | ---: | ---: | ---: | --- |
| Galaxea A1Z | 626.5 mm | 额定 20 N·m；峰值 50 N·m | 额定 31.92 N；峰值 79.81 N | 可按统一机械规格计算 |
| AgileX NERO 7 DoF | 580 mm | 未公开 | 无法给出同口径机械力 | SDK 量程不能替代机械额定/峰值扭矩 |
| AgileX PiPER 6 DoF | 626 mm | 未公开 | 无法给出同口径机械力 | SDK 量程不能替代机械额定/峰值扭矩 |

A1Z 的官方“关于 A1Z”页在“技术规格”表列出臂展 `R:90–626.5 mm`，在“机械关节”表列出 J1 额定 20 N·m、峰值 50 N·m；同页“关节运动范围”又给出 J1 旋转半径 618.5 mm。主计算采用产品总规格的最长半径 626.5 mm；若采用 J1 专门标注的 618.5 mm，换算为 32.34 N / 80.84 N。[原页：技术规格与机械关节](https://docs.galaxea-dynamics.com/A1Z/docs/)

NERO 官方产品页“基本性能参数”列工作半径 580 mm，“关节与其它参数”只列速度、运动范围、接口和功耗，未列关节扭矩。[NERO 产品页](https://www.agilex.ai/product/69314a20866efa631c9812fa?mi=1&rn=NERO-7+DoF)；[官方产品 PDF（第 4 页参数表）](https://www.agilex.ai/raw/files/page-manage_69314a20866efa631c9812fa_1764838764848-14854099.pdf)

PiPER 官方产品页“基本性能参数”列工作半径 626 mm，“关节参数”只列运动范围和最大速度，未列关节扭矩。[PiPER 产品页](https://www.agilex.ai/products/piper)；[官方产品 PDF](https://www.agilex.ai/raw/files/page-manage_690abe7b5e78cfa260412c92_1772707176694-162637989.pdf)

### 只能作为接口量程的算术代理值

这些数值是 SDK 对 MIT `t_ff` 的输入/编码范围，不是机械关节的持续或峰值额定值：

- NERO：固件 ≤1.10 的 J1–J2 输入范围为 ±24 N·m，算术上 `24/0.580 = 41.38 N`；固件 ≥1.11 为全关节 ±16 N·m，算术上 `16/0.580 = 27.59 N`。[NERO 固件参考：MIT 参数表](https://github.com/agilexrobotics/pyAgxArm/blob/cc498c00af0bcb9e297943e94f4792c0e3ee5b2c/docs/nero/firmware_reference.md#L50-L55)
- PiPER：旧固件 ≤S-V1.8-2 的 J1–J3 输入范围为 ±32 N·m，但编码前乘 0.25（线上有效范围 ±8），对应的纯算术分别是 51.12 N 与 12.78 N；S-V1.8-3～7 为 ±8 N·m，即 12.78 N；S-V1.8-8 为 ±16 N·m，即 25.56 N。[PiPER 固件参考：MIT 参数表](https://github.com/agilexrobotics/pyAgxArm/blob/cc498c00af0bcb9e297943e94f4792c0e3ee5b2c/docs/piper/firmware_reference.md#L69-L78)

SDK/固件之间的范围会变化，进一步说明不能把它们当作硬件额定值。旧 `piper_sdk` 的接口注释还曾列出 `t_ref` 为 `[-18, 18]`。[PiPER SDK 接口定义](https://github.com/agilexrobotics/piper_sdk/blob/c05c5454b1cf61c05ad26385e0c0a3aa6d3c7bad/piper_sdk/interface/piper_interface.py#L3617-L3625)

## 额定负载对应的重量

这不是 `J1 扭矩 / 半径` 的结果，只用于理解厂家 payload 的量级，按 `g = 9.80665 m/s²`：

- A1Z：3 kg 额定负载为 29.42 N；5 kg 峰值负载为 49.03 N。A1Z 官方页明确展示 100% 臂展的 3 kg 额定与 5 kg 峰值静态保持测试。
- NERO：3 kg payload 的重量为 29.42 N，但产品页没有明确保证其在每个最大伸展姿态下均可持续保持。
- PiPER：1.5 kg payload 的重量为 14.71 N，但产品页没有明确保证其在每个最大伸展姿态下均可持续保持。

## 双臂遥操文档位置

### AgileX NERO

- [NERO 官方 Python SDK](https://github.com/agilexrobotics/pyAgxArm)
- [NERO API：Leader-Follower Arm](https://github.com/agilexrobotics/pyAgxArm/blob/main/docs/nero/nero_api.md#leader-follower-arm)：包含 `set_leader_mode()`、`set_follower_mode()`、`get_leader_joint_angles()` 和 follower 的 `move_js()`。
- [NERO 固件差异](https://github.com/agilexrobotics/pyAgxArm/blob/main/docs/nero/firmware_reference.md)：固件 1.11、1.12、1.20 对 MIT、CPV、leader/follower 和反馈行为有差异。
- 用户给出的[松灵飞书文档](https://mammotion.feishu.cn/docx/XryDdbv7Aoud8TxwmSPcGA5gn7e)当前要求登录，无法在未登录会话中核对正文。

官方 SDK 文档说明了单对 leader/follower 的底层能力，但未提供一份与 OpenA1Z-T 同等完整的“两个 leader + 两个 follower”端到端双臂启动脚本。因此双臂工程仍需自行实例化四条设备链路、做左右臂路由和同步。

### Galaxea A1Z

- [OpenA1Z-T 官方仓库](https://github.com/userguide-galaxea/OpenA1Z-T)：README 同时给出单臂与 `--dual` 双臂命令。
- [英文硬件安装指南](https://github.com/userguide-galaxea/OpenA1Z-T/blob/main/hardware/assembly_guide_en.md)
- [中文硬件安装指南](https://github.com/userguide-galaxea/OpenA1Z-T/blob/main/hardware/assembly_guide_cn.md)
- [A1Z SDK](https://github.com/userguide-galaxea/GALAXEA-A1Z)
- [A1Z 文档中心](https://docs.galaxea-dynamics.com/A1Z/docs/)在“开源项目”中同时链接 A1Z 与 A1Z-T。

OpenA1Z-T 的双臂命令使用两个 follower SocketCAN 通道（默认 `can0`/`can1`）；两个 servo leader 可用独立 USB 串口，或把左右 leader 配置为 ID 1–14 后共用一个 USB 菊花链。配置文件可调夹爪刻度、关节方向、follower PD 增益与力反馈参数。

## 对实际开发的影响

### NERO 双臂遥操

- 7 DoF 同构 leader/follower 直接复制关节状态时，可保留 leader 的肘部姿态，避障和拟人动作自由度更高；若改成末端位姿控制，则必须增加冗余解析、零空间目标和关节限位策略。
- 每帧双臂动作至少有 14 个关节维度（另加夹爪），比 6 DoF 双臂的数据和策略输出更高维；标定、异常检测与数据质量检查也多两个关节通道。
- leader 与 follower 都是完整 NERO 时，运动学一致，映射误差较小；代价是 leader 本体的齿轮摩擦、惯量和重量会影响手感，即使使用零力拖动模式也不等于低惯量专用示教器。
- 固件版本是集成风险。≤1.10、1.11、≥1.12/1.20 的 leader/follower、CPV、反馈和扭矩编码行为不同；项目应固定固件与 `NeroFW` 驱动版本，并在启动时校验。
- 官方资料提供 leader/follower 原语而非完整双臂应用编排，开发者需要自行完成四臂 CAN 路由、左右臂同步、时间戳、急停和数据记录。

### OpenA1Z-T 双臂遥操

- 6 DoF follower 没有冗余自由度，关节空间映射和模型动作空间更小（双臂 12 个关节，另加夹爪），数据管线、策略输出和回放验证相对直接。
- 无冗余意味着末端到达同一位姿时没有独立的肘部零空间可选，狭窄环境避障、奇异位形处理和“更像人”的肘部姿态通常比 7 DoF 更受约束。
- leader 是专用 servo 机构而非另一台 A1Z follower：操控端可以更轻、更易布置，并支持配置力反馈；但首次装配需要刷写舵机 ID/波特率、校准零位/方向和夹爪刻度，leader/follower 异构误差需要软件补偿。
- 官方仓库已经包含 `--dual` 路径、CAN 初始化脚本、双 USB/单 USB 菊花链两种接线方式和配置文件，端到端跑通成本较低；但 Linux SocketCAN、USB 设备稳定命名和左右通道绑定仍是部署重点。
- follower 侧基于 A1Z SDK 的 250 Hz 控制、Pinocchio 重力补偿和 PD 参数；调参不当会直接影响跟随延迟、振荡和操作安全。

## 结论

如果目标是尽快搭出可重复的数据采集系统，OpenA1Z-T 的端到端双臂脚本、专用 leader 和较低动作维度更省集成工作。若任务依赖绕障、肘部姿态或更拟人的双臂运动，NERO 的 7 DoF 更有潜力，但必须为冗余控制、四臂编排和固件版本管理预留明显更多工程量。
