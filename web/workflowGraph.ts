import type { Project } from "./main";

export const CARD_WIDTH = 236;
export const CARD_HEIGHT = 218;
export const ROW_STEP = 266;
export const FIRST_ROW = 222;
const COLUMN_STEP = 306;
export type Topology = {
  shots: { id: string; generation: string | null }[];
  build: string;
  audio: boolean;
};
export type Positions = Record<string, number>;
export type GraphNode = {
  id: string;
  kind: "shot" | "generation" | "media" | "render" | "delivery";
  shot?: string;
  x: number;
  y: number;
  width: number;
  height: number;
};
export type GraphEdge = {
  id: string;
  kind: "flow" | "merge" | "audio";
  shot?: string;
  points: [number, number][];
  d: string;
};
export type Graph = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  width: number;
  height: number;
  hasGeneration: boolean;
  columns: { x: number; title: string }[];
  rows: { id: string; y: number }[];
  renderY: number;
};

// Status, output file IDs, delivery packaging and prompt edits are deliberately
// absent: these update card contents without invalidating layout or edge geometry.
export function topologyKey(project: Project): string {
  const current = project.tasks
    .slice()
    .reverse()
    .find((t) => t.revision === project.revision);
  const output = new Map(
    current?.shot_outputs?.map((o) => [o.shot_id, o]) || [],
  );
  return JSON.stringify({
    shots: project.planning.plan.shots.map((s) => ({
      id: s.id,
      generation: output.get(s.id)?.node_id || null,
    })),
    build: current?.id || "pending-r" + project.revision,
    audio: !!current && !!project.planning.plan.audio_file_id,
  } satisfies Topology);
}
// Round reference routes inside their reserved gutter. Limit each bend to half
// its adjoining segments so short routes cannot overshoot into a card.
export const path = (points: [number, number][]) => {
  if (!points.length) return "";
  let d = `M ${points[0].join(" ")}`;
  for (let i = 1; i < points.length - 1; i++) {
    const a = points[i - 1], b = points[i], c = points[i + 1];
    const incoming = Math.hypot(b[0] - a[0], b[1] - a[1]);
    const outgoing = Math.hypot(c[0] - b[0], c[1] - b[1]);
    const r = Math.min(24, incoming / 2, outgoing / 2);
    if (!r) continue;
    const before = b.map((v, axis) => v + (a[axis] - v) * r / incoming);
    const after = b.map((v, axis) => v + (c[axis] - v) * r / outgoing);
    d += ` L ${before.join(" ")} Q ${b.join(" ")} ${after.join(" ")}`;
  }
  if (points.length > 1) d += ` L ${points[points.length - 1].join(" ")}`;
  return d;
};

export function layoutGraph(
  topology: Topology,
  positions: Positions = {},
): Graph {
  const hasGeneration = topology.shots.some((s) => !!s.generation);
  const mediaX = COLUMN_STEP * (hasGeneration ? 2 : 1);
  const renderX = mediaX + COLUMN_STEP;
  const deliveryX = renderX + COLUMN_STEP;
  const nodes: GraphNode[] = [],
    edges: GraphEdge[] = [];
  // Existing rows retain their slots. New rows take free slots, never displacing
  // rows that the user already moved. Vertical row movement preserves topology.
  const occupied = new Set<number>();
  const reserved = new Map<string, number>();
  for (const s of topology.shots) {
    const saved = positions["row:" + s.id];
    if (!Number.isFinite(saved)) continue;
    let slot = Math.max(0, Math.round((saved - FIRST_ROW) / ROW_STEP));
    while (occupied.has(slot)) slot++;
    occupied.add(slot);
    reserved.set(s.id, slot);
  }
  const rows = topology.shots.map((s, i) => {
    if (reserved.has(s.id))
      return { id: s.id, y: FIRST_ROW + reserved.get(s.id)! * ROW_STEP };
    let slot = i;
    while (occupied.has(slot)) slot++;
    occupied.add(slot);
    return { id: s.id, y: FIRST_ROW + slot * ROW_STEP };
  });
  const average = rows.length
    ? rows.reduce((n, r) => n + r.y, 0) / rows.length
    : FIRST_ROW;
  const renderY = Math.max(FIRST_ROW, positions["finish"] ?? average);
  const add = (
    id: string,
    kind: GraphNode["kind"],
    x: number,
    y: number,
    shot?: string,
  ) => {
    const n = { id, kind, x, y, shot, width: CARD_WIDTH, height: CARD_HEIGHT };
    nodes.push(n);
    return n;
  };
  const edge = (
    id: string,
    kind: GraphEdge["kind"],
    points: [number, number][],
    shot?: string,
    d = path(points),
  ) => edges.push({ id, kind, points, d, shot });
  topology.shots.forEach((s, i) => {
    const y = rows[i].y,
      cy = y + CARD_HEIGHT / 2;
    add("shot:" + s.id, "shot", 0, y, s.id);
    if (s.generation) {
      add("generation:" + s.id, "generation", COLUMN_STEP, y, s.id);
      edge(
        "input:" + s.id,
        "flow",
        [
          [CARD_WIDTH, cy],
          [COLUMN_STEP, cy],
        ],
        s.id,
      );
      edge(
        "generated:" + s.id,
        "flow",
        [
          [COLUMN_STEP + CARD_WIDTH, cy],
          [mediaX, cy],
        ],
        s.id,
      );
    } else
      edge(
        "input:" + s.id,
        "flow",
        [
          [CARD_WIDTH, cy],
          [mediaX, cy],
        ],
        s.id,
      );
    add("media:" + s.id, "media", mediaX, y, s.id);
  });
  add("render:" + topology.build, "render", renderX, renderY);
  add("delivery:" + topology.build, "delivery", deliveryX, renderY);
  if (rows.length) {
    const busX = renderX - 16,
      cy = renderY + CARD_HEIGHT / 2;
    const sourceX = mediaX + CARD_WIDTH;
    const controlX = (sourceX + busX) / 2;
    const ys = rows.map((r) => r.y + CARD_HEIGHT / 2);
    rows.forEach((r, i) =>
      edge(
        "merge:" + r.id,
        "merge",
        [
          [sourceX, ys[i]],
          [controlX, ys[i]],
          [controlX, cy],
          [busX, cy],
        ],
        r.id,
        `M ${sourceX} ${ys[i]} C ${controlX} ${ys[i]} ${controlX} ${cy} ${busX} ${cy}`,
      ),
    );
    // All curves meet with a horizontal tangent, then share one short trunk.
    edge("bus", "merge", [
      [busX, cy],
      [renderX - 8, cy],
    ]);
    edge("compose", "flow", [
      [renderX - 8, cy],
      [renderX, cy],
    ]);
  }
  edge("deliver", "flow", [
    [renderX + CARD_WIDTH, renderY + CARD_HEIGHT / 2],
    [deliveryX, renderY + CARD_HEIGHT / 2],
  ]);
  if (topology.audio)
    edge("audio", "audio", [
      [renderX + CARD_WIDTH / 2, 136],
      [renderX + CARD_WIDTH / 2, renderY],
    ]);
  return {
    nodes,
    edges,
    width: deliveryX + CARD_WIDTH,
    height: Math.max(renderY, ...rows.map((r) => r.y)) + CARD_HEIGHT + 30,
    hasGeneration,
    rows,
    renderY,
    columns: [
      { x: 0, title: "镜头输入" },
      ...(hasGeneration ? [{ x: COLUMN_STEP, title: "生成任务" }] : []),
      { x: mediaX, title: "镜头素材" },
      { x: renderX, title: "合成" },
      { x: deliveryX, title: "交付" },
    ],
  };
}

export function moveRow(
  graph: Graph,
  positions: Positions,
  id: string,
  y: number,
): Positions {
  const slot = Math.max(0, Math.round((y - FIRST_ROW) / ROW_STEP));
  const used = new Set(
    graph.rows
      .filter((r) => r.id !== id)
      .map((r) => Math.round((r.y - FIRST_ROW) / ROW_STEP)),
  );
  let free = slot;
  for (let distance = 0; used.has(free); distance++) {
    const below = slot + distance + 1,
      above = slot - distance - 1;
    free = above >= 0 && !used.has(above) ? above : below;
  }
  // Pin all rows, including automatically placed ones, before moving one row.
  return {
    ...positions,
    ...Object.fromEntries(graph.rows.map((r) => ["row:" + r.id, r.y])),
    ["row:" + id]: FIRST_ROW + free * ROW_STEP,
  };
}
