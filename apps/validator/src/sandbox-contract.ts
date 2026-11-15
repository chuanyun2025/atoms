import {basename, dirname, posix} from "node:path";
import {createHash} from "node:crypto";
import ts from "typescript";
import {ValidationDiagnostic} from "./diagnostic.js";

const syncMethods = new Set(["get", "set", "remove"]);
const promiseMethods = new Set(["then", "catch", "finally"]);
const browserStorage = new Set(["localStorage", "sessionStorage", "indexedDB"]);
const submitMethods = new Set(["submit", "requestSubmit"]);
const sourceRoot = "/__atoms_source";
const sdkPath = sourceRoot + "/__preview_sdk.d.ts";
const sdkDeclarations = `
  declare var atoms: {
    readonly storage: {
      get<T>(key: string, fallback: T): T;
      get(key: string): unknown;
      set(key: string, value: unknown): void;
      remove(key: string): void;
      flush(): Promise<void>;
    };
  };
  interface Window { readonly atoms: typeof atoms; }
`;

function member(node: ts.Node): { base: ts.Expression; name: string } | undefined {
  if (ts.isPropertyAccessExpression(node)) return {base:node.expression, name:node.name.text};
  if (ts.isElementAccessExpression(node) && ts.isStringLiteralLike(node.argumentExpression)) {
    return {base:node.expression, name:node.argumentExpression.text};
  }
}

function sandboxProgram(sources: Map<string, ts.SourceFile>) {
  const options: ts.CompilerOptions = {
    target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.Preserve, allowJs: true,
    module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler,
    lib: ["lib.es2022.d.ts", "lib.dom.d.ts"], types: [],
  };
  const standardHost = ts.createCompilerHost(options);
  const libraryDir = dirname(standardHost.getDefaultLibFileName(options));
  const isLibrary = (path: string) => dirname(path) === libraryDir && /^lib\.[\w.]+\.d\.ts$/.test(basename(path));
  const sdk = ts.createSourceFile(sdkPath, sdkDeclarations, ts.ScriptTarget.ES2022, true);
  const folders = new Set([sourceRoot]);
  for (const path of sources.keys()) {
    for (let folder = posix.dirname(path); folder.startsWith(sourceRoot); folder = posix.dirname(folder)) {
      folders.add(folder);
    }
  }
  return ts.createProgram([...sources.keys(), sdkPath], options, {
    ...standardHost,
    getCurrentDirectory: () => sourceRoot,
    directoryExists: path => folders.has(path) || path === libraryDir,
    fileExists: path => sources.has(path) || path === sdkPath || (isLibrary(path) && standardHost.fileExists(path)),
    readFile: path => sources.get(path)?.text ?? (path === sdkPath ? sdk.text : isLibrary(path) ? standardHost.readFile(path) : undefined),
    getSourceFile: (path, languageVersion) => sources.get(path) ?? (path === sdkPath ? sdk :
      isLibrary(path) ? standardHost.getSourceFile(path, languageVersion) : undefined),
  });
}

function isDomDeclaration(declaration: ts.Declaration) {
  return basename(declaration.getSourceFile().fileName) === "lib.dom.d.ts" &&
    !declaration.getSourceFile().fileName.startsWith(sourceRoot + "/");
}

function isDomSymbol(symbol: ts.Symbol | undefined) {
  const declarations = symbol?.declarations;
  return !!declarations?.length && declarations.every(isDomDeclaration);
}

export function checkSandboxContract(files: Record<string, unknown>, executableFiles?:ReadonlySet<string>) {
  const sources = new Map<string, ts.SourceFile>();
  for (const [path, code] of Object.entries(files)) {
    if (!/\.(?:jsx?|tsx?)$/.test(path) || typeof code !== "string") continue;
    const filename = sourceRoot + "/" + path;
    sources.set(filename, ts.createSourceFile(filename, code, ts.ScriptTarget.ES2022, true));
  }
  let program: ts.Program | undefined;
  const types = () => (program ??= sandboxProgram(sources)).getTypeChecker();
  const domMember = (base: ts.Expression, name: string) => {
    const checker = types();
    const receiver = checker.getNonNullableType(checker.getTypeAtLocation(base));
    return isDomSymbol(checker.getPropertyOfType(receiver, name));
  };
  const storageError = "预览无法使用浏览器原生存储。使用 window.atoms.storage。";
  const formError = '预览禁用原生表单提交。使用 type="button" 的本地点击处理，并按需绑定回车键。';
  const printer=ts.createPrinter({removeComments:true});

  function hasHandler(expression: ts.Expression | undefined) {
    if (!expression) return false;
    let value=expression;
    while (ts.isParenthesizedExpression(value) || ts.isAsExpression(value) ||
           ts.isNonNullExpression(value) || ts.isSatisfiesExpression(value)) value=value.expression;
    if (value.kind===ts.SyntaxKind.NullKeyword || ts.isVoidExpression(value)) return false;
    return !ts.isIdentifier(value) || value.text!=="undefined" ||
      !!types().getSymbolAtLocation(value)?.declarations?.length;
  }

  for (const [filename, file] of sources) {
    const path = filename.slice(sourceRoot.length + 1);
    if (file.isDeclarationFile || executableFiles && !executableFiles.has(path)) continue;
    let first: {code:string; reason:string; line:number; column:number; subject:string; occurrences:number} | undefined;
    function record(node: ts.Node, code:string, reason:string, api:string) {
      const {line, character} = file.getLineAndCharacterOfPosition(node.getStart(file));
      let scope = node.parent;
      while (scope && !ts.isFunctionDeclaration(scope) && !ts.isVariableDeclaration(scope) && !ts.isMethodDeclaration(scope)) {
        scope = scope.parent;
      }
      const name = scope?.name?.getText(file);
      const anchors=ts.isJsxAttribute(node) ? node.parent.properties.filter(prop =>
        ts.isJsxAttribute(prop) && ["id","name","key","aria-label"].includes(prop.name.getText(file))) : [];
      const syntax=(anchors.length ? anchors : [node]).map(part => printer.printNode(ts.EmitHint.Unspecified,part,file)).join(",");
      const key=createHash("sha256").update(syntax).digest("hex").slice(0,16);
      const subject = (name ? api + "@" + name : api)+"#"+key;
      if (!first) first={code,reason,line:line+1,column:character+1,subject,occurrences:1};
      else if (first.code===code && first.subject===subject) first.occurrences++;
    }
    function visit(node: ts.Node) {
      if (ts.isTypeNode(node) || ts.isInterfaceDeclaration(node) || ts.isTypeAliasDeclaration(node) ||
          (ts.canHaveModifiers(node) && ts.getModifiers(node)?.some(modifier => modifier.kind===ts.SyntaxKind.DeclareKeyword))) return;
      if (ts.isJsxAttribute(node) && ["onSubmit", "onSubmitCapture"].includes(node.name.getText(file))) {
        const {tagName} = node.parent.parent;
        const initializer = node.initializer;
        if (ts.isIdentifier(tagName) && tagName.text === "form" && initializer && ts.isJsxExpression(initializer) &&
            hasHandler(initializer.expression)) {
          const handler = initializer.expression!;
          const api = ts.isIdentifier(handler) ? node.name.getText(file) + ":" + handler.text : node.name.getText(file);
          record(node, "SANDBOX_FORM_SUBMIT", '原生 <form> 上的提交事件在预览沙箱中不可用。使用 type="button" 的 onClick，并按需绑定 onKeyDown。', api);
        }
      }
      const access = member(node);
      if (access && (browserStorage.has(access.name) || access.name === "cookie") && domMember(access.base, access.name)) {
        record(node, "SANDBOX_NATIVE_STORAGE", storageError, access.name);
        return;
      }
      if (ts.isIdentifier(node) && browserStorage.has(node.text)) {
        const checker = types();
        const symbol = ts.isShorthandPropertyAssignment(node.parent)
          ? checker.getShorthandAssignmentValueSymbol(node.parent) : checker.getSymbolAtLocation(node);
        if (isDomSymbol(symbol)) record(node, "SANDBOX_NATIVE_STORAGE", storageError, node.text);
      }
      if (access && promiseMethods.has(access.name) && ts.isCallExpression(access.base)) {
        const declaration = types().getResolvedSignature(access.base)?.declaration;
        if (declaration?.getSourceFile().fileName === sdkPath && ts.isMethodSignature(declaration) &&
            ts.isIdentifier(declaration.name) && syncMethods.has(declaration.name.text)) {
          record(node, "SANDBOX_SDK_SYNC", "Atoms storage.get/set/remove 是同步方法，只有 storage.flush() 返回 Promise。", declaration.name.text);
          return;
        }
      }
      if (access?.name === "onsubmit" && ts.isBinaryExpression(node.parent) && node.parent.left === node &&
          node.parent.operatorToken.kind === ts.SyntaxKind.EqualsToken && hasHandler(node.parent.right) &&
          domMember(access.base, "requestSubmit")) {
        record(node, "SANDBOX_FORM_SUBMIT", formError, "onsubmit");
      }
      if (ts.isCallExpression(node)) {
        const method = member(node.expression);
        const event = node.arguments[0];
        if (method && (submitMethods.has(method.name) ||
            (method.name === "addEventListener" && event && ts.isStringLiteralLike(event) && event.text === "submit")) &&
            domMember(method.base, "requestSubmit") && domMember(method.base, method.name)) {
          record(node, "SANDBOX_FORM_SUBMIT", formError, method.name);
        }
      }
      ts.forEachChild(node, visit);
    }
    visit(file);
    if (first) {
      const {code,reason,...location}=first;
      throw new ValidationDiagnostic(code,reason,{file:path,...location});
    }
  }
}
