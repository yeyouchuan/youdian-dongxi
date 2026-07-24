# 构建与发布手册

## 1. 前置条件

- Node.js 22
- EAS 账号：`lahuse`
- Apple Team：`T8745MYJTF`
- Bundle ID：`com.yeyou.youdiandongxi`
- EAS 项目：`@lahuse/youdian-dongxi`
- EAS Project ID：`eebd9ad8-7776-4f4e-9eae-37d77ed1e53e`

确认登录与项目：

```powershell
npx eas-cli@latest whoami
npx eas-cli@latest project:info
```

## 2. 构建前检查

```powershell
npm ci
npm run typecheck
npm run lint
npm test
npm run doctor
npx expo config --type introspect
```

introspect 输出必须包含：

- `com.apple.developer.healthkit: true`
- `NSHealthShareUsageDescription`
- `NSLocalNetworkUsageDescription`
- `NSAppTransportSecurity.NSAllowsLocalNetworking: true`
- production 配置不包含全局 `NSAllowsArbitraryLoads: true`
- 包含 Apple 二进制校验要求的 `NSHealthUpdateUsageDescription` 透明说明，但授权请求仍不包含 HealthKit `toShare` 类型，当前版本不会写入或修改 Apple 健康数据
- `expo.sqlite.useSQLCipher: true`
- `ios.deploymentTarget: 17.0`
- `expo-notifications` 已生成本地通知配置

## 3. iPhone 设备注册

查看 Apple Team 中已登记的设备：

```powershell
npx eas-cli@latest device:list --apple-team-id T8745MYJTF
```

如果目标 iPhone 不在列表：

```powershell
npx eas-cli@latest device:create
```

按 EAS 给出的网页链接在目标 iPhone 上安装临时描述文件并完成注册。新设备加入后，已有 development provisioning profile 通常需要重新生成，因此要重新构建 Dev Client。

## 4. 构建配置

`eas.json` 包含：

- `development`：真机、internal distribution、Dev Client
- `ios-simulator`：模拟器 Dev Client；不能验证 HealthKit
- `preview`：内部预览包
- `production`：生产签名并自动递增 build number

本阶段只构建真机 development 包：

```powershell
npx eas-cli@latest build --platform ios --profile development
```

非交互环境可先尝试：

```powershell
npx eas-cli@latest build --platform ios --profile development --non-interactive --no-wait
```

首次为新 Bundle ID 创建 App ID、证书或 provisioning profile 时，EAS 可能要求 Apple 登录、双重认证或确认设备。完成后不要把登录信息保存到项目。

## 5. 安装与启动

构建完成后，在 EAS 构建详情页打开安装链接或二维码，用已注册的 iPhone 安装。

启动开发服务器：

```powershell
npm run start:dev-client
```

让 iPhone 和开发电脑处于可互通网络，打开“有垫东西”Dev Client 并连接 Metro。

## 6. 何时必须重建 Dev Client

以下变化需要重新执行 EAS development build：

- 新增、删除或升级原生依赖
- 修改 HealthKit capability、entitlement 或权限文案
- 修改本地网络权限说明或 ATS 设置
- 修改 SQLCipher、SecureStore 等 config plugin
- 修改 Bundle ID、scheme、最低 iOS 版本或 Apple Team
- 注册新测试设备并更新 provisioning profile

仅修改 TypeScript、样式和文案通常不需要重建，重新连接 Metro 即可。

本次新增了 `expo-notifications`、`expo-document-picker` 和
`expo-file-system`，旧 Dev Client 与旧 TestFlight 包均不包含这些原生模块，
必须重新构建。

本次还新增了 iOS 本地网络用途说明和 ATS 本地网络放行。即使 MQTT.js 本身不含
原生 TCP 模块，Info.plist 变化也必须重新构建 Dev Client 后才能在真机验证。

## 7. 真机验收清单

- [ ] 安装并冷启动成功，浅色品牌启动页无拉伸
- [ ] 日报、健康、设置三个标签可切换
- [ ] 日报完整滚动，仪表、时间轴和固定导航无裁切
- [ ] 首次主动连接时只出现四项核心只读权限
- [ ] 未授权或无记录时显示明确空状态
- [ ] 日报与健康页显示相同的真实 Apple Health 数值、来源和测量时间
- [ ] 体重显示所选日期当日或之前最近一次记录
- [ ] 没有真实坐垫片段时不生成坐姿评分、洞察或趋势点
- [ ] 生产界面不出现固定演示日期、演示分数或测试数据入口
- [ ] iPhone 与坐垫连接 `ADVX-Players`，首次访问时允许“本地网络”
- [ ] 使用默认 `ws://10.76.7.182:9001` 或设置页保存的新地址后，两个 MQTT 主题均订阅成功
- [ ] Broker 重启后状态显示“正在重连”，恢复后回到“已连接”，且没有重复消息
- [ ] App 进入后台后断开并保存当前姿态；回到前台后仅在未主动结束会话时重连
- [ ] 心率有效而呼吸率无效时仍显示心率；五路 ADC 全满量程时不更新姿态并显示诊断错误
- [ ] 经期与心境默认关闭，启用时分别追加授权
- [ ] Apple“心境”只显示用户自述，不从 HRV 生成情绪标签
- [ ] HRV 基线不足 7 个日期或 10 个样本时显示“信号不足”
- [ ] 只有 BPM 时，呼吸率等待且其他流不中断
- [ ] BPM＋呼吸率连续 5 分钟后生成中位数、覆盖率与稳定度
- [ ] MQTT 姿态在生产健康页可见；未来压力阵列未校准时仍不进行客户端坐姿分类
- [ ] 心率 10 秒、呼吸率 90 秒、姿态 2 秒无更新时分别显示“已中断”
- [ ] development build 可手动导入和回放 JSONL；生产界面没有测试入口
- [ ] 本地提醒默认关闭，拒绝权限后仍保持关闭
- [ ] 锁屏提醒不显示 HRV、BPM、呼吸率或情绪标签
- [ ] 杀掉并重启 App 后，上次成功缓存仍可读
- [ ] 同步失败不丢失旧数据，不推进失败类型 anchor
- [ ] HealthKit 删除对象同步删除本地镜像
- [ ] “停止同步”保留缓存
- [ ] “删除导入缓存”清除镜像、anchor 与派生汇总，不影响系统“健康”原始记录
- [ ] 日志不出现 HRV、BPM、呼吸率、压力、体重、经期或心境原始值

## 8. Preview 与 Production

内部预览：

```powershell
npx eas-cli@latest build --platform ios --profile preview
```

生产构建：

```powershell
npx eas-cli@latest build --platform ios --profile production
```

提交现有生产构建到 TestFlight：

```powershell
npx eas-cli@latest submit --platform ios --profile production --latest
```

生产前必须再次审核隐私文案、App Store 隐私清单、截图、支持链接和健康免责声明。

## 9. 凭据安全

禁止提交：

- Apple `.p8`、`.p12`、`.mobileprovision`
- EAS token、Apple 密码、App 专用密码、2FA 验证码
- SQLCipher 实际数据库密钥
- 真实健康数据库或导出数据

凭据由 EAS 凭据服务或本机安全存储管理；项目仓库只保存非秘密的项目标识与构建配置。
