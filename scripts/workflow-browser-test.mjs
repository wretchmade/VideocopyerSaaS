// Read-only UI regression. Synthetic snapshots exercise status transitions and
// scale in the browser only; all application writes are blocked by this test.
import { chromium, expect } from "@playwright/test";
import fs from "node:fs/promises";
const base = "http://127.0.0.1:8765",
  pid = "49b2b8b68b1a46ab99d232d6992e1a52",
  empty = "2ef94da9bb9a49ee87f8c4ba8b5287b4";
const browser = await chromium.launch({ channel: "chrome", headless: true });
const context = await browser.newContext({
  viewport: { width: 1500, height: 1000 },
});
const page = await context.newPage();
const errors = [],
  mutations = [],
  checks = [],
  benchmarks = [];
let fixture = null;
page.on("pageerror", (e) => errors.push(e.message));
await page.addInitScript(
  ({ pid }) => {
    const original = window.fetch;
    window.fetch = async (...args) => {
      const r = await original(...args);
      if (String(args[0]) === "/api/projects/" + pid)
        window.__lastProjectResponse = performance.now();
      return r;
    };
  },
  { pid },
);
await context.route("**/api/**", async (route) => {
  const req = route.request();
  if (!["GET", "HEAD"].includes(req.method())) {
    mutations.push(req.url());
    return route.abort();
  }
  if (fixture && req.url() === base + "/api/projects/" + pid)
    return route.fulfill({ json: fixture });
  return route.continue();
});
const budgetBefore = await page.request
  .get(base + "/api/bootstrap")
  .then((r) => r.json());
const actual = await page.request
  .get(base + "/api/projects/" + pid)
  .then((r) => r.json());
const key = "videocopyer.workflow.v2." + pid;
const saved = () =>
  page.evaluate((k) => JSON.parse(localStorage.getItem(k)), key);
const runs = () => page.locator(".workflow").getAttribute("data-layout-runs");
try {
  await page.goto(base + "/projects/" + pid);
  await expect(
    page.getByRole("heading", { name: "制作工作流 R2" }),
  ).toBeVisible();
  await expect(page.locator(".wf-node")).toHaveCount(6);
  await expect(page.locator(".wf-generation")).toHaveCount(0);
  await expect(page.getByText("复用已有素材", { exact: true })).toHaveCount(2);
  await expect(page.locator(".wf-delivery-preview")).toHaveCount(1);
  await expect(page.locator("[data-reference]")).toHaveCount(0);
  await expect(page.locator('[data-edge="bus"]')).toHaveCount(1);
  await page.waitForFunction(() =>
    [...document.querySelectorAll(".wf-media video")].every(
      (v) => v.readyState >= 1 && v.duration >= 5,
    ),
  );
  checks.push(
    "real revision: 2 reused media, no invented generation tasks, 1 current delivery, one merge bus",
  );
  const originalRuns = await runs();
  await page.locator('[data-flow-node="shot:s1"] .wf-shot-select').click();
  await expect(page.locator(".context-tag")).toContainText("整理白色雏菊");
  await expect(page.locator('[data-reference="s1"]')).toHaveCount(1);
  expect(await runs()).toBe(originalRuns);
  await page.getByRole("button", { name: "取消选中", exact: true }).click();
  await expect(page.locator("[data-reference]")).toHaveCount(0);
  await page.getByRole("button", { name: /历史与包装/ }).click();
  await expect(
    page.getByRole("complementary", { name: "历史构建与交付" }),
  ).toBeVisible();
  await expect(page.locator(".wf-history-build .flow-card")).toHaveCount(2);
  expect(await runs()).toBe(originalRuns);
  await page.getByRole("button", { name: "关闭画布侧栏" }).click();
  await page
    .getByRole("button", { name: "展开工作流画布", exact: true })
    .click();
  await expect(page.locator(".workflow-focus")).toHaveCSS("position", "fixed");
  await page.screenshot({
    path: "docs/evidence/workflow-lanes-full.png",
    fullPage: true,
  });
  expect(await runs()).toBe(originalRuns);
  await page.getByRole("button", { name: "放大画布", exact: true }).click();
  await expect.poll(async () => (await saved())?.zoom).toBeGreaterThan(0.8);
  expect(await runs()).toBe(originalRuns);
  await page
    .getByRole("button", { name: "适应全部工作流", exact: true })
    .click();
  const box = await page.locator('[data-drag-row="s1"]').boundingBox();
  const z = await page
    .locator(".workflow-navigation")
    .getByRole("button", { name: "实际大小", exact: true })
    .textContent();
  const distance = (532 * parseFloat(z)) / 100;
  await page.mouse.move(box.x + 40, box.y + 10);
  await page.mouse.down();
  await page.mouse.move(box.x + 40, box.y + 10 + distance, { steps: 6 });
  await page.mouse.up();
  await expect
    .poll(async () => (await saved())?.positions["row:s1"])
    .toBeGreaterThan(700);
  const positions = (await saved()).positions;
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "制作工作流 R2" }),
  ).toBeVisible();
  await expect
    .poll(async () => JSON.stringify((await saved()).positions))
    .toBe(JSON.stringify(positions));
  await page.getByRole("button", { name: "整理布局", exact: true }).click();
  await expect
    .poll(async () => Object.keys((await saved()).positions).length)
    .toBe(0);
  checks.push(
    "selection highlights auxiliary refs only; history is off main graph; zoom/focus do not rerun layout; row drag persists; organize resets it",
  );
  const beforePan = await runs();
  await page.locator(".workflow-surface").focus();
  await page.keyboard.press("ArrowLeft");
  expect(await runs()).toBe(beforePan);
  await page.getByRole("button", { name: "编辑规划", exact: true }).click();
  await page.getByRole("button", { name: "添加镜头", exact: true }).click();
  await page.getByRole("button", { name: "关闭编辑", exact: true }).click();
  await page
    .locator(".workflow-footer")
    .getByRole("button", { name: "准备制作" })
    .click();
  await expect(
    page.getByRole("heading", { name: "确认制作范围" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "关闭授权" }).click();
  await page
    .getByRole("button", { name: "适应全部工作流", exact: true })
    .click();
  await page.screenshot({
    path: "docs/evidence/workflow-lanes-desktop.png",
    fullPage: true,
  });
  await page.goto(base + "/projects/" + empty);
  await expect(
    page.getByRole("heading", { name: "制作工作流 R0" }),
  ).toBeVisible();
  await expect(page.getByText("等待确定分镜", { exact: true })).toBeVisible();
  await expect(page.locator(".workflow-footer button")).toBeDisabled();
  await expect(page.locator(".wf-generation")).toHaveCount(0);
  await page.screenshot({
    path: "docs/evidence/workflow-lanes-empty.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(base + "/projects/" + pid);
  await page.getByRole("button", { name: "制作画布", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "制作工作流 R2" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "适应全部工作流" }).click();
  await page.screenshot({
    path: "docs/evidence/workflow-lanes-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  checks.push(
    "authoring/quote modals, empty workflow and 390px mobile still work without writes",
  );
  await page.setViewportSize({ width: 1500, height: 1000 });
  for (const count of [10, 50, 100]) {
    const shots = Array.from({ length: count }, (_, i) => ({
      id: "bench" + i,
      title: "性能测试镜头 " + (i + 1),
      description: "合成快照，仅测试浏览器布局和状态更新。",
      duration: 5,
      subtitle: "",
      character_ids: [],
      file_id: null,
      source_start: 0,
      generate: true,
    }));
    fixture = {
      ...structuredClone(actual),
      revision: 50,
      files: [],
      deliveries: [],
      tasks: [
        {
          id: "bench-build",
          revision: 50,
          status: "running",
          nodes: [{ id: "$render", status: "pending" }],
          shot_outputs: shots.map((s) => ({
            shot_id: s.id,
            node_id: "gen_" + s.id,
            status: "pending",
            output_file_id: null,
            input_file_ids: [],
            reused: false,
            provider: "test",
            model: "snapshot",
          })),
        },
      ],
      planning: {
        plan: {
          ...actual.planning.plan,
          title: "浏览器性能测试",
          characters: [],
          shots,
          audio_file_id: null,
        },
      },
    };
    await page.goto(base + "/projects/" + pid);
    await expect(page.locator(".wf-node")).toHaveCount(count * 3 + 2);
    const before = await runs();
    const geometry = await page
      .locator('[data-edge="input:bench0"]')
      .getAttribute("d");
    const initialMs = Number(
      await page.locator(".workflow").getAttribute("data-layout-ms"),
    );
    await page.evaluate(() => {
      window.__stateLatency = null;
      const target = document.querySelector(".wf-generation .flow-status");
      window.__statusObserver = new MutationObserver(() => {
        if (target.textContent.includes("执行中")) {
          window.__stateLatency =
            performance.now() - window.__lastProjectResponse;
          window.__statusObserver.disconnect();
        }
      });
      window.__statusObserver.observe(target, {
        subtree: true,
        childList: true,
        characterData: true,
      });
    });
    fixture.tasks[0].shot_outputs[0].status = "running";
    await expect(
      page.locator(".wf-generation .flow-status").first(),
    ).toHaveText("执行中", { timeout: 10000 });
    expect(await runs()).toBe(before);
    expect(
      await page.locator('[data-edge="input:bench0"]').getAttribute("d"),
    ).toBe(geometry);
    const latency = await page.evaluate(() => window.__stateLatency);
    expect(latency).not.toBeNull();
    benchmarks.push({
      shots: count,
      nodes: count * 3 + 2,
      browser_layout_ms: initialMs,
      response_to_status_dom_ms: latency,
      status_layout_recalculations: Number(await runs()) - Number(before),
    });
  }
  // A newer, unbuilt revision must not acquire the previous build's media/ports.
  fixture = { ...structuredClone(actual), revision: 3 };
  await page.goto(base + "/projects/" + pid);
  await expect(
    page.getByRole("heading", { name: "制作工作流 R3" }),
  ).toBeVisible();
  await expect(page.locator(".wf-media video")).toHaveCount(0);
  await expect(page.locator(".wf-delivery-preview")).toHaveCount(0);
  await expect(page.locator(".wf-generation")).toHaveCount(0);
  checks.push(
    "synthetic 32/152/302-node status transitions preserve positions/paths with zero layout reruns; unbuilt revision never presents old build outputs",
  );
  const budgetAfter = await page.request
    .get(base + "/api/bootstrap")
    .then((r) => r.json());
  expect(budgetAfter.reserved_micros).toBe(budgetBefore.reserved_micros);
  expect(errors).toEqual([]);
  expect(mutations).toEqual([]);
  const result = {
    checks,
    benchmarks,
    errors,
    mutations,
    reserved_micros: budgetAfter.reserved_micros,
    measurement:
      "Browser: one initial layout and one synthetic poll response per scale; response arrival to DOM status mutation, excludes network and next-poll wait, no generated video decoding in scale fixtures. Not a p95 or production SLA.",
  };
  await fs.writeFile(
    "docs/evidence/workflow-browser.json",
    JSON.stringify(result, null, 2),
  );
  console.log(JSON.stringify(result));
} finally {
  await browser.close();
}
