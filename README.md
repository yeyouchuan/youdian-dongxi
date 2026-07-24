# 有垫东西

有垫东西是一款面向 iPhone 的坐姿健康日报应用。它把智能坐垫的姿态片段整理成日报与趋势，并在用户主动授权后只读同步 Apple Health 数据。所有洞察均在设备端生成。

> 生产运行时不内置演示健康或坐姿数据。没有真实坐垫记录时，坐姿日报与趋势显示空状态；Apple Health 区域只显示实际读取到的记录。应用仅提供健康参考，不属于医疗诊断设备。

## 主要功能

- 按日期查看坐姿得分、在座时长、正坐比例、非正坐时长与离座情况
- 通过 7 天或 30 天范围查看真实得分曲线、姿势趋势和日历热力图
- 只读同步 Apple Health 的静息心率、HRV、呼吸频率与体重
- 在日报与健康页显示 Apple Health 原始来源和测量时间
- 通过 MQTT WebSocket 接收坐垫心率、呼吸率、姿态和五路原始 ADC；Broker 地址可在设置中修改
- 使用 5 分钟实时会话与 Apple Health SDNN 生成恢复状态参考
- development build 支持手动数据和 JSONL 文件回放
- 按需追加经期流量和心境读取权限
- 使用 SQLCipher 加密本地健康数据镜像，并将数据库密钥保存在 iOS 钥匙串
- 在 iOS 26 使用原生 Liquid Glass 标签页，在 iOS 17/18 使用兼容样式

## 技术栈

- Expo SDK 57
- React Native 0.86 / React 19.2
- Expo Router
- Expo SQLite + SQLCipher
- Expo SecureStore
- Expo Notifications（仅本地通知，不申请推送令牌）
- Expo DocumentPicker / FileSystem（仅开发回放入口使用）
- `@kingstinct/react-native-healthkit`
- MQTT.js 5.15.1（React Native 原生 WebSocket）
- TypeScript

项目最低支持 iOS 17。Expo SDK 57 要求 Node.js 22.13.x 或更高版本。

## 快速开始

安装依赖：

```powershell
npm ci
```

启动网页预览：

```powershell
npm run web
```

网页预览适合开发界面，但不提供 HealthKit。验证 Apple Health、SQLCipher 等原生能力时，必须使用 iPhone development build，不能使用 Expo Go：

```powershell
npm run start:dev-client
```

坐垫默认连接 `ws://10.76.7.182:9001`。iPhone 与坐垫/Broker 必须位于可互通的
同一局域网，并允许 App 访问“本地网络”。App 只统计前台连接且实际收到姿态消息的
时段；进入后台时会断开，回到前台后按用户此前的会话意图重连。

首次构建 Dev Client、注册 iPhone 以及配置 EAS 凭据的完整步骤见 [构建与发布手册](docs/BUILD_AND_RELEASE.md)。

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `npm run start` | 启动 Expo 开发服务器 |
| `npm run start:dev-client` | 启动 development build 使用的 Metro 服务 |
| `npm run web` | 启动网页预览 |
| `npm run typecheck` | 执行 TypeScript 类型检查 |
| `npm run lint` | 执行 ESLint 检查 |
| `npm run doctor` | 检查 Expo 项目依赖与配置 |

## 项目结构

```text
src/
  app/              页面、路由与原生标签导航
  components/       可复用界面、图表与加载状态
  data/             SQLCipher 仓库、真实姿态记录与同步合并
  domain/           数据模型、评分和展示规则
  hooks/            跨平台交互 Hook
  services/         坐垫、Apple Health 与手动记录适配层
  state/            HealthKit 与坐垫实时会话状态
assets/             应用图标、启动图与静态资源
docs/               构建和发布文档
scripts/            本地开发脚本
```

## 数据与隐私

- 应用只申请 HealthKit 读取权限，不写入或修改 Apple Health 记录。
- HRV 只读取 Apple Health SDNN；坐垫 BPM 和呼吸率不能反推或伪装为 HRV。
- Apple“心境”只显示用户主动记录的标签，不与恢复状态或情绪推断合并。
- 经期与心境数据默认关闭，必须由用户分别启用。
- HealthKit 样本保存在设备端加密数据库中；同步 anchor 与样本在同一事务提交。
- 原始 BPM、呼吸率和 ADC 仅存在十分钟内存窗口中；数据库只保存姿态片段、5 分钟汇总和派生特征。
- 坐姿洞察在本机根据坐垫片段与评分规则生成，不上传健康原始数据。
- 没有真实坐垫片段时不生成坐姿评分、洞察或趋势点，也不会回退到固定样例。
- 日志、错误上报和埋点不得包含 HRV、体重、经期或心境原始值。
- “停止同步”保留本地缓存；“删除导入缓存”不会删除 Apple Health 中的原始记录。

实时坐垫事件格式、范围和未来硬件接入边界见
[实时数据接口规范](docs/CUSHION_REALTIME_DATA_SPEC.md)。

## 仓库范围

发布仓库不包含本地测试用例、测试运行产物、AI 助手配置、提示词、浏览器 QA 会话或视觉比对截图。密钥、签名文件、真实 HealthKit 导出与本地环境变量同样不会提交。

## 许可证

[MIT](LICENSE)
