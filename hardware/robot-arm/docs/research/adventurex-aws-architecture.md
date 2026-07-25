# AdventureX United / Passport AWS 架构与 WAF 修复核查

核查日期：2026-07-23（Asia/Shanghai）

核查对象：`https://united.adventure-x.org/`、`https://passport.adventure-x.org/`

## 口径与边界

本次只做低频、只读的公开面核查：DNS CNAME/A 记录、正常 `GET` 的响应头，以及少量无效请求 ID 的服务指纹验证。没有并发压测、端口扫描、源站枚举、认证绕过或写操作。结论按以下等级标注：

- **已证实**：公开数据可直接验证，或响应与 AWS 官方定义的服务级错误完全吻合。
- **强推断**：多项独立证据一致，但缺少该 AWS 账户的控制台、IaC 或日志作为最终确认。
- **不能确认**：公开面不足以区分多个可行架构。

## 结论摘要

| 问题 | 结论 | 等级 |
| --- | --- | --- |
| 是否经过 CloudFront | 两个域名都 CNAME 到同一个 `cloudfront.net` 分发域名，响应也带 `Via: ... (CloudFront)`、`X-Cache`、`X-Amz-Cf-*` | **已证实** |
| 是否使用 Next.js / OpenNext | 动态登录页同时返回 `x-powered-by: Next.js` 与 `x-opennext: 1`；OpenNext 官方源码会在相应配置下添加此头 | **已证实到应用构建层** |
| 动态请求链路是否触及 Lambda | 格式错误的 `x-amzn-requestid` 在两站均触发与 AWS Lambda 官方定义完全一致的 `InvalidRequestContentException`；正常动态页同时返回 OpenNext 内容 | **已证实到公开协议层；页面计算由 Lambda 承担为强推断** |
| 是 Lambda Function URL 还是 API Gateway → Lambda | 两者都可用 HTTP 调用 Lambda；当前响应没有不可由客户端覆盖的 `x-amz-apigw-id`。OpenNext 参考实现使用 Function URL 作为 CloudFront HTTP origin，因此 Function URL 更像，但不能排除 API Gateway | **不能确认；Function URL 为强推断** |
| 是否存在 ALB | 没有观察到 `server: awselb/2.0`；但 AWS 允许关闭该头，`x-amzn-trace-id` 也不是 ALB 独占 | **不能确认** |
| 是否使用 EC2 | 公开链路没有 EC2 专属证据；当前动态前门明显触及 Lambda，但其数据库、后台任务或其他服务仍可能使用 EC2/ECS | **不能确认存在；“动态站主要由 EC2 直接提供”不符合现有证据** |
| 是否已经新增 AWS WAF | 被允许的请求通常没有能证明 Web ACL 存在的专属响应头；没有账户配置或 WAF 日志 | **不能确认** |
| 历史 403 是否由 WAF 产生 | AWS 明确说明 CloudFront 无法区分 WAF 403 与源站 403；历史截图/浏览器 403 不够 | **不能确认** |

## 1. 对“增购额外 WAF”的评价

### 有效的部分

如果事故确实是面向登录、Session 或 SSR 接口的 L7 HTTP flood，那么把 AWS WAF Web ACL 关联到 CloudFront，并配置按路径、方法和攻击特征区分的 rate-based rule、托管规则、Challenge/CAPTCHA，能在请求到达 Lambda 和数据库之前终止一部分恶意流量。AWS 官方把 rate-based rule 定义为限制聚合条件下请求量的应用层 DDoS 基础保护；Shield Advanced 也用 WAF Web ACL 和速率规则做自动 L7 缓解。[AWS：配置应用层 DDoS 防护](https://docs.aws.amazon.com/waf/latest/developerguide/ddos-get-started-web-acl-rbr.html)

因此，**WAF 是合适的边缘减压手段，但不是对后端容量问题的修复**。它不能增加 Lambda 并发、数据库连接数或 Session 存储吞吐，也不能修复每次页面加载都查/写 Session 的调用放大。

### 这份事故说明的问题

“增购额外 WAF”在技术上过于模糊：AWS WAF 是规则化的请求检查与阻断能力；效果取决于 Web ACL 关联位置、具体规则、阈值、作用路径、日志和误杀回滚策略，不是买了一个更大的盒子就自动增加源站容量。若他们实际购买的是 AWS 托管 Anti-DDoS rule group、Shield Advanced 或第三方托管规则，应当明确写出，否则无法评估。

WAF 的 `Block` 默认就是 `403 Forbidden`。[AWS WAF rule actions](https://docs.aws.amazon.com/waf/latest/developerguide/waf-rule-action.html) AWS 还明确说明：CloudFront 无法区分 403 是 WAF 还是源站产生；要定位必须查 Web ACL 日志/规则和源站日志。[AWS：CloudFront 与 WAF 的 403 行为](https://docs.aws.amazon.com/waf/latest/developerguide/cloudfront-waf-use-cases.html) CloudFront 403 还可能来自 CNAME、源站、S3 权限、地理限制、签名 URL/Cookie 等多种原因。[AWS：CloudFront 403 排障](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/http-403-permission-denied.html)

所以，如果此前“认证页整体 403、无法登录，随后回滚”的时间点正好对应 WAF 规则上线，最值得怀疑的并不是 WAF 不够多，而是规则或默认动作误配。AWS 的上线建议是先在测试环境或 `Count` 模式观察和调优，再切到 `Block`。[AWS：测试与调优 WAF protections](https://docs.aws.amazon.com/waf/latest/developerguide/web-acl-testing.html)

### 锐评

> WAF 能把恶意请求挡在门外，但不能把一个每次刷新都要动用认证和数据库的门厅变成静态大厅；如果规则未经 Count 模式就直接 Block，所谓“修复 DDoS”很可能只是把全体合法用户也统一修成 403。

尤其是活动现场的大量用户可能共用校园网、酒店或会场 NAT。只按源 IP 设置粗暴阈值，可能把 2000 名真实选手聚合成少数几个“高频 IP”。更合理的策略是：

- 静态资源由 CloudFront/S3 缓存，不经过认证函数；
- `/login`、`/api/auth/*`、Session 读取和业务写入分开设置阈值；
- 先 `Count`、看 WAF sampled requests/完整日志，再逐步启用 `Challenge` 或 `Block`；
- 对登录失败、验证码、Session refresh、业务写操作分别做服务端限流和幂等；
- 保留静态故障页和只读降级路径；
- L3/L4 大流量依赖 CloudFront/Shield，不能只把 WAF 当作全部 DDoS 方案。AWS 将 WAF 定位为应用层请求控制，而 Shield Standard/Advanced 负责更广的 DDoS 防护。[AWS WAF or Shield 决策指南](https://docs.aws.amazon.com/decision-guides/latest/waf-or-shield/waf-or-shield.html)

## 2. 本站公开可观察证据

### DNS 与 CloudFront

2026-07-23 读取到：

```text
united.adventure-x.org   CNAME d1ia56atuq7ao3.cloudfront.net
passport.adventure-x.org CNAME d1ia56atuq7ao3.cloudfront.net
```

两站正常响应均包含：

```text
x-cache: Miss from cloudfront
via: 1.1 <id>.cloudfront.net (CloudFront)
x-amz-cf-pop: FRA56-P6
x-amz-cf-id: <opaque-id>
```

**判定：CloudFront 已证实。** `Hit/Miss` 只能说明某次请求是否从边缘缓存返回，不能识别源站是 Lambda、API Gateway、ALB、EC2 或 S3。AWS 说明 CloudFront 会添加 `X-Amz-Cf-Id` 并处理 `Via` 等头。[CloudFront custom-origin request/response behavior](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/RequestAndResponseBehaviorCustomOrigin.html)

### Next.js 与 OpenNext

动态登录页观察到：

```text
content-type: text/html; charset=utf-8
x-opennext: 1
x-powered-by: Next.js
cache-control: private, no-cache, no-store, max-age=0, must-revalidate
```

OpenNext 官方源码的 `addOpenNextHeader()` 会在 Next `poweredByHeader` 开启时设置 `X-OpenNext: 1`。[OpenNext 源码：`addOpenNextHeader`](https://github.com/opennextjs/opennextjs-aws/blob/ab8f063a71a7c7a89c8502d887ace39d6891b408/packages/open-next/src/core/routing/util.ts#L293-L304)

**判定：使用 Next.js/OpenNext 已证实到应用构建层。** 但这本身不等于 Lambda：OpenNext v3 官方说明它能部署到 AWS Lambda、Cloudflare、classic Node.js，并能把不同路由拆到 ECS、Lambda 或 Workers。[OpenNext AWS 首页](https://opennext.js.org/aws)

### Lambda 服务指纹

正常请求返回随机 UUID 形式的 `x-amzn-requestid` 与 `x-amzn-trace-id`。单独看这两个头不够：API Gateway 会返回 `x-amzn-RequestId`；ALB 会在发给 target 的请求中添加或更新 `X-Amzn-Trace-Id`，且 AWS 明确说中间服务/应用也可以添加或更新它。[API Gateway logging/request IDs](https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-logging.html)；[ALB request tracing](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-request-tracing.html)

更强的验证是给请求提供格式错误的 `x-amzn-requestid`。两个站的多个公开动态路径均得到：

```http
HTTP/2 400
x-amzn-errortype: InvalidRequestContentException
x-amzn-requestid: codex-invalid-probe
x-cache: Error from cloudfront

{"Type":"User","message":"Invalid Request ID: The 'x-amzn-RequestId' header must be a valid UUID format string."}
```

AWS Lambda 官方 API 对 `InvalidRequestContentException` 的定义明确以“`x-amzn-RequestId` 不是有效 UUID”为示例；错误类型、状态码和语义均与现场完全吻合。[AWS Lambda Invoke API](https://docs.aws.amazon.com/lambda/latest/api/API_Invoke.html#API_Invoke_Errors)

另一次使用合法 UUID `11111111-2222-4333-8444-555555555555` 请求 Passport 登录页，成功响应中的 `x-amzn-requestid` 原样为该 UUID，并同时返回 OpenNext HTML。两项组合表明，请求不只是经过一个模糊的 AWS 组件，而是到达了 Lambda 调用面。

**判定：动态请求链路触及 Lambda 已证实到公开协议层；OpenNext 页面计算由 Lambda 承担是强推断。** 这使“动态站直接跑在 EC2 上、没有 Lambda”的解释与证据不符。

### Function URL、API Gateway、ALB 与 EC2 的边界

AWS 官方说明，可通过 Lambda Function URL 或 API Gateway 两种 HTTP 入口调用 Lambda。[Lambda Function URL invocation](https://docs.aws.amazon.com/lambda/latest/dg/urls-invocation.html) OpenNext 官方 CDK 参考实现则创建 Lambda Function URL，并把它作为 CloudFront 的 `HttpOrigin`；典型实现同时把静态资产放到 S3。[OpenNext reference implementation](https://opennext.js.org/aws/reference-implementation)

因此当前最符合证据的动态路径是：

```text
Viewer
  → CloudFront
    → Lambda Function URL（强推断）
      → OpenNext / Next.js server Lambda
        → 认证、Session、业务 API、数据库等
```

但以下仍然**不能确认**：

- CloudFront 源站究竟是 `*.lambda-url.*.on.aws`，还是 API Gateway；
- 是否另有 ALB；
- 认证数据库是 RDS/Aurora、DynamoDB、Redis/ElastiCache 还是其他服务；
- 后台任务或其他未访问路由是否跑在 EC2/ECS；
- Lambda 是单函数还是按路由拆分多个函数；
- 是否启用 RDS Proxy、Provisioned Concurrency、Reserved Concurrency 或 VPC。

API Gateway 的更强公开特征是 `x-amz-apigw-id`，AWS 说明该 ID 由 API Gateway 生成且调用者不能覆盖；本次响应未观察到它。[API Gateway logging/request IDs](https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-logging.html) 但头可以在中间层被策略处理，因此缺失不能绝对排除 API Gateway。

ALB 的 `server: awselb/2.0` 若出现会是强证据；AWS 也明确允许关闭该响应头，所以缺失不能排除 ALB。[ALB response header modification](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/header-modification.html) 而且 ALB target 可以是 Lambda，也可以是 EC2/ECS/IP，所以即使发现 ALB，仍不能据此完成 Lambda/EC2 二选一。[Use Lambda functions as ALB targets](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/lambda-functions.html)

## 3. OpenNext on AWS 的典型架构

OpenNext 官方推荐架构的核心是：

| 路径/功能 | 典型 AWS 组件 |
| --- | --- |
| `/_next/static/*` 与 public assets | CloudFront → S3 |
| SSR、SSG/ISR、`/api/*`、catch-all | CloudFront → server Lambda backend |
| `/_next/image` | 独立 image optimization function |
| ISR/SSG 增量缓存 | S3，tag/revalidation metadata 可用 DynamoDB |
| Revalidation | SQS FIFO → revalidation Lambda |
| Warmer | EventBridge 定时触发 warmer Lambda |

OpenNext 文档明确称 server Lambda backend 处理 SSR、ISR、SSG 和 API 请求；静态资产可以绕过 server function。[OpenNext architecture](https://opennext.js.org/aws/inner_workings/architecture)

需要强调：这是官方推荐/参考架构，不是某个站点的部署清单。OpenNext 只生成部署产物，实际基础设施可以由 SST、CDK、Terraform 等创建，也可以把路由改部署到 ECS/Node。[OpenNext AWS](https://opennext.js.org/aws)

## 4. 怎样最终确认，而不是继续猜

最短的确证路径不在外网继续“探测”，而在其 AWS 账户内部读取以下任一项：

1. CloudFront distribution 的 Origins：域名若为 `*.lambda-url.<region>.on.aws` 即 Function URL；`*.execute-api.*.amazonaws.com` 即 API Gateway；`*.elb.amazonaws.com` 即 ELB/ALB。
2. API Gateway Integration：可直接看到 Lambda ARN 或 HTTP origin。
3. ALB target group：target type 会显示 `instance`、`ip` 或 `lambda`。
4. IaC/SST/CDK/CloudFormation 输出：能确认函数、分发、S3、DynamoDB、SQS 与数据库配置。
5. CloudWatch Logs：`/aws/lambda/<function>` 与每次调用的 `START/END/REPORT RequestId` 能确认 Lambda；EC2/ECS 则看实例、任务和容器日志。
6. X-Ray/CloudWatch ServiceLens：可还原 CloudFront 之后的 API Gateway/Lambda/下游服务链路。
7. WAF Web ACL 的 sampled requests、完整日志和关联资源：这是判断历史 403 是否由某条规则产生的必要证据。

## 最终评价

现有证据支持的说法不是“他们应该是 EC2”，而是：**CloudFront 与 OpenNext 已明确；动态路径确实触及 Lambda，Function URL 是最可能入口；是否另有 API Gateway、ALB、EC2/ECS 或何种数据库，公开面不能确认。**

增购/增加 WAF 对恶意 L7 流量可以有效，但如果没有按路径调规则、先 Count 后 Block、保护源站不可绕过，并同时降低 Session/数据库放大，它只是边缘止血。此前整站 403 反而说明 WAF 规则发布和回滚机制需要重点审计；仅凭客户端 403，无法证明事故来自攻击、WAF 误杀还是源站权限/认证失败。
