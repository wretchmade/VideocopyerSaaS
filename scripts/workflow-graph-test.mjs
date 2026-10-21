import assert from "node:assert/strict";
import fs from "node:fs/promises";
import ts from "typescript";
const source = await fs.readFile(
  new URL("../web/workflowGraph.ts", import.meta.url),
  "utf8",
);
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ESNext,
  },
}).outputText;
const { layoutGraph, topologyKey, moveRow, FIRST_ROW, ROW_STEP } = await import(
  "data:text/javascript;base64," + Buffer.from(compiled).toString("base64")
);
const tests = [];
const topology = {
  shots: [
    { id: "s1", generation: "gen_s1" },
    { id: "s2", generation: null },
  ],
  build: "b1",
  audio: true,
};
const graph = layoutGraph(topology);
assert.equal(graph.nodes.filter((n) => n.kind === "generation").length, 1);
assert.equal(graph.nodes.length, 7);
assert.equal(
  graph.nodes.find((n) => n.id === "shot:s1").y,
  graph.nodes.find((n) => n.id === "media:s1").y,
);
assert.equal(graph.edges.filter((e) => e.id === "bus").length, 1);
tests.push(
  "actual generation node only; reused media bypasses generation; aligned lanes; one merge bus",
);
function crosses([ax, ay], [bx, by], r) {
  if (ax === bx)
    return (
      ax > r.x &&
      ax < r.x + r.width &&
      Math.max(ay, by) > r.y &&
      Math.min(ay, by) < r.y + r.height
    );
  return (
    ay > r.y &&
    ay < r.y + r.height &&
    Math.max(ax, bx) > r.x &&
    Math.min(ax, bx) < r.x + r.width
  );
}
function checkEdges(g) {
  for (const e of g.edges)
    for (let i = 1; i < e.points.length; i++) {
      const a = e.points[i - 1],
        b = e.points[i];
      assert.ok(a[0] === b[0] || a[1] === b[1]);
      for (const n of g.nodes)
        assert.ok(!crosses(a, b, n), `${e.id} crosses ${n.id}`);
    }
}
checkEdges(graph);
let positions = moveRow(graph, {}, "s1", FIRST_ROW + ROW_STEP);
const moved = layoutGraph(topology, positions);
checkEdges(moved);
assert.equal(new Set(moved.rows.map((r) => r.y)).size, 2);
assert.equal(
  moved.rows.find((r) => r.id === "s2").y,
  graph.rows.find((r) => r.id === "s2").y,
);
const added = layoutGraph(
  { ...topology, shots: [{ id: "new", generation: null }, ...topology.shots] },
  positions,
);
for (const row of moved.rows)
  assert.equal(added.rows.find((r) => r.id === row.id).y, row.y);
checkEdges(
  layoutGraph(topology, { ...positions, finish: FIRST_ROW + ROW_STEP * 8 }),
);
tests.push(
  "orthogonal edges never cross card interiors, including moved rows and finish; inserting a row preserves pinned rows",
);
const p = {
  revision: 1,
  planning: {
    plan: { shots: [{ id: "s1", title: "title" }], audio_file_id: null },
  },
  tasks: [
    {
      id: "b1",
      revision: 1,
      status: "running",
      nodes: [],
      shot_outputs: [
        {
          shot_id: "s1",
          node_id: "gen_s1",
          status: "running",
          output_file_id: null,
        },
      ],
    },
  ],
};
const before = topologyKey(p);
p.tasks[0].status = "succeeded";
p.tasks[0].shot_outputs[0].status = "succeeded";
p.tasks[0].shot_outputs[0].output_file_id = "new-file";
p.planning.plan.shots[0].title = "changed title";
p.deliveries = [{ id: "delivery" }];
assert.equal(topologyKey(p), before);
p.revision = 2;
assert.notEqual(topologyKey(p), before);
assert.equal(JSON.parse(topologyKey(p)).shots[0].generation, null);
tests.push(
  "status, output readiness, title and packaging changes do not invalidate topology; new revision never borrows old task",
);
const metrics = [];
for (const count of [10, 50, 100]) {
  const t = {
    shots: Array.from({ length: count }, (_, i) => ({
      id: "s" + i,
      generation: "gen_s" + i,
    })),
    build: "benchmark",
    audio: true,
  };
  for (let i = 0; i < 20; i++) layoutGraph(t);
  const samples = [];
  for (let i = 0; i < 100; i++) {
    const start = performance.now();
    layoutGraph(t);
    samples.push(performance.now() - start);
  }
  samples.sort((a, b) => a - b);
  const g = layoutGraph(t);
  checkEdges(g);
  metrics.push({
    shots: count,
    nodes: g.nodes.length,
    layout_p50_ms: samples[50],
    layout_p95_ms: samples[95],
  });
}
await fs.writeFile(
  "docs/evidence/workflow-graph-tests.json",
  JSON.stringify(
    {
      tests,
      metrics,
      scope:
        "Pure deterministic layout in Node.js; no DOM/video decode or network",
    },
    null,
    2,
  ),
);
console.log(JSON.stringify({ tests, metrics }));
