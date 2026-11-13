---
document_id: ATOMS-DEMO-PLAN
version: 1.2
status: experience_update_plan_ready
updated_at: 2026-11-12
requirements: ./requirements.md
development_first: local
deployment_target: Alibaba_Cloud_ECS_Linux_Docker_Compose
implementation_started: true
implementation_status: baseline_local_implemented_experience_update_planned
---

# Atoms-Demo 技术规划与实现手册

本轮实施从[第 27 节 · 创作体验更新实现计划](#27-创作体验更新实现计划)开始。第 27 节落实[需求规格 v0.3](./requirements.md#17-创作入口与体验更新)。第 26 节继续约束积分和模型预算，其余章节作为既有系统的设计基线。

## 26. 匿名积分系统实现修订（2026-11-12，优先契约）

执行顺序：已先更新需求规格 v0.2，再更新本节与旧数字，随后才修改实现与验证。对应 FR-013～FR-015。

### 26.1 数据与迁移

新增 Alembic 0002，不修改已执行的 0001，不删除现有项目或任务。

- credit_wallets：visitor_id 主键/外键、balance_units、held_units、spent_units，均为非负整数且 held_units <= balance_units；1 积分 = 1,000,000 units。
- credit_ledger：id、visitor_id、event_key、kind、signed amount_units、input_tokens、output_tokens、run_id、call_id、created_at；(visitor_id,event_key) 唯一。
- model_calls：id、visitor_id、run_id、attempt、lease_token、status、reserved_units、input_ceiling、output_limit、实际 input/output token、provider_request_id、错误原因、创建/结算时间；(run_id,attempt) 唯一。
- 0002 为现存 visitor 创建钱包并写唯一 welcome 流水，赠送 500,000,000 units。新会话在同一事务中建立 visitor、钱包和赠送记录。
- 旧 usage 缺失的历史调用不追溯收费。Cookie 识别随机 ID，刷新及服务重启沿用身份；不做登录、支付或未授权的指纹采集。

### 26.2 原生输出能力与预算

DeepSeek /models 提供 max_output_tokens/context_window；Worker 缓存元数据。元数据缺失时使用明确的供应商能力回退 393216。官方当前 max_tokens 范围为 1～393216；省略它在非思考模式仍默认 8K，因此不能简单删掉字段。依据：[模型元数据](https://api-docs.deepseek.com/api/list-models/)、[输出参数与 usage](https://api-docs.deepseek.com/api/create-chat-completion/)。

移除提示词内 8000 token 与 64/96 KiB 要求。准备完整上下文后，以输入消息 UTF-8 字节数加固定协议余量形成保守输入预授权，不当成真实用量收费。输入价格每 token 20 units，输出每 token 80 units。

输出参数 = min(供应商原生输出上限, floor((可用 units - 输入预授权 units) / 80))。足额钱包使用模型原生上限；不足一输出 token 的预算拒绝调用。这里的缩减只来自账户余额或供应商能力，不保留项目自定小上限。

### 26.3 调用预授权与精确结算

1. Run 幂等创建先返回已有请求，再检查余额；创建本身不扣费。多个项目可以排队；实际每次调用前重新查余额。
2. Worker 领取后，在短写事务内核验 Run lease、attempt 唯一性和余额；写 model_calls、增加 held_units、增加真实调用计数，再发 HTTP。网络等待绝不持有 DB 事务。
3. 成功响应先提取并验证 usage，再结算，然后才解析代码、校验或决定修复。即使 length/refusal/空代码/校验失败，有可信 usage 也需结算。
4. 费用 = input_tokens * 20 + output_tokens * 80 units；以单事务释放本次 held、减少 balance、增加 spent，并写唯一 consumption 流水。重复结算同一调用不重复扣费；不使用浮点数计算金额。
5. 认证/限流/参数明确拒绝且无 usage 的请求释放预授权。已发送后网络失败、超时、无 usage、硬退出或异常用量超出授权时标为 uncertain，继续冻结，不伪造实际费用。
6. 回收过期 Run 时只释放尚未发出的预留；in-flight 标 uncertain。旧 Worker 的真实迟到 usage 可按原 call/lease 身份幂等结算，但仍不得交付失效 Run 的代码。
7. 维护 CLI 提供按 call_id 核对真实 input/output token，或在确认未收费时释放冻结；不开放客户端任意改余额的接口。核对行为写账本。

余额始终不为负。usage 超过本次授权不盲目超额扣费，转待核对并展示原因为准。自动修复单独预授权；额度不足则停止修复，保留旧版本与已发生用量记录。

### 26.4 API 与界面

- POST /api/v1/session 保留 visitor_id/CSRF，确保一次赠送。
- GET /api/v1/wallet：随机用户 ID、总余额、冻结、可用、累计消费，以及初始赠送、换算和输入/输出费率。
- GET /api/v1/wallet/transactions：仅当前用户的赠送/消费流水及待核对调用，限制分页数量，不包含密钥、原始 prompt 或其他访客数据。
- Run 返回关联用量及积分消费，阶段 SSE 可记录扣费已结算。余额不足返回 402 insufficient_credits。
- 侧栏可见积分余额；积分弹窗显示完整用户 ID、500 积分=50元说明、计费规则、精确六位小数消费与冻结状态。提交、阶段结束、焦点恢复与周期查询均刷新钱包。
- 余额用尽时不能再生成；预览、代码查看、恢复和导出不扣 token 积分。

### 26.5 技术保护与验收

产物总 8 MiB/单文件 4 MiB，模型响应 32 MiB，Validator 请求/子进程输入 32 MiB；公开输入 2 MiB。总 Run 3600 秒、模型读取 1500 秒；浏览器 watchdog 12 秒继续保护无限循环。

新增检查覆盖：新旧用户只赠一次、整数精度、钱包隔离、低余额、并发预授权、幂等扣费、修复费用、失败但有 usage、无 usage 冻结、崩溃回收、人工核对、原生输出上限请求及超过旧尺寸的有效代码。随后跑现有端到端并验证页面积分，再在本地迁移/重建 API 与 Worker；保留原数据和密钥。

## 1. 执行范围与阅读顺序

本文件以 [需求规格 v0.3](./requirements.md) 为业务基线。第 26 节定义匿名积分、真实 token 结算和供应商原生输出预算，覆盖早期次数配额规则。第 27 节定义本轮创作体验更新。开发先在本地进行，后续部署到阿里云。实际状态见[验证记录](./verification.md)。

第 17 节记录首版里程碑。本轮在现有代码上执行第 27 节，按需求 ID 验收相关交互和既有流程。

默认交付范围：

| 范围 | 本次决定 |
| --- | --- |
| P0 | 实现 FR-001～FR-015；FR-012 实现业务数据持久化，FR-013～FR-015 为匿名积分和生成预算 |
| P1 | 选入 FR-105 历史恢复、FR-109 源码导出 |
| 体验更新 | FR-016～FR-020，实施范围与验收见第 27 节 |
| 暂不选入 | FR-101～FR-104、FR-106～FR-108、FR-110～FR-112 |
| UI 辅助 | 加入桌面/手机宽度切换、代码文件切换、真实运行阶段和错误反馈；不宣称完整移动端编辑器 |
| 本地 | Windows 上使用 Docker Desktop 的 Linux 容器，通过 Compose 开发和验收 |
| 上云 | 阿里云单台 Linux ECS，同一组应用镜像和数据库迁移；生产使用 Nginx、HTTPS、持久卷 |
| 源码 | 准备 GitHub 可交付仓库；本规划阶段不创建仓库、不部署云资源 |

本计划没有将需求规格中的全部候选功能升级为必做。后续若调整范围，记录具体 FR/AT、原因和影响，不能静默跳过。

## 2. 已做出的技术决策

| 决策 ID | 选择 | 理由与边界 |
| --- | --- | --- |
| ADR-001 | React + TypeScript + Vite SPA | 工作区交互清晰；无需 SSR；本地开发和 Nginx 静态部署一致 |
| ADR-002 | Python 3.12、FastAPI、Pydantic v2、HTTPX | HTTP 接口、约束校验、模型调用和 Worker 共用 Python 业务代码 |
| ADR-003 | SQLite + SQLAlchemy 2 Core + Alembic | 单机 Demo 的持久化和事务需求；减少额外数据库服务；不支持多主机横向部署 |
| ADR-004 | 独立 Worker + 数据库中的持久 Run | 浏览器断开不取消执行；API 重启不丢失排队任务；不使用进程内 BackgroundTasks 承担关键任务 |
| ADR-005 | Node.js 24 LTS 的独立 Validator 服务 | HTML/CSS/JS 解析、统一产物编译、受限 Chromium 基础启动检查；只在私有容器网络提供接口 |
| ADR-006 | 三文件静态应用产物 | 固定 index.html、styles.css、app.js；没有用户指定的依赖安装、后端生成或任意宿主命令 |
| ADR-007 | HTTP 提交 + SSE 事件回放 | HTTP 提交即返回 Run；事件落库后投递；重连通过游标补读 |
| ADR-008 | 匿名 HttpOnly 会话 + 项目所有权 | 免注册评审，仍隔离不同访客；不提供跨设备账户恢复 |
| ADR-009 | HTTP CSP + opaque-origin iframe + 限定 MessagePort | 执行生成应用，同时隔离平台页面和凭据；业务数据由宿主按项目绑定授权 |
| ADR-010 | 两项 P1：恢复版本、导出源码 | 利用已有不可变版本，能明确展示工程取舍和交付能力 |
| ADR-011 | Nginx + Docker Compose，ECS 单机 | 本地验证后迁移同一组镜像；云端不暴露 API、数据库或 Validator 端口 |

### 2.1 比较过的备选方案

| 领域 | 备选 | 本次不采用的原因 |
| --- | --- | --- |
| 平台后端 | 全部使用 Node/Next.js | 可行，但本计划统一采用 Python API/Worker；后续不要混搭第二套业务后端 |
| 数据库 | PostgreSQL/RDS | 适合并发和多实例；当前单 Worker Demo 使用 SQLite 足够，升级条件见第 21 节 |
| 任务队列 | Redis + Celery | 可以提供分布式队列；当前仅一个 Worker，以数据库状态和租约实现所需恢复能力 |
| 生成产物 | React 工程 + npm 构建 + 任意依赖 | 涉及包安装、网络、构建和更强沙箱；超出当前明确支持范围 |
| 预览成功判断 | 仅检查模型返回的字符串 | 无法验证基础启动；改为解析检查和受限浏览器检查 |
| 预览成功判断 | 必须等待当前用户浏览器回执 | 用户关闭页面会影响任务交付；由独立 Validator 检查，用户浏览器另有加载状态 |
| 预览存储 | 直接调用 iframe 的 localStorage | opaque-origin 沙箱不可依赖该能力；使用受限存储桥 |
| 部署 | Kubernetes、SAE、函数计算 | 当前没有相应规模需求；本地到 ECS 的 Compose 路径更直接 |

这些是工程决策。官方文档只用于核对机制，不代表官方建议了本项目的完整架构。

## 3. 支持的生成应用

### 3.1 固定产物形态

每次生成或修改输出完整三文件快照：

- index.html：页面结构，可提供完整 HTML；有效内容来自 body。不得包含脚本、样式表链接、事件属性或主动嵌入。
- styles.css：普通 CSS，可使用响应式布局和内联生成的视觉样式；无外部字体、网络图片和 @import。
- app.js：普通浏览器 JavaScript，ECMAScript 2022 语法；通过 DOM API 实现交互。

支持任务看板、计算器、筛选列表、本地表单及简单数据看板。允许 data URL 图片；默认使用系统字体、CSS 和文字/Unicode 图标。

不支持 npm 包、ES module/import、CDN 依赖、任意联网请求、上传执行服务器代码、支付和外部账户。超出范围的请求在说明和生成提示中明确限制；如果模型仍返回不支持的产物，校验失败并给出原因，不能假装实现。

修改时返回全部三文件，不输出文件补丁。限制产物规模以降低长代码重写风险；语义回归由真实验收补充，不能声称修改过程绝不会改变无关功能。

### 3.2 产物契约

下例仅说明数据结构，不能作为真实生成的固定替代结果：

~~~json
{
  "schema_version": "1",
  "title": "任务看板",
  "summary": "支持添加任务、完成状态和筛选。",
  "files": {
    "index.html": "<main id=\"app\"><h1>任务看板</h1><div id=\"tasks\"></div></main>",
    "styles.css": "body { font-family: system-ui; }",
    "app.js": "const tasks = window.atoms.storage.get('tasks', []);"
  }
}
~~~

规范源文件规划为 shared/contracts/artifact.schema.json。JSON Schema 使用固定必填属性和 additionalProperties=false；业务大小限制在服务端另行校验，提供商接口只接收其支持的 Schema 子集。

约束：

1. 文件名集合必须恰好等于上述三项；不接受路径、压缩包或额外文件。
2. title 为 1～80 字符，summary 为 1～600 字符；文件总 UTF-8 技术保护为 8 MiB、单文件 4 MiB，替代旧版 96/64 KiB 的小限制，不以此代替积分预算。
3. 严格解析 JSON，并拒绝重复键；只允许去掉包住整个响应的一层 Markdown JSON 围栏，不使用任意截取大括号的“修复”。
4. 产物及编译结果保存在数据库，不按模型给出的文件路径写宿主文件系统。
5. Code Viewer 展示原始三文件；沙箱运行的受控包装和原始产物分别管理。

## 4. 总体架构

~~~mermaid
flowchart LR
    U["浏览器：React 工作区"] --> G["Nginx Gateway"]
    G --> A["FastAPI：会话、项目、Run、版本、SSE"]
    G --> P["沙箱文档响应 /sandbox/"]
    P --> A
    A --> D[("SQLite 持久卷")]
    W["独立 Python Worker"] --> D
    W --> L["配置的模型服务"]
    W --> V["私有 Validator 服务"]
    V --> B["受限 Chromium 基础检查"]
    U --> F["sandbox iframe"]
    F --> M["受限 MessagePort"]
    M --> U
    U --> A
~~~

服务边界：

| 服务 | 职责 | 不能承担的职责 |
| --- | --- | --- |
| gateway | 静态文件/开发代理、/api 和 /sandbox 反向代理、HTTPS、SSE 转发 | 不连接模型，不保存项目数据 |
| api | 会话、ACL、请求去重、短事务、SSE、版本/数据访问、导出、沙箱文档包装 | 不在 HTTP 请求生命周期内执行完整生成 |
| worker | 获取 Run、生成/修改、一次有界修复、校验、提交结果、心跳 | 不把生成代码作为 Python/Node 命令在宿主执行 |
| validator | 严格解析、HTML/CSS/JS 校验与规范化、无外网启动检查 | 不持有模型密钥、会话密钥和数据库卷 |
| migrate | 一次性运行 Alembic 迁移，完成后退出 | 不和另一迁移实例并发变更 schema |

首版固定一个 API 进程、一个 Worker、一个 Validator 检查槽位。API 多连接可并发读取，Run 可进入 pending，但每个项目同时仅一个活动 Run，实际模型执行全局并发为 1。

## 5. 代码仓库与模块职责

以下路径为实现目标：

~~~text
atoms/
├─ docs/
│  ├─ requirements.md
│  ├─ technical-plan.md
│  ├─ decisions.md                 # 实现时记录偏离本计划的决定
│  └─ verification.md              # 实际执行的验证结果
├─ apps/
│  ├─ web/
│  │  ├─ src/api/                  # HTTP 客户端、生成的 API 类型、错误转换
│  │  ├─ src/features/projects/
│  │  ├─ src/features/workspace/    # 对话、Run 状态、阶段列表
│  │  ├─ src/features/preview/      # iframe 生命周期、MessagePort 存储桥
│  │  ├─ src/features/versions/     # 历史、恢复、导出
│  │  ├─ src/components/
│  │  └─ src/styles/
│  ├─ api/
│  │  ├─ app/main.py
│  │  ├─ app/api/routes/
│  │  ├─ app/core/                 # settings、安全、错误、日志
│  │  ├─ app/db/                   # metadata、事务、repositories、迁移
│  │  ├─ app/services/             # 项目、Run、版本、存储、导出
│  │  ├─ app/agent/                # 模型适配器、上下文、生成/修复流程
│  │  ├─ app/worker/               # 领取、心跳、执行、过期恢复
│  │  ├─ app/preview/              # 可信模板包装、票据与响应头
│  │  ├─ app/cli.py               # migrate/check/backup/restore 工具
│  │  ├─ migrations/
│  │  └─ tests/
│  └─ validator/
│     ├─ src/server.ts
│     ├─ src/validate.ts           # parse5、CSS parser、Acorn
│     ├─ src/probe-child.ts        # 独立检查进程，启动受限 Chromium
│     └─ tests/
├─ shared/
│  ├─ contracts/artifact.schema.json
│  ├─ contracts/preview-message.schema.json
│  ├─ preview-runtime/runtime.js   # 可信 IIFE，非模型生成
│  └─ fixtures/                   # 明确标记的测试产物
├─ tests/e2e/
├─ deploy/nginx/
├─ deploy/seccomp/
├─ deploy/docker/
├─ scripts/
├─ compose.yaml
├─ compose.dev.yaml
├─ compose.prod.yaml
├─ .env.example
├─ .gitignore
└─ README.md
~~~

依赖安排：

- Web：React、React Router、TanStack Query、CodeMirror 6 只读查看器、Lucide；样式采用 CSS variables + CSS Modules，减少组件脚手架依赖。
- API/Worker：FastAPI、Uvicorn、Pydantic v2、pydantic-settings、HTTPX、SQLAlchemy 2 Core、Alembic、jsonschema。
- Validator：Node 24、TypeScript、parse5、PostCSS、Acorn、Playwright；只安装 Chromium。
- 测试：pytest、Vitest、Playwright。测试驱动与运行时检查使用一致的 Playwright 精确版本。
- 后端依赖使用 uv.lock，Node 包使用根 workspace 的 package-lock.json；提交锁文件，镜像锁定基础版本/digest。

Node 24 是有意选择的 LTS 基线，不是“最新版本”声明。首次实现时锁定兼容的精确依赖，记录在 README；不要将浮动 latest 标签作为生产版本。

## 6. 平台数据、访客身份与事务

### 6.1 SQLite 部署模式

数据库路径统一为 /var/lib/atoms/atoms.db。API、Worker 和迁移容器以相同非 root UID 访问同一个本地 Docker 命名卷。

首版采用 journal_mode=DELETE、synchronous=FULL、foreign_keys=ON、busy_timeout=5000。短事务、低并发下先简化运行基线。所有模型调用、浏览器检查、SSE 等待必须在数据库事务之外。

使用 SQLAlchemy Core 的显式连接和 UnitOfWork，不跨请求/线程共享连接。按官方 SQLite 事务说明，统一使用“禁用驱动隐式 BEGIN + begin 事件显式发出 BEGIN”的路径；写 UnitOfWork 使用 BEGIN IMMEDIATE，读事务使用 BEGIN。不得再混用 autocommit=False 的另一套事务控制。

WAL 仅为后续可选优化。启用前必须检查实际 SQLite 运行库已包含 WAL-reset 修复，例如 3.51.3+ 或官方列出的修复回移版本；不能仅检查 Python 版本。依据见第 24 节 SQLite 来源。

限制：SQLite 卷只部署在单个 ECS 本地磁盘上；不用 NAS/NFS 挂载数据库，不把同一文件挂到多台主机。

### 6.2 表与约束

统一使用 UUID 字符串 ID、UTC 时间、JSON 文本字段。JSON 字段在服务层进行严格 Schema/大小校验。

| 表 | 主要列 | 必需约束/索引 |
| --- | --- | --- |
| visitors | id、cookie_token_hash、created_at、expires_at | token hash 唯一；不存原始 cookie |
| projects | id、visitor_id、client_key、name、revision、current_version_id、active_run_id、created_at、updated_at | visitor_id+client_key 唯一；revision 初始 0；版本归属在事务中校验 |
| messages | id、project_id、run_id、role、content、created_at | project_id+时间索引；不存模型私密推理 |
| runs | id、visitor_id、project_id、kind、prompt、base_version_id、base_revision、retry_of_run_id、status、stage、lease_token、lease_expires_at、heartbeat_at、deadline_at、attempt_count、result_version_id、error_code、error_message、created_at、started_at、finished_at | 活动状态部分唯一索引；状态/创建时间索引 |
| run_events | run_id、seq、type、stage、data_json、created_at | 主键 run_id+seq；只追加；每个 seq 单调递增 |
| request_keys | visitor_id、idempotency_key、request_hash、run_id、created_at | visitor_id+key 唯一 |
| artifacts | id、digest、files_json、body_html、css_base64、js_base64、compiler_version、sdk_version、created_at | digest 包含产物和编译版本；内容不可原地覆盖 |
| versions | id、project_id、number、parent_version_id、source_run_id、artifact_id、title、summary、validation_json、created_at | project_id+number 唯一；source_run_id 唯一 |
| project_actions | id、project_id、visitor_id、type、from_version_id、to_version_id、revision、created_at | 记录恢复操作；不伪造一次模型 Run |
| app_states | project_id、namespace、revision、values_json、updated_at | project_id+namespace 唯一；namespace 首版固定 default |
| quota_windows（0001 遗留） | 历史次数窗口 | 不再用于限制生成；积分由 credit_wallets/model_calls/credit_ledger 管理 |
| worker_status | singleton_key、boot_id、leader_token、lease_expires_at、heartbeat_at、current_run_id、model_configured、model_display_name、contract_version | 单例 codegen；限定一个有效执行者，提供不含密钥的就绪信息 |
| system_settings | key、value_json、updated_at | 仅运维 CLI 修改；首版用于 maintenance 标志 |

SQLite 迁移中创建：

~~~sql
CREATE UNIQUE INDEX uq_one_active_run_per_project
ON runs(project_id)
WHERE status IN ('pending', 'running');
~~~

projects.current_version_id 始终指向已通过基础启动检查的不可变版本。所谓“最后可用版本”在首版即当前稳定引用；最新生成的版本号可从版本表独立计算。恢复 V1 后，V2 保留，后续可产生 parent=V1 的 V3。

循环引用外键（project.current_version、active_run）通过后续迁移/可空列和事务顺序处理；同时必须有归属检查，不能仅依赖外键确认版本属于同一项目。

### 6.3 匿名会话

1. 浏览器同源调用 POST /api/v1/session；服务端发放至少 256 bit 的随机令牌。
2. cookie 为 HttpOnly、Path=/、host-only、SameSite=Lax；生产启用 Secure。开发 HTTP 只允许本地 origin。
3. cookie 的 SHA-256 hash 查找 visitor；expires_at 和 cookie 默认均为 30 天，不因重开标签页更换身份。
4. CSRF token 由服务端密钥与 cookie 派生，session 响应返回给同源工作区内存；多个标签页不会互相使 token 失效。
5. 修改接口要求精确匹配的 Origin、application/json、X-App-Request: 1 和 X-CSRF-Token。拒绝 Origin:null。
6. session 创建接口不要求已有 CSRF token，但仍要求同源 Origin、自定义请求头和 JSON。
7. 所有项目/Run/版本/存储请求按 visitor 过滤；未知或非本人资源统一返回 404。visitor_id 请求参数不是授权依据。
8. API 不对任意 Origin 开 CORS；前端和 API 通过 Gateway 同源。

cookie 丢失、更换浏览器、从 localhost 改为云端域名会产生新身份。默认不提供账户恢复或跨设备同步。数据卷保留保证同一站点/会话下的进程重启与应用升级不丢数据，不能把它描述为跨域身份迁移。

## 7. HTTP 接口契约

业务接口统一前缀 /api/v1；表中的 /session、/projects 等为相对路径，/sandbox/* 与 /health/* 为绝对路径。字段使用 snake_case。错误响应：

~~~json
{
  "error": {
    "code": "PROJECT_BUSY",
    "message": "当前项目仍在生成，请等待完成。",
    "request_id": "uuid",
    "details": { "active_run_id": "uuid" }
  }
}
~~~

只返回可向当前用户披露的 details，不透传提供商原始响应、Authorization 或堆栈。

| 方法与路径 | 输入/输出摘要 | 事务或边界 |
| --- | --- | --- |
| POST /session | 返回 visitor_id、csrf_token、有效期；设置 cookie | 匿名创建/复用身份 |
| GET /capabilities | configured、read_only、supported_artifact、limits、selected_features | 不返回密钥或内部 URL |
| GET /projects | cursor、limit；返回本访客项目摘要 | limit 默认 20，上限 50 |
| POST /projects | client_key 必填、name 可选；返回 revision=0 的项目 | 按 visitor+client_key 幂等创建，不调用模型 |
| GET /projects/{id} | 项目、当前版本、active_run 摘要 | 所有权校验 |
| GET /projects/{id}/messages | cursor、limit | 按创建顺序分页 |
| POST /projects/{id}/runs | 见 7.1；返回 202 和 Run | 幂等、配额、版本条件一次提交 |
| GET /runs/{id} | 状态、阶段、基础版本、结果、last_event_seq | 重连后的真实状态来源 |
| GET /runs/{id}/events | SSE；after 或 Last-Event-ID | 重放已落库事件 |
| GET /projects/{id}/versions | number、id、时间、摘要、是否当前 | 不随列表下载所有源码 |
| GET /versions/{id} | 三文件、摘要、校验结果、版本号 | 所有权校验；只读 |
| POST /projects/{id}/restore | target_version_id、expected_revision | 无活动 Run；恢复引用并记审计 |
| POST /versions/{id}/preview-ticket | 返回 iframe_url、instance_id、channel_nonce、expires_at | 校验所有者；短期票据 |
| GET /sandbox/versions/{id}?ticket=... | 返回受控 HTML 与 CSP | 非 JSON 路由；已授权签发的短期单版本只读票据，另校验 iframe 请求上下文 |
| GET /projects/{id}/app-state | 返回 revision、values | 宿主调用；iframe 不直接调用 |
| PATCH /projects/{id}/app-state | expected_revision、set、remove | 原子更新 KV，超限拒绝 |
| GET /versions/{id}/export | 下载 ZIP | 路径/内容仅来自允许的产物 |
| GET /health/live | 进程存活 | 不返回配置 |
| GET /health/ready | DB 迁移状态、Worker 心跳、Validator 可达、模型是否配置 | 配置缺失返回不可生成状态；模型连通不每次收费探测 |

浏览器运行时错误首版进入本地预览错误面板，不自动改变服务器 Run 终态。诊断持久化不是本次额外必做项。

### 7.1 创建/重试 Run

请求头 Idempotency-Key 为浏览器生成的 UUID，直到收到确定结果前重试复用同一个键。

~~~json
{
  "kind": "generate",
  "prompt": "创建一个可以添加和筛选任务的中文看板",
  "base_version_id": null,
  "expected_revision": 0,
  "retry_of_run_id": null
}
~~~

kind 为 generate、modify、retry。修改与重试明确绑定当前版本；重试引用原失败 Run 只为关联记录，UI 必须说明按当前稳定版本重试，不能悄悄沿用已经过时的基础版本。

返回：

~~~json
{
  "run": {
    "id": "uuid",
    "status": "pending",
    "base_version_id": null,
    "base_revision": 0,
    "last_event_seq": 1
  },
  "events_url": "/api/v1/runs/uuid/events"
}
~~~

写事务顺序：

1. 先按 visitor+Idempotency-Key 查找已存在记录；请求 hash 一致则返回相同 Run，不再次扣额度。hash 不同返回 409 IDEMPOTENCY_KEY_REUSED。
2. 校验 project 所有权、expected_revision、base_version_id 和是否有活动 Run。
3. 校验输入及额度；创建用户消息、pending Run、accepted 事件、幂等记录并设置 active_run_id。
4. 一次提交后返回 202。不在此等待模型或浏览器检查。

expected_revision 不匹配返回 409 STALE_PROJECT；客户端刷新项目后让用户重新提交。活动 Run 冲突返回 409 PROJECT_BUSY 并带该用户可见的 active_run_id。

### 7.2 SSE 协议

~~~text
id: 12
event: stage
data: {"run_id":"uuid","seq":12,"stage":"browser_check","status":"running","message":"正在检查预览启动"}

id: 13
event: completed
data: {"run_id":"uuid","seq":13,"status":"succeeded","version_id":"uuid","project_revision":2}
~~~

事件类型固定为 accepted、stage、completed、failed、interrupted。事件来自真实动作：read_context、generating、validating、repairing、browser_check、committing。

- 新连接以 query after 恢复；浏览器自动重连优先使用合法 Last-Event-ID；seq 必须为非负整数。
- 每次先读取 seq>cursor 的事件；客户端按 run_id+seq 去重。事件和其状态变化同事务保存。
- 最多每 0.5 秒短查询一次数据库，查询结束立即释放连接；15 秒发一次 SSE 注释心跳，心跳不落库。
- 已有终态事件投递后关闭连接；客户端收到终态后主动关闭 EventSource，防止无意义重连。
- 事件连接失败时先 GET Run，再按游标重连；不能重新 POST 一个新 Run。
- 单访客最多 3 条 SSE 连接；同一工作区组件切换时销毁旧订阅。
- Gateway 对 SSE 关闭 proxy_buffering，发送 X-Accel-Buffering:no、Cache-Control:no-cache，读超时 75 秒，心跳保持连接。

## 8. Worker 与有界 Code Agent

### 8.1 实际执行流程

~~~mermaid
stateDiagram-v2
    [*] --> pending
    pending --> running: 原子领取并设置租约
    running --> succeeded: 校验通过且事务提交
    running --> failed: 明确失败或总超时
    running --> interrupted: 租约失效且执行不可恢复
    pending --> interrupted: 排队超时或停机恢复判定
    succeeded --> [*]
    failed --> [*]
    interrupted --> [*]
~~~

默认控制值见第 15 节。Worker 按 created_at 领取最早 pending Run，使用 BEGIN IMMEDIATE 和条件更新一次完成领取；设置随机 lease_token、heartbeat、lease_expires_at、deadline_at。

Worker 启动先条件领取 worker_status 的单例租约；已有有效执行者时等待或退出，不并行启动第二条生成链。空闲时也持续更新心跳和 model_configured。创建 Run 前 API 检查近期 Worker 状态；缺少模型配置或 Worker 不可用时返回 503，不先扣额度排队。Run 提交同时要求当前 Worker 仍持有单例租约。

模型请求等待期间由独立异步心跳任务维护租约；心跳使用短数据库操作。API 的异步 SSE/定时恢复检查将同步数据库查询放到工作线程，避免 SQLite 等待阻塞事件循环。

执行顺序：

1. read_context：读取基础版本的全部三文件、项目摘要和有限最近消息，随后释放数据库连接。
2. generating：构造明确的生成/修改提示，调用配置的模型适配器。
3. validating：严格 JSON、Schema 和尺寸校验；通过后发 browser_check 阶段事件，调用一次 Validator 完成能力范围解析及基础启动检查。
4. repairing：若格式、产物、浏览器检查或主 Agent 审核未通过，携带候选、具体反馈和原始目标自动修复。修复稿重新检查，最多修复 3 轮。第三轮游戏通过编译和启动、未捕获运行异常时，可交付输入结果未确认的版本。
5. 检查交付条件：最终候选必须已有通过报告；每个候选只调用一次 Validator，不对已经通过的同一候选重复启动检查。最终仍失败则明确终止。
6. committing：重新确认 Run 仍由当前租约持有且未超时，执行 8.3 的交付事务。

这是单个有界 Code Agent：模型生成/修改，程序执行实际校验并向模型反馈错误；阶段及工具记录是真实编排。首版不显示虚构的产品经理/架构师交接，也不安装通用 Agent 框架。

### 8.2 租约、超时和故障恢复

- 实际执行并发=1，heartbeat 每 5 秒更新，租约 30 秒。API 定期做短事务过期检查，Worker 启动也执行同一检查。
- 过期回收必须在写锁内再次校验 deadline/lease；不能根据之前的陈旧查询结果直接回收。
- 总执行截止默认 3600 秒，单次模型读取默认 1500 秒，支持长代码生成；排队等待最多 3600 秒。明确超时记 failed/TIMEOUT；失去执行者记 interrupted/WORKER_LOST。缺少 usage 的已发送调用冻结预授权待核对。
- pending Run 可在 Worker 重启后继续领取；已经 running 的过期 Run 不自动重放模型调用，转 interrupted，用户显式重试。
- 所有 heartbeat、阶段写入和交付更新要求 status=running 且 lease_token 匹配；旧执行者即使晚返回也不能提交。
- 网络断开不改 Run 状态。API 重启后 SSE 仍可读取历史；Worker 重启后按租约规则处理。
- 收到 SIGTERM 后 Worker 停止领取，尝试在 stop_grace_period 内结束当前工作；如取消本地调用则记录 interrupted，不宣称已撤销提供商已开始的计费。
- failed/interrupted 也必须一次事务写终态、失败摘要和事件，并仅在 active_run_id 匹配时清空项目活动引用；不改变当前稳定版本或 revision。pending 超时同样释放引用。

### 8.3 成功交付事务

在进入事务前，Validator 已返回通过及完整规范化产物。事务内：

1. 核验 Run 租约、status、deadline、project.active_run_id。
2. 核验 project.revision==run.base_revision 且 current_version_id==base_version_id。
3. 保存不可变 Artifact，创建新 Version，number 为项目内下一个序号，parent 指基础版本。
4. 更新项目 current_version_id、revision+1、updated_at，清空 active_run_id。
5. 写入完成摘要消息、completed 事件并将 Run 设 succeeded/result_version_id。
6. 提交后前端才可读取新版本；失败时整笔回滚，不能只推进当前版本指针。

保存的是“通过固定基础启动检查的可交付版本”，不是“证明所有业务功能正确”。用户浏览器自己的加载/运行错误另外显示，不反向篡改已完成的执行历史。

### 8.4 模型适配

第一版实现一个可配置的 Chat Completions 兼容 HTTP 适配器，接口为 generate_artifact(context, budget) → raw_content+usage+provider_request_id。若使用 OpenAI 官方接口，后续可新增 Responses 适配器；当前兼容层选择不代表所有厂商支持相同参数。

配置：LLM_BASE_URL、LLM_MODEL、LLM_API_KEY、LLM_RESPONSE_MODE、LLM_TOKEN_LIMIT_PARAM，以及模型能力元数据/回退值和长任务超时。删除 LLM_MAX_OUTPUT_TOKENS=8192 和 LLM_CONTEXT_BUDGET=64000；输出 token 参数由供应商原生能力与钱包可用积分动态计算。API Key 只注入 Worker，适配器只追加一次 /chat/completions。

- response mode 为 json_schema、json_object、text 三选一；按提供商实际能力配置，不在失败后连续盲试所有模式。
- 使用 json_schema 时采用官方支持的 Schema 子集；json_object/text 下仍必须服务端严格校验。JSON 合法不等于满足本项目 Schema。
- stream=false，SSE 展示工作流阶段而非尚未校验的源码片段。
- 不默认发送 temperature/reasoning 参数；只有接入服务明确支持且已经验证时配置。
- output token 参数允许 max_tokens 或 max_completion_tokens，不能同时发送；由选定服务决定。
- 首稿之外最多 3 轮自动修复。用量不确定的供应商请求按现有账本保留预授权并结束当前任务。
- 401/403 为配置失败，429/5xx/网络错误明确失败；服务端错误不得暴露完整上游 URL、请求体和凭据。
- 拒绝、截断、空内容、不支持的内容返回及 JSON 错误分别编码；截断不被当作完整源码提交。

上下文固定包含：支持范围、产物 Schema、可信 storage SDK 契约、当前完整三文件、此次用户需求、最近至多 6 条消息及版本摘要。修改以基础代码为准；不把历史产物作为系统权限指令。超过上下文预算时返回 CONTEXT_TOO_LARGE，不静默截断当前源码。

实现前以所选模型做一次小型协议试验，验证参数、输出长度、响应格式和超时；模型名及额度未提供时可继续实现模块和非付费测试，但真实生成验收保持未完成。

## 9. Validator 与预览安全契约

本模块是先验证的基础设施，不能等业务页面完成后才补。生成代码仅在用户的受限 iframe 与隔离的检查容器中的 Chromium 执行。

### 9.1 私有服务接口

POST /internal/validate，只接受固定 JSON 契约：

~~~json
{
  "request_id": "uuid",
  "artifact": { "schema_version": "1", "title": "...", "summary": "...", "files": {} },
  "compiler_version": "1",
  "sdk_version": "1"
}
~~~

通过时返回 ok=true、digest、规范化 body_html、css_base64、js_base64、版本信息和检查报告。失败返回 ok=false、error_code、限长 diagnostics；禁止返回本机文件路径、环境变量和任意浏览器内部数据。

Validator 只在私有网络监听；不做公网映射。使用服务间随机 token 校验，token 不传入 Chromium。HTTP 总超时 15 秒，单次检查进程硬上限 12 秒，同一时刻最多一个检查，超限返回 VALIDATOR_BUSY。

### 9.2 解析和编译

顺序固定：

1. 使用同一 Artifact Schema 校验文件集合及字段；检查大小、UTF-8 内容与空产物。
2. parse5 解析 HTML、提取 body，按允许集合重建节点，拒绝不支持的主动内容，不用正则表达式充当 HTML 安全解析器。
3. 允许常见静态布局、文字、表单控件、列表、表格及 canvas。允许普通 class/id/data/aria 属性及受控 style 属性。
4. 拒绝 script、iframe、object、embed、link、base、meta refresh、srcdoc、on* 事件属性及 javascript: URL。SVG 主动标记首版不支持；使用 CSS 或文字图标。
5. URL 属性只允许页内 hash 与受支持的 data:image 图片；不允许外部地址、srcset、form action、target 或下载导航。表单由 app.js 处理本地交互，使用 `type="button"` 的点击和输入框 Enter 键调用同一处理函数。预览 iframe 的 sandbox 禁用表单提交，浏览器会在派发 `submit` 前终止原生提交流程。
6. PostCSS 检查 CSS 语法，拒绝 @import 及未支持的外部资源；运行时 CSP 仍是网络访问约束，不能只依赖字符串规则。
7. Acorn 按 ECMAScript 2022 script 模式解析 app.js；拒绝 import/export、动态 import 和顶层 await。平台不调用 eval/Function 执行模型代码。
8. 输出规范化 body_html，以及 CSS/JS 的 UTF-8 Base64；digest 包含原始三文件、compiler_version 和 sdk_version。

生成 CSS/JS 不直接插入 style/script 原始文本块，避免内容中的闭合标签改变文档结构。可信 runtime 和生成 app.js 都通过 data URL 脚本加载，CSS 通过 data URL 样式表加载；CSP 仅允许 data: 脚本源，不允许外部脚本源或 inline/eval。这项组合必须在 M0 通过实际 Chromium 试验。

本方案不使用可被同一 iframe 内不可信脚本读取、复用的 script nonce 来允许任意脚本地址。允许执行 data: 脚本是有意授予沙箱内本地代码执行能力，不授予其平台 DOM、凭据或 HTTP 脚本访问能力。

如果发现不支持内容，明确拒绝并将诊断传给自动修复。不得静默删除业务脚本后仍把空页面算成功。

### 9.3 用户浏览器中的受控文档

React 创建 iframe：

~~~html
<iframe sandbox="allow-scripts" referrerpolicy="no-referrer" title="应用预览"></iframe>
~~~

不设置 allow-same-origin、allow-forms、allow-popups、allow-top-navigation、allow-downloads。iframe 使用 /sandbox/versions/{id}?ticket=... 的响应，不把生成 HTML 放进工作区 DOM。

服务端在签发预览票据时生成 instance_id 和 channel_nonce，文档响应使用已验证票据中的同一组值，与工作区拿到的值保持一致；重新加载时签发新票据。可信配置使用 head 内固定名称的 meta 元素保存 Base64 编码 JSON，由可信 runtime 读取；不把生成代码插入配置字符串。响应头的设计基线：

~~~text
Content-Type: text/html; charset=utf-8
Cache-Control: no-store
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
Content-Security-Policy:
  sandbox allow-scripts;
  default-src 'none';
  script-src data:;
  style-src 'unsafe-inline' data:;
  img-src data: blob:;
  connect-src 'none';
  font-src 'none';
  media-src 'none';
  worker-src 'none';
  frame-src 'none';
  object-src 'none';
  base-uri 'none';
  form-action 'none';
  frame-ancestors <APP_ORIGIN>;
~~~

其中 <APP_ORIGIN> 必须替换成实际精确 origin。HTTP 的 sandbox 指令不能用 meta 标签代替。

工作区页面的 CSP 限制 frame-src 'self'、object-src 'none'、base-uri 'self'；正式构建不允许任意 inline/eval 脚本。开发 HMR 所需例外仅在开发配置中启用。不得把工作区的 CSP 直接覆盖到沙箱响应，否则会错误阻断其受控脚本。

预览票据：

- 由已经通过项目所有权检查的 preview-ticket 接口签发；包含 version_id、artifact digest、instance_id、channel_nonce、exp，并做 HMAC。
- 默认有效期 120 秒，只有读取该版本文档的权限，不包含平台会话令牌或访问其他接口的能力。
- 文档导航不依赖第三方/沙箱 cookie 行为；主业务 API 的身份验证仍使用 HttpOnly cookie 和 CSRF。
- /sandbox 响应只接受浏览器 iframe 导航上下文（Sec-Fetch-Dest=iframe，且父页面发起的同源上下文）；直接顶层打开返回普通错误，不提供不受 iframe 约束的 HTML。
- Gateway 不记录票据 query；票据不能用于读取聊天或 app-state。版本 ID 被替换后签名校验失败。
- 刷新预览由工作区申请新票据并重建 iframe；不依赖子页面自行 reload。

即使有这些边界，也不承诺在同一个用户浏览器内实现恶意 JavaScript 的独立 CPU/进程配额。检查端有硬超时；用户预览提供重新加载入口。更强的公共任意代码托管不属于当前范围。

### 9.4 基础浏览器检查

Validator 的检查流程使用与实际预览一致的编译结果和 runtime SDK：

1. 固定 Node 父进程启动固定检查子进程，产物通过受限 stdin/IPC 传递，不插入 shell 命令或启动参数。
2. 子进程启动 Chromium，使用非 root 用户、Chromium sandbox、经审核的 seccomp 配置。不得用 --no-sandbox 或 privileged 绕过失败。
3. 创建独立 BrowserContext，禁用 service worker。拦截网络，只通过 route.fulfill 提供以 APP_ORIGIN 为 origin 的两个固定虚拟 URL：可信父页面和候选 iframe；不实际请求该站点或 API。
4. 其他 HTTP(S) 请求全部中止；阻断 WebSocket；CSP 禁止外联、worker、弹窗及导航逃逸。检查端没有模型密钥、数据库挂载或宿主 Docker socket。
5. 父页面用内存 app-state 完成同一 MessagePort 初始化；启动生成 app.js。
6. 等待可信 runtime.ready、非空可见内容，以及短暂启动稳定窗口；采集 pageerror、unhandledrejection、CSP/资源阻断和基础超时。
7. 基础错误失败，输出具体诊断。console.error 可作为诊断，不能仅因为存在一条普通日志就伪造完整业务失败结论。
8. 总硬超时由父进程执行，清理检查子进程及其浏览器进程组；init 负责回收僵尸进程。

检查证明“能按当前支持约束启动并渲染”，不证明任务看板的所有功能正确。AT-001、AT-002 仍需实际交互验证。

容器采用自建 Node + Playwright/Chromium 镜像，固定浏览器版本，设置 non-root、init、只读根文件系统、tmpfs、资源限额及独立共享内存。官方测试镜像的默认 root/测试配置不能原样当作不可信代码生产隔离方案。若当前主机不能启动所需沙箱，M0 失败，先解决运行环境，不能悄悄降低隔离。

## 10. 生成应用的存储 SDK

### 10.1 固定公开接口

~~~javascript
const items = window.atoms.storage.get("tasks", []);
window.atoms.storage.set("tasks", [...items, { id: crypto.randomUUID(), title: "学习", done: false }]);
window.atoms.storage.remove("temporary");
await window.atoms.storage.flush();
~~~

- get 同步读取已初始化的内存快照，返回深拷贝；set/remove 同步更新副本并排队保存；flush 等待此前写入获得保存确认。
- 只接受可 JSON 序列化值。key 长度 1～64，限制为明确字符集并拒绝 __proto__、constructor、prototype；实现使用 Map 或无原型字典。
- 每项目默认 128 个 key，总 JSON UTF-8 大小 64 KiB、单值 16 KiB。
- SDK 只提供存储和必要运行反馈，不提供任意 URL 请求、平台 API 代理、文件读写或执行命令。
- 代码提示要求使用 SDK，不使用 iframe localStorage、cookie、IndexedDB。读初始数据前不启动 app.js。

### 10.2 宿主桥

1. iframe 文档先只运行可信 runtime；生成 app.js 暂不启动。
2. React 根据自己绑定的 project/version/instance 获取 app-state，创建 MessageChannel。
3. 对该 iframe.contentWindow 发送一次 init 和 port2。由于接收端是 opaque origin，这一次传递使用 targetOrigin="*"；目标窗口引用必须是本实例，并携带 channel_nonce。
4. runtime 核对 event.source===window.parent、event.origin===配置的 APP_ORIGIN、instance/nonce 和消息格式；完成后只使用收到的 MessagePort。
5. 宿主端口只接受 storage.set、storage.remove、storage.flush、runtime.ready、runtime.error。project_id、URL、权限从宿主绑定信息取得，忽略 iframe 提供的同类字段。
6. runtime 在 DOM 和初始快照就绪后，通过 data URL 加载 app.js，脚本加载完成后报告就绪。生成提示明确 app.js 此时应直接初始化，或按 document.readyState 分支；不能只订阅已经发生的 DOMContentLoaded/load。工作区独立显示 loading/ready/failed。
7. 项目或 iframe 切换时关闭端口和监听器；旧 instance 的消息不再处理。

桥接消息含 protocol_version、instance_id、message_id、type 和经 Schema 验证的 payload。超限消息拒绝；错误文本限长并脱敏。端口只允许当前项目已授权的数据操作，不把 CSRF token、cookie 或模型配置交给 iframe。

### 10.3 保存、并发与版本行为

- 数据按 project_id+namespace=default 保存，跨同一项目的代码版本共享；不跨项目、访客或站点共享。
- 宿主串行合并写操作，100ms 内可合并一次，调用 PATCH app-state 时带 expected_revision；服务端按 revision 条件原子更新。
- 保存确认前显示“保存中”，确认后显示“已保存”；失败和 409 冲突显示“尚未保存”，保留本地待处理内容，不静默覆盖其他标签页修改。
- 冲突后读取新快照并明确提示重新操作；首版不实现自动业务级合并。
- 新生成/恢复版本前先 flush 当前待保存内容。代码恢复不回滚业务数据；字段兼容性由应用逻辑处理，不做隐式清空。
- 历史版本预览绑定只读桥，set/remove 返回只读错误；恢复为当前版本后重新创建可写实例。
- app-state 保存已确认后，刷新同一版本应保留记录。生成版本的基础检查使用空的内存快照，不读取真实业务数据。

由此实现 FR-012 和 AT-011 的明确边界：同一站点、同一访客、同一项目内持久化；跨版本共享但无自动 schema 迁移或数据回滚。

## 11. 历史恢复与源码导出

### 11.1 FR-105 恢复

历史列表展示版本号、摘要、时间、当前标记，允许查看目标代码和只读预览。

POST restore 的事务：

1. 校验 owner、expected_revision、无活动 Run，确认目标版本属于项目。
2. 将 current_version_id 指向目标，revision+1，写 project_actions 审计记录。
3. 返回新的项目摘要；不创建模型 Run，不扣模型额度，不删除较新版本。
4. UI 关闭旧预览端口，为恢复版本重新加载 app-state 和可写预览；后续 Run 的 base_version 指向恢复目标。

已是当前版本时返回幂等成功和 unchanged=true，不产生重复审计记录。存在活动 Run 返回 PROJECT_BUSY，过期 revision 返回 STALE_PROJECT。

### 11.2 FR-109 导出

导出 ZIP 至少包含：

~~~text
index.html                 # 增加受控的 CSS、SDK、JS 资源引用
styles.css                 # 版本中的原始内容
app.js                     # 版本中的原始内容
atoms-runtime.js           # 独立 localStorage 适配器，不含平台桥和凭据
source/index.html          # 版本中的原始 HTML
artifact.json              # 版本、三文件及摘要、内容 hash
README.md
~~~

导出生成的顶层 index.html 复用已验证的 body；README 说明增加了独立运行包装。CSS/JS 保持原样，原始 HTML 在 source 中保留，不能导出另一个版本的代码。

独立 SDK 使用相同 get/set/remove/flush 接口，保存到当前浏览器 origin 的 localStorage，namespace 包含项目 ID。默认不导出用户业务记录、对话、运行日志和服务端配置。

README 指导在专用本地目录通过 HTTP 静态服务运行，例如 python -m http.server 8081；不保证 file:// 的存储行为。部署导出应用使用独立 origin，不把不可信导出代码挂在平台工作区同源路径。

后端使用标准 ZIP 库在大小受限的内存中打包固定路径；Content-Disposition 为 attachment，文件名经清理，无 Zip Slip 路径。

## 12. 前端页面与状态组织

### 12.1 页面

| 路由 | 内容 |
| --- | --- |
| / | 产品介绍、明确的支持范围、需求输入、示例、项目列表 |
| /projects/:projectId | 左侧项目导航，中间对话与阶段，右侧预览/代码；顶部项目名、当前版本、历史及导出 |
| 404/错误边界 | 可理解错误和返回入口，不泄露内部堆栈 |

初次从首页提交需求：先创建项目，再以持久的 Idempotency-Key 创建 Run，再导航到工作区；保存未确认请求的键，网络结果未知时先查询/幂等重试，不再创建另一个项目。可将 pending 创建流程在客户端 sessionStorage 中记录，仅用于网络恢复，业务记录仍在服务端。

### 12.2 状态归属

- 服务端状态：项目、消息、Run、事件、版本、app-state，由 TanStack Query 缓存。
- UI 状态：当前文件、预览宽度、展开阶段、历史面板、本地待提交 prompt，由 React 状态管理。
- SSE：只有工作区 Run 订阅器持有连接；终态后刷新项目、消息、版本查询，并关闭连接。
- 预览：以 project_id+version_id+instance_id 为 key；生成期间继续显示当前稳定版本，不显示尚未检查的候选代码。
- 代码：CodeMirror 只读、按文件类型配置高亮；不把查看器误做成手动编辑功能。
- 错误：统一 API error code 到中文反馈；403、404、409、422、429、503 有区别。

### 12.3 视觉和交互完成标准

采用完整的应用工作台布局：稳定导航、清晰的主操作、真实阶段时间线、可辨认的版本和预览边界。界面文案面向用户，不展示内部数据库、队列或容器术语。

必须覆盖：首次空状态、模型未配置、pending、running、有旧结果的生成中、首次生成失败、修改失败、预览加载/错误、存储保存失败、历史恢复冲突及导出中。

在 1280×720 和 1440×900 验证工作区；预览宽度可切换 desktop/390px。代码区域横向滚动不导致整页溢出，输入框和生成按钮保持可见。

## 13. 错误、额度与日志

### 13.1 错误码

| 错误码 | 含义/处理 |
| --- | --- |
| INVALID_INPUT / INPUT_TOO_LARGE | 客户端修正输入，不创建 Run |
| UNAUTHENTICATED / CSRF_REJECTED | 重新初始化本站会话；不自动重新生成 |
| NOT_FOUND | 项目不存在或非本人资源 |
| PROJECT_BUSY / STALE_PROJECT | 展示活动任务或刷新版本后重新提交 |
| IDEMPOTENCY_KEY_REUSED | 相同键对应不同请求，修正客户端逻辑 |
| MODEL_NOT_CONFIGURED / MODEL_AUTH_FAILED | 明确不可生成/配置错误，已有项目可读取 |
| MODEL_UNAVAILABLE / MODEL_RATE_LIMITED | 明确上游失败，不连续自动请求 |
| MODEL_REFUSED / MODEL_OUTPUT_TRUNCATED | 说明拒绝或超出生成限制，保留稳定版本 |
| ARTIFACT_INVALID / UNSUPPORTED_ARTIFACT | 进入最多一次校验修复，仍失败则结束 |
| PREVIEW_START_FAILED / VALIDATOR_UNAVAILABLE | 基础预览失败或检查服务异常，不推进版本 |
| CONTEXT_TOO_LARGE / RESOURCE_LIMIT | 减小范围或由操作者调整明确配置 |
| APP_STATE_CONFLICT / APP_STATE_TOO_LARGE | 保留待保存数据，提示未保存及限制 |
| TIMEOUT / WORKER_LOST | failed 或 interrupted；允许显式重试 |

### 13.2 匿名积分预算

首次赠送 500 积分，显示价值 50 元；输入每百万 token 20 积分、输出每百万 token 80 积分。以供应商真实 usage 结算，预授权防止并发超支，异常缺失 usage 则待核对。具体实现见第 26 节。

移除每小时/每天次数配额，以及 8 项目/20 版本的商业限制。一个项目仍只允许一条活动 Run，真实并发仍为单 Worker；这是执行一致性机制。沙箱、HTTP 大小和超时是独立的技术保护，不冒充用户套餐。

### 13.3 日志

JSON 日志至少包含 timestamp、level、request_id、run_id、project_id、stage、duration_ms、error_code、provider_request_id（可得时）、token usage（可得时）。

默认不记录完整 prompt、模型原始响应、cookie、CSRF token、preview ticket 或模型密钥。API 访问日志只记录路径模板及方法，不记录 /sandbox query。检查报告与 UI 输出限制长度。

## 14. 开发和生产的配置契约

所有变量由服务端配置读取；Vite 客户端仅获得公开 API 路径和构建标识。LLM_API_KEY 不使用 VITE_ 前缀。

| 变量 | 默认/要求 | 使用服务 |
| --- | --- | --- |
| APP_ENV | development / production | 全部可信服务 |
| APP_ORIGIN | 本地 http://localhost:8080；生产精确 HTTPS origin | API、Web、Validator runner 配置 |
| DATABASE_URL | sqlite:////var/lib/atoms/atoms.db | API、Worker、迁移 |
| SESSION_SECRET | 本地随机生成；生产至少 32 字节随机值且跨重启保持 | API |
| SERVICE_TOKEN | 私有 Validator 调用 token | API/Worker、Validator |
| COOKIE_SECURE | 本地 false，生产 true | API |
| LLM_BASE_URL | 提供商给出的兼容 API 基址 | Worker |
| LLM_MODEL | 实际可用的代码生成模型 | Worker |
| LLM_API_KEY | 实际密钥，只在本地/服务器受控配置中 | Worker |
| LLM_RESPONSE_MODE | text / json_object / json_schema，显式选择 | Worker |
| LLM_TOKEN_LIMIT_PARAM | max_tokens / max_completion_tokens，显式选择 | Worker |
| LLM_PROVIDER_MAX_OUTPUT_TOKENS | 能力元数据缺失时使用的原生能力回退；DeepSeek 为 393216，不是自定商业上限 | Worker |
| LLM_REQUEST_TIMEOUT_SECONDS / RUN_TIMEOUT_SECONDS | 1500 / 3600，防止长代码被旧短时限打断 | Worker / API |
| VALIDATOR_URL | http://validator:9000 | API/Worker |
| READ_ONLY_MODE | false；维护时 true，禁止新 Run/恢复/数据写入 | API |
| DATA_VOLUME_NAME | 生产 atoms_data；本地生产检查和恢复试验指定独立名称 | Compose |

模型配置字段在进程启动时允许为空，Worker 仍能启动并维护 configured=false 的心跳，平台可读取现有项目；真正创建 Run 前才执行完整模型配置检查。用户看见未配置状态，不能宣称真实生成验收已通过。

API、Worker、Validator 的 health 响应暴露 build/contract/sdk 版本；启动时校验契约兼容，避免仅更新一个服务造成产物包装失配。

## 15. 超时和资源默认值

| 配置 | 初始值 | 说明 |
| --- | --- | --- |
| prompt 最大字符 | 100000 | 输入实际 token 仍计费，不静默截断需求 |
| 公开 API / Validator 请求体 | 2 MiB / 32 MiB | 外层 Gateway 与内部进程同步设置 |
| 产物总大小/单文件 | 8 MiB / 4 MiB | 高于完整应用输出的旧限制，保留资源保护 |
| app-state 总大小/单值 | 64 KiB / 16 KiB | UTF-8 JSON 大小 |
| app-state key 数 | 128 | 可配置 |
| 同项目活动 Run | 1 | 数据库唯一索引兜底 |
| 实际模型并发 | 1 | 单 Worker |
| 模型 HTTP 连接/单次读取超时 | 10 秒 / 1500 秒 | 总 Run 截止另行生效 |
| Run 总执行时长 | 3600 秒 | 覆盖规划、实现、校验、审核与自动修复 |
| pending 最长等待 | 3600 秒 | 超限转可解释终态 |
| heartbeat / 租约 | 5 秒 / 30 秒 | 条件写入和条件回收 |
| Validator HTTP / 检查硬超时 | 15 秒 / 12 秒 | 父进程清理浏览器 |
| SSE 心跳 / Gateway 读超时 | 15 秒 / 75 秒 | 连接断开不取消任务 |
| preview ticket TTL | 120 秒 | 只控制文档重新加载；已加载实例的数据权限来自宿主桥 |
| Validator 容器预算 | 1 CPU、约 768 MiB、shm 256 MiB | M0 根据实际 Chromium 启动检查调整 |

资源数字是起始配置，不是未经测量的性能保证。真实模型和首次镜像下载时间单独记录。

## 16. 测试、验收和可复现验证

测试以需求中的 AT 场景为主，覆盖可能破坏交付的机制，不为每个展示组件编写镜像式测试。

### 16.1 必须有的自动验证

| 层次 | 核心验证 |
| --- | --- |
| 业务/数据库 | 所有权过滤、相同幂等键重放、不同请求键冲突、两个并发请求仅一个活动 Run、租约过期旧 Worker 禁止提交 |
| 一致性 | 成功交付事务整体回滚、修改失败保留版本、恢复后创建分支版本、重复事件不重复推进结果 |
| 产物/安全 | 路径/重复 JSON 键/主动 HTML/外部依赖被拒绝；JS 语法错误；脚本含闭合标签时包装不被突破 |
| Validator | 合法看板启动、空产物失败、未捕获错误失败、无限循环硬超时并清理、访问网络/宿主受限 |
| API | 跨访客项目/Run/版本拒绝，Origin:null 和错误 CSRF 被拒绝，伪造 ticket 拒绝，app-state CAS 冲突 |
| 前端集成 | Run 状态与禁用按钮、SSE 事件去重/重连、预览切换销毁旧端口、存储失败保留提示 |
| E2E | AT-001～AT-011 的可自动部分；数据库持久卷重启后仍可恢复 |

稳定 E2E 使用明确标记的测试模型适配器及固定 fixtures，验证流程机制；该适配器仅允许 APP_ENV=test，生产启动时检测到测试适配器必须失败。

### 16.2 真实模型验收

至少以实际配置模型完成：

1. AT-001：自然语言生成任务看板，真实添加、完成、筛选。
2. AT-002：增加优先级，验证原有交互仍可使用。
3. AT-003：刷新与关闭标签页后重新打开，代码与版本保留且不重复调用模型。
4. AT-005：另建计算器，验证项目隔离。
5. AT-009：恢复 V1 后继续修改，形成新分支版本。
6. AT-010：下载导出包，以独立 HTTP 静态服务实际运行。
7. AT-011：记录保存确认后刷新预览，业务数据保留。

受控失败使用测试注入或本地测试服务，不通过耗尽额度制造失败。AT-006、AT-007 需验证 Worker 进程停止/重启与 API/SSE 重连，保留实际终态和日志。

在 docs/verification.md 记录命令、环境、模型标识、场景、结果、失败原因和已知限制，不记录密钥或隐私数据。截图可辅助证明 UI，但不能代替交互验收。

### 16.3 完成门槛

- P0 与选入的两项 P1 可逐项映射到实现和实际验收。
- 当前浏览器真实加载失败时不会继续显示成功预览；失败运行不覆盖最后稳定版本。
- 同站点会话与数据库卷保留时，容器重启/升级不丢项目和已确认的业务数据。
- 真实模型验收、隔离验证和源码运行验证完成后才能标记“本地完成”。
- ECS 上重复最重要的真实流程后才能标记“在线部署完成”。

## 17. 实现里程碑与退出条件

所有任务初始未完成。后续 AI 按阶段更新复选框，并在 verification.md 附证据；完成代码不等于完成阶段验收。

### M0：先验证运行和隔离方案

需求：FR-004、FR-007、NFR-003、NFR-005。

- [ ] 确认 Docker Desktop Linux 容器可用，锁定 Node/Python/Chromium 精确版本。
- [ ] 创建受限 Validator 最小镜像，验证 non-root Chromium sandbox。
- [ ] 用标记为测试的 fixture 跑通三文件解析、规范化、CSP、真实 iframe 和 runtime SDK 初始化。
- [ ] 验证仅允许 data: 脚本的 CSP、data CSS 能执行，脚本中的闭合标签不改变父页面。
- [ ] 验证 parent DOM/cookie/API 不可读、外网阻断、无限循环超时清理。
- [ ] 锁定 Artifact 和桥消息 Schema，记录编译/SDK 版本。

退出条件：合法 fixture 可交互，隔离检查通过。若失败，修正具体机制并记录，不通过关闭 sandbox 解决。

### M1：数据、会话和项目骨架

需求：FR-001～FR-003、FR-010、NFR-004、DATA-001～DATA-004。

- [ ] 建立 API/Worker 包、配置、日志、错误模型、事务帮助器和 Alembic。
- [ ] 实现会话/CSRF、所有权、capabilities、项目幂等创建和列表。
- [ ] 实现 Run 创建事务、活动 Run 唯一约束、幂等键和额度。
- [ ] 验证两个访客互不可读、同键重放和并发提交。

退出条件：重启后项目保留，请求真实持久化；无模型时明确未配置。

### M2：真实生成与后台执行

需求：FR-004、FR-005、FR-009、FR-011。

- [ ] 实现 Worker 单例租约、Run 领取、心跳、恢复和截止时间。
- [ ] 实现模型适配、上下文、Schema 校验和自动修复。
- [ ] 连接 Validator，完成交付事务、失败终态和事件记录。
- [ ] 实现 SSE 游标回放、去重和断线恢复。
- [ ] 模型配置可用时完成实际协议和生成验证；否则记录真实验收待补。

退出条件：任务不依赖浏览器连接，成功才推进版本，失败保留旧版本，旧租约不能提交。

### M3：可用的工作区闭环

需求：FR-001、FR-002、FR-005～FR-008、UX-001～UX-005。

- [ ] 完成首页、项目列表、工作区、真实阶段、代码查看、版本标识和错误状态。
- [ ] 绑定当前成功版本，签发票据、加载 iframe、管理 MessagePort 生命周期。
- [ ] 支持修改、预览重载和桌面/手机宽度切换。
- [ ] 验证 AT-001、AT-002、AT-004、AT-005。

退出条件：用户能从自然语言走到真实可操作结果并继续修改；无虚假进度和成功状态。

### M4：两层持久化及故障恢复

需求：FR-010～FR-012、NFR-002、AT-003、AT-006、AT-007、AT-011。

- [ ] 实现 app-state、KV SDK、CAS、保存确认和限额。
- [ ] 验证平台刷新/关闭重开、预览刷新后的数据恢复。
- [ ] 验证 API 重启、Worker 执行中重启、SSE 中断、模型失败。
- [ ] 版本更新/恢复不无提示清空业务记录。

退出条件：按声明边界持久化并恢复；异常不留下永久活动任务。

### M5：两项延展

需求：FR-105、FR-109、AT-009、AT-010。

- [ ] 历史列表、只读查看、恢复事务和审计。
- [ ] 固定 ZIP、独立 SDK、原始代码和运行说明。
- [ ] 验证恢复后分支生成、多个版本导出准确。
- [ ] 用独立 HTTP 静态服务实际运行导出包。

退出条件：两项延展真实可用，导出不混入工作中代码、凭据或另一版本。

### M6：本地生产形态与验收

需求：NFR-009、NFR-010、DEL-003～DEL-005。

- [ ] 完成 Dockerfile、Compose、Nginx 静态页面和 API/SSE/沙箱转发。
- [ ] 本地 production build 走通流程，开发和生产保持相同安全边界。
- [ ] 用真实模型执行第 16.2 节，补齐 README、配置样例和验证记录。
- [ ] 备份并在独立临时环境恢复，验证项目、版本和业务数据。
- [ ] 公开源码不含 .env、数据库、cookie、票据和密钥。

退出条件：本地生产模式、真实模型、恢复和导出有证据，可标记本地完成。

### M7：后续阿里云部署

前置：M6 完成，拿到第 23 节真实云端条件。用户当前要求规划，实施时按实际授权执行本阶段。

- [ ] 核实 ECS、地域、系统、架构、域名、HTTPS 和模型连通。
- [ ] 按第 19 节配置持久卷、变量、镜像、迁移和 Gateway。
- [ ] 验证安全组、容器端口、健康状态、SSE 和生产 CSP。
- [ ] 在线重复生成、修改、刷新恢复、保存业务数据、恢复版本和导出。
- [ ] 记录在线 URL、源码 URL、部署版本和验证结果。

退出条件：外部评审可访问，在线关键流程通过，不能以本地成功替代。

### 17.1 投入和范围控制

原题建议开发 6–8 小时。本方案包含独立浏览器检查、两层持久化和两项 P1，估算本地约 8–12 小时，云端约 1–2 小时；初次配置模型、镜像下载、账号/域名/备案等待另计。估算不是承诺。

先获得 M0→M4 的完整闭环，再完成 M5/M6。若真实时间缩短，记录延后的具体 P1，优先保留一项延展；不得移除真实生成、持久化、隔离或失败恢复来保持表面完成度。

## 18. 本地开发步骤

以下命令是实现后应可运行的目标，不要对不存在的文件执行。

### 18.1 前置条件

- Windows 工作区 D:/project/agent/atoms。
- Docker Desktop 启用 Linux 容器及 Compose 插件，具备足够内存和磁盘。
- 本项目配置存于 .env.local；不从其他项目或浏览器会话寻找、复制密钥。
- 主要运行路径是 Compose，不要求本机安装全部依赖。

### 18.2 开发命令契约

PowerShell：

~~~powershell
Copy-Item -LiteralPath .env.example -Destination .env.local
docker compose --env-file .env.local -f compose.yaml -f compose.dev.yaml build
docker compose --env-file .env.local -f compose.yaml -f compose.dev.yaml run --rm migrate
docker compose --env-file .env.local -f compose.yaml -f compose.dev.yaml up -d
docker compose --env-file .env.local -f compose.yaml -f compose.dev.yaml ps
~~~

先填写 .env.local；初始化工具生成本地随机 SESSION_SECRET 和 SERVICE_TOKEN，不将其打印到共享日志。

打开 http://localhost:8080。开发 Gateway 只绑定 127.0.0.1:8080：/ 代理 Vite，/api、/sandbox 代理 API。Web 用 bind mount 和 HMR，API 可 reload；Worker 代码更新按重启/中断规则处理。

HMR 经 Gateway 的 WebSocket，client port=8080；生产不启用 HMR、不发布 Vite 端口。

自动验证命令目标：

~~~powershell
docker compose --env-file .env.local -f compose.yaml -f compose.dev.yaml run --rm api pytest
docker compose --env-file .env.local -f compose.yaml -f compose.dev.yaml run --rm web npm run test
docker compose --env-file .env.local -f compose.yaml -f compose.dev.yaml run --rm validator npm run test
docker compose --env-file .env.local -f compose.yaml -f compose.dev.yaml run --rm e2e npm run test:e2e
~~~

测试镜像包含开发依赖；e2e 属于测试 profile，不进入生产集合。测试适配器不能代替真实模型验收。

### 18.3 本地生产形态

用 compose.prod.yaml 的 localhost 专用配置测试真正的 dist/Nginx，不能只验 Vite。

本地 HTTP 采用 APP_ENV=development、COOKIE_SECURE=false，但应用镜像内容和路由与生产相同；严格 production 配置在 HTTPS 环境验证，不能为了本地 HTTP 移除生产校验。

本地生产检查使用独立 Compose project name，如 atoms-prodcheck，且设置 DATA_VOLUME_NAME=atoms_prodcheck_data。external 卷不随 project name 改名，因此两项必须同时区分。备份恢复/故障测试也使用独立卷和实例，不能覆盖开发数据。

## 19. 阿里云部署设计

### 19.1 默认资源

- 单台 x86_64 Linux ECS，优先复用用户已有实例。
- 主机可用 Ubuntu 24.04 LTS 或 Alibaba Cloud Linux 3；应用依赖在镜像中，主机只承担容器和网络入口。
- 起始建议 2 vCPU、4 GiB 内存、约 40 GiB 可用磁盘，供 Chromium、应用、镜像和备份使用；以测量和已有资源为准，不自动购买。
- 不默认引入 RDS、OSS、Redis、Kubernetes 或公网 Validator。
- 核实 ECS 到模型服务、镜像仓库的可用网络路径，不假设本地可访问即云端可访问。

若实际实例为 ARM、内存较小或内核不同，先运行 M0 检查；Chromium 条件不能直接视为已验证。

### 19.2 网络和容器

定义私有 backend 网络及 Gateway/Worker 必要出入站网络：

| 服务 | 网络和卷 |
| --- | --- |
| gateway | 入口网络+backend；只映射 80/443；只读证书挂载 |
| api | backend、atoms_data；不映射 8000 |
| worker | backend+模型出站网络、atoms_data；不映射端口 |
| validator | 仅 internal backend；无数据库卷、模型密钥或宿主挂载 |
| migrate | backend+atoms_data，一次性执行 |

internal 网络不能代替浏览器访问控制，同一私网仍有其他服务。Validator 的浏览器额外按第 9 节阻断网络。

生产设置 restart:unless-stopped、固定非 root UID、no-new-privileges、资源限制及日志轮转。需要回收子进程的服务设置 init。Validator 使用 M0 验证的 seccomp、tmpfs、只读根文件系统和 shm_size；不用 host 网络/IPC、privileged 或 Docker socket。

迁移完成后 API/Worker 启动；Validator 有独立 liveness。Worker 不依赖 API 完整 ready（其中包含 Worker 心跳，避免循环依赖）；Gateway 可在 API started 后提供未配置界面。最终端到端 ready 在全部服务运行后核对。

### 19.3 安全组与 HTTPS

- 22 仅开放给操作者所需来源 IP；80/443 对预期评审来源开放。
- 8000、9000、5173 以及任何数据库端口不开放到公网。
- 域名解析后配置 HTTPS；APP_ORIGIN 为最终精确 origin，生产 cookie Secure=true。
- 证书只读挂载，私钥不打入镜像、不提交仓库。
- 中国内地地域通过域名提供网站服务时，按阿里云指引完成相应 ICP 备案前置；部署前核实实际情况，不保证外部流程在开发时间内完成。

公网 IP 可用于受限连通性检查；正式评审默认 HTTPS，不把临时 HTTP 设置当生产配置。

依据：[ECS Docker/Compose](https://help.aliyun.com/zh/ecs/user-guide/install-and-use-docker)、[安全组](https://help.aliyun.com/en/ecs/user-guide/security-group-rules)、[建站前置](https://help.aliyun.com/zh/ecs/user-guide/build-a-website/)。

### 19.4 镜像和发布

生产 Compose project name 固定 atoms，external named volume 由 DATA_VOLUME_NAME 指定，当前生产固定为 atoms_data。升级不能因为目录名变化创建新卷；开发、生产检查和恢复试验另用各自独立卷。

镜像包含代码、Web 构建、Python 依赖和浏览器；生产不 bind mount 仓库。密钥、APP_ORIGIN 等放到 ECS 受控 .env.production，限制文件权限。

首次部署：

1. 核实主机、磁盘、Docker/Compose 和 sandbox。
2. 放置对应版本镜像或已审阅源码，准备固定卷与备份目录。
3. 运行唯一迁移实例。
4. 启动全部服务，检查版本和健康。
5. 外部浏览器验证 HTTPS、会话、SSE、生成、保存、恢复和导出。

实现和配置完成后，在 ECS 执行的目标命令：

~~~bash
docker compose -p atoms --env-file .env.production -f compose.yaml -f compose.prod.yaml pull
docker compose -p atoms --env-file .env.production -f compose.yaml -f compose.prod.yaml run --rm migrate
docker compose -p atoms --env-file .env.production -f compose.yaml -f compose.prod.yaml up -d
docker compose -p atoms --env-file .env.production -f compose.yaml -f compose.prod.yaml ps
~~~

生产文件引用版本化 image。没有镜像仓库时，在 ECS 从相同源码和锁文件 build 后再 up；不混用 pull latest 和任意本机构建。阿里云镜像仓库是发布渠道选择，不是应用必需运行服务。

### 19.5 Gateway 必需配置

- /assets/ 为内容 hash 静态文件；/ 为 SPA fallback。
- /api/ 保留完整路径，不因 proxy_pass 尾斜杠意外移除 /api。
- SSE 关闭 buffering/cache、75 秒读取超时、保留 text/event-stream；可统一关闭 /api buffering 简化。
- /sandbox/ 保留 API 独立 CSP/Cache-Control，不继承工作区 frame deny 或脚本策略，不记录 query。
- 转发 Host、X-Forwarded-Proto 和可信 X-Forwarded-For；API 仅信任 Gateway，不能让客户端伪造来源绕过额度。
- body 大小与服务端一致；生产不开放通配 CORS。

## 20. 备份、迁移和回滚

### 20.1 数据保留

数据库包含项目、代码、版本、运行记录和 app-state。重建、重启、升级保留 atoms_data，镜像不含开发数据库；生产操作不能删除持久卷。

开发/生产默认独立。不要自动把开发对话和真实输入复制成公开样例。如选择迁移本地数据，先做一致备份，再单独处理 origin/cookie 身份变化；复制数据库不会让本地访客在新域名自动登录。

### 20.2 备份 CLI

实现 app.cli backup：

- 使用 SQLite Online Backup API，即 Python sqlite3.Connection.backup，生成一致快照；不直接复制正在写入的数据库文件。
- 输出迁移版本、应用版本、时间和校验摘要，写入受控备份目录。
- 部署前备份；演示期按数据变化安排；备份文件不进入 Git。
- 独立临时实例执行 integrity_check，检查项目、版本、源码和 app-state。

ECS 之外保留受控副本；第一版可人工安全下载，OSS 自动化后续再做。

### 20.3 更新和回滚

实现 app.cli maintenance on/off，以短事务更新 system_settings.maintenance；API 的有效只读状态为该标志或环境 READ_ONLY_MODE。只读时拒绝新 Run、恢复和 app-state 写入，Worker 不再领取 pending；已运行任务可以正常提交终态。这样可以排空任务，不必先重启 API 才进入维护。

更新：CLI 进入维护 → 不再接收/领取新任务 → 等待活动 Run 结束或按规则中断 → 一致备份 → 停止旧 API/Worker → 迁移 → 启动新镜像 → 只读验证 → CLI 恢复写入。

代码回滚仅使用明确旧镜像，并确认数据库 schema 兼容；不能把降级镜像当作已撤销迁移。

restore CLI 提供 dry-run、目标实例标识和明确覆盖确认；恢复时停止数据库连接，在独立位置校验备份后原子替换。备份后新增数据可能丢失，须由操作者明确选择；本规划不替操作者作数据覆盖决定。

## 21. 扩展条件和工程边界

| 新需求 | 演进路径 |
| --- | --- |
| 多 API/Worker 或多 ECS | PostgreSQL，重新验证任务领取、租约和事件通知；不共享 SQLite 网络文件 |
| 跨设备/多人 | 真实账户及成员模型，迁移匿名归属 |
| React/npm 工程生成 | 独立构建沙箱、依赖代理、文件系统配额；不能只放开文件名 |
| 任意外部 API | 作用域凭据、后端代理、网络策略；不向 iframe 暴露平台密钥 |
| 独立公开发布 | Publication、单独 origin、应用数据授权和撤回机制 |
| 多模型/多角色 | 真实子任务和模型配置，补充验收；不能只增加头像菜单 |
| 大媒体 | 对象存储和资源引用，避免数据库保存大文件 |

已知边界：

- 全文件重写可能引入回归，通过产物规模、支持类型和代表测试控制。
- 基础启动检查不证明任意业务正确；交互仍须实际验证。
- KV 跨代码版本共享，无自动 schema 迁移或随代码恢复。
- 会话过期/清理后无跨设备身份恢复。
- 单机 Compose/SQLite 不提供高可用，不承诺大规模公共多租户运行。
- 模型质量、外部服务、首次镜像下载和云端前置影响实际排期。

## 22. 需求—实现—验收映射

| 需求 | 实现/阶段 | 验收 |
| --- | --- | --- |
| FR-001 | capabilities、session、首页；M1/M3 | AC-001、AT-001 |
| FR-002 | projects、路由；M1/M3 | AC-002、AT-003、AT-005 |
| FR-003 | 提交事务、幂等、额度；M1 | AC-003、AT-004 |
| FR-004 | agent、Schema、Validator；M0/M2 | AC-004、AT-001、AT-005 |
| FR-005 | Run、SSE、阶段 UI；M2/M3 | AC-005、AT-006、AT-007 |
| FR-006 | 版本代码、只读 CodeMirror；M3 | AC-006、AT-002、AT-003 |
| FR-007 | 编译、票据、iframe；M0/M3 | AC-007、AT-001、AT-008 |
| FR-008 | base_version、上下文、快照修改；M2/M3 | AC-008、AT-002 |
| FR-009 | 不可变版本、交付事务；M2 | AC-009、AT-002、AT-006 |
| FR-010 | 持久卷、恢复、备份；M1/M4/M6 | AC-010、AT-003、AT-007 |
| FR-011 | 错误、重试、租约；M2/M4 | AC-011、AT-006、AT-007 |
| FR-012 | KV、SDK、宿主桥；M4 | AC-012、AT-011 |
| FR-105 | 恢复、审计、历史；M5 | AT-009 |
| FR-109 | ZIP、独立 SDK、README；M5 | AT-010 |
| UX-001～UX-005 | 布局和状态；M3/M6 | 两个目标视口与人工流程 |
| DATA-001～DATA-005 | 事务、CAS、基础版本；M1/M2/M5 | 并发、失败、恢复、重放 |
| NFR-001～NFR-002 | 真事件、独立 Worker、持久化；M2/M4 | 真实模型、故障恢复 |
| NFR-003～NFR-005 | 沙箱、ACL、凭据；M0/M1/M4 | AT-008、配置/产物检查 |
| NFR-006～NFR-008 | 快速接受、限制、日志；M1/M2 | 超限、超时、失败定位 |
| NFR-009～NFR-010 | 浏览器、镜像、README；M6 | 本地生产、干净启动 |
| EXAM-004、DEL-001 | Gateway、ECS；M7 | 外部在线验收 |
| EXAM-005、DEL-002～DEL-005 | 仓库、说明、证据、原题副本 | 材料逐项检查 |

未选 FR-101～FR-104、FR-106～FR-108、FR-110～FR-112，不将其缺失当作本轮 P0 失败，也不在 UI 宣称已支持。

## 23. 仍需真实输入的条件

| 条件 | 当前处理 | 必须解决的阶段 |
| --- | --- | --- |
| 收题时间/预算 | 不推定截止日，按阶段推进 | 真实截止约束排期前 |
| 模型服务/模型名/Key/额度 | 已记录 DeepSeek 真实计数器生成。真实业务验收和云端测试前核对目标环境配置与额度 | AT-016、M7 |
| ECS/地域/架构/资源 | 默认单机 x86_64 Linux Compose | M7 前 |
| 域名/HTTPS/备案 | 精确 HTTPS origin，不把外部流程记完成 | 正式对外部署前 |
| 云端模型/镜像网络 | 本地成功不代表云端验证 | M7 连通性检查 |

缺少 ECS 信息不阻止本地实现；缺少模型也可先完成不收费的机制验证。测试 fixture 成功不能记作真实模型或云端成功。

## 24. 官方技术依据

核对日期：2026-11-11。链接支撑机制；范围、默认数字和架构属于本项目决定。

- [Vite](https://vite.dev/guide/)、[Node 发布状态](https://nodejs.org/en/about/previous-releases)：构建要求和 Node 24 LTS。
- [FastAPI Docker](https://fastapi.tiangolo.com/deployment/docker/)：容器部署；持久 Worker 是本项目额外设计。
- [SQLAlchemy SQLite](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html)：事务和 foreign_keys。
- [SQLite WAL](https://sqlite.org/wal.html)：文件系统限制及 WAL-reset 修复；本计划默认 DELETE。
- [SQLite Backup API](https://sqlite.org/backup.html)：一致备份。
- [OpenAI 官方 Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)：response_format 和输出参数；兼容厂商另行验证。
- [MDN iframe](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe)、[CSP sandbox](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/sandbox)：opaque origin 与 HTTP 头限制。
- [MDN postMessage](https://developer.mozilla.org/en-US/docs/Web/API/Window/postMessage)：身份/origin/格式校验；仅已绑定 opaque iframe 的一次端口传递使用必要通配目标。
- [Playwright Docker](https://playwright.dev/docs/docker)：sandbox、non-root、seccomp、版本与镜像边界。
- [Nginx proxy](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)：buffering。
- [Compose 生产部署](https://docs.docker.com/compose/how-tos/production/)：单机与生产 override。
- [ECS Docker/Compose](https://help.aliyun.com/zh/ecs/user-guide/install-and-use-docker)、[安全组](https://help.aliyun.com/en/ecs/user-guide/security-group-rules)、[阿里云建站](https://help.aliyun.com/zh/ecs/user-guide/build-a-website/)：云端安装、网络和地域前置。

## 25. 给实现 AI 的交接指令

1. 读取 requirements.md、本文件及实际 AGENTS.md；核对已有实现，不覆盖用户未授权修改。
2. 对本轮更新执行第 27 节。M0～M6 用于理解和回归既有实现，M7 对应后续云端交付。
3. 依赖、接口、Schema、SDK、编译器和状态流保持一致；必要偏离记录 ADR/FR、理由和替代验收。
4. 不用固定输出替代真实生成，不用展示进度替代持久 Run。
5. 不增加未选 P1/P2，不安装生成应用任意依赖或执行宿主命令。
6. 持续用代表流程检查纵向闭环，完成阶段后更新复选框和 verification.md，写明真实验证范围。
7. 缺少模型/ECS 时继续独立本地工作，列明真实环境条件；未验证内容保持未完成。
8. 交付本地代码、README、配置、测试证据和 ECS 部署说明；上线后再写真实在线地址。

## 27. 创作体验更新实现计划

### 27.1 实施基线与模块

当前仓库已经有 React、TypeScript、Vite 工作台，FastAPI、SQLite、独立 Worker 与 Validator，以及预览、版本、失败恢复和积分。迁移 0004 增加了 `projects.kind`，已有项目默认 `web`。本轮优先用已有数据和接口完成 FR-016～FR-020。

| 模块 | 现有入口 | 变更 |
| --- | --- | --- |
| 导航与页面布局 | `apps/web/src/App.tsx`、`Studio.tsx`、`studio.css` | 保留 `/`、`/games`、`/slides`、`/video`、`/projects` 和 `/projects/:pid`，重排创作首屏和作品区 |
| 创作类型与输入 | `apps/web/src/creationModes.ts`、`Studio.tsx` | 首页从需求识别交付类型，按入口保存草稿，增加可停止的打字提示 |
| 试玩 | `apps/web/src/StarRun.tsx` | 用打砖块替换右侧小游戏。将规则和绘制与首屏控件分离，同一游戏规则也能用于示例预览 |
| 预置示例 | 现有提示词列表 | 新增本地示例目录、封面和预览。首页复用 `ProjectLibrary` 展示已有项目 |
| 版本入口 | `Workspace`、`Preview`、现有 versions API | 用 `source_run_id` 将成功消息关联已保存版本，调用既有预览选择逻辑 |
| 验收 | `tests/e2e`、`docs/verification.md`、`docs/deployment.md` | 补增量回归、真实业务验收和上线交付证据 |

第 27 节所列模块可在本地完成。预置示例和版本卡片均可使用现有 SQLite schema 和生产镜像构建方式。

### 27.2 首页与输入框（FR-016）

1. 首页路由是通用入口。提交时在本地根据需求开头的作品名称识别类型，通用需求默认 `web`。模型读取完整需求，类型识别无需额外模型请求。专页从路由确定类型。创建时用该 `kind` 调用现有 `POST /api/v1/projects`，工作区继续从 `Project.kind` 读标签。
2. 沿用 `atoms:studio-draft:<kind>` 按入口保存草稿。首页使用既有 `web` 键。已创建项目的草稿继续用 `atoms:draft:<projectId>`。
3. 将打字提示作为显示状态，保持 `textarea` 的值由用户草稿独立控制。空闲时逐字显示、停顿再切句，焦点进入、用户开始输入、页面进入后台或组件卸载时清理计时器。`prefers-reduced-motion` 下固定一条可读提示。辅助技术使用固定输入标签。
4. 从示例带入时填写当前入口的草稿。草稿非空且内容不同时，先展示替换或保留的选择。取消后保持原草稿。确认填入后聚焦输入框，用户仍可编辑。
5. 继续使用现有项目创建键、Run 幂等键和提交状态。只有显式提交才进入项目创建和 Run 流程。模型暂不可用时按既有行为保存可继续提交的项目草稿。失败时给出可操作反馈，已经输入的需求可恢复。

### 27.3 背景试玩（FR-017）

- 布局采用一个居中的创作列。待机、暂停和终局时，首屏背景为可点击、可聚焦的触发层。创作框和试玩控件在触发层上方。激活后在创作框上方显示分数、挡板和小型暂停控件。
- 将状态设计为 `ready`、`playing`、`paused`、`won`、`lost`。输入聚焦造成的收起是界面状态，收起时保存本局状态并暂停。结束本局重置为 `ready`，重新开始创建一份新状态。
- 用 `requestAnimationFrame` 驱动小球、挡板和砖块。按容器尺寸映射逻辑坐标与触摸、鼠标位置。限定模拟时间步长以避免恢复后一帧跳跃。暂停时停止帧循环，恢复时重新计算时间基准。
- `visibilitychange`、窗口 `blur`、创作框 `focus`、打开示例预览均调用同一个暂停动作。回来后保持暂停，继续由用户触发。路由卸载时清理帧、监听和指针捕获。方向键监听限定在活跃且聚焦的游戏区，手机仅在操作区域内接管拖动。
- 游戏控制、计分和重开使用本地状态。首屏试玩与示例弹层各自拥有独立的一局。游戏逻辑无需创建项目、访问预览票据或调用模型。

### 27.4 作品库与可操作示例（FR-018）

示例目录作为随前端交付的静态数据。每项包含稳定 `id`、`kind`、`category`、标题、简介、封面、提示词和预览组件。首页配置发现和模板集合，项目页签继续请求已有项目 API。游戏分类只使用首批示例实际覆盖的分类。

| 首批示例 | 类型 | 预览中的最低可操作内容 |
| --- | --- | --- |
| 海边旅宿 | 网站 | 浏览房型并切换查看详情 |
| 手作陶器 | 网站 | 按分类筛选并查看产品详情 |
| 未来城市 | 网页幻灯片 | 至少三页，可前后翻页，并显示当前页 |
| 打砖块 | 街机 | 控制挡板，撞砖得分，结束后可重开 |
| 贪吃蛇 | 街机 | 控制移动、吃到食物计分，碰撞后重开 |
| 翻牌记忆 | 解谜 | 翻开两张牌、匹配计分和重新洗牌 |

- 封面选用原创生成图，挑选后复制到 `apps/web/public` 下的示例资产目录。用适合卡片的尺寸和压缩格式，统一封面比例并设置尺寸占位。首屏优先加载可见图，其余延迟加载。封面负责展示，预览交互由本地示例实现。
- 示例预览使用随前端交付的可信组件，与运行用户生成代码的 iframe 分开。复用已有弹窗入口，补齐预览尺寸、键盘关闭、焦点进入与返回。关闭预览后保留当前页签、分类和滚动位置。弹窗内游戏随关闭卸载，终止后台帧循环。
- 「使用此示例的提示词」将固定目录里的提示词填入当前入口，走 27.2 的草稿替换逻辑。该操作不把示例写成某位访客的项目或版本。实际代码复制对应后续 FR-106。

### 27.5 对话版本卡片（FR-019）

1. versions API 的列表已返回 `source_run_id`。把它补进前端 `Version` 类型，用 `source_run_id → Version` 映射关联 `Message.run_id`。仅为已交付版本的成功助手消息渲染卡片。较早的消息用持久列表关联，完成事件用于触发现有查询刷新。
2. 卡片显示版本号和「查看预览」。点击复用工作区的版本选择与预览页签，版本详情、源码和导出统一读取选中的 `version.id`。本项目当前版本继续从 `project.current_version_id` 获取。
3. 选择历史预览时沿用只读限制。继续修改默认使用当前版本。用户显式恢复后，由既有恢复 API 更新当前指针与 revision。失败消息继续走已有 `BuildFailure` 和候选恢复路径。
4. 用户已选中历史预览时，后续构建完成更新当前版本提示和列表，查看版本仍按用户选择。用户可通过「回到当前」或点击新卡片切回。成功卡片等版本列表实际返回后显示。

### 27.6 实施顺序与完成条件

| 阶段 | 需求 | 实施 | 完成条件 |
| --- | --- | --- | --- |
| E1 | FR-016、FR-017 | 居中布局、需求类型识别、草稿、打字提示、背景试玩 | AT-012、AT-013 通过，桌面和手机的首屏可操作 |
| E2 | FR-018 | 本地示例目录、原创封面、筛选、可操作预览、填入提示词 | AT-014 通过，六个示例具备各自的最低交互 |
| E3 | FR-019 | 成功消息版本卡、指定版本预览和工作区回归 | AT-015 通过，已有失败恢复与导出流程通过 |
| E4 | FR-020 | 本地构建、真实模型业务验收，随后按现有部署手册完成线上交付 | 本地记录 AT-012～AT-016，实际部署后记录 AT-017 |

E1、E2 可独立实现页面和示例，合并时通过草稿填入逻辑连接。E3 复用现有版本数据。E4 先完成本地验收，云端在目标环境就绪后执行。

### 27.7 验收执行

- 前端执行 `npm run check` 和 `npm run build`。在隔离 Compose 测试环境运行 `npm run test:e2e`，更新已有导航和小游戏测试中受本轮交互影响的断言。
- 对 AT-012～AT-015 做针对性浏览器回归。用浏览器页面可见性与焦点事件覆盖暂停和恢复，在人工验收时切换一次真实窗口。记录 1280×720、1440×900 和约 390 像素宽视口下的主要页面。对示例预览、筛选和填入操作检查项目/Run 创建请求未发送，积分余额与流水保持一致。
- 回归原有任务提交、积分结算、刷新恢复、错误继续修复、代码查看、历史恢复、导出和访客隔离。测试提供器覆盖状态与故障注入，真实模型覆盖实际结果的业务操作。
- AT-016 用已配置的模型生成任务看板，新增和移动任务后修改筛选或布局，刷新并重新打开。记录项目类型、至少两个实际版本、任务数据和用量结算。以前的真实计数器是模型链路证据，任务看板按这条场景单独验收。
- AT-017 依照 [ECS 部署手册](./deployment.md) 核对公网 HTTPS 与服务配置，以独立无痕访客验收。真实在线 Demo、GitHub 和飞书副本链接按 DEL-001～DEL-005 记录。在本地和线上结果分别记录实际执行环境及未验收条件。

## 28. 规划、专业实现与效果审核

游戏当前采用可玩性检查流程。规划与实现使用类型指导，交付由浏览器确认可进入、真实输入有响应和运行异常。已有玩法断言与专项脚本用于开发回归。游戏交付不调用额外的模型审核，浏览器记录的实际结果随版本保存。

React 网站和游戏由主 Agent 规划、专业实现 Agent 编码，隔离浏览器验证后再交回主 Agent 审核。角色通过独立消息上下文运行，共用当前模型服务。正常首稿有规划、实现、审核三次模型调用。每轮修复先复验，再审核，所有模型调用复用现有预授权与真实用量结算。

规划用结构化契约保存原始需求、实现任务、视觉方向和验收条件，随源码保存为 `src/agent/plan.json`。浏览器的页面文本、实际交互和状态变化作为审核证据，审核结论随不可变版本保存，并通过版本接口提供。审核拒绝时，将具体问题和候选源码交给实现 Agent 修复，重新完成浏览器检查和审核。

FPS 需求在规划和浏览器验收两处保留第一人称 3D 要求。预装 Three.js 以浏览器 ESM 入口打包，版本化依赖清单也用于导出的开发工程。专业实现可参考已验证的 3D 引擎。FPS 校验检查 WebGL 画面、世界坐标移动、拖动视角、射击命中和换弹。

软件 WebGL 验收使用 960×640 视口和 0.4 像素比，保留实际游戏代码与真实浏览器事件。校验容器可使用两个 CPU 核，随后继续检查 390 像素窄屏。开始与继续按钮在玩家手势内请求鼠标锁定，支持画布内无按键转向作为后备。触屏用独立手势瞄准。当前主 Agent 审核使用源码和文本化浏览器证据。

规划中的核心需求、验收条件与可选增强分别保存。用户明确要求优先；主 Agent 自行提出的额外装饰与玩法列为建议，不阻塞已经完成原始需求的实现。恢复候选时同时恢复计划、专业上下文和调用序号；浏览器复查失败后仍能完整执行修复与再次审核。候选已经通过技术检查时，React 项目仍需主 Agent 审核，其实际模型用量照常结算。

`fps-3d-v2` 验证实际鼠标锁定、左键与键盘操作，再用 Esc 和父页面焦点变化验证暂停。鼠标转向优先使用原生移动，无头浏览器未传递相对移动量时，给画布发送不按键的相对移动事件，报告记录 `look_input`。敌方开火检查观察发射计数、场景弹道和生命变化。首发是否命中作为观察值，左键开火由射击计数和弹药变化独立验证。继续重新获取锁定，重开验证本局状态归零。浏览器收集试玩全过程的异常，反馈给实现 Agent 修复。

游戏规划使用 `game_benchmarks.py` 提供的官方资料和交互约定。实现和审核读取匹配的参考条目。普通游戏报告还包含实际操作的控件与操作后的可见反馈。不同类型的专业检查可沿用独立验收标识接入。

FPS 试玩使用原生鼠标事件，操作必须产生实际状态变化。软件 GPU 下跳过 Playwright 对控件连续动画帧稳定性的等待，仍检查可见控件及操作结果；等待实际首帧像素后再验收画面。GPU 验收进程上限 70 秒，API 调用上限 75 秒，普通网页继续使用原有更短预算。
