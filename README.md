# 有垫东西

有垫东西是一款面向 iPhone 的坐姿健康日报应用。它把智能坐垫的姿态片段整理成日报与趋势，并在用户主动授权后只读同步 Apple Health 数据。所有洞察均在设备端生成。

> 当前仓库使用演示坐垫数据。应用仅提供健康参考，不属于医疗诊断设备。

## 主要功能

- 按日期查看坐姿得分、在座时长、正坐比例、二郎腿时长与离座情况
- 通过周/月/年范围查看得分曲线、姿势趋势和日历热力图
- 只读同步 Apple Health 的静息心率、HRV、呼吸频率与体重
- 按需追加经期流量和心境读取权限
- 使用 SQLCipher 加密本地健康数据镜像，并将数据库密钥保存在 iOS 钥匙串
- 在 iOS 26 使用原生 Liquid Glass 标签页，在 iOS 17/18 使用兼容样式

## 技术栈

- Expo SDK 57
- React Native 0.86 / React 19.2
- Expo Router
- Expo SQLite + SQLCipher
- Expo SecureStore
- `@kingstinct/react-native-healthkit`
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
  data/             演示数据、SQLCipher 仓库与同步合并
  domain/           数据模型、评分和展示规则
  hooks/            跨平台交互 Hook
  services/         坐垫、Apple Health 与手动记录适配层
  state/            HealthKit 连接、授权与同步状态
assets/             应用图标、启动图与静态资源
docs/               构建和发布文档
scripts/            本地开发脚本
```

## 数据与隐私

- 应用只申请 HealthKit 读取权限，不写入或修改 Apple Health 记录。
- 经期与心境数据默认关闭，必须由用户分别启用。
- HealthKit 样本保存在设备端加密数据库中；同步 anchor 与样本在同一事务提交。
- 坐姿洞察在本机根据坐垫片段与评分规则生成，不上传健康原始数据。
- 日志、错误上报和埋点不得包含 HRV、体重、经期或心境原始值。
- “停止同步”保留本地缓存；“删除导入缓存”不会删除 Apple Health 中的原始记录。

## 仓库范围

发布仓库不包含本地测试用例、测试运行产物、AI 助手配置、提示词、浏览器 QA 会话或视觉比对截图。密钥、签名文件、真实 HealthKit 导出与本地环境变量同样不会提交。

## 许可证

[MIT](LICENSE)
