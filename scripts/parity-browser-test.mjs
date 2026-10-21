import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
const base = process.env.VC_TEST_URL;
const pid = process.env.VC_TEST_PROJECT;
const suffix = process.env.VC_TEST_FORCED ? "-forced" : "";
if (!base?.startsWith("http://127.0.0.1:") || !pid) throw Error("Isolated fixture URL and project required");
const browser = await chromium.launch({ headless: true, channel: "chrome" });
const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
const errors = [];
page.on("pageerror", error => errors.push(error.message));
try {
  await page.goto(`${base}/projects/${pid}`);
  await page.getByRole("img", { name: /完整制作依赖图/ }).waitFor();
  await page.getByRole("button", { name: "查看范围并确认", exact: true }).click();
  await page.getByRole("heading", { name: "确认制作范围" }).waitFor();
  await page.screenshot({ path: `docs/evidence/parity/native${suffix}-quote.png`, fullPage: true });
  await page.getByRole("button", { name: "关闭授权" }).click();
  await page.getByRole("button", { name: process.env.VC_TEST_FORCED ? /^B 计划重做/ : /^B 待确认/ }).click();
  if (!(await page.getByText(/已选 B/).isVisible())) throw Error("Native node selection not reflected");
  await page.screenshot({ path: `docs/evidence/parity/native${suffix}-canvas.png`, fullPage: true });
  const bootstrap = await (await page.request.get(`${base}/api/bootstrap`)).json();
  const snapshot = await (await page.request.get(`${base}/api/projects/${pid}`)).json();
  if (!(await page.locator(".topbar").getByText(`修订 ${snapshot.native.authorRevision}`, { exact: true }).isVisible())) throw Error("Header revision differs from the native graph");
  const canvas = await page.request.post(`${base}/api/projects/${pid}/tools/d_canvas_status`, {
    headers: { "x-vc-token": bootstrap.token },
    data: { projectId: snapshot.native.projectId, revision: snapshot.native.authorRevision },
  });
  if (!(await canvas.json()).visibleReceipts?.length) throw Error("Browser-visible receipt missing");
  await page.reload();
  await page.getByRole("img", { name: /完整制作依赖图/ }).waitFor();
  // UI-only delayed quote: prove a pending ordinary action cannot disable Stop.
  // The real stop transaction is separately covered by the cross-process slot test.
  let releaseQuote, enteredQuote;
  const quoteEntered = new Promise(resolve => { enteredQuote = resolve; });
  const quoteRelease = new Promise(resolve => { releaseQuote = resolve; });
  const quotePath = `${base}/api/projects/${pid}/native/quote`;
  const stopPath = `${base}/api/projects/${pid}/stop`;
  await page.route(quotePath, async route => {
    enteredQuote(); await quoteRelease;
    await route.fulfill({ status: 409, json: { detail: "offline delayed quote fixture" } });
  });
  await page.route(stopPath, route => route.fulfill({ json: { new_work_blocked: true } }));
  await page.getByRole("button", { name: "查看范围与增量报价", exact: true }).click();
  await quoteEntered;
  const stopResponse = page.waitForResponse(stopPath);
  const stopStarted = performance.now();
  await page.getByRole("button", { name: "全局停止", exact: true }).click();
  await stopResponse;
  const stopDuringQuoteMs = performance.now() - stopStarted;
  if (stopDuringQuoteMs > 2000) throw Error("Stop was blocked by the pending quote");
  releaseQuote();
  await page.getByText("offline delayed quote fixture").waitFor();
  await page.unroute(quotePath); await page.unroute(stopPath);
  if (errors.length) throw Error(errors.join("\n"));
  fs.writeFileSync(path.resolve(`docs/evidence/parity/browser${suffix}.json`), JSON.stringify({
    source: "isolated local Responses/provider fixture",
    native_graph: true, quote_modal: true, node_selection: true, browser_visible_receipt: true,
    reload: true, pending_quote_does_not_display_old_build_success: !!process.env.VC_TEST_FORCED,
    stop_during_quote_wait: true, stop_during_quote_wait_ms: stopDuringQuoteMs, page_errors: errors
  }, null, 2));
} finally { await browser.close(); }
