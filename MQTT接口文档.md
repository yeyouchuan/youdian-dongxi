# 智能坐垫 MQTT 接口文档

> 面向队友：如何订阅坐垫的实时姿态/体征数据，自己写页面或服务来消费。
> 更新：2026-07-24（AdventureX 会场）

## 总览

```
坐垫 FSR×5 ── ESP32-S3 ──┐
                          ├─ WiFi(ADVX-Players) ─→ MQTT Broker ─→ 你的程序/页面
椅背雷达 ─── XIAO C6 ────┘                        (Mac 上的 amqtt)
```

## 连接参数

| 项 | 值 |
|---|---|
| Broker 地址 | `10.76.7.182`（Mac 的会场 WiFi IP，**IP 变了要同步改**） |
| TCP 端口 | `1883`（后端程序 / Python / 硬件用） |
| WebSocket 端口 | `9001`（浏览器和 App 使用，`ws://10.76.7.182:9001`） |
| 认证 | 无（匿名允许，仅限会场局域网） |
| 现成仪表盘 | `http://10.76.7.182:8000/dashboard.html`（同 WiFi 手机直接开） |

## 主题一：`zuodian/posture`（坐姿，FSR）

**频率**：每 500ms 一条
**Payload**（JSON）：

```json
{"s1":208, "s3":85, "s4":175, "s5":127, "s6":0, "pose":"UPRIGHT"}
```

| 字段 | 含义 | 范围 |
|---|---|---|
| `s1` | 左坐骨压力 | 0~4095（ADC 原始值，空载≈0，坐着典型 100~600） |
| `s4` | 右坐骨压力 | 同上 |
| `s5` | 左大腿压力 | 同上 |
| `s6` | 右大腿压力 | 同上 |
| `s3` | 前缘压力 | 同上 |
| `pose` | 姿态判定（端侧已算好，带 1 秒防抖） | 见下表 |

**pose 枚举**：

| 值 | 含义 | 可信度 |
|---|---|---|
| `AWAY` | 离座 | 高（加热断电就订这个） |
| `UPRIGHT` | 正坐 | 高 |
| `LEAN_L` | 左歪坐 | 高 |
| `LEAN_R` | 右歪坐 | 高 |
| `EDGE` | 坐前缘（坐骨承重、腿悬空） | 高 |
| `OTHER` | 其他坐姿（前倾/后仰/翘腿等，暂不细分） | 兜底类 |

**使用建议**：
- 做久坐提醒：`pose != "AWAY"` 累计时长，`AWAY` 清零（仪表盘已内置示例）
- 做安全联动（加热）：**收到 `AWAY` 立即断电**，这是安全红线
- 想自己算姿态：用 s1~s6 原始值，但注意 FSR 有蠕变，**用相对比例别用绝对值**

## 主题二：`zuodian/radar`（体征，毫米波雷达）

**频率**：有新帧时每 1s 一条；没有新帧时每 5s 发送一次 `seq` 不变的保活
**Payload**（JSON）：

```json
{"heart":97.0,"heart_med":110.0,"breath":16.0,"breath_med":17.0,"dist":68.9,"seq":88}
```

| 字段 | 含义 | 注意 |
|---|---|---|
| `heart` | 心率瞬时值 | 仅供诊断，不进入观众界面或健康模型 |
| `heart_med` | 60 秒心率滑动中值 | App 展示值，有效范围 40–150 |
| `breath` | 呼吸瞬时值 | 仅供诊断，不进入观众界面或健康模型 |
| `breath_med` | 60 秒呼吸滑动中值 | App 展示值，有效范围 6–30 |
| `seq` | 雷达端新帧序号 | 相同值表示缓存保活；不替代 App 事件序号 |
| `dist` | 人体距雷达距离（cm） | 60–120 cm 为展会推荐距离，仅用于诊断和摆位 |

`heart_med` 与 `breath_med` 必须分别校验。一个字段无效时只丢弃该字段，不能丢掉
同包中另一个有效字段。App 不得在中值无效时回退到瞬时值。

## App 接收语义

- App 使用 MQTT 3.1.1、QoS 0、匿名连接、`clean=true`，订阅两个主题成功后才显示“已连接”。
- 默认 Broker 为 `ws://10.76.7.182:9001`。IP 变化时可在 App“设置 → 智能坐垫连接”修改；保存后，活动会话会自动重连。
- 未加密的 `ws://` 只允许私有 IP、`localhost` 或 `.local` 主机；公网 Broker 必须使用 `wss://`。
- MQTT 消息没有设备时间戳。App 的 `capturedAt` 是手机收到消息的时间，不代表传感器实际采样时刻。
- 每次主动连接生成新的 `sessionId`；心率、呼吸率和姿态各自使用 App 本地递增序号。设备端 `seq` 只判断新帧：相同 `seq` 不刷新健康值或 `capturedAt`，变小按雷达重启后的新帧处理。
- App 只在前台采集。进入后台会保存当前姿态片段并断开；用户没有主动结束会话时，回到前台会创建新会话并重连。
- 原始 ADC、心率和呼吸事件只保留在十分钟内存窗口，不写日志。数据库只保存姿态片段和既有汇总。
- 姿态超过 2 秒、心率或呼吸率超过 15 秒没有新 `seq` 时，界面保留最后值并标记“已中断”。
- 五路 ADC 必须都是 0–4095 的有限整数；若五路同时接近 4095，整条姿态消息按线材或接地故障丢弃。

## 订阅示例

**浏览器（WebSocket）**：

```html
<script src="mqtt.min.js"></script>  <!-- 本地文件在 ~/zuodian/radar/，别依赖 CDN -->
<script>
const client = mqtt.connect('ws://10.76.7.182:9001');
client.on('connect', () => {
  client.subscribe('zuodian/posture');
  client.subscribe('zuodian/radar');
});
client.on('message', (topic, msg) => {
  const d = JSON.parse(msg.toString());
  if (topic === 'zuodian/posture') console.log(d.pose, d.s1, d.s4);
  else console.log(d.heart_med, d.breath_med, d.dist, d.seq);
});
</script>
```

**Python（paho-mqtt）**：

```python
import json
import paho.mqtt.client as mqtt

c = mqtt.Client()
c.on_message = lambda cl, u, m: print(m.topic, json.loads(m.payload))
c.connect("10.76.7.182", 1883)
c.subscribe([("zuodian/posture", 0), ("zuodian/radar", 0)])
c.loop_forever()
```

**命令行快速看数据（Mac 装了 mosquitto 的话）**：

```bash
mosquitto_sub -h 10.76.7.182 -t 'zuodian/#' -v
```

## 基础设施位置（谁负责重启）

| 组件 | 位置 | 启动方式 |
|---|---|---|
| MQTT Broker | Amber 的 Mac | `cd ~/zuodian/radar && uvx --from amqtt amqtt -c broker.yaml` |
| HTTP 服务(仪表盘) | 同上 | `cd ~/zuodian/radar && python3 -m http.server 8000` |
| 姿态固件源码 | `~/zuodian/firmware/fsr_posture_mqtt/` | arduino-cli 烧录 ESP32-S3 |
| 雷达固件源码 | `~/Documents/Arduino/radar_mqtt/` | 烧录 XIAO ESP32-C6 |

## 已知坑

1. **Mac 的 IP 变了全断**：固件里 `MQTT_HOST` 是写死的，会场 WiFi 重连后先 `ipconfig getifaddr en0` 核对，变了要改固件重烧 + 通知所有订阅方
2. ESP32-S3 板子姿态/音频调试共用，**烧录互相覆盖**，动板子前群里说一声
3. 串口 `/dev/cu.usbserial-110` 同时只能一个程序占用
4. 坐垫线材怕拉扯（后仰扯松过 GND，全通道会读 4095）——App 会丢弃全通道饱和数据，现场仍应立即查线
5. 姿态阈值基于两人标定，换人 demo 时 `UPRIGHT/AWAY/EDGE` 最稳，`OTHER` 出现偏多属正常
