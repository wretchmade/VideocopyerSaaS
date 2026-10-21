import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ArrowUpRight,
  Check,
  ChevronDown,
  Download,
  Expand,
  FileText,
  Film,
  GripHorizontal,
  History,
  Maximize2,
  Minus,
  Plus,
  RotateCcw,
  Settings2,
  Users,
  X,
} from "lucide-react";
import type { Project, FileRow, Task } from "./main";
import {
  CARD_HEIGHT,
  CARD_WIDTH,
  FIRST_ROW,
  layoutGraph,
  moveRow,
  path,
  topologyKey,
  type GraphNode,
  type Positions,
} from "./workflowGraph";
import "./workflow.css";

type View = { x: number; y: number; zoom: number; positions: Positions };
type Props = {
  project: Project;
  selected: string;
  busy: boolean;
  onSelect: (id: string) => void;
  onEdit: () => void;
  onPrepare: () => void;
  onPanel: (p: string) => void;
  onControl: (t: Task, op: "stop" | "resume") => void;
  onDeliver: (t: Task) => void;
};
const labels: Record<string, string> = {
  ready: "素材就绪",
  pending: "等待执行",
  queued: "排队中",
  running: "执行中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已停止",
  reconciling: "待核对",
  waiting: "等待制作",
  blocked: "等待上游",
};
const defaults = (): View => ({ x: 24, y: 30, zoom: 0.75, positions: {} });
function readView(key: string): View | null {
  try {
    const v = JSON.parse(localStorage.getItem(key) || "null");
    if (
      !v ||
      ![v.x, v.y, v.zoom].every(Number.isFinite) ||
      v.zoom < 0.1 ||
      v.zoom > 1.5 ||
      !v.positions ||
      !Object.values(v.positions).every(
        (x) => Number.isFinite(x) && Number(x) >= FIRST_ROW,
      )
    )
      return null;
    return v;
  } catch {
    return null;
  }
}
function Status({ value, text }: { value: string; text?: string }) {
  return (
    <span className={"flow-status " + value}>
      <i />
      {text || labels[value] || value}
    </span>
  );
}
// Poll snapshots create new objects. Stable geometry + content signatures keep
// unaffected node subtrees out of React reconciliation, including their videos.
const NodeCard = memo(
  function NodeCard({
    node,
    selected,
    children,
  }: {
    node: GraphNode;
    selected: boolean;
    signature: string;
    busy: boolean;
    children: React.ReactNode;
  }) {
    return (
      <article
        className={
          "flow-card wf-node wf-" + node.kind + (selected ? " selected" : "")
        }
        data-flow-node={node.id}
        style={{
          left: node.x,
          top: node.y,
          width: node.width,
          height: node.height,
        }}
      >
        {node.kind !== "shot" && <i className="wf-port input" />}
        {node.kind !== "delivery" && <i className="wf-port output" />}
        {children}
      </article>
    );
  },
  (a, b) =>
    a.node === b.node &&
    a.selected === b.selected &&
    a.signature === b.signature &&
    a.busy === b.busy,
);

export default function WorkflowCanvas({
  project,
  selected,
  busy,
  onSelect,
  onEdit,
  onPrepare,
  onPanel: showPanel,
  onControl,
  onDeliver,
}: Props) {
  const key = "videocopyer.workflow.v2." + project.id;
  const [view, setView] = useState<View>(() => readView(key) || defaults());
  const [focus, setFocus] = useState(false),
    [historyOpen, setHistoryOpen] = useState(false),
    [inputsOpen, setInputsOpen] = useState(false),
    [storageError, setStorageError] = useState(false);
  const surface = useRef<HTMLDivElement>(null),
    autoFit = useRef(!readView(key));
  const gesture = useRef<{
    pointer: number;
    x: number;
    y: number;
    view: View;
    row?: string;
    rowY: number;
  } | null>(null);
  const [dragPreview, setDragPreview] = useState<{
    id: string;
    y: number;
  } | null>(null);
  const structure = topologyKey(project);
  const previousStructure = useRef(structure);
  const stats = useRef({ runs: 0, ms: 0 });
  const graph = useMemo(() => {
    const start = performance.now();
    const result = layoutGraph(JSON.parse(structure), view.positions);
    stats.current = {
      runs: stats.current.runs + 1,
      ms: performance.now() - start,
    };
    return result;
  }, [structure, view.positions]);
  const plan = project.planning.plan;
  const current = project.tasks
    .slice()
    .reverse()
    .find((t) => t.revision === project.revision);
  const outputs = new Map(
    current?.shot_outputs?.map((o) => [o.shot_id, o]) || [],
  );
  const shots = new Map(plan.shots.map((s) => [s.id, s]));
  const files = new Map(project.files.map((f) => [f.id, f]));
  const deliveries = project.deliveries.slice().reverse();
  const latest = deliveries.find((d) => d.task_id === current?.id);
  const previous = deliveries.filter((d) => d.id !== latest?.id);
  const past = project.tasks.filter((t) => t.id !== current?.id);
  const total = plan.shots.reduce((n, s) => n + s.duration, 0);
  const sourceFiles = project.files.filter((f) => !f.generated_by);
  const selectedShot = shots.get(selected);
  const selectedCharacter = plan.characters.find((c) => c.id === selected);
  const relevantIds = new Set(
    selectedShot
      ? [
          selectedShot.file_id,
          ...plan.characters
            .filter((c) => selectedShot.character_ids.includes(c.id))
            .map((c) => c.reference_file_id),
        ]
      : selectedCharacter
        ? [selectedCharacter.reference_file_id]
        : [],
  );
  const refs = useMemo(() => {
    const selectedShots = selectedShot
      ? [selectedShot]
      : selectedCharacter
        ? plan.shots.filter((s) =>
            s.character_ids.includes(selectedCharacter.id),
          )
        : [];
    return selectedShots
      .filter((s) => s.file_id || s.character_ids.length)
      .flatMap((s, i) => {
        const n = graph.nodes.find((n) => n.id === "shot:" + s.id);
        if (!n) return [];
        const gutter = -24 - i * 8;
        return [
          {
            id: s.id,
            d: path([
              [0, 86],
              [gutter, 86],
              [gutter, n.y + CARD_HEIGHT / 2],
              [0, n.y + CARD_HEIGHT / 2],
            ]),
          },
        ];
      });
  }, [
    graph,
    selected,
    JSON.stringify(plan.shots.map((s) => [s.id, s.character_ids, s.file_id])),
  ]);
  const fileUrl = (id: string) => `/api/projects/${project.id}/files/${id}`;
  const deliveryUrl = (id: string, kind: string) =>
    `/api/projects/${project.id}/deliveries/${id}/${kind}`;
  const openPanel = useCallback(
    (panel: string) => {
      autoFit.current = true;
      setFocus(false);
      showPanel(panel);
    },
    [showPanel],
  );
  const fit = useCallback(() => {
    const s = surface.current;
    if (!s || !s.clientWidth) return;
    const zoom = Math.max(
      0.1,
      Math.min(
        1,
        (s.clientWidth - 72) / graph.width,
        (s.clientHeight - 85) / graph.height,
      ),
    );
    setView((v) => ({
      ...v,
      zoom,
      x: Math.max(36, (s.clientWidth - graph.width * zoom) / 2),
      y: 25,
    }));
  }, [graph]);
  const zoomBy = useCallback(
    (amount: number, absolute = false) =>
      setView((v) => {
        const z = Math.max(
            0.1,
            Math.min(1.5, absolute ? amount : v.zoom + amount),
          ),
          cx = (surface.current?.clientWidth || 600) / 2,
          cy = (surface.current?.clientHeight || 600) / 2;
        return {
          ...v,
          zoom: z,
          x: cx - ((cx - v.x) * z) / v.zoom,
          y: cy - ((cy - v.y) * z) / v.zoom,
        };
      }),
    [],
  );
  useEffect(() => {
    const save = () => {
      try {
        localStorage.setItem(key, JSON.stringify(view));
        setStorageError(false);
      } catch {
        setStorageError(true);
      }
    };
    const timer = setTimeout(save, 150);
    window.addEventListener("pagehide", save);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("pagehide", save);
    };
  }, [view, key]);
  useLayoutEffect(() => {
    if (previousStructure.current !== structure) {
      previousStructure.current = structure;
      autoFit.current = true;
    }
    if (autoFit.current && surface.current?.clientWidth) {
      autoFit.current = false;
      fit();
    }
  }, [structure, focus, graph, fit]);
  useEffect(() => {
    const s = surface.current;
    if (!s) return;
    const ro = new ResizeObserver(() => {
      if (autoFit.current && s.clientWidth) {
        autoFit.current = false;
        fit();
      }
    });
    ro.observe(s);
    return () => ro.disconnect();
  }, [fit]);
  useEffect(() => {
    const exit = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setHistoryOpen(false);
        setInputsOpen(false);
        autoFit.current = true;
        setFocus(false);
      }
    };
    window.addEventListener("keydown", exit);
    return () => window.removeEventListener("keydown", exit);
  }, []);
  useEffect(() => {
    const s = surface.current;
    if (!s) return;
    const wheel = (e: WheelEvent) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        zoomBy(-e.deltaY * 0.001);
      } else if (
        !(e.target as HTMLElement).closest(".wf-inputs-detail,video,audio")
      ) {
        e.preventDefault();
        setView((v) => ({ ...v, x: v.x - e.deltaX, y: v.y - e.deltaY }));
      }
    };
    s.addEventListener("wheel", wheel, { passive: false });
    return () => s.removeEventListener("wheel", wheel);
  }, [zoomBy]);
  const preview = (f: FileRow) =>
    f.kind === "image" ? (
      <img src={fileUrl(f.id)} alt={f.name} loading="lazy" />
    ) : f.kind === "video" ? (
      <video
        src={fileUrl(f.id)}
        aria-label={f.name}
        controls
        preload="metadata"
      />
    ) : f.kind === "audio" ? (
      <audio controls preload="metadata" src={fileUrl(f.id)} />
    ) : (
      <FileText size={28} />
    );
  const finishDrag = () => {
    const g = gesture.current;
    if (g?.row && dragPreview) {
      setView((v) => ({
        ...v,
        positions:
          g.row === "finish"
            ? { ...v.positions, finish: Math.max(FIRST_ROW, dragPreview.y) }
            : moveRow(graph, v.positions, g.row!, dragPreview.y),
      }));
    }
    gesture.current = null;
    setDragPreview(null);
  };
  const renderNode = (node: GraphNode) => {
    const shot = node.shot ? shots.get(node.shot) : undefined,
      output = node.shot ? outputs.get(node.shot) : undefined;
    const f = files.get(
      output?.output_file_id || (!shot?.generate ? shot?.file_id || "" : ""),
    );
    const render = current?.nodes?.find((n) => n.id === "$render");
    let body: React.ReactNode,
      signature = "";
    if (node.kind === "shot" && shot) {
      signature = JSON.stringify(shot);
      body = (
        <>
          <div className="wf-node-head">
            <span className="wf-kind">镜头输入</span>
            <small>{shot.duration}s</small>
          </div>
          <button
            className="wf-shot-select"
            aria-pressed={selected === shot.id}
            onClick={() => onSelect(shot.id)}
          >
            <strong>{shot.title}</strong>
            <p>{shot.description || "待补充镜头描述"}</p>
          </button>
          {shot.subtitle && (
            <blockquote title={shot.subtitle}>{shot.subtitle}</blockquote>
          )}
          <div className="flow-tags">
            {shot.character_ids.map((cid) => (
              <span key={cid}>
                {plan.characters.find((c) => c.id === cid)?.name || cid}
              </span>
            ))}
            <span>{shot.generate ? "生成画面" : "引用素材"}</span>
          </div>
          <button className="wf-node-foot" onClick={() => onSelect(shot.id)}>
            {selected === shot.id
              ? "已选中 · 在对话中修改"
              : "选中镜头，查看参考与修改"}
          </button>
        </>
      );
      signature += JSON.stringify(plan.characters.map((c) => [c.id, c.name]));
    } else if (node.kind === "generation" && shot) {
      signature = JSON.stringify([shot.title, output, current?.error]);
      body = (
        <>
          <div className="wf-node-head">
            <span className="wf-kind">生成任务</span>
            <Status value={output?.status || "pending"} />
          </div>
          <strong>{shot.title}</strong>
          <div className="wf-operation">
            <Film size={26} />
            <span>
              {output?.provider} / {output?.model}
            </span>
            <small>{output?.input_file_ids.length || 0} 份参考输入</small>
          </div>
          <small className="wf-task-id">{output?.node_id}</small>
          {output?.status === "failed" && (
            <p className="inline-error">生成失败，查看执行详情后继续。</p>
          )}
          <button className="wf-node-foot" onClick={() => openPanel("tasks")}>
            执行详情 <ArrowUpRight size={12} />
          </button>
        </>
      );
    } else if (node.kind === "media" && shot) {
      signature = JSON.stringify([shot.title, shot.generate, output, f]);
      body = (
        <>
          <div className="wf-node-head">
            <span className="wf-kind">镜头素材</span>
            <Status
              value={output?.status || (f ? "ready" : "waiting")}
              text={output?.reused ? "复用已有素材" : undefined}
            />
          </div>
          <div className="wf-media-preview">
            {f ? (
              preview(f)
            ) : (
              <div className="wf-media-pending">
                <Film size={25} />
                <span>
                  {output?.node_id
                    ? "等待生成结果"
                    : shot.generate
                      ? "尚未启动生成"
                      : "待绑定素材"}
                </span>
              </div>
            )}
          </div>
          <div className="wf-file-caption">
            <span title={f?.name || shot.title}>{f?.name || shot.title}</span>
            {f && (
              <a
                href={fileUrl(f.id)}
                target="_blank"
                rel="noreferrer"
                aria-label={"打开镜头素材 " + shot.title}
              >
                <ArrowUpRight size={13} />
              </a>
            )}
          </div>
          <small>
            {output?.reused
              ? "沿用已完成构建的原始素材"
              : f
                ? "供本镜头合成使用"
                : "制作后在这里显示真实素材"}
          </small>
        </>
      );
    } else if (node.kind === "render") {
      signature = JSON.stringify([
        current?.id,
        current?.status,
        current?.error,
        render,
        plan.audio_file_id,
        plan.shots.map((s) => s.subtitle),
        !!latest,
      ]);
      body = (
        <>
          {current && plan.audio_file_id && <i className="wf-audio-port" />}
          <div className="wf-node-head">
            <span className="wf-kind">合成任务</span>
            <Status
              value={render?.status || (current ? "pending" : "waiting")}
            />
          </div>
          <strong>画面、字幕与声音</strong>
          <div className="wf-render-inputs">
            <span>{plan.shots.length} 个镜头画面</span>
            <span>{plan.shots.filter((s) => s.subtitle).length} 段字幕</span>
            <span>{plan.audio_file_id ? "已接入背景音轨" : "无背景音轨"}</span>
          </div>
          <small>
            {current
              ? `按修订 ${project.revision} 合成`
              : "确认制作后建立执行任务"}
          </small>
          {current?.error && (
            <p className="wf-error" title={current.error}>
              {current.error}
            </p>
          )}
          <div className="flow-actions">
            {current &&
              ["running", "queued", "reconciling"].includes(current.status) && (
                <button
                  disabled={busy}
                  onClick={() => onControl(current, "stop")}
                >
                  停止新增工作
                </button>
              )}
            {current && ["failed", "cancelled"].includes(current.status) && (
              <button
                disabled={busy}
                onClick={() => onControl(current, "resume")}
              >
                继续任务
              </button>
            )}
            {current && (
              <button onClick={() => openPanel("tasks")}>执行详情</button>
            )}
            {!current && (
              <button disabled={busy || !plan.shots.length} onClick={onPrepare}>
                准备制作
              </button>
            )}
          </div>
        </>
      );
    } else {
      signature = JSON.stringify([latest, current?.status]);
      body = latest ? (
        <>
          <div className="wf-node-head">
            <span className="wf-kind">当前交付 · R{latest.revision}</span>
            <Status value="succeeded" text="已交付" />
          </div>
          <video
            className="wf-delivery-preview"
            controls
            preload="metadata"
            src={deliveryUrl(latest.id, "preview")}
            aria-label={"修订 " + latest.revision + " 成片预览"}
          />
          <div className="flow-downloads">
            <a href={deliveryUrl(latest.id, "preview")} download>
              <Download size={12} />
              MP4
            </a>
            <a href={deliveryUrl(latest.id, "zip")}>
              <Download size={12} />
              剪映工程
            </a>
          </div>
          <button
            className="wf-node-foot"
            onClick={() => openPanel("delivery")}
          >
            <Check size={11} />
            同一构建 · 交付说明
          </button>
        </>
      ) : (
        <>
          <div className="wf-node-head">
            <span className="wf-kind">成片与工程</span>
            <Status value="waiting" text="等待交付" />
          </div>
          <div className="wf-operation">
            <Download size={28} />
            <p>
              同一构建的 MP4 与剪映工程
              <br />
              在这里成对保存
            </p>
          </div>
          {current?.status === "succeeded" && (
            <button
              className="secondary"
              disabled={busy}
              onClick={() => onDeliver(current)}
            >
              生成配套交付
            </button>
          )}
        </>
      );
    }
    return (
      <NodeCard
        key={node.id}
        node={node}
        selected={!!node.shot && node.shot === selected}
        busy={busy}
        signature={signature}
      >
        {body}
      </NodeCard>
    );
  };
  return (
    <div
      className={"workflow wf-v2 " + (focus ? "workflow-focus" : "")}
      data-layout-runs={stats.current.runs}
      data-layout-ms={stats.current.ms.toFixed(3)}
    >
      <header className="workflow-header">
        <div>
          <span className="eyebrow">D / PRODUCTION WORKFLOW</span>
          <h2>
            制作工作流 <span>R{project.revision}</span>
          </h2>
        </div>
        <div className="workflow-header-actions">
          <button
            className="icon"
            aria-label={focus ? "退出专注画布" : "展开工作流画布"}
            onClick={() => {
              autoFit.current = true;
              setFocus(!focus);
            }}
          >
            {focus ? <X size={17} /> : <Expand size={17} />}
          </button>
          <button className="secondary" disabled={busy} onClick={onEdit}>
            <Settings2 size={14} />
            编辑规划
          </button>
        </div>
      </header>
      <div className="workflow-summary">
        <span>{plan.shots.length} 个镜头</span>
        <span>{total.toFixed(1)} 秒</span>
        {current && (
          <Status
            value={current.status}
            text={"本次构建 · " + (labels[current.status] || current.status)}
          />
        )}
        <button onClick={() => openPanel("activity")}>
          执行记录 <ArrowUpRight size={12} />
        </button>
      </div>
      <div className="wf-legend">
        <span>
          <i className="solid" />
          制作依赖
        </span>
        <span>
          <i className="dashed" />
          选中时显示参考引用
        </span>
        <button
          onClick={() => {
            setHistoryOpen(!historyOpen);
            setInputsOpen(false);
          }}
          aria-expanded={historyOpen}
        >
          <History size={13} />
          历史与包装 · {past.length} 次构建 / {previous.length} 份交付
        </button>
      </div>
      <div
        className="workflow-surface"
        ref={surface}
        tabIndex={0}
        aria-label="工作流画布，拖动空白平移，拖动镜头行调整位置"
        onPointerDown={(e) => {
          if (
            e.button !== 0 ||
            (e.target as HTMLElement).closest(
              "button,a,video,audio,input,summary",
            )
          )
            return;
          const handle = (e.target as HTMLElement).closest<HTMLElement>(
            "[data-drag-row]",
          );
          if (
            !handle &&
            (e.target as HTMLElement).closest(".wf-node,.wf-shared")
          )
            return;
          const row = handle?.dataset.dragRow;
          gesture.current = {
            pointer: e.pointerId,
            x: e.clientX,
            y: e.clientY,
            view,
            row,
            rowY:
              row === "finish"
                ? graph.renderY
                : graph.rows.find((r) => r.id === row)?.y || 0,
          };
          e.currentTarget.setPointerCapture(e.pointerId);
          e.currentTarget.focus();
        }}
        onPointerMove={(e) => {
          const g = gesture.current;
          if (!g || g.pointer !== e.pointerId) return;
          if (g.row)
            setDragPreview({
              id: g.row,
              y: Math.max(FIRST_ROW, g.rowY + (e.clientY - g.y) / g.view.zoom),
            });
          else
            setView({
              ...g.view,
              x: g.view.x + e.clientX - g.x,
              y: g.view.y + e.clientY - g.y,
            });
        }}
        onPointerUp={finishDrag}
        onPointerCancel={() => {
          gesture.current = null;
          setDragPreview(null);
        }}
        onLostPointerCapture={() => {
          gesture.current = null;
          setDragPreview(null);
        }}
        onKeyDown={(e) => {
          if (e.target !== e.currentTarget) return;
          const delta: Record<string, [number, number]> = {
            ArrowLeft: [40, 0],
            ArrowRight: [-40, 0],
            ArrowUp: [0, 40],
            ArrowDown: [0, -40],
          };
          if (delta[e.key]) {
            e.preventDefault();
            setView((v) => ({
              ...v,
              x: v.x + delta[e.key][0],
              y: v.y + delta[e.key][1],
            }));
          }
          if (e.key === "+" || e.key === "=") zoomBy(0.1);
          if (e.key === "-") zoomBy(-0.1);
        }}
      >
        <div
          className="workflow-world"
          style={{
            width: graph.width,
            height: graph.height,
            transform: `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`,
          }}
        >
          <div className="wf-shared" style={{ width: graph.width }}>
            <div className="wf-shared-title">
              <Users size={15} />
              <strong>公共输入</strong>
              <span>需求 · 人物 · 参考素材</span>
              <button
                onClick={() => {
                  setInputsOpen(!inputsOpen);
                  setHistoryOpen(false);
                }}
              >
                查看全部 <ChevronDown size={13} />
              </button>
            </div>
            <div className="wf-shared-content">
              <span
                className="wf-brief"
                title={project.messages.find((m) => m.role === "user")?.text}
              >
                {plan.title}
              </span>
              {plan.characters.map((c) => (
                <button
                  className={
                    selectedCharacter?.id === c.id ||
                    selectedShot?.character_ids.includes(c.id)
                      ? "active"
                      : ""
                  }
                  key={c.id}
                  onClick={() => onSelect(c.id)}
                >
                  <Users size={12} />
                  {c.name}
                </button>
              ))}
              {sourceFiles.map((f) => (
                <a
                  className={relevantIds.has(f.id) ? "active" : ""}
                  key={f.id}
                  href={fileUrl(f.id)}
                  target="_blank"
                  rel="noreferrer"
                >
                  {f.name}
                </a>
              ))}
              {!plan.characters.length && !sourceFiles.length && (
                <small>在对话中添加参考资料并确认分镜</small>
              )}
            </div>
            <div className="wf-shared-note">
              {selectedShot
                ? "已选中 " + selectedShot.title + "：相关输入已高亮"
                : selectedCharacter
                  ? "已选中 " + selectedCharacter.name + "：显示引用它的镜头"
                  : "选择镜头或人物，查看辅助引用关系"}
              {plan.audio_file_id && (
                <span>
                  背景音轨：{files.get(plan.audio_file_id)?.name || "已选择"}
                </span>
              )}
            </div>
          </div>
          {graph.columns.map((c) => (
            <div
              className="wf-column-label"
              key={c.title}
              style={{ left: c.x, width: CARD_WIDTH, top: 170 }}
            >
              {c.title}
            </div>
          ))}
          <svg
            className="workflow-links"
            style={{ width: graph.width, height: graph.height }}
            aria-hidden="true"
          >
            <defs>
              <marker
                id={"flow-arrow-" + project.id}
                markerWidth="6"
                markerHeight="6"
                refX="5"
                refY="3"
                orient="auto"
              >
                <path d="M0,0 L6,3 L0,6" fill="#829c91" />
              </marker>
            </defs>
            {graph.edges.map((edge) => (
              <path
                key={edge.id}
                data-edge={edge.id}
                className={
                  (edge.kind === "merge" ? "merge " : "") +
                  (edge.shot === selected ? "active" : "")
                }
                d={edge.d}
                markerEnd={
                  edge.kind === "merge"
                    ? undefined
                    : `url(#flow-arrow-${project.id})`
                }
              />
            ))}
            {refs.map((r) => (
              <path
                key={r.id}
                className="reference"
                data-reference={r.id}
                d={r.d}
                markerEnd={`url(#flow-arrow-${project.id})`}
              />
            ))}
          </svg>
          {graph.rows.map((r, i) => (
            <div
              className="wf-row-handle"
              key={r.id}
              data-drag-row={r.id}
              style={{
                left: 0,
                top: r.y - 24,
                width: (graph.hasGeneration ? 612 : 306) + CARD_WIDTH,
              }}
            >
              <span>
                {String(i + 1).padStart(2, "0")} / {shots.get(r.id)?.title}
              </span>
              <GripHorizontal size={13} />
            </div>
          ))}
          <div
            className="wf-row-handle wf-finish-handle"
            data-drag-row="finish"
            style={{
              left: graph.columns.at(-2)!.x,
              top: graph.renderY - 24,
              width: 542,
            }}
          >
            <span>汇合与交付 · 当前修订</span>
            <GripHorizontal size={13} />
          </div>
          {!plan.shots.length && (
            <div
              className="wf-empty"
              style={{ top: FIRST_ROW, width: graph.columns.at(-2)!.x - 70 }}
            >
              <Film size={30} />
              <strong>等待确定分镜</strong>
              <p>
                先在对话中确定人物、镜头和声音。每个镜头会沿一行展开制作过程。
              </p>
              <button className="secondary" onClick={onEdit}>
                手动添加分镜
              </button>
            </div>
          )}
          {graph.nodes.map(renderNode)}
          {dragPreview && (
            <div
              className="wf-drag-preview"
              style={{
                left: dragPreview.id === "finish" ? graph.columns.at(-2)!.x : 0,
                top: dragPreview.y,
                width:
                  dragPreview.id === "finish"
                    ? 542
                    : graph.columns.at(-2)!.x - 70,
                height: CARD_HEIGHT,
              }}
            >
              松开后保留整行位置
            </div>
          )}
        </div>
        <div className="workflow-navigation">
          <button aria-label="缩小画布" onClick={() => zoomBy(-0.1)}>
            <Minus size={16} />
          </button>
          <button aria-label="实际大小" onClick={() => zoomBy(1, true)}>
            {Math.round(view.zoom * 100)}%
          </button>
          <button aria-label="放大画布" onClick={() => zoomBy(0.1)}>
            <Plus size={16} />
          </button>
          <span />
          <button aria-label="适应全部工作流" onClick={fit}>
            <Maximize2 size={16} />
          </button>
          <button
            aria-label="整理布局"
            title="恢复按镜头排列"
            onClick={() => {
              autoFit.current = true;
              setView(defaults());
            }}
          >
            <RotateCcw size={15} />
          </button>
        </div>
        <div className="workflow-hint">
          拖动空白平移 · 镜头整行拖动 · Ctrl + 滚轮缩放
        </div>
      </div>
      {(historyOpen || inputsOpen) && (
        <aside
          className="wf-overlay"
          aria-label={historyOpen ? "历史构建与交付" : "公共输入详情"}
        >
          <header>
            <strong>{historyOpen ? "历史构建与交付" : "公共输入详情"}</strong>
            <button
              aria-label="关闭画布侧栏"
              onClick={() => {
                setHistoryOpen(false);
                setInputsOpen(false);
              }}
            >
              <X size={17} />
            </button>
          </header>
          <div className="wf-overlay-content">
            {inputsOpen ? (
              <>
                <h3>创作需求</h3>
                <p>{project.messages.find((m) => m.role === "user")?.text}</p>
                {plan.notes && <p>{plan.notes}</p>}
                {plan.characters.map((c) => (
                  <div className="flow-card" key={c.id}>
                    <strong>{c.name}</strong>
                    <p>{c.description}</p>
                  </div>
                ))}
                {sourceFiles.map((f) => (
                  <div className="flow-card" key={f.id}>
                    <div className="wf-media-preview">{preview(f)}</div>
                    <a href={fileUrl(f.id)} target="_blank" rel="noreferrer">
                      {f.name}
                    </a>
                  </div>
                ))}
                <button
                  className="secondary"
                  onClick={() => openPanel("assets")}
                >
                  全部素材与 COS
                </button>
              </>
            ) : (
              <>
                {!previous.length && !past.length && (
                  <p>还没有历史构建或旧交付包装。</p>
                )}
                {project.tasks
                  .filter(
                    (t) =>
                      t.id !== current?.id ||
                      previous.some((d) => d.task_id === t.id),
                  )
                  .slice()
                  .reverse()
                  .map((t) => (
                    <section className="wf-history-build" key={t.id}>
                      <h3>
                        修订 {t.revision}{" "}
                        {t.id === current?.id
                          ? "· 当前构建的旧包装"
                          : "· 历史构建"}
                      </h3>
                      <Status value={t.status} />
                      <small>构建 {t.id.slice(0, 10)}</small>
                      {t.id !== current?.id &&
                        t.shot_outputs?.map((o) => {
                          const f = files.get(o.output_file_id || "");
                          return f ? (
                            <a
                              className="wf-history-file"
                              key={o.shot_id}
                              href={fileUrl(f.id)}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {o.shot_id} · {f.name}
                              <ArrowUpRight size={12} />
                            </a>
                          ) : null;
                        })}
                      {previous
                        .filter((d) => d.task_id === t.id)
                        .map((d) => (
                          <div className="flow-card" key={d.id}>
                            <strong>交付包装 {d.id.slice(0, 6)}</strong>
                            <video
                              controls
                              preload="metadata"
                              className="wf-delivery-preview"
                              src={deliveryUrl(d.id, "preview")}
                            />
                            <div className="flow-downloads">
                              <a href={deliveryUrl(d.id, "preview")}>MP4</a>
                              <a href={deliveryUrl(d.id, "zip")}>剪映工程</a>
                            </div>
                          </div>
                        ))}
                    </section>
                  ))}
              </>
            )}
          </div>
        </aside>
      )}
      <footer className="workflow-footer">
        <div>
          <span className="online-dot" />
          {storageError ? "布局暂未保存" : "布局已保存在此浏览器"}
        </div>
        <button
          className="primary"
          disabled={!plan.shots.length || busy}
          onClick={onPrepare}
        >
          准备制作 <ArrowUpRight size={14} />
        </button>
      </footer>
      {!!plan.shots.length && (
        <div className="workflow-timeline" aria-label="分镜时间线">
          <span>
            时间线 <small>{total}s</small>
          </span>
          <div>
            {plan.shots.map((s, i) => (
              <button
                key={s.id}
                className={selected === s.id ? "selected" : ""}
                style={{ flex: s.duration }}
                title={`${s.title} · ${s.duration}s`}
                onClick={() => onSelect(s.id)}
              >
                {String(i + 1).padStart(2, "0")} <small>{s.duration}s</small>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
