# Vidu 原生视频生成

视频入口使用 **Vidu Q3 Pro（`viduq3-pro`）** 的原生文生视频 / 图生视频接口。输入文字即可生成，不需要首帧。
默认清晰度为 **540p**、时长 **5 秒**，可选择 1–16 秒和是否生成声音。
也可以选择一张 PNG、JPEG 或 WebP 图片作为首帧，本应用限制为 5 MB。移除图片后切回文生视频。

官方接口文档：
[文生视频](https://platform.vidu.cn/docs/api-reference/video-models/vidu-q3/text-to-video)、[图生视频](https://platform.vidu.cn/docs/api-reference/video-models/vidu-q3/image-to-video)、[官方定价](https://platform.vidu.cn/pricing)

## 配置

在根目录 `.env.local` 设置独立的 Vidu 密钥。不要使用 DeepSeek 密钥替代。

```dotenv
VIDU_API_KEY=填写自己的Vidu密钥
VIDU_BASE_URL=https://api.vidu.cn
VIDU_MODEL=viduq3-pro
VIDU_RESOLUTION=540p
VIDU_POLL_SECONDS=5
VIDU_CREDIT_PRICE_CNY=0.03125
```

然后运行：

```powershell
docker compose --env-file .env.local up -d --build api worker
```

Vidu 密钥只进入 API 与 Worker 的服务端配置，不返回前端、不写入生成产物、日志或示例。
所有用户统一使用平台积分，无需提供供应商账户或密钥。平台按供应商实际费用折算，不额外加价，也不虚构 token 用量。
没有密钥时，视频页显示服务未连接并禁用生成。网站、游戏、幻灯片继续使用原来的文本模型配置。

## 积分计费

- `GET /api/v1/video/quote?duration=5` 返回平台积分预估。Q3 Pro 标准模式 540p 每秒 9 个供应商积分；默认供应商单价 0.03125 元/积分，平台 10 积分=1元。5 秒预估 **14.0625 平台积分**。声音开关使用相同费率。
- `VIDU_CREDIT_PRICE_CNY` 是操作者实际购入的供应商积分单价，支持折扣采购。每次预授权保存单价快照；后续改价不会影响已接收任务。
- 创建任务在同一事务内校验余额并预授权，所有文本与媒体调用共享同一钱包，避免并发超支。前端展示费用、可用积分与禁用原因，服务端重新校验。
- 成功后读取任务查询结果的 `credits`，按实际用量结算一次，剩余预授权释放。明细显示「视频生成消费」。供应商明确拒绝或生成失败时释放全部预授权；生成成功但下载失败仍按已产生的费用结算，重试只续取原任务，不重复付费。
- 提交结果不确定或供应商未返回可确认用量时保留冻结，避免猜测扣款或盲目重提。视频仍可保存交付。操作者确认账单后可使用以下命令核对，金额不得超出预授权：

```powershell
docker compose --env-file .env.local exec -T api python -m atoms.ops media-reconcile CALL_ID --provider-credits 45
# 确认上游没有扣费时：
docker compose --env-file .env.local exec -T api python -m atoms.ops media-reconcile CALL_ID --release
```

## 任务和媒体

- 无参考图使用 `POST /ent/v2/text2video`；有参考图使用 `POST /ent/v2/img2video`。通过 `Authorization: Token ...` 提交首帧、原始提示词和输出设置，显式传入 `resolution=540p`（默认）及 `is_rec=false`。
- `GET /ent/v2/tasks/{id}/creations` 查询创建、排队、生成、成功和失败状态。任务 ID 写入 SQLite 的 `video_jobs`，页面刷新不影响 Worker。
- 查询失败最多自动重试八次，临时下载故障自动重试两次。已有上游任务可继续查询，不会重新提交相同的付费任务。
- 提交超时、无法确认是否受理时不会盲目重发。需要操作者在 Vidu 控制台核对，避免重复付费。仅明确返回 429 的拒绝提交可自动重试。
- 成功后将 MP4 下载到持久化目录，再提交项目的新版本。供应商的临时 URL 不进入前端视频产物。
- 原生视频版本使用独立的 `schema_version=3` 媒体清单，绑定可选首帧、视频文件与请求设置，兼容历史 Q4 视频。它不经过 HTML 编译器，也不在生成代码的沙箱里联网播放。旧的 HTML 分镜版本仍能预览和导出。
- 首帧和视频只通过有访客归属校验的媒体接口提供。视频支持 Range 请求，原生播放器可以拖动进度，导出接口下载 MP4。

## 本地、阿里云与备份

开发和生产 Compose 都将媒体保存到 `/var/lib/atoms/media`，与数据库共享持久化卷。
重建服务不会丢失视频；迁移到阿里云 ECS 时需要同时迁移数据库和媒体文件。

`atoms.ops backup` 会为数据库备份创建同名 `.media` 配套目录。
备份、传输时必须同时保留数据库和该目录；离线恢复会验证媒体完整性并恢复对应文件。
未来如改为 OSS，保持媒体资产 ID、项目归属校验和视频版本清单不变，替换存储适配层即可。

## 验证

供应商协议测试使用 HTTP MockTransport，浏览器测试使用本地生成的短 MP4 测试素材。
`APP_ENV=test` 和 `TEST_FIXTURE=true` 必须同时满足才能使用测试视频，生产环境拒绝启用测试模式。
未配置真实 Vidu 密钥时，这些验证不会触发付费调用，也不代表已经完成供应商真实出片联调。
