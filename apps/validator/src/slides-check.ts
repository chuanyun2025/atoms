import type {Frame} from "playwright";

export const SLIDES_NAVIGATION = "slides-navigation-v1";

const actionTimeout = 800;

/** A generated deck can use any navigation, page indicator, or keyboard scheme. */
export async function sampleSlideNavigation(frame: Frame) {
  const pages = frame.locator("[data-deck-slide]");
  if (await pages.count() < 2) return {status:"unconfirmed" as const};
  const visible = pages.filter({visible:true});
  const next = frame.locator("button[data-deck-next]:visible:enabled").or(
    frame.getByRole("button", {name:/^(下一页|下一张|next(?: slide| page)?)$/i})
      .and(frame.locator(":visible:enabled")),
  );
  // A scrolling deck or custom navigation does not have to follow the template contract.
  if (await visible.count() !== 1 || await next.count() !== 1) return {status:"unconfirmed" as const};
  const initial = await visible.first().evaluate(element => Array.from(document.querySelectorAll("[data-deck-slide]")).indexOf(element));
  await next.click({timeout:actionTimeout});
  const advanced = await frame.waitForFunction(index => Array.from(document.querySelectorAll("[data-deck-slide]")).some((page, i) =>
    i !== index && page.getClientRects().length > 0 && getComputedStyle(page).visibility !== "hidden"), initial, {timeout:1200}).catch(error => {
    if (error?.name !== "TimeoutError") throw error;
    return null;
  });
  return advanced
    ? {status:"observed" as const,action:"next_slide"}
    : {status:"issue" as const,action:"next_slide",diagnostic:"点击可见的下一页按钮后，演示没有翻页"};
}

export async function checkSlidePreview(frame: Frame): Promise<void> {
  const report = await sampleSlideNavigation(frame);
  if (report.status === "issue") throw new Error(report.diagnostic);
}
