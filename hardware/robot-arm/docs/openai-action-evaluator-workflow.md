# OpenAI 动作验收与纠偏闭环

更新日期：2026-07-25

状态：代码已接入 `ssh-mark` 双视角路径并通过单元/集成测试。Mac 相机已移除；
Mark 笔记本相机是固定外部视角，DaBai 是夹爪随动视角。API key 只从仓库外的
0600 runtime env 注入。外参与内参未标定前，GPT actuator correction 保持关闭。

## 目标与边界

DGX 上的 G0.5 继续负责生成 SO101 action chunk，Mark 上的现有 client 和 safe daemon 继续负责确定性安全执行。OpenAI evaluator 只在一个动作阶段完成、机械臂停止并取得新观测后回答：

1. 机械臂是否移动到当前子任务需要的位置；
2. 是否对准并夹起了正确物体；
3. 证据不足、失败或部分成功时，下一次 G0.5 子任务应如何修改。

OpenAI 不进入 15/50 Hz 控制环，不直接输出关节角、夹爪数值、CAN frame 或 shell command。所有 evaluator 输出必须先通过结构化 schema、允许列表、重试预算和现有 safety checks。

直接纠偏 fallback 只接受结构化 `CorrectionPlan`：

1. 初始 G0.5 动作前，GPT 必须确认同一个目标和夹爪两指在
   `exterior_right/wrist` 两路均可见，且运动区无人；
2. 这一步只返回无动作的 `SceneAssessment`，并从
   `left_hand_model/center_hand_model/right_hand_model/small_card` 中固定一个目标；
   选定目标的稳定 ID 和描述会进入 G0.5、evaluator 及后续纠偏，任何换目标计划都
   fail closed；
3. G0.5 返回失败或无进展后，GPT 最多提出四个候选工具步；
4. workflow 每次只执行第一个 `move_tool_delta` 或 `set_gripper`，其余候选步骤视为
   已过期并丢弃；
5. 每个物理步骤完成后重新取得两路帧，再由 GPT 评价并重新规划；
6. `move_tool_delta` 每轴 ≤20 mm、向量 ≤30 mm、速度 ≤0.1，daemon 还会检查 IK
   关节变化、TCP 实测方向/误差和 J4 漂移；
7. 两路相机内参、Mark external 的 base-frame 外参、腕部
   `arm_link6_from_camera` 安装外参、显式 enable flag 或 OpenAI key 任一缺失时，
   完整 manipulation workflow 不会创建；腕部 `base_from_camera` 会用每次动作前
   读取的 `base_from_tool` 动态合成，不能填写静态 identity 占位。

## 闭环

```text
RobotIntent
    ▼
PRECHECK
    ▼
OBSERVE_BEFORE ── exterior + wrist + joints + gripper
    ▼
SELECT_SUBTASK
    ▼
G0.5_ACTION_CHUNK (DGX)
    ▼
EXECUTE (Mark safety client + 50 Hz daemon)
    ▼
SETTLE_AND_OBSERVE_AFTER
    ▼
OPENAI_EVALUATE
    ├── SUCCESS ───────────────> result + optional deterministic return-neutral
    ├── RETRY + safe feedback ─> SELECT_SUBTASK
    ├── INSUFFICIENT_EVIDENCE ─> reobserve once, then abort
    └── ABORT ─────────────────> hold + result
```

多步抓取应显式拆成：

```text
approach -> align -> grasp -> verify grasp -> lift -> verify lift -> return
```

不要把“识别、接近、闭合、抬升、回位”全部塞进一个开放式 64-step prompt 后，只按进程退出码判断成功。

## Evaluator 输入

每次评价保存一个 `EvaluationBundle`：

- 原始目标、当前子任务、iteration、prompt catalog version；
- action chunk 摘要和实际执行 step 数；
- 执行前/后的 A1Z 六轴位置、夹爪位置和安全事件；
- exterior 执行前/后各 2–3 帧；
- wrist_right 执行前/后各 2–3 帧；
- 每帧采集时间、帧龄、相机序列号和方向修正信息；
- 目标物体文本描述或固定测试物体 ID；
- 上一次 evaluator verdict 和反馈。

评价发生在动作块边界，而不是每个 motor tick。动作结束后先等待约 `0.5–1.0 s`，再取一个短 burst，降低模糊帧或单帧遮挡造成的误判。

当前只有腕部相机时，系统不能可靠证明“物体已经被夹住并抬离桌面”：夹爪靠近后目标会离开视野。因此：

- 非接触手势可以在单相机模式下测试；
- 目标识别、抓取和抬升验收必须接入真实 exterior 相机；
- exterior 或 wrist 图像缺失/过期时返回 `INSUFFICIENT_EVIDENCE`，不能把不可见当成成功。

## Structured Output

Evaluator 使用支持图像输入的 Responses API，并以 strict JSON Schema 返回。例如：

```json
{
  "verdict": "retry",
  "position_correct": false,
  "target_correct": true,
  "grasp_confirmed": false,
  "confidence": 0.82,
  "failure_code": "stopped_short",
  "evidence": [
    "The target remains above and ahead of the open gripper in the exterior view",
    "The wrist view does not show the object between both fingertips"
  ],
  "next_subtask": "move_closer_with_gripper_open",
  "feedback": "Move slightly closer to the same target while keeping the gripper open.",
  "requires_new_observation": false
}
```

允许值应被压缩在小型枚举内：

- `verdict`: `success | retry | abort | insufficient_evidence`
- `failure_code`: `wrong_target | stopped_short | overshot | misaligned | gripper_open | object_dropped | occluded | unsafe_scene | no_progress | none`
- `next_subtask`: `reobserve | move_closer_with_gripper_open | realign_left | realign_right | realign_up | realign_down | close_gripper | lift | return_neutral | stop`

`feedback` 只解释允许列表里的修正，不是下一条任意用户 prompt。Workflow 根据 `next_subtask` 选择版本化模板，再把目标和有限反馈填入。例如：

```text
Goal: grasp the lightweight silver test packet.
Previous result: the gripper stopped short; the same target remains centered.
Next safe subtask: move slightly closer with the gripper open, then stop.
Do not move toward or touch any person.
```

任何 schema refusal、解析失败、未知 enum 或 API timeout 都按 `abort` 处理，不继续运动。

## 重试和停止

当前实现预算：

- 每次只执行 16 个 G0.5 action steps，然后强制重新观察；
- 最多 5 次 corrective iteration；
- 最多 7 次 OpenAI evaluation（含一次纯 reobserve）；
- 总 G0.5 action steps 不超过 96；
- workflow wall clock 不超过 90 秒；
- 连续两次没有可见改善时 `no_progress -> abort`；
- `insufficient_evidence` 只允许一次纯 reobserve，不自动移动；
- 同一机器人一次只运行一个 workflow。

以下情况不允许 LLM 自动重试：

- joint limit、stream jump、watchdog、CAN bus-off；
- 温度、电机 error code 或反馈 timeout；
- 相机断开或帧龄超限；
- 人进入清空的测试工作区；
- evaluator 判断 `unsafe_scene`；
- OpenAI API 不可用。

失败时终止 headless action stream，让 safe daemon 保持当前位置。确定性回中立位只有在经过路径/限位验证且当前姿态允许时才执行；不得用自然语言 prompt 恢复精确关节姿态。

## 服务模块

```text
ReminderOrchestrator
    │ RobotIntent
    ▼
ManipulationWorkflow
    ├── ObservationAdapter
    ├── G05PolicyAdapter
    ├── RobotExecutionAdapter
    ├── OpenAIEvaluatorAdapter
    ├── WorkflowStore (SQLite)
    └── PromptCatalog
```

`ManipulationWorkflow.run(intent) -> WorkflowResult` 是深 module：调用者不处理图片
配对、retry、OpenAI schema、G0.5 子任务或恢复逻辑。当前每一次 transition、帧摘要、
prompt、verdict 和 safety event 写入内存 Job log；持久化 WorkflowStore 仍是生产化
待办，服务重启后尚不能恢复未完成 workflow。

当前仓库中的实现文件：

- `cushion-reminder-service/src/cushion_reminder/manipulation_workflow.py`
- `cushion-reminder-service/src/cushion_reminder/openai_evaluator.py`
- `cushion-reminder-service/src/cushion_reminder/actuator_tools.py`
- `cushion-reminder-service/src/cushion_reminder/camera_capture.py`
- `cushion-reminder-service/src/cushion_reminder/vision.py`

`SshMarkObservationAdapter` 在 action boundary：

1. 从 Windows `usbipd list` 动态解析 `0408:30c3` 的 BUSID；
2. 设备缺失时 attach 一次并保持，单拍 `exterior_right`；
3. 按 VID:PID `2bc5:0557` 单拍 DaBai；
4. 用时间戳、方向、来源和 SHA-256 生成双帧 observation。

这个顺序是现场验证后的约束：Windows RGB 与 DaBai 持续并发 streaming 会让 Windows
复合 UVC 设备掉线，而反复 attach/detach 会干扰 CAN 反馈。保持 attached、边界单拍
同时给下一次 G0.5 chunk 和 GPT evaluator 提供新图像。

## 模型与评测策略

模型通过配置选择，不把某个具体 ID 写死在业务代码里。候选模型必须支持：

- 多图像输入；
- Structured Outputs；
- 对小物体位置、夹爪/物体关系和前后变化的可靠判断。

上线前建立固定验证集：

- 正确靠近、停得过早、越过目标、左右/上下偏移；
- 空夹、夹错物体、物体仍在桌面、已成功抬起、抬起后掉落；
- exterior 遮挡、wrist 遮挡、相机反向、陈旧帧；
- 人进入工作区、安全边界和应该 abort 的场景。

每个样本由人工标注 verdict、failure code 和允许的 next subtask。比较不同模型、detail 配置和 prompt 版本的 false-success rate；对于真机，错误地判断“已经安全/已经抓住”比保守 abort 的代价更高。

## 隐私

exterior 相机可能拍到人。只上传完成任务所需的短帧 burst，优先裁剪工作区，不做人脸识别或身份推断；明确告知现场人员，配置短期保留时间，并在 audit log 中保存图像引用和删除状态而不是无限保存原图。

## OpenAI 参考

- [Images and vision](https://developers.openai.com/api/docs/guides/images-vision)：Responses API 的图像输入和 detail 选项；
- [Structured model outputs](https://developers.openai.com/api/docs/guides/structured-outputs)：strict JSON Schema、refusal 和解析合同；
- [Working with evals](https://developers.openai.com/api/docs/guides/evals)：以测试输入、结果分析和迭代改进验证 LLM 应用。
