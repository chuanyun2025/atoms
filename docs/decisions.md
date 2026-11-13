# 实现决策记录

## 2026-11-12：匿名积分修订（覆盖此前的小输出和次数配额决策）

用户明确要求按余额管理消费，首次赠送 500 积分，输入/输出每百万 token 分别 20/80 积分。已依次更新需求 v0.2、技术计划 v1.1、实现和验证。

- 不再使用 8192 输出、8000-token 提示、64/96 KiB 代码限制、每小时/每天次数、项目数或版本数配额。
- DeepSeek 省略 max_tokens 默认仍为 8K（非思考模式），因此改为查询原生 max_output_tokens，并按可用积分预授权动态输出空间；当前真实请求 output_limit 为 393216。
- 账本使用百万分之一积分整数单位，供应商 usage 为唯一实际计费来源；失败但有 usage 仍结算。无连接的确定失败释放预授权，已发送而缺 usage 的调用冻结待核对。
- 0002 只新增钱包/账本/调用记录，现存会话沿用随机 ID，给旧访客补发一次积分；不删除项目、不追溯未知历史用量。
- 生成长任务资源保护改为 8 MiB 总产物/4 MiB 单文件、32 MiB 校验传输、1500 秒模型读取和 3600 秒 Run；沙箱隔离和 12 秒浏览器 watchdog 继续保持。
- 已完成真实 DeepSeek 用量结算：543 输入 + 1969 输出，消费 0.168380 积分。下述“模型密钥为空”与不展示费用等内容为之前版本的历史状态，当前以本节和 verification.md 为准。

## 状态

以 technical-plan.md v1.0 为基线。任何必要偏离在此记录原因和验收影响。

## 2026-11-11：开发环境

- Docker Desktop Linux/amd64 可用。
- 宿主 Node 24；Python 应用使用容器内 Python 3.12，避免宿主 Python 3.15 的差异。
- 在本地仓库实现；云端部署留在 M7。

## 2026-11-12：本地实现与手册细化

### 固定实现范围

已落地 FR-001～FR-012 的本地实现，以及 FR-105、FR-109。真实模型生成的业务验收等待本地密钥，不能用测试产物宣布完成。未增加未选入的可视化编辑、附件、独立发布、多角色或通用宿主工具执行。

前端为 React/TypeScript/Vite；API/Worker 为 Python 3.12、FastAPI、SQLAlchemy Core 文本 SQL 与 Alembic；数据库为 SQLite DELETE journal。实际依赖版本在 package-lock.json 和 apps/api/uv.lock 中锁定。

### Chromium 沙箱与系统调用

M0 首次实测在 cap_drop=ALL 下遇到 Chromium 的 namespace 内 chroot 被 seccomp 拒绝。没有关闭 Chromium 沙箱，也没有增加宿主 capability。

- 保存 [Playwright 官方上游配置](https://raw.githubusercontent.com/microsoft/playwright/main/utils/docker/seccomp_profile.json) 为 deploy/seccomp/upstream.json。
- 上游文件 SHA-256：cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849。
- deploy/seccomp/playwright.json 在 namespace syscall 允许列表中额外允许 chroot。内核仍要求相应 namespace 内权限；容器仍为非 root、cap_drop=ALL、no-new-privileges。
- chromiumSandbox=true 保持启用；/tmp 为限额 tmpfs，根文件系统只读；校验子进程有 12 秒进程组 watchdog。
- 真实浏览器已验证父 DOM、原生存储、fetch 和 WebSocket 隔离；无限循环被终止，随后正常候选仍能校验。

此项为支持当前 Chromium 所需的配置细化。后续更新 Playwright 或迁移 ECS 时必须重新验证，不能把本机通过视为任何宿主都兼容。

### 私有校验接口

在手册基础上增加 app_origin 字段并与 Validator 环境配置精确比较，保证校验环境的父来源与用户预览一致。仍只接受固定三文件产物，不接受任意待访问 URL。

编译器使用共享 JSON Schema、parse5、PostCSS 和 Acorn。摘要包含原始产物及 compiler/sdk 版本。模板采用单次替换，避免生成内容中的模板字样再次被替换。浏览器与检查子进程使用环境白名单，不继承服务 token 或模型密钥。

### 数据、任务与恢复

- deadline 使用 started_at + 180 秒推导；排队截止为 created_at + 600 秒，不单独存储可互相矛盾的 deadline 列。
- worker_status 额外记录 model_configured。模型密钥只交给 Worker，API 根据该状态展示配置能力。
- 首次领取的 Run 租约不超过单例 Worker 租约；之后在同一短事务中续约。旧执行者无法越过租约或终态提交。
- 幂等重放优先于版本、额度与可用性检查。前端保留未确认请求的原始 body 和 key，即使当前项目 revision 已推进也能查询到同一提交结果。
- 业务数据 PATCH 增加可选 version_id；预览宿主始终携带绑定版本，旧版本保存会被拒绝。普通访客仍可通过受所有权保护的项目数据接口管理自身数据。
- 切换预览时关闭旧 MessagePort，并检查端口实例，阻止旧队列在新预览中继续写入。
- 当前不展示供应商 token 用量或费用。记录真实阶段和调用次数，不估算账单。

接口的实际字段与错误码以 apps/api 的 OpenAPI 和源码为准；需求 ID 与验收语义保持不变。

### 网关与生产镜像

容器重建测试发现 Nginx 静态解析上游地址会保留旧 IP。已改为 Docker DNS resolver + shared upstream zone + resolve，5 秒刷新。首次更新本地挂载配置时，启动脚本同时重载 Nginx。

日常开发卷为 Compose 管理的 atoms_app_data；生产使用明确命名的 external volume atoms_data。E2E 为 atoms-e2e 独立项目；静态生产检查同时使用 atoms-prodcheck 和 atoms_prodcheck_data，防止 external volume 复用。

基础镜像 digest 已固定。生产镜像使用静态 SPA 和 HTTPS Nginx；本地 8083 检查通过显式 HTTP override 运行，不能直接当成生产 HTTPS 配置发布。生产 Compose 默认 production、Secure Cookie，并要求显式 APP_ORIGIN。

### 模型接入

用户选择 DeepSeek，已核对 [官方文档](https://api-docs.deepseek.com/)：服务地址为 https://api.deepseek.com，API 模型名为 deepseek-flash，对应 DeepSeek-V4.1-Flash-1017。

默认使用 json_object、max_tokens 和显式 disabled 思考模式；支持配置响应模式、输出长度参数及思考开关，不猜测厂商参数。上游错误仅返回脱敏类别，不向浏览器暴露请求体、凭据或完整错误响应。

开发时 .env.local 的 LLM_API_KEY 仍为空；适配器已通过 HTTP 协议测试，真实模型调用和生成应用业务验收仍待补做。测试产物仅在 APP_ENV=test + TEST_FIXTURE=true 时可达，其他环境启用会直接拒绝启动。
