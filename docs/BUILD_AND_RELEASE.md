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
- 不包含 HealthKit 更新权限文案
- `expo.sqlite.useSQLCipher: true`
- `ios.deploymentTarget: 17.0`

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
- 修改 SQLCipher、SecureStore 等 config plugin
- 修改 Bundle ID、scheme、最低 iOS 版本或 Apple Team
- 注册新测试设备并更新 provisioning profile

仅修改 TypeScript、样式、文案和演示数据通常不需要重建，重新连接 Metro 即可。

## 7. 真机验收清单

- [ ] 安装并冷启动成功，浅色品牌启动页无拉伸
- [ ] 日报、健康、设置三个标签可切换
- [ ] 日报完整滚动，仪表、时间轴和固定导航无裁切
- [ ] 首次主动连接时只出现四项核心只读权限
- [ ] 未授权或无记录时显示明确空状态
- [ ] 经期与心境默认关闭，启用时分别追加授权
- [ ] 心境原始标签优先于 HRV 估算
- [ ] HRV 不足五个日期时显示“正在建立个人基线”
- [ ] 杀掉并重启 App 后，上次成功缓存仍可读
- [ ] 同步失败不丢失旧数据，不推进失败类型 anchor
- [ ] HealthKit 删除对象同步删除本地镜像
- [ ] “停止同步”保留缓存
- [ ] “删除导入缓存”清除镜像与 anchor，不影响系统“健康”原始记录
- [ ] 日志不出现 HRV、体重、经期或心境原始值

## 8. Preview 与 Production

当前范围不提交 TestFlight。将来需要内部 preview：

```powershell
npx eas-cli@latest build --platform ios --profile preview
```

生产构建：

```powershell
npx eas-cli@latest build --platform ios --profile production
```

生产前必须再次审核隐私文案、App Store 隐私清单、截图、支持链接和健康免责声明。

## 9. 凭据安全

禁止提交：

- Apple `.p8`、`.p12`、`.mobileprovision`
- EAS token、Apple 密码、App 专用密码、2FA 验证码
- SQLCipher 实际数据库密钥
- 真实健康数据库或导出数据

凭据由 EAS 凭据服务或本机安全存储管理；项目仓库只保存非秘密的项目标识与构建配置。
