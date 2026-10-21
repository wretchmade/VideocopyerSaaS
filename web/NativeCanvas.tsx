import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Download, Minus, Plus, Square } from "lucide-react";
import type { Project, Task } from "./main";
import "./native.css";

type Node = { id: string; kind: string; depends_on: string[]; state: string; start?: number; end?: number };
const labels: Record<string, string> = { planned: "待确认", redo: "计划重做", reuse: "计划复用", pending: "等待执行", running: "执行中", succeeded: "已完成", failed: "失败", cancelled: "已停止", stopping: "正在停止" };
function routeReason(reason:string) {
  const translations: [string,string][] = [
    ["operator selected","已选择兼容模式"],["alpha MOV","透明视频输出"],["transparent background","透明背景"],
    ["transitions","含转场"],["input budget","输入数量超出流式处理范围"],["procedural component","含程序化图层"],
    ["temporal layer","含动画或淡入淡出"],["protected brand","保持品牌效果"],["timed typography","含逐字字幕"],
    ["transformed or translucent","含视频旋转或透明度变化"],["deployed FFmpeg","本机媒体组件缺少所需能力"],
    ["rotation metadata","素材含旋转信息"],["non-square","素材像素比例需要兼容处理"],["pixel format","素材像素格式尚未验证"],
    ["HDR","HDR 素材"],["fractional cover","保持精确裁切采样"],["video scale","保持缩放画质"],["source clock","素材时间戳需要兼容处理"]
  ];
  return translations.find(([key])=>reason.includes(key))?.[1] || "使用已验证的兼容处理";
}
function graph(document: any): Node[] {
  const nodes: Node[] = document.assets.map((a: any) => ({ id: a.id, kind: a.kind, depends_on: [], state: "reuse" }));
  nodes.push(...document.tasks.map((t: any) => ({ id: t.id, kind: t.kind, depends_on: [...new Set([...t.depends_on, ...t.inputs])], state: "planned" })));
  nodes.push(...document.layers.map((l: any) => ({ id: "layer:" + l.id, kind: l.kind, depends_on: [l.asset, l.transcript, ...l.fonts].filter(Boolean), state: "planned", start: l.start, end: l.end })));
  nodes.push(...document.audio.map((a: any, i: number) => ({ id: "audio:" + i, kind: "audio", depends_on: [a.asset], state: "planned", start: a.start, end: a.end })));
  nodes.push(...document.transitions.map((t: any, i: number) => ({ id: "transition:" + i, kind: t.kind, depends_on: ["layer:" + t.source, "layer:" + t.target], state: "planned" })));
  nodes.push({ id: "$render", kind: "render", depends_on: nodes.map(n => n.id), state: "planned" });
  return nodes;
}
export default function NativeCanvas({ project, selected, onSelect, onPrepare, onStop, onDeliver, onVisible, busy, stopPending }:
  { project: Project; selected: string; onSelect: (id: string) => void; onPrepare: () => void; onStop: () => void; onDeliver: (t: Task) => void; onVisible: () => void; busy: boolean; stopPending: boolean }) {
  const native = project.native!;
  const [zoom, setZoom] = useState(0.8);
  const viewport = useRef<HTMLDivElement>(null);
  const quote = project.quotes?.find(q => q.document_hash === native.sha256);
  const task = quote ? undefined : [...project.tasks].reverse().find(t => t.native && t.core_project === native.projectId && t.revision === native.authorRevision);
  const route = task?.result?.render_plan || quote?.render_plan;
  const routeNames: Record<string,string> = { ffmpeg:"流式合成", "legacy-png":"兼容合成", "copy-file":"直接复用原文件", "copy-video":"复用视频轨" };
  const stageNames: Record<string,string> = { waiting_local:"等待本地处理资源", compositing:"正在合成", validating:"正在验证成片" };
  const nodes = useMemo(() => {
    const all = graph(native.document);
    const states = new Map(quote?.graph?.map((n: any) => [n.id, n.state]));
    return all.map(n => ({ ...n, state: states.get(n.id) as string || n.state }));
  }, [native.sha256, quote?.id]);
  const layout = useMemo(() => {
    const remaining = new Map(nodes.map(n => [n.id, n]));
    const ranked = new Map<string, { x: number; y: number; rank: number }>();
    const counts: Record<number, number> = {};
    while (remaining.size) {
      const ready = [...remaining.values()].filter(n => n.depends_on.every(d => ranked.has(d) || !remaining.has(d)));
      if (!ready.length) break;
      for (const n of ready) {
        const rank = n.depends_on.length ? 1 + Math.max(0, ...n.depends_on.map(d => ranked.get(d)?.rank || 0)) : 0;
        const row = counts[rank] || 0; counts[rank] = row + 1;
        ranked.set(n.id, { x: 28 + rank * 270, y: 32 + row * 126, rank }); remaining.delete(n.id);
      }
    }
    if(native.canvas?.version) {
      for(const group of native.canvas.view.groups) {
        group.members.forEach((member:string,index:number)=>{
          const raw=member.startsWith("task:")?member.slice(5):member;
          const key=ranked.has(raw)?raw:ranked.has("layer:"+raw)?"layer:"+raw:raw;
          if(group.collapsed)ranked.delete(key);
          else if(ranked.has(key))ranked.set(key,{x:Math.max(0,group.x)+28,y:Math.max(0,group.y)+40+index*126,rank:0});
        });
      }
    }
    return { ranked, width: Math.max(700, ...[...ranked.values()].map(p => p.x + 240)), height: Math.max(400, ...[...ranked.values()].map(p => p.y + 120)) };
  }, [nodes,native.canvas?.version]);
  useEffect(()=>{
    if(native.canvas?.version)setZoom(native.canvas.view.viewport.zoom);
  },[native.canvas?.version]);
  useEffect(() => {
    const el = viewport.current;
    if (!el) return;
    const observer = new IntersectionObserver(entries => {
      if (document.visibilityState === "visible" && entries.some(e => e.isIntersecting)) onVisible();
    });
    observer.observe(el); return () => observer.disconnect();
  }, [native.sha256,native.canvas?.version]);
  return <div className="native-canvas">
    <div className="native-toolbar">
      <div><strong>制作流程</strong><small>D 修订 {native.authorRevision} · {native.document.frames} 帧</small></div>
      <button disabled={busy} onClick={onPrepare}>查看范围与增量报价</button>
      <button disabled={stopPending} onClick={onStop}><Square size={13} /> {stopPending ? "正在停止" : "全局停止"}</button>
    </div>
    {project.flow?.stopped && <div className="native-notice">已阻止新增工作。运行中的本地任务正在停止；已提交的远端请求保留原记录，等待核对。修改后请确认新报价。</div>}
    {quote && <div className="native-notice">待确认：新增 {quote.new_nodes?.join("、") || "无生成任务"}；复用 {quote.reused_nodes?.join("、") || "无已完成产物"}；重新合成完整成片。最多新增 ¥{(quote.maximum_micros / 1e6).toFixed(quote.maximum_micros > 0 && quote.maximum_micros < 10000 ? 6 : 2)}。</div>}
    {route && <div className="native-notice">{route.resolved ? "实际处理" : "预计处理"}：{routeNames[route.route] || route.route}{route.fallback_reasons?.length ? ` · ${[...new Set<string>(route.fallback_reasons.map(routeReason))].join("；")}` : ""}{task?.result?.static_cache_hits ? ` · 复用 ${task.result.static_cache_hits} 个静态图层` : ""}</div>}
    {task && ["queued","running","stopping"].includes(task.status) && stageNames[task.stage?.stage] && <div className="native-notice" role="status">{stageNames[task.stage.stage]}</div>}
    <div className="native-viewport" ref={viewport}>
      <svg width={layout.width * zoom} height={layout.height * zoom} viewBox={`${native.canvas?.version ? -native.canvas.view.viewport.x : 0} ${native.canvas?.version ? -native.canvas.view.viewport.y : 0} ${layout.width} ${layout.height}`} role="img" aria-label={`D 修订 ${native.authorRevision} 完整制作依赖图`}>
        <defs><marker id="native-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#789a9e" /></marker></defs>
        {native.canvas?.version ? native.canvas.view.groups.map((g:any)=><text key={g.id} x={Math.max(0,g.x)+28} y={Math.max(0,g.y)+25} fill="#315d4f" fontSize="14">{g.title}{g.collapsed?` · ${g.members.length} 个节点已折叠`:""}</text>):null}
        {nodes.flatMap(n => n.depends_on.map(dep => {
          const a = layout.ranked.get(dep), b = layout.ranked.get(n.id);
          if (!a || !b) return null;
          return <path key={`${dep}:${n.id}`} d={`M ${a.x + 218} ${a.y + 44} C ${a.x + 245} ${a.y + 44}, ${b.x - 30} ${b.y + 44}, ${b.x} ${b.y + 44}`} fill="none" stroke="#789a9e" strokeWidth="1.5" markerEnd="url(#native-arrow)" />;
        }))}
        {nodes.map(n => {
          const pos = layout.ranked.get(n.id); if (!pos) return null;
          const actual = task?.nodes?.find(x => x.id === n.id);
          const state = actual?.status || ((n.id === "$render" || n.id.startsWith("layer:") || n.id.startsWith("audio:") || n.id.startsWith("transition:")) ? task?.status : null) || n.state;
          return <g key={n.id} transform={`translate(${pos.x},${pos.y})`} role="button" tabIndex={0} onClick={() => onSelect(n.id)} onKeyDown={e => { if (e.key === "Enter") onSelect(n.id); }} aria-label={`${n.id} ${labels[state] || state}`}>
            <rect width="218" height="90" rx="12" fill={n.state === "reuse" ? "#edf7f0" : "#fffdf8"} stroke={selected === n.id ? "#087a73" : "#d0dedb"} strokeWidth={selected === n.id ? 2.5 : 1} />
            <text x="14" y="23" fontSize="11" fill="#65716d">{n.kind.toUpperCase()}</text>
            <text x="14" y="46" fontSize="15" fill="#213b36">{n.id.length > 23 ? n.id.slice(0, 21) + "…" : n.id}</text>
            <text x="14" y="70" fontSize="12" fill="#297367">{labels[state] || state}{n.start !== undefined ? ` · ${n.start}–${n.end} 帧` : ""}</text>
          </g>;
        })}
      </svg>
    </div>
    <div className="native-footer">
      <div><button aria-label="缩小" onClick={() => setZoom(z => Math.max(.3, z - .1))}><Minus size={14} /></button><span>{Math.round(zoom * 100)}%</span><button aria-label="放大" onClick={() => setZoom(z => Math.min(1.5, z + .1))}><Plus size={14} /></button></div>
      <span>{selected ? `已选 ${selected}，可在对话中修改` : "选择任意任务或图层，在对话中提出修改"}</span>
      {task?.status === "succeeded" && <button disabled={busy} onClick={() => onDeliver(task)}><Check size={14} /> 生成配套交付</button>}
    </div>
    {project.deliveries.length > 0 && <div className="native-deliveries">{[...project.deliveries].reverse().map(d => <div key={d.id}><strong>修订 {d.revision}</strong><video controls preload="none" src={`/api/projects/${project.id}/deliveries/${d.id}/preview`} /><a href={`/api/projects/${project.id}/deliveries/${d.id}/zip`}><Download size={14} /> 剪映工程</a></div>)}</div>}
  </div>;
}
