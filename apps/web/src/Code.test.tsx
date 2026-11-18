// @vitest-environment happy-dom
import {act} from "react";
import {createRoot,type Root} from "react-dom/client";
import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import Code from "./Code";

(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT = true;

describe("Code workspace component", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it("remounts CodeMirror cleanly when switching between React and classic HTML layouts", () => {
    const onEdit = vi.fn();
    const reactFiles = {
      "src/App.tsx": "export default function App() { return <h1>React View</h1>; }",
      "src/components/Card.tsx": "export function Card() { return <div>Card Body</div>; }",
      "src/styles.css": "body { margin: 0; }",
    };
    const classicFiles = {
      "index.html": "<main>Classic HTML View</main>",
      "styles.css": "main { padding: 16px; }",
      "app.js": "console.log('ready');",
    };

    act(() => {
      root.render(<Code files={reactFiles} edits={{}} editable={true} onEdit={onEdit} />);
    });

    expect(container.querySelector(".react-code-panel")).not.toBeNull();
    expect(container.querySelector(".cm-editor")).not.toBeNull();
    expect(container.querySelector(".cm-content")?.textContent).toContain("React View");

    // Switch to classic 3-file HTML container layout
    act(() => {
      root.render(<Code files={classicFiles} edits={{}} editable={false} onEdit={onEdit} />);
    });

    expect(container.querySelector(".react-code-panel")).toBeNull();
    expect(container.querySelector(".file-tabs")).not.toBeNull();
    expect(container.querySelector(".cm-editor")).not.toBeNull();
    expect(container.querySelector(".cm-content")?.textContent).toContain("Classic HTML View");

    // Switch file tab in classic mode
    const cssTab = Array.from(container.querySelectorAll(".file-tabs button")).find(
      button => button.textContent === "styles.css",
    );
    expect(cssTab).toBeDefined();
    act(() => {
      cssTab?.dispatchEvent(new MouseEvent("click", {bubbles: true}));
    });
    expect(container.querySelector(".cm-content")?.textContent).toContain("padding: 16px");

    // Switch back to React container layout and filter files
    act(() => {
      root.render(<Code files={reactFiles} edits={{}} editable={true} onEdit={onEdit} />);
    });

    expect(container.querySelector(".react-code-panel")).not.toBeNull();
    expect(container.querySelector(".cm-editor")).not.toBeNull();
    expect(container.querySelector(".cm-content")?.textContent).toContain("React View");

    const cardButton = Array.from(container.querySelectorAll(".code-file-browser button")).find(
      button => button.textContent?.includes("Card.tsx"),
    );
    expect(cardButton).toBeDefined();
    act(() => {
      cardButton?.dispatchEvent(new MouseEvent("click", {bubbles: true}));
    });
    expect(container.querySelector(".cm-content")?.textContent).toContain("Card Body");
  });
});
