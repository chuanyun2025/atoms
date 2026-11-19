// @vitest-environment happy-dom
import {act} from "react";
import {createRoot,type Root} from "react-dom/client";
import {QueryClient,QueryClientProvider} from "@tanstack/react-query";
import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import WalletButton from "./Wallet";

(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT = true;

describe("WalletButton and ledger modal", () => {
  let container: HTMLDivElement;
  let root: Root;
  let queryClient: QueryClient;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    queryClient = new QueryClient({
      defaultOptions: {queries: {retry: false}},
    });
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    queryClient.clear();
    container.remove();
    vi.restoreAllMocks();
  });

  it("displays shortened balance and opens modal with pending uncertain holds and ledger entries", async () => {
    let redeemed = false;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/session")) {
        return new Response(
          JSON.stringify({visitor_id: "vis_demo_123", csrf_token: "csrf_test"}),
          {status: 200, headers: {"Content-Type": "application/json"}},
        );
      }
      if (url.endsWith("/api/v1/wallet/passcode") && init?.method === "POST") {
        redeemed = true;
      }
      if (url.endsWith("/api/v1/wallet") || url.endsWith("/api/v1/wallet/passcode")) {
        return new Response(
          JSON.stringify({
            visitor_id: "vis_demo_123",
            balance: "49",
            held: "13",
            available: "36",
            spent: "1",
            available_units: 36_000_000,
            welcome_credits: 50,
            credits_per_yuan: 10,
            pricing: {input_per_million: 20, output_per_million: 80},
            guardrails: {
              daily_budget_enabled: true,
              daily_budget_credits: "1000",
              daily_remaining_credits: "0",
              daily_budget_reached: !redeemed,
              reset_at: 1763481600,
              reset_label: "2026-11-18 00:00 (Asia/Shanghai)",
              public_video_enabled: false,
              video_unlocked: redeemed,
              passcode: redeemed
                ? {
                    id: "pc_1",
                    label: "面试官专属",
                    status: "active",
                    budget: "100",
                    spent: "0",
                    held: "0",
                    remaining: "100",
                    remaining_units: 100_000_000,
                    bypass_daily_budget: true,
                    allow_video: true,
                    expires_at: null,
                  }
                : null,
            },
          }),
          {status: 200, headers: {"Content-Type": "application/json"}},
        );
      }
      return new Response(
        JSON.stringify({
          items: [
            {
              id: "led_1",
              kind: "consumption",
              amount: "-1",
              input_tokens: 1200,
              output_tokens: 400,
              created_at: 1763000000,
            },
            {
              id: "led_2",
              kind: "balance_adjustment",
              amount: "-10",
              input_tokens: 0,
              output_tokens: 0,
              created_at: 1763000050,
            },
          ],
          pending: [
            {
              id: "call_uncertain_1",
              status: "uncertain",
              reserved: "13",
              created_at: 1763000100,
              error_code: "MODEL_NETWORK",
            },
          ],
          next_before: null,
        }),
        {status: 200, headers: {"Content-Type": "application/json"}},
      );
    });

    await act(async () => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <WalletButton />
        </QueryClientProvider>,
      );
    });
    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 20));
    });

    expect(container.querySelector('[data-testid="credit-balance"]')?.textContent).toBe("36");

    await act(async () => {
      container.querySelector(".wallet-button")?.dispatchEvent(new MouseEvent("click", {bubbles: true}));
    });
    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 20));
    });

    const dialog = document.body.querySelector('[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog?.querySelector('[data-testid="visitor-id"]')?.textContent).toBe("vis_demo_123");
    expect(dialog?.textContent).toContain("新用户赠送 50 积分");
    expect(dialog?.textContent).toContain("50 积分相当于 5 元使用额度");
    expect(dialog?.textContent).toContain("待核对用量");
    expect(dialog?.textContent).toContain("call_uncertain_1");
    expect(dialog?.textContent).toContain("模型用量消费");
    const adjustment = Array.from(dialog?.querySelectorAll(".wallet-entry") ?? [])
      .find(row => row.querySelector("strong")?.textContent === "余额调整");
    expect(adjustment?.querySelector("b")?.textContent).toBe("-10");
    expect(dialog?.querySelector('[data-testid="public-budget-banner"]')?.textContent).toContain("今日公共体验额度已达上限");

    const codeInput = dialog?.querySelector<HTMLInputElement>('input[aria-label="输入体验口令"]');
    expect(codeInput).not.toBeNull();
    await act(async () => {
      if (codeInput) {
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
        setter?.call(codeInput, "ATOMS-TEST-2026");
        codeInput.dispatchEvent(new Event("input", {bubbles: true}));
      }
    });
    await act(async () => {
      dialog?.querySelector(".wallet-passcode-form")?.dispatchEvent(new Event("submit", {bubbles: true, cancelable: true}));
      await new Promise(resolve => setTimeout(resolve, 20));
    });
    expect(dialog?.querySelector('[data-testid="bound-passcode"]')?.textContent).toContain("面试官专属");

    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
    });
    expect(document.body.querySelector('[role="dialog"]')).toBeNull();
  });
});
