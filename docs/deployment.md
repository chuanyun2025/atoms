# 阿里云 ECS 部署与运维

当前交付先完成本地开发。本文提供后续部署路径，未创建云资源、上传代码或执行公网部署。

## 1. 部署前的输入

- 单台 Linux x86_64 ECS，建议先以 2 vCPU / 4 GiB / 40 GiB 作为 Demo 起点，实际需按 Chromium 峰值内存调整。
- 可解析到 ECS 的域名，以及该域名的有效 TLS 证书和私钥。
- 可访问的镜像源、Chromium 下载源、模型服务地址及模型余额。
- 安全组向公网开放 80/443，22 仅向操作者的固定 IP 开放。8000、8100、9000、5173 使用容器内网。
- 中国内地地域对外建站前核对备案要求；地域、域名和备案属于部署前置，不能由本地测试代替。

安装 Docker Engine 与 Compose 插件时，按 [阿里云 ECS Docker 指南](https://help.aliyun.com/zh/ecs/user-guide/install-and-use-docker) 和 [Docker 官方文档](https://docs.docker.com/engine/install/) 对照所用发行版操作。[安全组说明](https://help.aliyun.com/en/ecs/user-guide/security-group-rules)、[建站前置说明](https://help.aliyun.com/zh/ecs/user-guide/build-a-website/)。

## 2. 准备配置

把仓库放在 ECS 的独立目录，例如 /opt/atoms。不要上传本地 node_modules、.venv、.env.local、测试产物或匿名会话文件。

在仓库根目录执行：

~~~bash
python3 scripts/production-env.py
chmod 600 .env.production
mkdir -p deploy/tls
~~~

编辑 .env.production：

~~~dotenv
APP_ENV=production
APP_ORIGIN=https://实际域名
COOKIE_SECURE=true
RUN_CONCURRENCY=1
DATA_VOLUME_NAME=atoms_data
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-flash
LLM_RESPONSE_MODE=json_object
LLM_THINKING_MODE=disabled
PROVIDER_KMS_REGION=cn-hangzhou
LLM_KMS_SECRET_NAME=atoms/deepseek
VIDU_KMS_SECRET_NAME=atoms/vidu
~~~

保留脚本生成的 SESSION_SECRET、SERVICE_TOKEN 和 PROVIDER_GATEWAY_TOKEN，限制文件读取权限。APP_ORIGIN 必须是完整 HTTPS origin，不包含路径和末尾斜杠。生产启动会检查 HTTPS 和安全 Cookie；主会话使用 host-only Cookie。

在 KMS 创建通用凭据，凭据值填入供应商 API Key 原文。给 ECS 实例绑定 RAM 角色，只授权读取配置的凭据及相应解密权限。网关通过加固模式获取实例角色的临时凭证，按区域读取 KMS，缓存五分钟。需要使用指定 KMS OpenAPI 域名时，填写 `PROVIDER_KMS_ENDPOINT`。没有配置 KMS 凭据名称的供应商使用 `LLM_API_KEY` 或 `VIDU_API_KEY` 环境配置，对应的 Key 只注入网关。[ECS 实例 RAM 角色访问 KMS](https://help.aliyun.com/zh/kms/key-management-service/use-cases/access-kms-from-an-ecs-instance-in-a-secure-manner/)。

将证书链保存为 deploy/tls/fullchain.pem，私钥保存为 deploy/tls/privkey.pem；设置最小读取权限。证书目录和所有实际环境文件已被 Git 忽略。证书签发、续期按所选 CA 的正式流程完成；续期后校验配置并重载网关。

## 3. 构建和启动

~~~bash
docker volume create atoms_data
docker compose --env-file .env.production -f compose.prod.yaml build
docker compose --env-file .env.production -f compose.prod.yaml up -d
docker compose --env-file .env.production -f compose.prod.yaml ps
docker compose --env-file .env.production -f compose.prod.yaml logs --tail 50 api worker gateway provider-gateway
~~~

Compose 先运行迁移，再启动 API 和 Worker。Worker 等待 Validator 和供应商网关健康。公网 Nginx 提供静态前端。API 和 Worker 以 UID 10001 访问同一个持久化卷，供应商网关独立运行，通过专用内网提供服务。

现有环境升级时先运行对应环境初始化脚本，补齐独立的网关令牌，再重建 Compose 服务并运行迁移。线上切换前等现有生成任务结束。更换兼容文本模型时更新 `LLM_BASE_URL`、`LLM_MODEL`、认证与能力配置，再单独重建 `provider-gateway`。视频任务在供应商侧生成后，保留原供应商账户的访问权限，直到已提交的任务查询和下载完成。

网关接口使用 `/internal/v1` 前缀，调用方通过 `Authorization: Bearer` 传入内部令牌。

| 方法和路径 | Worker 契约 |
| --- | --- |
| `GET /capabilities` | 文本模型名称及文本、视频配置状态 |
| `GET /text/capabilities` | 本次配置的输出 token 上限，优先取供应商元数据 |
| `POST /text/generate` | 输入消息、输出上限、可选 JSON Schema。返回文本及输入、输出 token |
| `POST /video/tasks` | 输入描述、可选首帧和视频参数。返回任务 ID |
| `GET /video/tasks/{task_id}` | 返回状态、实际供应商积分和结果地址 |

视频由网关选择供应商模型。Worker 提交任务时带上已报价的模型标识，配置切换导致型号不一致时，在调用供应商前拒绝提交。更换视频型号时同步更新平台的可售型号和费率，并处理完旧供应商的在途任务。

网关记录操作、Run ID、耗时和错误类。默认每分钟最多 120 个付费请求，文本和视频各最多 3 个并发请求，可用 `PROVIDER_REQUESTS_PER_MINUTE` 和 `PROVIDER_MAX_CONCURRENCY` 调整。积分预授权、结算及任务恢复仍由应用执行。部署的容器无法从公网访问该接口。

基础镜像已固定 digest，JavaScript 使用 package-lock.json，Python 使用 uv.lock。升级基础镜像、依赖或 Playwright 时，需要重新运行解析、真实沙箱和端到端检查，随后再上云。

Validator 保持非 root、只读根文件系统、资源限制和 Chromium 系统沙箱开启。若云主机的 user namespace/seccomp 配置不支持，检查失败并修复主机兼容性；不要改成 privileged 或使用 --no-sandbox。

## 4. 上线检查

按顺序验证：

1. HTTP 重定向到 HTTPS，证书域名有效；主站的来源与 APP_ORIGIN 完全一致。
2. /health/live 返回 200；/health/ready 在数据库、Worker 和模型配置就绪时返回 200。缺少模型配置会返回 503。
3. 浏览器创建访客会话，查看项目列表；换另一个浏览器确认不能读取原访客项目。
4. 用真实模型创建任务看板，添加任务并刷新；修改样式或筛选功能，确认已有业务数据保留。
5. 故意提交不支持的需求或模拟模型错误，确认旧版本不被覆盖。
6. 恢复历史版本、基于恢复版本继续修改、导出 ZIP；在独立端口运行导出结果。
7. 重建 API/Worker 后确认项目、版本、消息和业务数据仍可读取。
8. 备份到 ECS 之外的受控存储，实际验证一次恢复流程。

真实模型、云端网络、HTTPS、安全组和外部评审地址的检查必须在目标云环境补做。本地 HTTP 的静态镜像检查不代表完成以上公网验收。

## 5. 本地检查生产静态镜像

以下步骤使用 8083、独立 Compose 项目和独立 external volume，保留日常开发数据。检查时明确使用 development 环境和 HTTP 覆盖配置，不把它对外发布。

~~~powershell
python scripts/prodcheck-env.py
docker volume create atoms_prodcheck_data
docker compose --env-file .env.prodcheck -f compose.prod.yaml -f deploy/compose.prodcheck.yaml -p atoms-prodcheck up -d --build
~~~

打开 http://localhost:8083，检查静态入口、会话和 API 路由。完成后停止：

~~~powershell
docker compose --env-file .env.prodcheck -f compose.prod.yaml -f deploy/compose.prodcheck.yaml -p atoms-prodcheck down
~~~

DATA_VOLUME_NAME 必须为 atoms_prodcheck_data；仅修改 Compose 项目名不会隔离 external volume。

## 6. 维护与备份

开启维护会禁止新的项目、生成、恢复和业务数据写入，Worker 不再领取新任务；当前任务可正常结束。已有数据继续可读。

~~~bash
docker compose --env-file .env.production -f compose.prod.yaml exec -T api python -m atoms.ops maintenance on
~~~

等待活动任务结束。准备宿主备份目录，其权限应允许容器 UID 10001 写入，并限制其他用户读取：

~~~bash
mkdir -p backups
sudo chown 10001:10001 backups
chmod 700 backups
docker compose --env-file .env.production -f compose.prod.yaml run --rm --no-deps -v "$PWD/backups:/backups" api python -m atoms.ops backup /backups/atoms-YYYYMMDD-HHMM.db
~~~

backup 使用 SQLite online backup API，完成后执行 integrity_check；目标文件已存在时会拒绝覆盖。备份包含匿名会话及应用数据，按私有数据保护，复制到主机之外后再按策略保留。不要直接复制在线数据库，也不要把备份提交到 Git。

恢复前先检查文件并保存当前数据库的一份新备份：

~~~bash
docker compose --env-file .env.production -f compose.prod.yaml run --rm --no-deps -v "$PWD/backups:/backups:ro" api python -m atoms.ops restore /backups/要恢复的备份.db
~~~

上述命令只做 dry run。核对备份时间、完整性、schema 和项目数量，再停止所有数据库连接：

~~~bash
docker compose --env-file .env.production -f compose.prod.yaml stop api worker
docker compose --env-file .env.production -f compose.prod.yaml run --rm --no-deps -v "$PWD/backups:/backups:ro" api python -m atoms.ops restore /backups/要恢复的备份.db --offline --confirm-restore
docker compose --env-file .env.production -f compose.prod.yaml up -d api worker
~~~

恢复会替换数据库，保留维护模式，并清除旧 Worker 单例租约。若停机来自强制退出，需要先等待旧租约过期（最长约 30 秒）；恢复命令会拒绝有效 Worker 租约。启动后确认目标项目、版本、业务数据无误，最后关闭维护模式：

~~~bash
docker compose --env-file .env.production -f compose.prod.yaml exec -T api python -m atoms.ops maintenance off
~~~

关闭维护不会覆盖环境变量 READ_ONLY_MODE=true；需要解除该变量时修改环境文件并重新创建服务。

## 7. 更新与回滚

每次更新前记录当前代码版本和镜像 ID，完成备份；新版本通过本地检查后，在维护模式下构建、迁移和重建。不要执行自动删除数据卷的命令。

当前 schema 为 0010，包含构建工作区和作品发布记录。只部署发布功能时可以先迁移到 0009_publish，合并部署时再迁移到 0010。历史备份应使用对应代码版本恢复，再执行迁移。

文本单次请求的时限为规划 45 秒、复核 20 秒、常规生成或修复 180 秒。需求或发送给模型的代码上下文较大时，生成和修复可用 420 秒。供应商网关可以通过 `LLM_REQUEST_TIMEOUT_SECONDS` 限制最大时限。部署时同步更新 Worker 和供应商网关。请求超时且用量未知时，任务会退出，未确认的预授权保留待核对。

## 8. 积分待核对调用

界面会显示缺少可信 usage 的调用 ID 和冻结积分。预授权不是实际扣费；核对供应商账单后，维护者通过服务器 CLI 结算：

~~~bash
docker compose --env-file .env.production -f compose.prod.yaml exec -T api python -m atoms.ops credits-reconcile 实际调用ID --input-tokens 实际输入token --output-tokens 实际输出token
~~~

若已确认供应商没有产生费用，释放该笔冻结：

~~~bash
docker compose --env-file .env.production -f compose.prod.yaml exec -T api python -m atoms.ops credits-reconcile 实际调用ID --release
~~~

只允许核对 uncertain 调用；不能从客户端给自己增加余额。结算和释放都会留账，已结算调用不会被重复扣费。不要仅根据“任务失败”就释放可能已产生的供应商用量。

`RUN_CONCURRENCY` 设置单 Worker 同时运行的任务数，默认 1，范围 1–8。已有环境文件如果显式配置了此变量，需要修改该文件并重建 Worker 才能切换。浏览器校验保留一个槽位。多项目共享钱包，并发调用仍按事务预授权和实际用量结算。

容量超过单机 SQLite、单 Worker 或 Chromium 配额时再规划 PostgreSQL、外部队列和更强执行隔离。不要直接增加 Worker 副本绕过本项目的单例租约。
