# Atoms Studio Demo

把自然语言需求变成可交互网页，并在同一项目中持续修改、保存业务数据、恢复版本和导出源码。

本地优先开发，后续通过同一组 Docker 镜像部署到阿里云 ECS。实现基线为 [需求规格](docs/requirements.md) 和 [技术手册](docs/technical-plan.md)。

## 本地启动

需要 Docker Desktop（Linux 容器）。当前 Windows 环境也可使用已安装的 Python、Node.js 24 和 uv 运行检查。

在项目根目录执行：

~~~powershell
python scripts/init_env.py
.\scripts\dev.ps1
~~~

打开 [http://localhost:8080](http://localhost:8080)。首次构建需要下载 Chromium。数据保存在 Docker 的 atoms_app_data 卷中，停止或重建容器会保留项目。

填入 .env.local 的模型配置：

~~~dotenv
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-flash
LLM_API_KEY=在本机填写
LLM_RESPONSE_MODE=json_object
LLM_TOKEN_LIMIT_PARAM=max_tokens
LLM_PROVIDER_MAX_OUTPUT_TOKENS=393216
LLM_THINKING_MODE=disabled
~~~

deepseek-flash 是官方 API 名称，目前对应 DeepSeek-V4.1-Flash-1017。[官方入口](https://api-docs.deepseek.com/)、[JSON 输出](https://api-docs.deepseek.com/guides/json_mode/)、[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)。

只修改供应商配置时，重新创建网关即可：

~~~powershell
docker compose --env-file .env.local up -d --no-deps --force-recreate provider-gateway
~~~

供应商密钥只注入内网 `provider-gateway`。Worker 使用单独的服务令牌请求统一文本和视频接口，API 通过 Worker 心跳读取能力。`.env.local` 已被 Git 和 Docker 构建上下文排除。缺少配置时工作台可以打开和读取项目，生成入口会明确提示待配置。换 OpenAI 兼容文本模型时修改网关配置并重新创建网关即可。

输出空间依据供应商 /models 的原生能力和用户可用积分动态分配。LLM_PROVIDER_MAX_OUTPUT_TOKENS 是能力元数据不可用时的供应商能力回退，不是旧的 8192 token 小上限。DeepSeek 不传 max_tokens 时非思考模式仍默认 8K，因此请求显式使用动态预算。

## 匿名用户与积分

首次打开由服务端生成随机用户 ID，浏览器 Cookie 维持身份，无需注册或登录；新用户免费获得 500 积分（相当于 50 元使用额度）。

- 输入每百万 token 20 积分，输出每百万 token 80 积分。
- 以供应商返回的 prompt_tokens / completion_tokens 精确扣费；支持百万分之一积分，不做整积分向上取整。
- 每次调用先预授权，结束后按真实用量结算并释放差额。自动修复单独计费；有实际用量的失败或截断也计费。
- 缺少 usage 的网络中断/超时或 Worker 硬退出，积分冻结并标记待核对；不会伪造消费数字。维护核对见部署手册。
- 侧栏或手机页头可查看余额、随机用户 ID、费率和流水。余额耗尽后既有项目、预览与导出继续可用。
- 移除旧生成次数、项目数和版本数配额；同项目单个活动任务、沙箱及较大的资源保护继续维持执行一致性。

迁移 0002 为旧访客补发一次 500 积分；原项目保留，历史未知 usage 不追溯收费。清除 Cookie、换浏览器会成为新匿名用户，这不是实名账户系统。当前没有充值、提现或支付功能。

## 已实现

- 匿名会话与访客项目隔离；创建项目、列表、重新打开和草稿。
- 匿名积分钱包、首次赠送、精确 token 账本、预授权、余额校验与异常用量核对。
- 真实模型调用适配器；持久化任务、SSE 阶段回放、刷新后继续观察。
- 按项目类型加载网站、幻灯片、游戏的生成 Skill。视频使用 Vidu Q3 Pro 文生视频 / 图生视频服务，默认 540p，文字即可生成，也可上传首帧，支持声音、时长、原生播放、MP4 下载与历史版本，按供应商实际费用折算平台积分。详见 [视频接入手册](docs/vidu-video.md)。
- React 网站和游戏由主 Agent 规划、专业实现 Agent 生成。网站经过浏览器检查与主 Agent 审核，游戏经过浏览器可玩性检查。失败反馈在同一个任务内触发最多 3 轮自动修复。第三轮游戏通过编译、启动且未捕获运行异常时，自动输入结果未确认也可交付，状态记录在版本报告。模型调用按供应商实际用量结算。
- 幻灯片模板支持翻页预览、编辑预填需求和按所选版式创建项目。
- 新网站和游戏交付 React 与 TypeScript 多文件源码。网站、游戏和幻灯片在构建后检查启动与主要操作。游戏可追加一次限时源码审查。首稿之外最多自动修复 3 轮，其中质量问题最多尝试修复一次。原生视频生成成功后直接保存。历史 HTML / CSS / JavaScript 产物仍可预览。
- 新闻与专题、个人作品集和产品发布页有内置 React 参考模板。模型会根据需求改写页面主题、视觉与内容，未匹配的需求进入自由生成。生成的版本支持继续修改和导出。
- 外汇项目在生成时可引入欧洲中央银行参考汇率快照，数据附来源与发布日期。数据源不可用时使用标注过期的缓存，首次拉取失败则提供空数据状态。
- 财经资讯需求可引入国家统计局和美联储的公开发布快照，展示标题、发布日期与官方地址。
- 交互预览、桌面/手机宽度切换、可搜索的只读源码树与语法高亮。React 源码 ZIP 含可直接托管的静态构建产物和可继续开发的 Vite 工程。
- 按项目保存生成应用业务数据；CAS 冲突检查及保存状态反馈。
- 不可变版本、历史只读预览、恢复后继续分支、源码 ZIP 导出。
- Worker 租约、过期任务回收、失败保留稳定版本。失败构建保留候选内容，继续修复时先复验已有候选。网站审核和必要的修改按实际模型用量结算。
- 本地 Compose、生产静态镜像、HTTPS Nginx 配置、维护模式与 SQLite 在线备份/离线恢复。

生成的网站以静态文件交付，工作台为预览提供按项目隔离的数据保存。React 运行时由平台统一打包，生成代码的网络和依赖权限由预览沙箱管理。真实数据由 Worker 接入受支持的数据源，生成内容使用随版本保存的数据快照。支持范围可在工作台内查看。

## 服务与源码

| 位置 | 职责 |
| --- | --- |
| apps/web | React、TypeScript、Vite 工作台 |
| apps/api/atoms/main.py | FastAPI 接口、会话、SSE、预览与导出 |
| apps/api/atoms/worker.py | 持久任务领取、模型生成、修复和事务交付 |
| apps/api/atoms/provider_gateway.py | 内网供应商凭据、限流和协议适配 |
| apps/api/atoms/model.py | Chat Completions 适配、输出预算与供应商用量 |
| apps/api/atoms/prompts.py、skills/、artifacts.py | 提示组装、专业生成指导与产物整理 |
| apps/api/atoms/exchange_rates.py | 欧洲中央银行公开参考汇率接入与短期缓存 |
| apps/validator | esbuild React 打包、parse5、PostCSS、Acorn 与 Playwright 校验 |
| shared | JSON Schema、可信预览模板和存储 SDK |
| deploy | Nginx、系统调用配置和生产部署文件 |
| scripts | 本地启动、隔离验收和运维检查 |

生成代码只在 opaque-origin iframe 或独立非 root Chromium 容器执行。预览由 HTTP CSP、MessagePort、单版本短期凭证和项目绑定的存储接口共同约束。校验器不挂载数据库，浏览器不继承服务密钥。机制与残余边界见 [实现决策](docs/decisions.md)。

SQLite 使用 DELETE journal、短事务和单 Worker；当前实现面向单台机器，不提供水平扩容。成功交付在同一事务中写入产物、版本、项目指针、完成消息和事件。

Worker 默认一次运行 1 个任务，网站、游戏、幻灯片和视频共用名额。满额后按提交顺序等待，同一项目保留一个活动任务。可在 `.env.local` 或生产环境文件中调整 `RUN_CONCURRENCY`（1–8），重建 Worker 后生效。浏览器校验使用独立的单槽位。

生成 Skill 的接入、游戏渲染选择和启动检查见[生成 Skill 实现](docs/generation-skills.md)。

## 开发与检查

~~~powershell
npm ci
uv sync --project apps/api --frozen
npm run check
npm run test
npm run build
uv run --directory apps/api pytest -q
~~~

完整 UI 验收使用独立的 atoms-e2e Compose 项目、8082 端口和数据库卷：

~~~powershell
.\scripts\test-e2e.ps1
~~~

测试产物提供器只允许 APP_ENV=test 且 TEST_FIXTURE=true；生产和日常开发不会用它替代模型生成。测试环境明确显示 test-fixture-only 模型。它验证编排、隔离和持久化机制，不代表真实模型生成验收。

测试服务运行时，还可以执行：

~~~powershell
uv run --project apps/api python scripts/check-restart.py
uv run --project apps/api python scripts/check-recovery.py
uv run --project apps/api python scripts/check-backup.py
Get-Content scripts/security-spike.mjs -Raw | docker compose --env-file .env.test -p atoms-e2e exec -T validator node --input-type=module
~~~

前三项检查使用已完成 UI 测试保存在 test-results 内的临时会话，或自行创建测试会话；不读取日常开发数据。check-recovery 会强制结束命名的测试 Worker。check-backup 会临时停止测试 API/Worker 并恢复测试数据库。可通过 .\scripts\test-e2e.ps1 -KeepRunning 保留测试服务供这些检查使用。

真实服务配置后，运行以下协议和生成冒烟检查；它会调用已配置的模型并消耗额度：

~~~powershell
uv run --project apps/api python scripts/model-smoke.py
~~~

实际结果、未完成的外部验收和范围追踪见 [验收记录](docs/verification.md)。后续阿里云部署步骤见 [部署手册](docs/deployment.md)。

界面记录：[首页](docs/screenshots/homepage.png)、[积分钱包](docs/screenshots/wallet-desktop.png)、[桌面工作台](docs/screenshots/workspace-desktop.png)、[手机预览](docs/screenshots/workspace-mobile.png)。工作台截图中的计数器和钱包用量为测试专用数据，用于记录机制验收；真实 DeepSeek 用量另记在验收记录中。

## 常用操作

~~~powershell
.\scripts\dev.ps1 status
.\scripts\dev.ps1 logs
.\scripts\dev.ps1 down
docker compose --env-file .env.local exec -T api python -m atoms.ops maintenance on
docker compose --env-file .env.local exec -T api python -m atoms.ops maintenance off
~~~

不要使用 down -v 清理有价值的数据卷。备份应通过 SQLite backup API，不能直接复制正在使用的数据库文件。备份和恢复命令见部署手册；含视频的备份必须同时保留数据库旁的同名 .media 目录。
