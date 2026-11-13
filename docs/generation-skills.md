# 生成 Skill

Worker 根据已保存的项目类型选择一个 Skill。首页继续从需求识别类型，专页使用路由指定的类型。Skill 是仓库内随镜像发布的生成指导，按类型读取并缓存。它定义交付方法和自检要点，由现有生成流程统一负责模型调用、修复、积分和版本交付。

## 规划与交付

React 网站和游戏由主 Agent 规划，再由专业实现 Agent 生成。计划随源码保存为 `src/agent/plan.json`。规划和实现共用已配置模型，首稿通常各用一次模型调用。

网站、游戏和幻灯片完成产物解析与构建后，在隔离 Chromium 中检查启动和可识别的主要操作。短测中的运行异常会反馈给实现 Agent。无法确认操作结果时记录 `unconfirmed`。成功报告记录 `acceptance: "smoke"`、短测结果和生成指导版本。视频任务由 Vidu 返回结果后直接保存。

游戏可以追加一次限时 25 秒的源码审查。缺陷须指向实际文件和源码片段，并说明触发条件与结果。计划用于理解实际设计。浏览器未观察到操作响应本身不触发修复。明确的源码缺陷或演示翻页故障共用一次质量修复机会，生成和复验共限时 120 秒。修复无进展、超时或引入构建和运行错误时，交付此前能运行的候选。硬故障仍可在首稿之外自动修复最多三轮，候选和错误都重复时提前停止。任务进行期间显示「建设中」。

| 类型 | 生成指导 |
| --- | --- |
| 网站 | [网站](../apps/api/atoms/skills/web.md)与 [Frontend Design](../apps/api/atoms/skills/frontend-design/SKILL.md) |
| 幻灯片 | [网页幻灯片](../apps/api/atoms/skills/slides.md)，参考 [pptx](../apps/api/atoms/skills/pptx/SKILL.md) |
| 游戏 | [游戏](../apps/api/atoms/skills/game.md)及按渲染方式选用的 [2D](../apps/api/atoms/skills/game-2d.md) 或 [Three.js](../apps/api/atoms/skills/threejs-game.md) 指导 |
| 视频 | Vidu 文生视频与图生视频 |

[Skill 目录](../apps/api/atoms/skills/__init__.py)读取并缓存生成指导。[提示组装](../apps/api/atoms/prompts.py)将产物契约和生成指导放进系统消息。用户需求、历史代码和修复反馈作为任务数据传入。[Worker](../apps/api/atoms/worker.py)负责模型调用、积分结算、构建和版本交付。

## 网站源码与数据

网站生成和修复会自动加载 [Frontend Design Skill](../apps/api/atoms/skills/frontend-design/SKILL.md)。规划先根据主题和受众确定首屏焦点、布局、配色及字体层级，生成时结合用户需求和可用的本地素材落实。已有网站按本次需求调整。视觉偏好用于生成指导。

项目随 Worker 镜像分发原版 Skill 和许可证。[Anthropic 上游版本](https://github.com/anthropics/skills/tree/2c5958ecac7cee2b583967a2c4981d0f4a75c579/skills/frontend-design) · [Apache 2.0 许可证](../apps/api/atoms/skills/frontend-design/LICENSE.txt)

新网站采用 [React 产物契约](../shared/contracts/react-artifact.schema.json)。入口是 `src/App.tsx`，全局样式是 `src/styles.css`。模型按职责拆分本地 TSX、TS 和 JSON 文件。校验器使用预装的 React 依赖打包，并在隔离浏览器里启动。失败原因回到现有修复流程。旧网站继续使用其原有契约完成版本编辑和导出。

识别到外汇或汇率需求时，Worker 写入 `src/data/exchange-rates.json`，来源、发布日期与汇率随版本保存。模型负责呈现平台给出的数据状态。导出 ZIP 根目录为构建产物，`source/` 是可继续开发的 Vite 工程。

### 网站模板

[网站模板选择器](../apps/api/atoms/website_starters.py)为新网站匹配新闻资讯、作品集和产品发布三种结构。命中后，模型同时收到原始需求和 [参考源码](../apps/api/atoms/website_templates)。仅指定网站类型时，模型也要选择适合的主题，创作站点名称、首屏和示例内容。参考源码用 `[[copy:字段名]]` 表示待创作文案，生成提示要求替换为本次项目的内容。示例配图按需显式复用。未匹配、意图重叠、明确要求不用模板的项目使用自由生成。版本迭代基于已保存的源码。

财经资讯由 [公开发布数据接入](../apps/api/atoms/editorial_feed.py)在构建时读取官方订阅源，并保存可追溯的标题、日期和链接。优先展示近 45 天的条目。资讯样稿只用于通用新闻模板，界面明确标为示例。

## 游戏渲染与生成

用户明确指定二维或三维时，以该要求为准。编辑已有游戏时沿用现有渲染方式。新游戏根据类型与视角判断，例如落块和卡牌通常用 2D，第一人称射击和跟车竞速通常用 3D。通用规划处理其他玩法。

游戏规划读取同类公开商店资料，来源保存在 `src/agent/research.json`。十分钟内的同类查询复用结果。外部服务不可用时使用 [内置参考](../apps/api/atoms/game_benchmarks.py)。参考用于补足操作和反馈设计，生成时按用户需求创作场景。

项目收录了 [threejs-game-skills](https://github.com/majidmanzarpour/threejs-game-skills/tree/8286774b22a2566bf894dbc825825c16921866af)，并参考 [web-artifacts-builder](https://github.com/anthropics/skills/tree/2c5958ecac7cee2b583967a2c4981d0f4a75c579/skills/web-artifacts-builder) 的 React 组件和构建原则编写 2D 指导。应用使用现有构建管线、预装依赖和本地资源。上游原文、许可证与脚本存放于仓库供查阅。专项浏览器测试可以独立执行。

## 从模板生成

网页幻灯片与模板生成共用演示设计指导，来源为 [Anthropic pptx](https://github.com/anthropics/skills/tree/2c5958ecac7cee2b583967a2c4981d0f4a75c579/skills/pptx)。交付格式是网页演示。模板管线由应用自带渲染器执行。

幻灯片页的模板目录和预览共用 [模板数据](../shared/slide-templates.json)。模板详情的提示词保存在当前浏览器会话。提交时将用户文字和模板 ID 分别保存，Worker 首次构建时向模型请求结构化的逐页内容。[模板渲染器](../apps/api/atoms/slide_decks.py)校验内容字段，按模板调色板和版式顺序生成三文件产物，翻页使用平台提供的脚本。最终产物仍经过隔离浏览器检查。修复沿用绑定的模板，后续编辑以已保存的版本为基础。

版式参考公开的演示模板类别，预览画面、文案和示例数据为本项目编排。 [SlidesCarnival 报告模板](https://www.slidescarnival.com/hub/report) · [Reveal.js 主题](https://revealjs.com/themes/)
