import {expect,test} from "vitest";
import {checkSandboxContract} from "../src/sandbox-contract.js";
import {ValidationDiagnostic} from "../src/diagnostic.js";

test.each([
  ["src/App.tsx", '<form onSubmit={save}><button>保存</button></form>', "onClick"],
  ["src/App.tsx", '<form onSubmitCapture={save} />', "onClick"],
  ["app.js", 'document.querySelector("form")?.addEventListener("submit", save)', "原生表单提交"],
  ["app.js", 'document.forms[0].requestSubmit()', "原生表单提交"],
  ["app.js", 'document.querySelector("form")?.["submit"]()', "原生表单提交"],
  ["app.js", 'const form = document.createElement("form"); form.onsubmit = save', "原生表单提交"],
  ["src/App.tsx", 'window.atoms.storage.get("key", []).then(setItems)', "同步方法"],
  ["src/App.tsx", 'const {remove} = atoms.storage; remove("key").finally(cleanup)', "同步方法"],
  ["src/App.tsx", 'window.localStorage.getItem("key")', "浏览器原生存储"],
  ["app.js", 'const host = window; host["sessionStorage"].clear()', "浏览器原生存储"],
  ["app.js", 'localStorage.getItem("key")', "浏览器原生存储"],
  ["app.js", 'const page = document; page.cookie = "test=1"', "浏览器原生存储"],
])("checks runnable source %s for sandbox contract violations", (path, source, diagnostic) => {
  expect(() => checkSandboxContract({[path]:"\n"+source})).toThrow(diagnostic);
  expect(() => checkSandboxContract({[path]:"\n"+source})).toThrow(path+":2:");
});

test("allows application interfaces with browser-like names", () => {
  expect(() => checkSandboxContract({"src/App.tsx":`
    const Widget = ({onSubmit}: {onSubmit: () => void}) =>
      <button type="button" onClick={onSubmit}>保存</button>;
    export const Screen = () => <Widget onSubmit={() => {}} />;
    const controller = {requestSubmit() {}, submit() {}, onsubmit: () => {}};
    controller.requestSubmit();
    controller.submit();
    controller.onsubmit = () => {};
    new EventTarget().addEventListener("submit", () => {});
    const localStorage = new Map();
    const atoms = {storage:{get: () => Promise.resolve("custom")}};
    localStorage.get("name");
    atoms.storage.get().then(console.log);
  ` })).not.toThrow();
});

test("checks browser use inferred through a local module import", () => {
  expect(() => checkSandboxContract({
    "src/form.ts": 'export const entry = document.createElement("form");',
    "src/App.tsx": 'import {entry} from "./form"; entry.requestSubmit();',
  })).toThrow("原生表单提交");
});

test("allows clearing a native handler and a lexically scoped storage object", () => {
  expect(() => checkSandboxContract({
    "app.js": 'const form = document.createElement("form"); form.onsubmit = null; { const localStorage = new Map(); localStorage.clear(); }',
    "src/Form.tsx": '<form onSubmit={null} />',
  })).not.toThrow();
});

test("allows real click handlers and the asynchronous flush method", () => {
  expect(() => checkSandboxContract({"src/App.tsx":`
    const save = () => {
      window.atoms.storage.set("draft", window.atoms.storage.get("value", ""));
      window.atoms.storage.flush().catch(reportError);
    };
    const app = <form><button type="button" onClick={save}>保存</button></form>;
  `})).not.toThrow();
});

function formDiagnostic(forms:string) {
  try {
    checkSandboxContract({"src/App.tsx":`export default function App(){return <>${forms}</>}`});
  } catch (error) {
    if (error instanceof ValidationDiagnostic) return error.location;
    throw error;
  }
  throw new Error("expected a form diagnostic");
}

test("tracks separate stable form sites inside the same component", () => {
  const form=(id:string)=>`<form id="${id}" onSubmit={event=>event.preventDefault()} />`;
  const first=formDiagnostic(form("a")+form("b"));
  const moved=formDiagnostic("\n\n"+form("a").replace("event=>","event => "));
  const next=formDiagnostic('<form id="a" />'+form("b"));
  expect(moved.line).not.toBe(first.line);
  expect(moved.subject).toBe(first.subject);
  expect(next.subject).not.toBe(first.subject);
});

test("counts identical sites so removing one still registers progress", () => {
  const form='<form onSubmit={event=>event.preventDefault()} />';
  const two=formDiagnostic(form+form), one=formDiagnostic("<form/>"+form);
  expect(two.subject).toBe(one.subject);
  expect(two.occurrences).toBe(2);
  expect(one.occurrences).toBe(1);
});
