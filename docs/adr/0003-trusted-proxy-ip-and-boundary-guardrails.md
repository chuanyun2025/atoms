# ADR-0003：多级反向代理真实访客 IP 剥离与流式边界防护

- **状态**：已采纳
- **关联模块**：`apps/api/atoms/core/security.py`、`apps/api/atoms/main.py`、`deploy/nginx/*.conf`

## 背景

作为无需登录即可体验的在线工作台，系统依靠访客 IP 执行新建匿名会话（每小时限额）与提交生成任务（每分钟限额）的速率限制，并限制上传与源码保存的请求体积。在生产环境中，服务常部署在本地 Nginx 容器 + 云负载均衡（SLB）或 Cloudflare Tunnel 之后：
- 若直接读取直连地址或被内层 Nginx 覆盖的 `$remote_addr`，所有公网访客会共享同一个隧道/代理容器 IP，导致全站正常用户共用一份限流桶而频繁误触发 `429`；
- 若盲目信任客户端传入的 `X-Forwarded-For` 最左端或 `CF-Connecting-IP`，攻击者又可伪造请求头绕过限流；
- 若仅检查 `Content-Length` 头限制请求大小，分块传输（Chunked Encoding）请求可绕过前置检查耗尽内存。

## 决策

1. **基于可信代理链的从右向左 IP 剥离**（`apps/api/atoms/core/security.py`）：
   - Nginx 入口统一透传 `X-Forwarded-For: $proxy_add_x_forwarded_for`；
   - `client_ip` 先校验直连对端是否属于显式可信代理集合（`TRUSTED_PROXY_CIDRS` 或内部私有/回环/链路本地网段 `_INTERNAL_PROXY_NETWORKS`，显式排除 Python 标准库 `is_private` 中包含的运营商 CGNAT `100.64.0.0/10` 与测试文档网段）；
   - 对端不可信时忽略一切转发头；对端可信时，仅在显式开启 `TRUST_CF_CONNECTING_IP` 时采信 `CF-Connecting-IP`，否则从右向左逐跳剥离可信代理 IP，取第一个非可信公网地址作为限流键。
2. **纯 ASGI 流式字节上限中间件**（`apps/api/atoms/main.py`）：
   - 使用原生 ASGI `BoundaryMiddleware` 包装 `receive()` 消息流，按路由分级统计真实流入字节（源码保存 `12 MiB`、图片上传 `8 MiB`、常规接口 `2 MiB`），一旦累计超限立即中断读取并返回带统一安全响应头的 `413 request_too_large`。

## 后果

- **正面**：兼容直连、Nginx 反代、云 SLB 与 Cloudflare Tunnel 等多种部署拓扑，兼顾防伪造与限流隔离，且彻底堵住分块超大请求绕过漏洞。
- **权衡**：若前置了公网 IP 段的第三方 CDN 且未走容器内网隧道，部署时需按手册将对应网段填入 `TRUSTED_PROXY_CIDRS`。
