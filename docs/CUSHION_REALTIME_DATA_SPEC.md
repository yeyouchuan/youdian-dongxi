# 坐垫实时数据接口规范

## 边界

应用领域层不绑定 BLE、Wi‑Fi 或串口。传输适配器只负责连接、解析和单位转换，
随后调用 `HealthDataService.cushionRealtime.ingest` 或 `ingestBatch`。

- 心率：BPM，允许范围 30–240
- 呼吸率：`breathsPerMinute`，允许范围 4–60
- MQTT 姿态：`away | upright | leanLeft | leanRight | edge | other`
- FSR 原始值：`fsr5-v1` 布局的五个 0–4095 整数 ADC 值
- 未来校准压力：标准坐标 0–1、力值牛顿且不小于 0
- 质量：0–1；省略时由连续性、序号丢包和突变推导
- 时间：带时区的 ISO 8601
- 去重键：`deviceId + sessionId + type + streamSequence`

同一流允许 2 秒乱序，超过窗口的旧事件丢弃。心率和呼吸率 15 秒、
姿态或压力 2 秒没有更新后，界面保留最后值但标记为“已中断”。

## MQTT 传输

当前硬件通过 MQTT WebSocket 连接。默认地址为 `ws://10.76.7.182:9001`，
连接参数为 MQTT 3.1.1、QoS 0、`clean=true`、5 秒连接超时、2 秒重连间隔和
30 秒 keepalive。只有 `zuodian/radar` 与 `zuodian/posture` 均订阅成功后，
连接状态才变为 `connected`。

每次主动连接生成新的 `sessionId`，每种事件类型使用 App 本地递增序号。硬件
消息没有可信时间戳，`capturedAt` 使用手机收到消息的时刻。因此该字段描述接收
时间，而不是设备采样时间。

App 只在前台采集。进入后台、断开或卸载时刷新当前姿态片段并关闭连接；回到前台
时，仅在用户此前没有主动结束会话的情况下新建会话并重连。连接缺口不推算或补齐。

Broker URL 允许任意 `wss://` 地址；未加密的 `ws://` 仅允许私有 IP、
`localhost` 或 `.local` 主机。

## MQTT 映射与无效值

`zuodian/radar` 使用 `heart_med`（40–150）和 `breath_med`（6–30）进入实时流，
两者必须独立校验；一个字段无效时，同包中另一个有效字段仍应进入实时流。瞬时值
`heart` 与 `breath` 只保留在内存诊断快照，禁止回退为展示值。

`seq` 必须是非负安全整数。首包或与上次不同的值代表新帧，包括设备重启后序号
变小；相同值代表缓存保活，只更新链路收包时间，不生成事件或刷新 `capturedAt`。
`dist` 是非负有限厘米值，60–120 cm 为展会推荐摆位。`seq`、`dist` 和瞬时值均
不进入数据库。

`zuodian/posture` 映射如下：

| MQTT 字段 | 领域字段 |
| --- | --- |
| `pose: AWAY` | `posture: away` |
| `pose: UPRIGHT` | `posture: upright` |
| `pose: LEAN_L` | `posture: leanLeft` |
| `pose: LEAN_R` | `posture: leanRight` |
| `pose: EDGE` | `posture: edge` |
| `pose: OTHER` | `posture: other` |
| `s1` | `leftIschial.rawAdc` |
| `s4` | `rightIschial.rawAdc` |
| `s5` | `leftThigh.rawAdc` |
| `s6` | `rightThigh.rawAdc` |
| `s3` | `frontEdge.rawAdc` |

五路 ADC 必须是 0–4095 的有限整数。若五路同时接近满量程 4095，整条姿态事件
按线材或接地故障丢弃，错误只记录 `SENSOR_SATURATED` 代码，不记录原始健康值。

## JSONL 示例

开发回放文件每行一个 JSON 对象：

```json
{"schemaVersion":1,"deviceId":"demo-cushion","sessionId":"session-a","streamSequence":1,"capturedAt":"2026-07-24T12:00:00+08:00","type":"heartRate","payload":{"bpm":72}}
{"schemaVersion":1,"deviceId":"demo-cushion","sessionId":"session-a","streamSequence":1,"capturedAt":"2026-07-24T12:00:00+08:00","type":"respiratoryRate","payload":{"breathsPerMinute":14}}
{"schemaVersion":1,"deviceId":"demo-cushion","sessionId":"session-a","streamSequence":1,"capturedAt":"2026-07-24T12:00:00+08:00","type":"posture","payload":{"posture":"upright","layoutId":"fsr5-v1","sensors":[{"sensorId":"leftIschial","rawAdc":208},{"sensorId":"rightIschial","rawAdc":175},{"sensorId":"leftThigh","rawAdc":127},{"sensorId":"rightThigh","rawAdc":0},{"sensorId":"frontEdge","rawAdc":85}]}}
{"schemaVersion":1,"deviceId":"demo-cushion","sessionId":"session-a","streamSequence":1,"capturedAt":"2026-07-24T12:00:00+08:00","type":"pressureFrame","payload":{"layoutId":"2x2-v1","cells":[{"sensorId":"fl","x":0,"y":0,"forceN":105},{"sensorId":"fr","x":1,"y":0,"forceN":103},{"sensorId":"rl","x":0,"y":1,"forceN":118},{"sensorId":"rr","x":1,"y":1,"forceN":116}]}}
```

`streamSequence` 按事件类型独立递增。`posture` 是当前 MQTT 硬件的端侧分类，
原始 ADC 不得冒充牛顿值。`pressureFrame` 保留给未来经过校准、能输出真实力值的
硬件；其阵列不限制单元数量，`layoutId` 标识传感器布局和校准版本。

## 压力校准

压力帧必须先匹配设备的 `PressureCalibration`：

- `emptyBaselineBySensor`：每个传感器空载基线，单位牛顿
- `occupantThresholdN`：判断有人坐下的总力阈值
- `modelVersion`：坐姿分类规则或模型版本

未校准时只返回 `calibrationRequired`，不得输出在座状态或坐姿。校准后应用
计算总力、压力中心、前后左右比例和四象限派生特征。旧的固定四象限日报通过
兼容转换器读取，不约束新硬件布局。本节仅适用于 `pressureFrame`，不适用于当前
由硬件直接给出 `pose` 的 `posture` 流。

## 姿态片段与日报

姿态变化时立即保存刚结束的片段并开始新片段；姿态不变时至少每分钟更新一次。
日报的在座时长包括除 `away` 外的全部姿态，正坐比例按实际记录的在座时段计算，
并展示 `nonUprightMinutes` 与 `observedMinutes`。历史 JSON 中的
`legsCrossed` 读取时兼容映射为 `other`。

当前评分只考虑连续久坐与起身次数。非正坐时长会出现在评分明细中，但暂不扣分。
日报和趋势必须明确说明“仅统计 App 前台连接并实际记录到的时段”，不能将结果
表述为全天覆盖。

## HRV 与隐私

BPM 和呼吸率不能用于计算 HRV。恢复状态只使用 Apple Health 的 SDNN，并要求
5 分钟有效坐垫实时会话。未来硬件只有提供逐搏 IBI/RR 且经过设备验证后，才可
新增独立的设备 HRV 类型。

原始 ADC、BPM 与呼吸事件只保留在十分钟内存窗口，应用重启即清除。数据库仅
保存姿态片段、5 分钟汇总、恢复评估和压力派生特征；不上传、不写入 iCloud，
也不把原始健康值写入日志。
