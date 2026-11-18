# ADR-0001：多层静态契约校验与隔离无头浏览器真实验收闭环

- **状态**：已采纳
- **关联模块**：`apps/validator/src/`、`apps/api/atoms/runtime/worker.py`、`apps/api/atoms/runtime/preview.py`

## 背景

自然语言生成的网页与游戏代码属于不可信输入，同时容易出现三类典型缺陷：
1. **语法与依赖幻觉**：引用未安装的第三方包、使用不存在的 TypeScript 类型或非法的相对路径。
2. **沙箱越界行为**：尝试调用原生表单提交（导致 iframe 导航白屏）、读写 `localStorage` / `document.cookie`、或发起外部网络请求。
3. **运行时静默崩溃**：编译通过但首屏挂载即抛异常、3D/Canvas 循环卡死或关键交互无响应。

仅靠提示词约束或单纯打包编译无法保证交付产物在受限预览环境中真正可操作。

## 决策

将代码验证拆分为无数据库访问权限的独立服务 `@atoms/validator`，在每次生成与自动修复候选落库前强制执行三级流水线：

1. **包白名单与捆绑编译**（`apps/validator/src/react-compiler.ts`、`compiler.ts`）：
   - 校验 JSON Schema（文件路径字符集、必需入口 `src/App.tsx` 与 `src/styles.css`）；
   - 通过自定义 `esbuild` 插件严格限定外部模块仅能解析平台预装依赖（`shared/runtime-dependencies.json`），拦截动态 `import()`、路径别名与越界文件访问。
2. **AST / HTML / CSS 静态沙箱契约检查**（`apps/validator/src/sandbox-contract.ts`）：
   - 对实际纳入捆绑图的运行时模块做 TypeScript 语义检查与 AST 扫描（跳过纯类型声明以消除误报），拦截原生存储 API、原生 `<form>` 提交事件及误把同步 `window.atoms.storage.get/set` 当 Promise 调用的常见错误；
   - 通过复用的增量 TypeScript `Program` 缓存标准库 AST，将静态契约校验耗时保持在毫秒级。
3. **隔离 Chromium 启动与探针验收**（`apps/validator/src/probe.ts`、`game-check.ts`、`fps-check.ts`、`slides-check.ts`）：
   - 在非 root Chromium 进程中以严格 CSP（`connect-src 'none'`、opaque-origin 沙箱）加载真实产物，捕获首屏未处理异常与空白渲染，并按项目类型执行自动化探针。
4. **受限根因修复闭环**（`apps/api/atoms/runtime/build_diagnostics.py`、`worker.py`）：
   - 失败诊断携带精确错误码、文件与行号回传生成 Agent（最多 10 轮，同一根因最多 2 轮），并在 `run_candidates` 中保留草稿支持断点续修，绝不覆盖上一可用版本。

## 后果

- **正面**：用户拿到的每一个成功版本均已通过真实浏览器启动检验；生成代码无法窃取宿主会话或发起越权外联。
- **权衡**：单机需要常驻轻量校验服务与 Chromium 运行环境，浏览器校验通过独立槽位控制并发以换取稳定的内存上界。
