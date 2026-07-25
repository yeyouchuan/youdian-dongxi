# A1Z IK、动力学、仿真与人体姿态跟随技术调研

核查日期：2026-07-23（Asia/Shanghai）

## 目标与边界

本文只讨论离线模型、IK/动力学、仿真和摄像头人体姿态管线，不连接或驱动真实机械臂，也不包含任何安装操作。真实机械臂控制应继续留在独立线程中；仿真输出在通过限位、碰撞、速度、加速度、可达性与时序检查之前，不得直接转发到硬件。

资料口径限于厂商官方仓库、项目官方文档和原始论文/实现。平台支持结论以 2026-07-23 可见的官方资料为准。

## 结论摘要

1. **当前最合理的本机主线是 Pinocchio + MuJoCo。** A1Z 官方 `gripper` 分支已经以 Pinocchio 实现 URDF 加载、限位投影的阻尼最小二乘 IK，以及 RNEA 重力/逆动力学；应复用这套关节约定作为唯一运动学真值。MuJoCo 有官方 macOS arm64 预编译包和 Python 绑定，适合补足接触、夹爪/人体代理碰撞、传感器与闭环物理仿真。
2. **SDK 内的模型不能直接成为完整数字孪生。** SDK 只提交了 `A1Z_G1Z.urdf` 和 `A1Z_Flange.urdf`；URDF 引用了 `package://A1Z_G1Z/meshes/*.STL`，但该提交没有这些网格。Galaxea 独立的官方 `URDF` 仓库提供了 A1Z/G1Z STL，已可补足显示模型；不过 G1Z 左右夹指仍是固定关节，不表示真实夹爪开度，碰撞代理、执行器、传感器和夹爪映射仍需补建。
3. **Drake 适合作为第二阶段的约束/碰撞感知 IK 基准，不是第一阶段依赖。** 它的 IK、最小距离约束和 differential IK 很强，且当前正式支持较新的 macOS arm64；但其 macOS Python 版本支持窗口严格，宜与现有 A1Z Python 环境隔离。
4. **PyBullet 适合快速冒烟和接口原型，但不是首选精度基准。** 它能直接加载 URDF 并提供 FK/IK、逆动力学、碰撞和仿真，官方也声明 Bullet 在 Mac OSX 上测试；不过官方资料没有对当前 Apple Silicon Python wheel 给出像 MuJoCo/Drake 那样明确的支持矩阵。
5. **Isaac Sim 不能在这台 Apple Silicon Mac 上本地运行。** Isaac Sim 6.0 的主程序只支持 Windows、Ubuntu x86-64，以及特定的 NVIDIA DGX Spark aarch64；macOS aarch64 下载项只是连接远端无头实例的 WebRTC 客户端。只有准备一台带受支持 RTX GPU 的 Windows/Linux 工作站或云实例后，才值得引入。
6. **单目 2D OpenPose 关键点不能直接当作机器人基座坐标。** 必须先获得米制 3D 人体点，再用经标定的 `T_base_camera` 变换到基座坐标。OpenPose 官方 3D 模块依赖多相机、内外参和三角化，并且只处理单人；Apple Silicon 上优先做 MediaPipe Pose/其他本机推理后端的可替换适配器，OpenPose 保留为兼容后端。

## 本机下载与离线验证快照

本机 `dimos/.venv` 已有原生 arm64 的 MuJoCo 3.5.0、Pinocchio 3.8.0、Pink 4.2.0、OpenCV 4.13.0，以及 editable A1Z `gripper` SDK，因此没有重复建立或修改该大型环境。

已浅克隆并稀疏检出以下厂家资源，均放在主仓库忽略的 `simulation/vendor/`：

- Galaxea 官方 `URDF` 仓库提交 `48289aef1fda293fe41f33a80738f1b566f6b659`：仅检出 `A1Z/A1Z_G1Z` 和 `A1Z/A1Z_Flange`，包含完整 STL。[官方 A1Z/G1Z 模型目录](https://github.com/userguide-galaxea/URDF/tree/galaxea/main/A1Z/A1Z_G1Z)
- Galaxea 官方 Isaac Sim 教程提交 `ca15a0d9a764c57fa6e4d6d94be7afc4c3dddfd0`：仅检出 A1/G1 USD、轨迹与控制示例；这些文件留给未来远端 RTX Isaac Sim 使用。[官方 Isaac Sim 教程](https://github.com/userguide-galaxea/A1_Simulation_Isaac_Sim_Usage_Tutorial)

新增的离线工具不会导入 CAN/串口传输模块：

- `simulation/prepare_a1z_mujoco.py` 复制厂家 STL，并仅对派生 URDF 加入 MuJoCo `balanceinertia` 编译指令；原始厂家文件不修改。
- `simulation/a1z_offline_smoke.py` 验证 Pinocchio FK→IK、RNEA 静态逆动力学以及 MuJoCo 模型加载/步进。

2026-07-23 实测结果：

- FK→IK 收敛，TCP 平移误差 `0.00003803 m`，旋转矩阵误差 `0.00013478`，结果在六轴限位内；
- 测试姿态重力矩为 `[0.0, -0.697404, -6.99355, -1.81034, 0.006706, 0.000234] Nm`，与零速度、零加速度 RNEA 完整逆动力学一致；
- MuJoCo 成功加载 `nq=6`、`7` 个融合后 body，并完成 `0.2 s` 无头物理步进；
- 这只证明运动学、惯性模型和被动物理可以启动；导入模型还没有 actuator、TCP site、接触传感器或可动夹爪，不代表完整闭环数字孪生。

## 1. A1Z 官方模型与 SDK 现状

本地 `GALAXEA-A1Z` 是官方仓库 `gripper` 分支提交 `e931ecd0e25ad35df251097ba42921b3d2fa7224`。官方 README 明确列出 Pinocchio 重力补偿、FK/IK、G1Z 夹爪和默认 `A1Z_G1Z.urdf`。[A1Z 官方 `gripper` 分支](https://github.com/userguide-galaxea/GALAXEA-A1Z/tree/gripper)

### 已可复用的内容

- `Kinematics` 使用 Pinocchio 从 URDF 建模，FK 返回 4×4 齐次变换；IK 使用局部坐标系误差、Jacobian 和阻尼最小二乘，每次迭代都投影到 URDF 关节限位，无法在限位内收敛时返回 `False`。[A1Z `kinematics.py`](https://github.com/userguide-galaxea/GALAXEA-A1Z/blob/e931ecd0e25ad35df251097ba42921b3d2fa7224/a1z/robots/kinematics.py)
- `GravityModel` 使用 Pinocchio RNEA 计算静态重力矩和完整逆动力学 `τ = M(q)q̈ + C(q,q̇)q̇ + g(q)`，并直接读取 URDF 关节限位。[A1Z `gravity_model.py`](https://github.com/userguide-galaxea/GALAXEA-A1Z/blob/e931ecd0e25ad35df251097ba42921b3d2fa7224/a1z/dynamics/gravity_model.py)
- `A1Z_G1Z.urdf` 含 6 个旋转关节的质量、惯量、轴、速度、力矩和位置限制。其弧度限位为：

| 关节 | 下限 | 上限 |
| --- | ---: | ---: |
| J1 | -2.094 | +2.094 |
| J2 | 0 | +3.142 |
| J3 | -3.142 | 0 |
| J4 | -1.309 | +1.309 |
| J5 | -1.484 | +1.484 |
| J6 | -2.007 | +2.007 |

来源：[A1Z_G1Z.urdf](https://github.com/userguide-galaxea/GALAXEA-A1Z/blob/e931ecd0e25ad35df251097ba42921b3d2fa7224/a1z/robot_models/a1z/A1Z_G1Z.urdf)

### 仿真前必须补齐的模型缺口

- SDK 提交只包含两个 URDF，没有提交它们引用的 STL；`package://A1Z_G1Z/meshes/...` 因而无法从 SDK 仓库单独解析。独立官方 `URDF` 仓库可补齐厂家显示网格，但仍不能把同一高面数 STL 直接视为已经审计的碰撞模型。[SDK 模型目录](https://github.com/userguide-galaxea/GALAXEA-A1Z/tree/e931ecd0e25ad35df251097ba42921b3d2fa7224/a1z/robot_models/a1z)；[官方完整 A1Z/G1Z 目录](https://github.com/userguide-galaxea/URDF/tree/galaxea/main/A1Z/A1Z_G1Z)
- `A1Z_G1Z.urdf` 把左右夹指都定义成 `fixed`，没有传动、mimic、行程或真实 G1Z 电机位置到指尖间距的映射。因此它只表达一个固定夹具质量/几何姿态，不能用于验证 20% 开度或夹持力。[G1Z 夹指定义](https://github.com/userguide-galaxea/GALAXEA-A1Z/blob/e931ecd0e25ad35df251097ba42921b3d2fa7224/a1z/robot_models/a1z/A1Z_G1Z.urdf#L396-L497)
- 同一 STL 同时被用作 visual 和 collision；即使取得原始网格，也应另建低面数、凸分解或胶囊/盒体碰撞几何，避免三角网格接触过慢或不稳定。
- 需要确认末端任务 frame。当前 SDK 未指定名称时使用 Pinocchio 的最后一个 frame；含固定夹指的 URDF 中，“最后一个 frame”未必等于希望控制的法兰中心或两指中点。仿真模型应显式新增 `tool_center_point`（TCP）frame。

### 推荐的模型验收标准

在选定任何仿真器前先产出一个与仿真器无关的 `model_manifest`：

- 6 个主动关节的名称、顺序、轴、零位、符号和限位与 SDK 完全一致；
- 法兰与 TCP 的固定变换有实测或厂家依据；
- 夹爪电机位置、归一化开度、左右指位移和指尖间距的映射有实测表；
- 每个 link 同时有 visual 与简化 collision 几何；
- 在 10–20 个限位内姿态上，Pinocchio、MuJoCo（以及以后可能加入的 Drake）FK 的 TCP 平移误差和旋转误差均有自动对比；
- 重力矩方向与量级交叉检查，但仿真参数在系统辨识前只作为近似模型。

## 2. macOS Apple Silicon 上的候选技术栈

| 技术 | macOS Apple Silicon 状态 | A1Z 模型/IK/动力学能力 | 适合本项目的角色 | 主要限制 |
| --- | --- | --- | --- | --- |
| **Pinocchio** | 官方支持 macOS；官方提供 Homebrew、Conda，当前下载页也列出 Linux/macOS 的 PyPI `pin` | URDF/MJCF/SDF；FK/Jacobian；RNEA、CRBA、ABA；SDK 已有阻尼最小二乘 IK | **运动学与逆动力学真值；第一阶段必选** | 本身不是接触丰富的场景仿真器；简单 DLS IK 不自动保证全臂避碰 |
| **MuJoCo** | 官方提供 macOS universal/arm64 预编译库和 `pip install mujoco` | URDF/MJCF；前向/逆动力学、Jacobian、关节限位、接触、传感器、Python API | **本机物理数字孪生；第一阶段必选** | URDF 导入后仍需补 actuator、sensor、contact 等 MJCF 配置；没有与 Drake 同等级的一站式约束 IK |
| **Drake** | 2026-07-23 官方支持 macOS 15/26 arm64，但只覆盖列出的较新 Python/安装组合 | `MultibodyPlant`、优化式 IK、位置/姿态/距离约束、碰撞约束、differential IK、动力学仿真 | **第二阶段约束/碰撞感知 IK 基准** | 依赖较重；应隔离环境；现有 A1Z 环境的 Python 版本未必落在其支持矩阵 |
| **PyBullet** | Bullet 官方声明在 Mac OSX 测试，推荐 pip 安装；未明确承诺当前 Apple Silicon wheel 矩阵 | URDF/SDF/MJCF；内置 IK、逆动力学、碰撞、射线、前向仿真 | 快速冒烟、简易视觉场景和算法对照 | 官方快速指南/平台矩阵较旧；不作为最终模型一致性或接触精度基准 |
| **Isaac Sim 6.0** | **主程序不支持本机 macOS**；macOS aarch64 只有 WebRTC 客户端 | 高保真 RTX 传感器、USD/URDF 导入、ROS 2、合成数据与大规模并行 | 有远端 RTX 主机后的高级视觉/合成数据平台 | 本地 Mac 无法运行；最低规格高，容器仅支持 Linux |

### Pinocchio

Pinocchio 官方文档说明它支持并测试 Windows、Mac OS X、Unix 和 Linux，并支持 URDF、SDF、MJCF；核心包括 FK/Jacobian、RNEA 逆动力学、CRBA 惯量矩阵和 ABA 前向动力学。[Pinocchio 官方仓库](https://github.com/stack-of-tasks/pinocchio)；[动力学算法](https://docs.ros.org/en/ros2_packages/rolling/api/pinocchio/doc/a-features/g-dynamic.html)

官方安装页给出 macOS Homebrew、Conda、源码构建，并在当前页面列出 Linux/macOS 的 PyPI 安装；但官方仓库首页仍写着 PyPI “currently only available on Linux”，两处表述不一致。因此新环境应优先使用 Conda/Homebrew，或先核对目标 Python/arm64 wheel，不把 `pip` 可用性当成无条件承诺。[Pinocchio installation](https://stack-of-tasks.github.io/pinocchio/download.html)

官方给出的阻尼伪逆 CLIK 示例与 A1Z SDK 的实现路线一致，但该示例本身也强调奇异点阻尼和迭代上限。[Pinocchio inverse kinematics 示例](https://docs.ros.org/en/jazzy/p/pinocchio/doc/b-examples/d-inverse-kinematics.html)

**判断：** 不另写一套 A1Z 几何解析 IK。先围绕现有 `Kinematics` 增加显式 TCP、连续性代价、多初值、可达性返回值、距限位 margin 和碰撞后验；需要严格碰撞约束时再接 Drake 或独立优化器。

### MuJoCo

MuJoCo 官方提供 Windows、Linux、macOS 的 x86_64/arm64 预编译库，macOS 发行物为 universal；Python ≥3.10 可直接安装官方绑定。[MuJoCo 官方仓库与安装](https://github.com/google-deepmind/mujoco)；[MuJoCo Programming Guide](https://mujoco.readthedocs.io/en/stable/programming/)

MuJoCo 可载入 URDF，但其原生 MJCF 能表达更完整的 actuator、传感器、接触、joint limit 和 force limit。引擎同时计算连续时间前向/逆动力学，并对软约束接触给出逆动力学。[MuJoCo 概览](https://mujoco.readthedocs.io/en/stable/overview.html)；[动力学计算](https://mujoco.readthedocs.io/en/stable/computation/index.html)；[MJCF/XML 参考](https://mujoco.readthedocs.io/en/stable/XMLreference.html)

**判断：** 先把 A1Z URDF 导入为运动学骨架，再维护一个项目内 MJCF overlay：补执行器、TCP site、相机、关节/力矩约束、低面数碰撞体、夹爪联动和接触传感。人体不要一开始做完整软体，先用关键点驱动的 capsule kinematic body 表示躯干和手臂，可重复验证最小距离和“戳”的接触力。

### Drake

Drake 当前支持表列出 macOS Sequoia 15 与 Tahoe 26 的 arm64 构建，并明确说明“正式支持”意味着有 CI 回归覆盖；具体 Python 版本随发行版变化，必须按安装页实时核对。[Drake Installation](https://drake.mit.edu/installation.html)

Drake `InverseKinematics` 默认可带 joint limits，并能添加位置/方向/几何距离等约束；新的 differential IK system 可同时施加 Cartesian 位置/速度、关节速度和碰撞约束。[Drake InverseKinematics](https://drake.mit.edu/doxygen_cxx/classdrake_1_1multibody_1_1_inverse_kinematics.html)；[Drake DifferentialInverseKinematicsSystem](https://drake.mit.edu/doxygen_cxx/classdrake_1_1multibody_1_1_differential_inverse_kinematics_system.html)

**判断：** 当“跟随人体方向”从简单目标点升级为同时满足全臂避碰、速度界、关节居中和多个 Cartesian 约束时引入。不要为了第一帧可视化就承担其环境和模型转换成本。

### PyBullet

官方快速指南称 PyBullet 能加载 URDF/SDF/MJCF，并提供前向动力学、逆动力学、FK/IK、碰撞和射线查询；Bullet 官方仓库声明 C++ SDK 在 Windows、Linux、Mac OSX 等平台测试。[PyBullet Quickstart Guide](https://github.com/bulletphysics/bullet3/blob/master/docs/pybullet_quickstart_guide/PyBulletQuickstartGuide.md.html)；[Bullet 官方仓库](https://github.com/bulletphysics/bullet3)

**判断：** 若只想很快确认关节顺序、URDF 尺度或做无头 CI 冒烟，它很方便；主线已经有 Pinocchio，物理主线又有 Apple Silicon 支持更明确的 MuJoCo，因此不应同时维护三套同功能模型。

### Isaac Sim

Isaac Sim 6.0 系统要求只列 Ubuntu 22.04/24.04 与 Windows 11 的 x86_64 RTX 系统；aarch64 主程序目前只支持 NVIDIA DGX Spark，容器也仅支持 Linux。[Isaac Sim Requirements](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/requirements.html)

NVIDIA 的下载页虽列出 macOS x86_64/aarch64，但这些条目明确属于 **Isaac Sim WebRTC Streaming Client**，不是 Isaac Sim 主程序；官方 FAQ 说明该客户端连接运行在 RTX 工作站上的无头实例。[Isaac Sim Downloads](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/download.html)；[Isaac Sim Setup Tips](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_faq.html)

**判断：** 本机不下载 Isaac Sim 主程序。未来如需 RTX 相机、域随机化和合成数据，准备 Linux/Windows RTX 服务器，在 Mac 上用浏览器或 WebRTC 客户端访问；机器人模型需另做 URDF→USD 导入和 articulation/drive 校准。

## 3. 摄像头人体姿态到机器人跟随的仿真架构

```text
camera frame + timestamp
        │
        ▼
pose backend adapter
(OpenPose / MediaPipe / later model)
        │ 2D keypoints + confidence
        ▼
association, confidence gate, temporal filter
        │
        ▼
metric 3D reconstruction
(RGB-D / stereo or multiview triangulation / validated monocular estimate)
        │ skeleton in camera frame
        ▼
calibrated transform T_base_camera
        │ skeleton in A1Z base frame
        ▼
intent mapper
(person direction, shoulder/hand target, standoff, interaction state)
        │ desired TCP pose/velocity
        ▼
safety governor
(workspace, keep-out capsules, confidence timeout, speed/accel/jerk, limits)
        │
        ▼
IK + collision validation
(Pinocchio first; Drake constrained IK later)
        │ joint trajectory
        ▼
MuJoCo-only controller and contact simulation
        │
        ├── logs: keypoints, transforms, target, q/qd/tau, min distance, contact
        └── pass/fail gate; no direct hardware forwarding
```

### 3.1 姿态检测后端

OpenPose 官方支持身体、手、脸和足部 2D 关键点；其 3D 功能是**多视角三角化**，官方模块只支持 1 人，且要求相机内外参。[OpenPose 官方仓库](https://github.com/CMU-Perceptual-Computing-Lab/openpose)；[OpenPose 3D reconstruction](https://cmu-perceptual-computing-lab.github.io/openpose/web/html/doc/md_doc_advanced_3d_reconstruction_module.html)

OpenPose 的 macOS 文档允许 `CPU_ONLY` 或 OpenCL；OpenCL 测试记录针对 AMD Vega/NVIDIA 10 系列，并没有承诺 Apple Silicon GPU。CPU 模式更容易安装但更慢。[OpenPose 安装说明](https://github.com/CMU-Perceptual-Computing-Lab/openpose/blob/master/doc/installation/0_index.md)；[OpenPose OpenCL 设置](https://cmu-perceptual-computing-lab.github.io/openpose/web/html/doc/md_doc_installation_2_additional_settings.html)

MediaPipe Pose Landmarker 的实时 API接受带单调时间戳的视频帧，异步模式为降低延迟可能丢帧；结果同时包含图像归一化关键点和 world landmarks。[MediaPipe PoseLandmarker Python API](https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/PoseLandmarker)；[PoseLandmarkerResult](https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/PoseLandmarkerResult)

**建议：** 定义统一 `PoseObservation`，至少包含 `timestamp_ns`、`person_id`、`landmark_name`、`position`、`coordinate_frame`、`confidence/visibility`。首个 Apple Silicon 原型优先验证 MediaPipe 的实际延迟；OpenPose 作为第二后端，不让后续坐标变换、意图映射与仿真依赖任何特定关键点编号。

### 3.2 从 2D 到机器人可用的米制 3D

最稳妥的优先级：

1. **RGB-D：** 用深度把高置信度 2D 关键点反投影到相机坐标；对关键点邻域做深度中值/离群过滤。
2. **同步双目或多视角：** 标定内外参后进行三角化。OpenPose 官方 3D 模块就是这一方案，并明确把错误 3D 的主要原因归为糟糕标定。[OpenPose calibration](https://cmu-perceptual-computing-lab.github.io/openpose/web/html/doc/md_doc_advanced_calibration_module.html)；[OpenPose 3D FAQ](https://cmu-perceptual-computing-lab.github.io/openpose/web/html/doc/md_doc_05_faq.html)
3. **单目估计：** 只用于方向/姿态原型；不能未经验证就把网络给出的相对人体坐标当成机器人基座中的绝对位置。

即使后端输出单位标为米的 world landmarks，也必须记录其坐标原点与轴定义，并通过已知距离/标定物验证尺度。它不是 `T_base_camera` 的替代品。[MediaPipe Landmark 坐标定义](https://developers.google.com/edge/api/mediapipe/js/tasks-vision.landmark)

### 3.3 相机到 A1Z 基座的外参

固定外置相机需要估计 `T_base_camera`。实践上可在工作区放置与机器人基座关系已知的标定板，求相机到标定板位姿，再组成到 base 的变换；眼在手上则做 hand-eye calibration。OpenCV 官方 `calibrateHandEye` 和 `calibrateRobotWorldHandEye` 定义了所需的机器人 base↔gripper 与 target↔camera 多姿态测量。[OpenCV camera/hand-eye calibration](https://docs.opencv.org/master/d9/d0c/group__calib3d.html)

每个观测必须显式使用坐标链：

```text
p_base = T_base_camera · p_camera
```

并在日志中保存所用外参版本、相机序列号、分辨率和时间戳。不能只靠“画面右边”等屏幕方向生成 J1 正负方向。

### 3.4 从人体方向到机器人目标

先把交互拆成可测试的有限状态，而不是“检测到人就连续追踪”：

1. `NO_PERSON`：没有稳定目标，机器人保持仿真安全姿态。
2. `ACQUIRE`：同一人和关键点连续高置信度若干帧后锁定。
3. `FOLLOW_DIRECTION`：用肩中点、胸口或手腕构造平滑目标；保持固定 standoff。
4. `APPROACH`：只移动到人体 capsule 外的预接触 waypoint。
5. `CONTACT_TEST_SIM`：只在 MuJoCo 中继续到接触，记录法向力、接触位置和最大关节力矩。
6. `LOST/RETREAT`：置信度、时间戳、最小距离或 IK 任一失效，回到仿真退避点。

“人的方向”需要先定义语义：

- 身体朝向：左右肩向量与躯干法向；
- 手指方向：手腕到指尖（需手部关键点）；
- 指向目标：肩→肘→腕的射线；
- 机器人跟随位置：胸口/手腕的低通后位置；
- 操作姿态：TCP 的接近轴和滚转角，不能只由一个点决定。

不同语义必须输出不同的 `TargetIntent`，避免一个含糊的三维点同时承担位置、方向和接触意图。

### 3.5 安全和验证门

仿真控制器至少执行：

- 人体关键点置信度下限、连续帧确认、超时即冻结/退避；
- 目标工作空间、关节位置/速度/加速度/jerk 限制；
- 每步 IK 从当前 `q` warm start，拒绝未收敛解；
- 对全轨迹而非仅终点检查 joint margin、自碰撞、桌面/基座/人体 keep-out；
- 限制每周期 Cartesian 与 joint 增量；
- 人体用 capsule/球体膨胀安全 margin，预接触与允许接触部位分离；
- 仿真接触力、最大穿透、关节力矩与求解器异常阈值；
- 原始观测、滤波结果、所有坐标变换、IK 状态和仿真结果可回放。

MuJoCo 的 joint limit、actuator force clamp 和 contact sensor 可作为仿真观测，但不能替代应用层安全状态机。[MuJoCo XML reference](https://mujoco.readthedocs.io/en/stable/XMLreference.html)

## 4. 推荐实施顺序

### 阶段 A：模型与解算基线

1. 冻结 A1Z SDK 提交和 `A1Z_G1Z.urdf` 哈希。
2. 显式定义关节顺序、base frame、法兰 frame、TCP 和夹爪开度映射。
3. 在没有 STL 时先用尺寸可核对的 primitive collision proxy；不得把代理几何冒充厂家 CAD。
4. 用现有 Pinocchio FK/IK 做纯离线 golden tests：随机限位内 `q → FK → IK`、奇异/不可达目标、限位 margin。
5. 建 MuJoCo 模型与单元测试，交叉比较 FK、重力方向、自由落体/保持、关节限位和接触。

### 阶段 B：视觉与坐标

1. 实现后端无关的 pose observation schema。
2. 先录制视频离线回放，不接实时机器人。
3. 选定 RGB-D 或多相机米制 3D 路径；完成相机内参和 `T_base_camera` 标定。
4. 将人体关键点在 MuJoCo 中显示为 capsule skeleton，验证轴方向、尺度、延迟、丢帧与遮挡。

### 阶段 C：跟随与交互仿真

1. 先只跟随胸口/肩中点，固定 TCP 姿态和 standoff。
2. 加入腕/指向方向与有限状态机。
3. 对所有动作进行 constrained trajectory 和 swept collision 检查。
4. 最后才模拟“戳”：使用低速、预接触 waypoint、允许接触区域和仿真力阈值。

### 阶段 D：高级栈

- 需要多约束 differential IK 时，在隔离环境中加入 Drake 做对照。
- 需要照片级相机、合成数据、域随机化或大规模训练时，部署远端 RTX Isaac Sim；Mac 仅作客户端和开发机。
- PyBullet 只在需要快速独立冒烟或外部项目兼容时加入，避免长期三引擎模型漂移。

## 5. 建议的仓库产物

后续实现可按以下边界组织，保持与真实硬件传输解耦：

```text
sim/
  models/a1z/             # 经审计的 URDF/MJCF、代理碰撞体、manifest
  tests/                  # FK/IK/限位/接触/跨引擎一致性
  mujoco/                 # 场景与控制器
perception/
  pose_backends/          # openpose.py, mediapipe.py
  calibration/            # intrinsics, T_base_camera（带版本元数据）
  tracking/               # association/filter/timeout
planning/
  intent/                 # 人体方向到 TargetIntent
  safety/                 # workspace/limits/collision/rate gates
  ik/                     # Pinocchio baseline；可选 Drake adapter
replay/
  schemas/                # 时间戳观测与仿真日志
  scenarios/              # 遮挡、丢帧、越界、接触等固定回放
```

硬件线程未来只应接收经过版本化 schema 表达的、已离线验证的轨迹；本仿真线程不导入 CAN/串口传输模块。

## 最终选型

**立即主线：Pinocchio（复用 A1Z SDK） + MuJoCo（Apple Silicon 本地物理仿真） + 后端无关视觉接口。**

**视觉首个本机验证：MediaPipe Pose；OpenPose 保留为指定兼容后端，3D 必须配 RGB-D 或标定多视角。**

**按需加入：Drake 用于碰撞/约束 differential IK。**

**暂不本机采用：Isaac Sim；只有远端 RTX 资源到位后启用。**

**仅作快速对照：PyBullet。**
