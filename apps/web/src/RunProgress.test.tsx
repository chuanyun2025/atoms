// @vitest-environment happy-dom
import {act} from "react";
import {createRoot,type Root} from "react-dom/client";
import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import RunProgress from "./RunProgress";

(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT = true;

describe("RunProgress component", () => {
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

  it("renders repair diagnostic location, reconnection banner, and action buttons", () => {
    const onCode = vi.fn();
    const onPreview = vi.fn();

    act(() => {
      root.render(
        <RunProgress
          busy={true}
          connection="reconnecting"
          events={[
            {
              id: 1,
              kind: "plan_ready",
              summary: "采用双栏看板布局",
              items: ["支持新增任务", "持久化状态"],
            },
            {id: 2, kind: "source_ready", message: "源码已可查看"},
            {id: 3, kind: "preview_ready", message: "临时预览已可体验"},
            {
              id: 4,
              kind: "repairing",
              message: "修正编译错误（第 1/10 轮）",
              diagnostic: {file: "src/App.tsx", line: 18},
            },
          ]}
          onCode={onCode}
          onPreview={onPreview}
        />,
      );
    });

    expect(container.textContent).toContain("修正编译错误（第 1/10 轮）");
    expect(container.textContent).toContain("src/App.tsx · 第 18 行");
    expect(container.textContent).toContain("实时连接已断开，正在重新连接");
    expect(container.textContent).toContain("采用双栏看板布局");

    const buttons = Array.from(container.querySelectorAll("button"));
    const codeBtn = buttons.find(btn => btn.textContent === "查看代码");
    const previewBtn = buttons.find(btn => btn.textContent === "打开预览");
    expect(codeBtn).toBeDefined();
    expect(previewBtn).toBeDefined();

    act(() => {
      codeBtn?.dispatchEvent(new MouseEvent("click", {bubbles: true}));
      previewBtn?.dispatchEvent(new MouseEvent("click", {bubbles: true}));
    });
    expect(onCode).toHaveBeenCalledTimes(1);
    expect(onPreview).toHaveBeenCalledTimes(1);
  });
});
