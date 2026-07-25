# 文档索引

## 产品与系统

- [系统架构](ARCHITECTURE.md)：端到端数据流、组件职责和信任边界
- [MQTT 协议](MQTT_PROTOCOL.md)：会场硬件主题、payload 与订阅示例
- [实时数据领域规范](CUSHION_REALTIME_DATA_SPEC.md)：校验、时序、隐私与持久化边界
- [展会验收清单](EXHIBITION_ACCEPTANCE_TEST.md)：现场冒烟测试、放行与排障

## App

- [构建与发布](BUILD_AND_RELEASE.md)：iPhone Dev Client、EAS 和 TestFlight
- [根 README](../README.md#快速开始)：Web 预览与常用检查

## 硬件与机器人

- [硬件工作区](../hardware/robot-arm/README.md)
- [G0.5 ↔ A1Z 部署](../hardware/robot-arm/a1z-g05-client/README.md)
- [提醒服务](../hardware/robot-arm/cushion-reminder-service/README.md)
- [黑客松演示流程](../hardware/robot-arm/docs/smart-cushion-a1z-hackathon-demo.md)
- [真机技术总结](../hardware/robot-arm/docs/g05-a1z-technical-summary.md)
- [离线研究索引](../hardware/robot-arm/docs/research/README.md)

历史真机记录保留失败现象与修复依据，不能替代当前入口文档。准备演示时，先读根
README，再进入对应组件的 README；不要直接从历史命令片段启动硬件。
