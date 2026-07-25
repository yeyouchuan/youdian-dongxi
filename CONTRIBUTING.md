# 贡献指南

感谢参与有垫东西。这个仓库同时包含健康数据与真实机器人代码，因此功能正确之外，
还需要守住隐私和硬件安全边界。

## 开发环境

- App：Node.js 22.13+，使用 `npm ci`
- Python 服务：Python 3.10+，推荐使用 `uv`
- A1Z macOS 工具：按 `hardware/robot-arm/README.md` 使用 Python 3.12

提交前至少运行与你改动相关的检查：

```bash
npm run typecheck
npm run lint

cd hardware/robot-arm/cushion-reminder-service
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
```

修改 A1Z 控制、映射或安全 daemon 时，还要运行相应的离线测试和 audit mode。
没有现场操作员、清空的工作区和急停准备时，不得用真机验证 PR。

## Pull Request

PR 请说明：

- 解决的问题和用户影响
- 修改涉及 App、协议、服务还是机器人层
- 已运行的检查
- 健康隐私或硬件安全影响
- UI 修改的截图，或协议修改的示例 payload

协议字段变化必须同步更新 `docs/MQTT_PROTOCOL.md`、
`docs/CUSHION_REALTIME_DATA_SPEC.md` 和消费端测试。

## 不应提交

- Apple/EAS token、签名证书、provisioning profile
- OpenAI、Hugging Face、MQTT 或其他服务密钥
- 真实 HealthKit 导出、SQLCipher 数据库和个人健康值
- 模型 checkpoint、虚拟环境、SDK vendor checkout 和构建产物
- 含真人面部或可识别信息的相机帧
- 未经限位和离线测试验证的真机动作脚本

发现安全或隐私问题时，请不要在公开 issue 中附带凭据、健康数据或可直接执行的
危险动作序列；先联系维护者进行最小化复现。
