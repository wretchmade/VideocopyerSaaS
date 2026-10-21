import React, { useState, useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import {
  Plus,
  ArrowUp,
  Paperclip,
  Square,
  Film,
  MessageSquare,
  LayoutDashboard,
  ChevronLeft,
  ChevronRight,
  Download,
  Play,
  RefreshCw,
  X,
  Check,
  Clapperboard,
  Image as ImageIcon,
  Users,
  FolderOpen,
  Settings2,
} from "lucide-react";
import "./style.css";
import "./markdown.css";
import Markdown from "react-markdown";
import WorkflowCanvas from "./WorkflowCanvas";
import NativeCanvas from "./NativeCanvas";
import {TemplateLibrary,TemplateDetail,TemplateMount,Mount} from "./templates/Templates";

export type FileRow = {
  id: string;
  name: string;
  kind: string;
  size: number;
  cos_verified?: boolean;
  generated_by?: string;
};
type Character = {
  id: string;
  name: string;
  description: string;
  reference_file_id: string | null;
};
type Shot = {
  id: string;
  title: string;
  description: string;
  duration: number;
  subtitle: string;
  character_ids: string[];
  file_id: string | null;
  source_start: number;
  generate: boolean;
};
type Plan = {
  title: string;
  aspect: "16:9" | "9:16" | "1:1";
  characters: Character[];
  shots: Shot[];
  audio_file_id: string | null;
  notes: string;
};
export type Task = {
  id: string;
  revision: number;
  status: string;
  error?: string;
  stage: any;
  result?: any;
  nodes: any[];
  native?: boolean;
  core_project?: string;
  shot_outputs?: {
    shot_id: string;
    node_id: string | null;
    status: string;
    output_file_id: string | null;
    input_file_ids: string[];
    reused: boolean;
    provider?: string;
    model?: string;
  }[];
};
type Delivery = {
  id: string;
  task_id: string;
  revision: number;
  preview_sha256: string;
  zip_sha256: string;
  limitations: any[];
  baked: any[];
};
export type Project = {
  id: string;
  title: string;
  revision: number;
  status: string;
  planning: { plan: Plan };
  files: FileRow[];
  messages: { id: string; role: string; text: string; selected?: string; template_instance?:string;template?:any }[];
  template_instance?:string;
  tasks: Task[];
  deliveries: Delivery[];
  questions: { id: string; question: any; status: string }[];
  usage: any[];
  native?: any;
  native_revision?: number;
  quotes?: any[];
  flow?: {epoch:number;stopped:boolean};
  event_cursor?: number;
};
let token = "";
const id = () => crypto.randomUUID();
async function api(path: string, method = "GET", body?: any) {
  const r = await fetch("/api" + path, {
    method,
    headers: {
      ...(body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      "X-VC-Token": token,
    },
    body:
      body === undefined
        ? undefined
        : body instanceof FormData
          ? body
          : JSON.stringify(body),
  });
  if (!r.ok) {
    let e = await r.json().catch(() => ({ detail: "服务连接失败" }));
    throw Error(
      typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail),
    );
  }
  return r.json();
}
const statusNames: Record<string, string> = {
  idle: "等待输入",
  starting: "连接 Codex",
  running: "执行中",
  queued: "排队中",
  succeeded: "制作完成",
  failed: "执行失败",
  cancelled: "已停止",
  interrupted: "已中断",
  completed: "已完成",
  reconciling: "请求待核对",
  waiting_user: "等待确认",
  waiting_budget: "等待预算",
};
const money = (n: number) => "¥" + (n / 1e6).toFixed(n > 0 && n < 10000 ? 6 : 2);
function App() {
  const [boot, setBoot] = useState<any>(null),
    [list, setList] = useState<any[]>([]),
    [pid, setPid] = useState(
      location.pathname.match(/^\/projects\/([a-f0-9]+)$/)?.[1] || "",
    ),
    [project, setProject] = useState<Project | null>(null);
  const [text, setText] = useState(""),
    [attachments, setAttachments] = useState<File[]>([]),
    [busy, setBusy] = useState(false),
    [stopPending, setStopPending] = useState(false),
    [error, setError] = useState(""),
    [selected, setSelected] = useState(""),
    [tab, setTab] = useState(""),
    [mobile, setMobile] = useState("chat");
  const [requestRows, setRequestRows] = useState<Record<string, any[]>>({});
  const [templateLibrary,setTemplateLibrary]=useState(false),[templateDetail,setTemplateDetail]=useState<any>(null);
  const [templateMount,setTemplateMount]=useState<Mount|null>(null),[composerId,setComposerId]=useState(""),[templateFiles,setTemplateFiles]=useState<any[]>([]),[composerReady,setComposerReady]=useState(false);
  const composerMeta=useRef({id:"",revision:0,payload:""});
  const saveQueue=useRef<Promise<any>>(Promise.resolve());
  const pendingTemplate=useRef<any>(null);
  const activeMount=useRef(templateMount);activeMount.current=templateMount;
  const [stream, setStream] = useState(""),
    [activity, setActivity] = useState<any[]>([]),
    [edit, setEdit] = useState<Plan | null>(null),
    [quote, setQuote] = useState<any>(null),
    [answer, setAnswer] = useState(""),
    [showSettings, setShowSettings] = useState(false);
  const input = useRef<HTMLInputElement>(null),
    bottom = useRef<HTMLDivElement>(null),
    current = useRef(pid);
  const refreshFlights = useRef(new Map<string, Promise<any>>());
  current.current = pid;
  const refresh = async (target = pid) => {
    if (!target) return;
    if(refreshFlights.current.has(target))return refreshFlights.current.get(target);
    const promise=api("/projects/"+target).then(p=>{
      if(current.current===target)setProject(p);
      setList(rows=>rows.map(row=>row.id===p.id?{...row,title:p.title,revision:p.revision,native_revision:p.native?.authorRevision ?? p.native_revision,status:p.status}:row));
      return p;
    }).finally(()=>refreshFlights.current.delete(target));
    refreshFlights.current.set(target,promise);
    return promise;
  };
  const init = async () => {
    const b = await api("/bootstrap");
    token = b.token;
    setBoot(b);
    setList(await api("/projects"));
  };
  useEffect(() => {
    init().catch((e) => setError(e.message));
    const pop = () =>
      setPid(location.pathname.match(/^\/projects\/([a-f0-9]+)$/)?.[1] || "");
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, []);
  useEffect(() => {
    setProject(null);
    setTab("");
    setSelected("");
    setStream("");
    setActivity([]);
    setEdit(null);
    if (!pid || !boot) return;
    let disposed=false;
    let es:EventSource|undefined;
    let refreshTimer:ReturnType<typeof setTimeout>|undefined;
    refresh(pid).then(p=>{
    if(disposed)return;
    let cursor=p?.event_cursor || 0;
    es = new EventSource(`/api/projects/${pid}/events?after=${cursor}`);
    es.onmessage = (e) => {
      const event = JSON.parse(e.data);
      if(event.seq<=cursor)return;
      cursor = event.seq;
      if (event.kind === "item/agentMessage/delta")
        setStream((s) => s + (event.data.delta || ""));
      else if (
        event.kind === "item/completed" &&
        event.data.item?.type === "agentMessage"
      )
        setStream("");
      if (!event.kind.endsWith("/delta"))
        setActivity((a) => [...a.slice(-60), event]);
      if (
        [
          "message",
          "plan/saved",
          "task/updated",
          "task/queued",
          "delivery/created",
          "question",
          "turn/completed",
          "agent/error",
          "file/added",
          "quote/prepared",
          "flow/stopped",
          "native/revision",
          "native/canvas",
          "agent/recovery_required",
          "agent/reconciled",
        ].includes(event.kind)
      )
        if(!refreshTimer)refreshTimer=setTimeout(()=>{refreshTimer=undefined;refresh(pid).catch(()=>{});},100);
    };
    }).catch(e=>setError(e.message));
    const timer = setInterval(() => refresh(pid).catch(() => {}), 15000);
    return () => {
      disposed=true;
      es?.close();
      if(refreshTimer)clearTimeout(refreshTimer);
      clearInterval(timer);
    };
  }, [pid, !!boot]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [project?.messages.length, stream]);
  useEffect(()=>{
    if(!boot)return;
    let active=true;setComposerReady(false);setTemplateMount(null);setTemplateFiles([]);
    const storageKey="vc-template-composer:"+ (pid||"new");
    const cid=localStorage.getItem(storageKey)||id().replaceAll("-","");
    localStorage.setItem(storageKey,cid);setComposerId(cid);
    api("/template-composers/"+cid).then(d=>{
      if(!active)return;
      composerMeta.current={id:cid,revision:d.revision,payload:JSON.stringify({project:pid||null,template_mount:d.template_mount,text:d.text||""})};
      pendingTemplate.current=JSON.parse(localStorage.getItem("vc-template-pending:"+cid)||"null");
      setTemplateMount(pendingTemplate.current?.body.template_mount||d.template_mount);setTemplateFiles(d.files||[]);
      if(d.template_mount)setText(pendingTemplate.current?.body.text??localStorage.getItem("vc-template-text:"+cid)??d.text??"");
      setComposerReady(true);
    }).catch(e=>setError(e.message));
    return()=>{active=false};
  },[pid,!!boot]);
  function saveTemplateDraft(value:Mount|null,draftText:string) {
    const cid=composerId,target=pid||null;
    const payload=JSON.stringify({project:target,template_mount:value,text:draftText});
    const job=saveQueue.current.catch(()=>{}).then(async()=>{
      if(composerMeta.current.id!==cid)throw Error("输入框已切换，请重试");
      if(composerMeta.current.payload===payload)return composerMeta.current.revision;
      const d=await api("/template-composers/"+cid,"PUT",{expected_revision:composerMeta.current.revision,...JSON.parse(payload)});
      composerMeta.current={id:cid,revision:d.revision,payload};
      return d.revision;
    });
    saveQueue.current=job;return job;
  }
  useEffect(()=>{
    if(!composerReady||!templateMount)return;
    if(pendingTemplate.current?.body.text===text&&JSON.stringify(pendingTemplate.current?.body.template_mount)===JSON.stringify(templateMount))return;
    const timer=setTimeout(()=>{if(activeMount.current)saveTemplateDraft(activeMount.current,text).catch(e=>setError(e.message))},300);
    return()=>clearTimeout(timer);
  },[text,composerReady,composerId]);
  async function useTemplate(value:Mount) {
    await action(async()=>{
      await saveTemplateDraft(value,text);
      setTemplateMount(value);setTemplateLibrary(false);setTemplateDetail(null);
    });
  }
  async function changeTemplate(value:Mount) {
    try{await saveTemplateDraft(value,text);setTemplateMount(value)}catch(e:any){setError(e.message)}
  }
  async function removeTemplate() {
    await action(async()=>{
      if(project?.template_instance)await api(`/projects/${pid}/template-detach`,"POST",{command_id:id(),expected_instance:project.template_instance});
      await saveTemplateDraft(null,text);setTemplateMount(null);if(pid)await refresh(pid);
    });
  }
  async function showMessageTemplate(key:string) {
    await action(async()=>{
      const inst=await api(`/projects/${pid}/template-instances/${encodeURIComponent(key)}`);
      setTemplateDetail({row:inst.template_revision,initial:{...inst.template,...inst.options},historical:true});
    });
  }
  const navigate = (p: string) => {
    setProject(null);
    setTab("");
    history.pushState({}, "", p ? "/projects/" + p : "/");
    setPid(p);
    setText("");
    setAttachments([]);
    setError("");
  };
  async function action(fn: () => Promise<any>) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function stopProduction() {
    if (stopPending || !pid) return;
    const target=pid;
    setStopPending(true);
    try {
      await api(`/projects/${target}/stop`,"POST");
      await refresh(target);
    } catch(e:any) { setError(e.message); }
    finally { setStopPending(false); }
  }
  async function send() {
    if (!text.trim()&&!templateMount) return;
    await action(async () => {
      if(templateMount) {
        if(attachments.length)throw Error("模板素材请使用挂载卡中的“上传并绑定”，完成每个素材槽的绑定后发送。");
        const retry=pendingTemplate.current?.body.composer_id===composerId&&pendingTemplate.current.body.text===text
          &&JSON.stringify(pendingTemplate.current.body.template_mount)===JSON.stringify(templateMount);
        if(!retry) {
          const revision=await saveTemplateDraft(templateMount,text);
          const signature=JSON.stringify({pid,composerId,revision,text,templateMount});
          pendingTemplate.current={signature,body:{command_id:id(),composer_id:composerId,expected_composer_revision:revision,text,template_mount:templateMount}};
          localStorage.setItem("vc-template-pending:"+composerId,JSON.stringify(pendingTemplate.current));
        }
        const result=await api(pid?`/projects/${pid}/messages`:"/template-messages","POST",pendingTemplate.current.body);
        const draft=await api("/template-composers/"+composerId);
        composerMeta.current={id:composerId,revision:draft.revision,payload:JSON.stringify({project:result.project,template_mount:templateMount,text:""})};
        localStorage.removeItem("vc-template-pending:"+composerId);localStorage.removeItem("vc-template-text:"+composerId);pendingTemplate.current=null;
        localStorage.setItem("vc-template-composer:"+result.project,composerId);
        if(!pid)localStorage.removeItem("vc-template-composer:new");
        setText("");setAttachments([]);
        history.pushState({},"","/projects/"+result.project);current.current=result.project;setPid(result.project);
        await refresh(result.project);setList(await api("/projects"));
        return;
      }
      let target = pid;
      const initial = !target;
      if (!target) {
        const p = await api("/projects", "POST", { text, command_id: id() });
        target = p.id;
        history.pushState({}, "", "/projects/" + target);
        current.current = target;
        setPid(target);
      }
      const fids = [];
      for (const f of attachments) {
        const form = new FormData();
        form.append("file", f);
        fids.push((await api(`/projects/${target}/files`, "POST", form)).id);
      }
      await api(`/projects/${target}/messages`, "POST", {
        text,
        command_id: id(),
        file_ids: fids,
        selected,
        initial,
      });
      setText("");
      setAttachments([]);
      await refresh(target);
    });
  }
  async function savePlan(plan: Plan) {
    await action(async () => {
      await api(`/projects/${pid}/plan`, "PUT", {
        base_revision: project!.revision,
        plan,
        command_id: id(),
      });
      setEdit(null);
      await refresh();
    });
  }
  const running = project && (["starting", "running"].includes(project.status) || project.tasks.some(t => ["queued","running","stopping","reconciling"].includes(t.status)));
  const plan = project?.planning.plan;
  const chosen = plan?.shots.find((x) => x.id === selected);
  const composer = (
    <div className="composer">
      {templateMount&&<TemplateMount api={api} mount={templateMount} onChange={changeTemplate} onRemove={removeTemplate}
        onDetail={row=>setTemplateDetail({row,initial:templateMount})} composerId={composerId}
        files={[...new Map([...templateFiles,...(project?.files||[])].map(f=>[f.id,f])).values()]}
        onError={setError} upload={async file=>{const form=new FormData();form.append("file",file);const f=await api(`/template-composers/${composerId}/files`,"POST",form);setTemplateFiles(rows=>[...rows.filter(r=>r.id!==f.id),f]);return f;}}/>}
      <div className="attachment-list">
        {attachments.map((f, i) => (
          <span key={i}>
            {f.name}
            <button
              aria-label="移除附件"
              onClick={() => setAttachments((a) => a.filter((_, j) => i !== j))}
            >
              <X size={12} />
            </button>
          </span>
        ))}
      </div>
      {selected && (
        <div className="context-tag">
          针对：
          {chosen?.title ||
            plan?.characters.find((c) => c.id === selected)?.name ||
            selected}
          <button aria-label="取消选中" onClick={() => setSelected("")}>
            <X size={13} />
          </button>
        </div>
      )}
      <textarea
        aria-label="消息"
        placeholder={
          pid
            ? "描述修改，或继续制作…"
            : "描述你想制作的视频，也可以附上参考素材…"
        }
        value={text}
        onChange={(e) => {setText(e.target.value);if(templateMount)localStorage.setItem("vc-template-text:"+composerId,e.target.value)}}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            send();
          }
        }}
      />
      <div className="composer-actions">
        <button disabled={!composerReady||busy} onClick={()=>setTemplateLibrary(true)} title="模板库">模板</button>
        <button
          className="icon"
          title="添加附件"
          aria-label="添加附件"
          onClick={() => input.current?.click()}
        >
          <Paperclip size={19} />
        </button>
        <span>{pid ? "Shift + Enter 换行" : "图片 · 视频 · 音频 · 文本"}</span>
        {running ? (
          <button
            className="send"
            title="停止"
            aria-label="停止"
            disabled={stopPending}
            onClick={stopProduction}
          >
            <Square size={16} />
          </button>
        ) : null}
          <button
            className="send"
            aria-label="发送"
            disabled={busy || (!text.trim()&&!templateMount)}
            onClick={send}
          >
            <ArrowUp size={20} />
          </button>
      </div>
      <input
        hidden
        multiple
        type="file"
        ref={input}
        accept="image/png,image/jpeg,image/webp,video/mp4,video/quicktime,audio/*,.txt,.srt,.md"
        onChange={(e) => {
          const selectedFiles = Array.from(e.target.files || []);
          setAttachments((a) => [...a, ...selectedFiles]);
          e.target.value = "";
        }}
      />
    </div>
  );
  return (
    <div className="app">
      {templateLibrary&&<TemplateLibrary api={api} onMount={useTemplate} onClose={()=>setTemplateLibrary(false)}/>}
      {templateDetail&&<div className="template-overlay"><TemplateDetail api={api} row={templateDetail.row} initial={templateDetail.initial}
        onMount={templateDetail.historical?undefined:useTemplate} onClose={()=>setTemplateDetail(null)}/></div>}
      <aside className="sidebar">
        <a
          className="brand"
          href="/"
          onClick={(e) => {
            e.preventDefault();
            navigate("");
          }}
        >
          <Clapperboard size={22} />
          <span>VideoCopyer</span>
          <small>LOCAL</small>
        </a>
        <button className="new-project" onClick={() => navigate("")}>
          <Plus size={17} /> 新建视频
        </button>
        <button className="new-project" disabled={!composerReady} onClick={()=>setTemplateLibrary(true)}>模板库</button>
        <div className="section-label">
          最近项目 <span>{list.length}</span>
        </div>
        <nav>
          {list
            .slice()
            .reverse()
            .map((p) => (
              <button
                className={"project-link " + (pid === p.id ? "active" : "")}
                key={p.id}
                onClick={() => navigate(p.id)}
              >
                <Film size={16} />
                <span>{p.title}</span>
              </button>
            ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="online-dot" />
          本地单用户工作区
          <button
            className="icon"
            aria-label="运行配置"
            onClick={() => setShowSettings(true)}
          >
            <Settings2 size={16} />
          </button>
        </div>
      </aside>
      <main>
        {!pid ? (
          <div className="home">
            <div className="home-intro">
              <span className="eyebrow">从一句想法，到一部可编辑的视频</span>
              <h1>这次，我们拍什么？</h1>
              <p>
                一起确定人物、镜头和声音。制作过程和每个版本，都留在项目里。
              </p>
            </div>
            {composer}
            <div className="home-notes">
              <div>
                <MessageSquare size={18} />
                <strong>对话定方案</strong>
                <span>从参考素材开始，逐步细化</span>
              </div>
              <div>
                <LayoutDashboard size={18} />
                <strong>分镜看进度</strong>
                <span>人物与素材有明确归属</span>
              </div>
              <div>
                <FolderOpen size={18} />
                <strong>带走可编辑工程</strong>
                <span>同版预览片与剪映工程</span>
              </div>
            </div>
            <div className="recent-home">
              {list.length > 0 && (
                <>
                  <h3>继续制作</h3>
                  {list
                    .slice(-3)
                    .reverse()
                    .map((p) => (
                      <button key={p.id} onClick={() => navigate(p.id)}>
                        <Film size={18} />
                        <span>{p.title}</span>
                        <small>修订 {p.native_revision ?? p.revision}</small>
                        <ChevronRight size={16} />
                      </button>
                    ))}
                </>
              )}
            </div>
          </div>
        ) : (
          <>
            <header className="topbar">
              <div>
                <button
                  className="icon mobile-back"
                  aria-label="返回项目"
                  onClick={() => navigate("")}
                >
                  <ChevronLeft size={18} />
                </button>
                <span>{project?.title || "正在打开项目"}</span>
                <small>修订 {project?.native?.authorRevision ?? project?.revision ?? "—"}</small>
              </div>
              <span className={"status " + (running ? "live" : "")}>
                {statusNames[project?.status || ""] || "载入中"}
              </span>
            </header>
            <div className="mobile-switch">
              <button onClick={() => setMobile("chat")}>会话</button>
              <button onClick={() => setMobile("canvas")}>制作画布</button>
            </div>
            <div className="workspace">
              <section
                className={
                  "conversation " + (mobile === "chat" ? "mobile-visible" : "")
                }
              >
                <div className="conversation-title">
                  <span className="codex-mark">✳</span>
                  <strong>Codex</strong>
                  <small>{boot?.model?.replace("doubao-", "")}</small>
                </div>
                <div className="messages">
                  {project?.messages.map((m) => (
                    <article key={m.id} className={"message " + m.role}>
                      <div className="message-label">
                        {m.role === "user"
                          ? "你"
                          : m.role === "assistant"
                            ? "Codex"
                            : "运行状态"}
                        {m.selected && <small> · {m.selected}</small>}
                      </div>
                      <div className="markdown">
                        {m.template_instance&&<button className="template-message" onClick={()=>showMessageTemplate(m.template_instance!)}>模板 v{m.template?.revision} · 查看当时的骨架与绑定</button>}
                        <Markdown>{m.text}</Markdown>
                      </div>
                    </article>
                  ))}
                  {stream && (
                    <article className="message assistant">
                      <div className="message-label">
                        Codex <span className="pulse" />
                      </div>
                      <div className="markdown">
                        <Markdown>{stream}</Markdown>
                      </div>
                    </article>
                  )}
                  {running && !stream && (
                    <div className="working">
                      <span className="pulse" /> Codex 正在处理…
                    </div>
                  )}
                  {project?.questions
                    .filter((q) => q.status === "pending")
                    .map((q) => (
                      <div className="question" key={q.id}>
                        <strong>
                          {typeof q.question === "string"
                            ? q.question
                            : JSON.stringify(q.question)}
                        </strong>
                        <input
                          aria-label="澄清答案"
                          value={answer}
                          onChange={(e) => setAnswer(e.target.value)}
                          placeholder="补充你的选择…"
                        />
                        <button
                          disabled={!answer.trim() || busy}
                          onClick={() =>
                            action(async () => {
                              await api(
                                `/projects/${pid}/questions/${q.id}`,
                                "POST",
                                { answer },
                              );
                              setAnswer("");
                              await refresh();
                            })
                          }
                        >
                          发送答案
                        </button>
                      </div>
                    ))}
                  {project?.quotes?.map(q => <div className="pending-quote" key={q.id}>
                    <strong>修订 {q.revision} 待确认报价</strong><div>本轮最多新增 {money(q.maximum_micros)} · {q.paid_tasks} 个付费任务</div>
                    <div>复用：{q.reused_nodes?.join("、") || "见规划范围"}；重新执行：{q.new_nodes?.join("、") || "见规划范围"}</div>
                    <small>确认报价 {q.id}</small><br/><button disabled={busy} onClick={() => setQuote(q)}>查看范围并确认</button>
                  </div>)}
                  <div ref={bottom} />
                </div>
                {project?.files.length ? (
                  <div className="file-bar">
                    {project.files.map((f) => (
                      <a
                        key={f.id}
                        href={`/api/projects/${pid}/files/${f.id}`}
                        target="_blank"
                      >
                        {f.kind === "image" ? (
                          <ImageIcon size={13} />
                        ) : (
                          <Paperclip size={13} />
                        )}{" "}
                        {f.name}
                      </a>
                    ))}
                  </div>
                ) : null}
                {composer}
                <div className="conversation-foot">
                  Codex {boot?.codex_version} · 支出由后端预算门禁控制
                </div>
              </section>
              <section
                className={
                  "canvas " + (mobile === "canvas" ? "mobile-visible" : "")
                }
              >
                {project?.native ? <NativeCanvas project={project} selected={selected} onSelect={setSelected} busy={busy}
                  onPrepare={() => action(async () => setQuote(await api(`/projects/${pid}/native/quote`,"POST",{})))}
                  onStop={stopProduction}
                  stopPending={stopPending}
                  onDeliver={task => action(async () => {await api(`/projects/${pid}/deliver`,"POST",{task_id:task.id,allow_baked:false,command_id:id()});await refresh();})}
                  onVisible={() => {api(`/projects/${pid}/native/visible`,"POST",{document_hash:project.native.sha256,revision:project.native.authorRevision,view_version:project.native.canvas?.version||0,command_id:id(),session:sessionStorage.getItem("vc-view-session") || (() => {const s=id();sessionStorage.setItem("vc-view-session",s);return s;})()}).catch(()=>{});}}
                /> : project && (
                  <WorkflowCanvas
                    key={project.id}
                    project={project}
                    selected={selected}
                    busy={busy}
                    onSelect={setSelected}
                    onEdit={() => setEdit(structuredClone(plan!))}
                    onPrepare={() =>
                      action(async () =>
                        setQuote(
                          await api(
                            `/projects/${pid}/quote?revision=${project.revision}`,
                          ),
                        ),
                      )
                    }
                    onPanel={setTab}
                    onControl={(task, op) =>
                      action(async () => {
                        const result = await api(
                          `/projects/${pid}/tasks/${task.id}/${op}`,
                          "POST",
                        );
                        if(result.quote)setQuote(result.quote);
                        await refresh();
                      })
                    }
                    onDeliver={(task) =>
                      action(async () => {
                        await api(`/projects/${pid}/deliver`, "POST", {
                          task_id: task.id,
                          allow_baked: false,
                          command_id: "export-" + task.id,
                        });
                        await refresh();
                      })
                    }
                  />
                )}
                {tab && (
                  <aside className="workflow-inspector" aria-label="工作流详情">
                    <div className="inspector-heading">
                      <strong>工作流详情</strong>
                      <button
                        className="icon"
                        aria-label="关闭工作流详情"
                        onClick={() => setTab("")}
                      >
                        <X size={17} />
                      </button>
                    </div>
                    <div className="tabs">
                      {[
                        ["assets", "素材"],
                        ["tasks", "执行任务"],
                        ["delivery", "交付记录"],
                        ["activity", "执行记录"],
                      ].map(([key, label]) => (
                        <button
                          className={tab === key ? "active" : ""}
                          key={key}
                          onClick={() => setTab(key)}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                    <div className="canvas-content">
                      {tab === "assets" && (
                        <>
                          <div className="panel-heading">
                            <h3>项目素材</h3>
                            <span>只显示此项目的文件</span>
                          </div>
                          <div className="asset-grid">
                            {project?.files.map((f) => (
                              <div className="asset-card" key={f.id}>
                                {f.kind === "image" ? (
                                  <img
                                    src={`/api/projects/${pid}/files/${f.id}`}
                                  />
                                ) : f.kind === "video" ? (
                                  <video
                                    controls
                                    preload="metadata"
                                    src={`/api/projects/${pid}/files/${f.id}`}
                                  />
                                ) : f.kind === "audio" ? (
                                  <audio
                                    controls
                                    src={`/api/projects/${pid}/files/${f.id}`}
                                  />
                                ) : (
                                  <Paperclip size={25} />
                                )}
                                <strong>{f.name}</strong>
                                <small>
                                  {(f.size / 1024).toFixed(0)} KB · {f.kind}
                                </small>
                                <div className="asset-actions">
                                  <a
                                    href={`/api/projects/${pid}/files/${f.id}`}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    打开
                                  </a>
                                  <button
                                    disabled={busy || f.cos_verified}
                                    onClick={() =>
                                      action(async () => {
                                        await api(
                                          `/projects/${pid}/files/${f.id}/storage`,
                                          "POST",
                                          {},
                                        );
                                        await refresh();
                                      })
                                    }
                                  >
                                    {f.cos_verified
                                      ? "COS 已校验"
                                      : "备份至 COS（预留 ¥1）"}
                                  </button>
                                </div>
                              </div>
                            ))}
                          </div>
                          {!project?.files.length && (
                            <div className="empty">
                              <Paperclip size={25} />
                              <p>
                                在对话中附上图片、视频、声音或文本。生成素材也会保存在这里。
                              </p>
                            </div>
                          )}
                        </>
                      )}
                      {tab === "tasks" && (
                        <>
                          <div className="panel-heading">
                            <h3>制作任务</h3>
                            <span>刷新或重启后可恢复状态</span>
                          </div>
                          {!project?.tasks.length && (
                            <div className="empty">
                              <Film size={30} />
                              <p>保存分镜后，点击「准备制作」。</p>
                            </div>
                          )}
                          {project?.tasks
                            .slice()
                            .reverse()
                            .map((t) => (
                              <div className="task" key={t.id}>
                                <div className="task-heading">
                                  <strong>修订 {t.revision}</strong>
                                  <span
                                    className={
                                      "status " +
                                      (t.status === "running" ? "live" : "")
                                    }
                                  >
                                    {statusNames[t.status] || t.status}
                                  </span>
                                </div>
                                <small>{t.id.slice(0, 12)}</small>
                                {t.nodes?.map((n: any) => (
                                  <div className="task-node" key={n.id}>
                                    <span>
                                      {n.id === "$render" ? "合成预览片" : n.id}
                                    </span>
                                    <span>
                                      {statusNames[n.status] || n.status}
                                    </span>
                                  </div>
                                ))}
                                {t.error && (
                                  <p className="inline-error">{t.error}</p>
                                )}
                                <div className="remote-requests">
                                  {requestRows[t.id]?.map((r) => (
                                    <div key={r.id}>
                                      <code>
                                        {r.remote || r.id.slice(0, 12)}
                                      </code>
                                      <span>{r.remote_status || r.state}</span>
                                      {r.query_status && (
                                        <small>{r.query_status}</small>
                                      )}
                                    </div>
                                  ))}
                                </div>
                                <div className="task-actions">
                                  <button
                                    disabled={busy}
                                    onClick={() =>
                                      action(async () => {
                                        const rows = await api(
                                          `/projects/${pid}/tasks/${t.id}/requests?refresh=true`,
                                        );
                                        setRequestRows((old) => ({
                                          ...old,
                                          [t.id]: rows,
                                        }));
                                      })
                                    }
                                  >
                                    核对远程状态
                                  </button>
                                  {[
                                    "running",
                                    "queued",
                                    "reconciling",
                                  ].includes(t.status) ? (
                                    <button
                                      disabled={stopPending}
                                      onClick={stopProduction}
                                    >
                                      停止新增工作
                                    </button>
                                  ) : ["failed", "cancelled"].includes(
                                      t.status,
                                    ) ? (
                                    <button
                                      onClick={() =>
                                        action(() =>
                                          api(
                                            `/projects/${pid}/tasks/${t.id}/resume`,
                                            "POST",
                                          ),
                                        )
                                      }
                                    >
                                      <RefreshCw size={13} />
                                      继续此任务
                                    </button>
                                  ) : null}
                                  {t.status === "succeeded" && (
                                    <button
                                      className="primary"
                                      disabled={busy}
                                      onClick={() =>
                                        action(async () => {
                                          await api(
                                            `/projects/${pid}/deliver`,
                                            "POST",
                                            {
                                              task_id: t.id,
                                              allow_baked: false,
                                              command_id: "export-" + t.id,
                                            },
                                          );
                                          await refresh();
                                          setTab("delivery");
                                        })
                                      }
                                    >
                                      <Download size={14} />
                                      生成配套交付
                                    </button>
                                  )}
                                </div>
                              </div>
                            ))}
                        </>
                      )}
                      {tab === "delivery" && (
                        <>
                          <div className="panel-heading">
                            <h3>交付版本</h3>
                            <span>预览片与可编辑工程成对保存</span>
                          </div>
                          {!project?.deliveries.length && (
                            <div className="empty">
                              <FolderOpen size={30} />
                              <p>任务完成后生成配套交付。旧版本会一直保留。</p>
                            </div>
                          )}
                          {project?.deliveries
                            .slice()
                            .reverse()
                            .map((d) => (
                              <div className="delivery" key={d.id}>
                                <div className="task-heading">
                                  <strong>修订 {d.revision}</strong>
                                  <small>同一构建 · 已校验文件哈希</small>
                                </div>
                                <video
                                  controls
                                  src={`/api/projects/${pid}/deliveries/${d.id}/preview`}
                                />
                                <div className="download-row">
                                  <a
                                    className="secondary"
                                    href={`/api/projects/${pid}/deliveries/${d.id}/preview`}
                                    download
                                  >
                                    <Download size={14} />
                                    预览 MP4
                                  </a>
                                  <a
                                    className="primary"
                                    href={`/api/projects/${pid}/deliveries/${d.id}/zip`}
                                  >
                                    <Download size={14} />
                                    剪映工程 ZIP
                                  </a>
                                </div>
                                <details>
                                  <summary>安装与兼容说明</summary>
                                  <p>
                                    关闭剪映，将 ZIP 解压到临时目录；用包内
                                    install_draft.py
                                    指定新的草稿目录。多轨结构已保留，目标剪映实机打开、编辑、保存、重开仍需验收。
                                  </p>
                                  <code>
                                    python install_draft.py --zip jianying.zip
                                    --destination 新的草稿目录
                                  </code>
                                  {d.limitations.map((l, i) => (
                                    <p key={i}>{l.reason}</p>
                                  ))}
                                  <p>MP4 SHA-256：{d.preview_sha256}</p>
                                  <p>ZIP SHA-256：{d.zip_sha256}</p>
                                </details>
                              </div>
                            ))}
                        </>
                      )}
                      {tab === "activity" && (
                        <>
                          <div className="panel-heading">
                            <h3>真实执行事件</h3>
                            <span>按持久游标恢复</span>
                          </div>
                          <div className="events">
                            {activity
                              .slice()
                              .reverse()
                              .map((a, i) => (
                                <details key={a.seq + "-" + i}>
                                  <summary>
                                    <span>#{a.seq}</span> {a.kind}
                                  </summary>
                                  <pre>{JSON.stringify(a.data, null, 2)}</pre>
                                </details>
                              ))}
                          </div>
                          <h3>用量记录</h3>
                          {project?.usage.map((u) => (
                            <div className="usage" key={u.id}>
                              <span>
                                {u.category === "planning"
                                  ? "文本规划"
                                  : "媒体制作"}
                              </span>
                              <strong>预留 {money(u.reserved_micros)}</strong>
                              <small>{u.bill_status || u.state}</small>
                            </div>
                          ))}
                        </>
                      )}
                    </div>
                  </aside>
                )}
              </section>
            </div>
          </>
        )}
        {error && (
          <div className="toast" role="alert">
            <span>{error}</span>
            <button aria-label="关闭提示" onClick={() => setError("")}>
              <X size={16} />
            </button>
          </div>
        )}
      </main>
      {edit && (
        <div className="modal-backdrop">
          <section className="modal editor">
            <div className="modal-head">
              <h2>编辑规划</h2>
              <button
                className="icon"
                aria-label="关闭编辑"
                onClick={() => setEdit(null)}
              >
                <X />
              </button>
            </div>
            <div className="modal-body">
              <label>
                项目名称
                <input
                  value={edit.title}
                  onChange={(e) => setEdit({ ...edit, title: e.target.value })}
                />
              </label>
              <label>
                画面比例
                <select
                  value={edit.aspect}
                  onChange={(e) =>
                    setEdit({
                      ...edit,
                      aspect: e.target.value as Plan["aspect"],
                    })
                  }
                >
                  {["16:9", "9:16", "1:1"].map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </select>
              </label>
              <div className="board-section-head">
                <h3>人物</h3>
                <button
                  className="text-button"
                  onClick={() =>
                    setEdit({
                      ...edit,
                      characters: [
                        ...edit.characters,
                        {
                          id: "char_" + id().slice(0, 8),
                          name: "新人物",
                          description: "",
                          reference_file_id: null,
                        },
                      ],
                    })
                  }
                >
                  添加人物
                </button>
              </div>
              {edit.characters.map((c, i) => (
                <div className="edit-card" key={c.id}>
                  <input
                    aria-label="人物名称"
                    value={c.name}
                    onChange={(e) =>
                      setEdit({
                        ...edit,
                        characters: edit.characters.map((x, j) =>
                          j === i ? { ...x, name: e.target.value } : x,
                        ),
                      })
                    }
                  />
                  <textarea
                    aria-label="人物描述"
                    value={c.description}
                    onChange={(e) =>
                      setEdit({
                        ...edit,
                        characters: edit.characters.map((x, j) =>
                          j === i ? { ...x, description: e.target.value } : x,
                        ),
                      })
                    }
                  />
                  <select
                    aria-label="人物参考图"
                    value={c.reference_file_id || ""}
                    onChange={(e) =>
                      setEdit({
                        ...edit,
                        characters: edit.characters.map((x, j) =>
                          j === i
                            ? {
                                ...x,
                                reference_file_id: e.target.value || null,
                              }
                            : x,
                        ),
                      })
                    }
                  >
                    <option value="">选择参考图</option>
                    {project?.files
                      .filter((f) => f.kind === "image")
                      .map((f) => (
                        <option value={f.id} key={f.id}>
                          {f.name}
                        </option>
                      ))}
                  </select>
                </div>
              ))}
              <div className="board-section-head">
                <h3>分镜</h3>
                <button
                  className="text-button"
                  onClick={() =>
                    setEdit({
                      ...edit,
                      shots: [
                        ...edit.shots,
                        {
                          id: "shot_" + id().slice(0, 8),
                          title: "新镜头",
                          description: "",
                          duration: 5,
                          subtitle: "",
                          character_ids: [],
                          file_id: null,
                          source_start: 0,
                          generate: false,
                        },
                      ],
                    })
                  }
                >
                  添加镜头
                </button>
              </div>
              {edit.shots.map((s, i) => {
                const change = (patch: Partial<Shot>) =>
                  setEdit({
                    ...edit,
                    shots: edit.shots.map((x, j) =>
                      j === i ? { ...x, ...patch } : x,
                    ),
                  });
                return (
                  <div className="edit-card" key={s.id}>
                    <div className="edit-card-head">
                      <span>镜头 {i + 1}</span>
                      <button
                        className="text-button"
                        onClick={() =>
                          setEdit({
                            ...edit,
                            shots: edit.shots.filter((_, j) => j !== i),
                          })
                        }
                      >
                        移除
                      </button>
                    </div>
                    <label>
                      标题
                      <input
                        value={s.title}
                        onChange={(e) => change({ title: e.target.value })}
                      />
                    </label>
                    <label>
                      画面与动作
                      <textarea
                        value={s.description}
                        onChange={(e) =>
                          change({ description: e.target.value })
                        }
                      />
                    </label>
                    <div className="field-pair">
                      <label>
                        时长（秒）
                        <input
                          type="number"
                          min="1"
                          max="30"
                          value={s.duration}
                          onChange={(e) =>
                            change({ duration: Number(e.target.value) })
                          }
                        />
                      </label>
                      <label>
                        素材起点（秒）
                        <input
                          type="number"
                          min="0"
                          value={s.source_start}
                          onChange={(e) =>
                            change({ source_start: Number(e.target.value) })
                          }
                        />
                      </label>
                    </div>
                    <label>
                      字幕
                      <input
                        value={s.subtitle}
                        onChange={(e) => change({ subtitle: e.target.value })}
                      />
                    </label>
                    <label>
                      素材
                      <select
                        value={s.file_id || ""}
                        onChange={(e) =>
                          change({ file_id: e.target.value || null })
                        }
                      >
                        <option value="">未绑定素材</option>
                        {project?.files
                          .filter((f) => ["image", "video"].includes(f.kind))
                          .map((f) => (
                            <option value={f.id} key={f.id}>
                              {f.name}
                            </option>
                          ))}
                      </select>
                    </label>
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={s.generate}
                        onChange={(e) => change({ generate: e.target.checked })}
                      />
                      使用模型生成此镜头（选中素材作为参考）
                    </label>
                  </div>
                );
              })}
              <label>
                背景音轨
                <select
                  value={edit.audio_file_id || ""}
                  onChange={(e) =>
                    setEdit({ ...edit, audio_file_id: e.target.value || null })
                  }
                >
                  <option value="">无</option>
                  {project?.files
                    .filter((f) => f.kind === "audio")
                    .map((f) => (
                      <option value={f.id} key={f.id}>
                        {f.name}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                制作备注
                <textarea
                  value={edit.notes}
                  onChange={(e) => setEdit({ ...edit, notes: e.target.value })}
                />
              </label>
            </div>
            <div className="modal-foot">
              <span>保存为新修订，保留旧版本</span>
              <button
                className="primary"
                disabled={busy}
                onClick={() => savePlan(edit)}
              >
                保存规划
              </button>
            </div>
          </section>
        </div>
      )}
      {quote && (
        <div className="modal-backdrop">
          <section className="modal small">
            <div className="modal-head">
              <h2>确认制作范围</h2>
              <button
                className="icon"
                aria-label="关闭授权"
                onClick={() => setQuote(null)}
              >
                <X />
              </button>
            </div>
            <div className="modal-body">
              <p>
                修订 {quote.revision} · {quote.duration} 秒 · {quote.paid_tasks}{" "}
                个付费素材任务
              </p>
              {quote.new_nodes && <p>新执行：{quote.new_nodes.join("、") || "无需新增生成"}<br/>复用：{quote.reused_nodes.join("、") || "无"}<br/>受影响下游：{quote.invalidated.join("、") || "成片合成"}</p>}
              {quote.mode === "native" && <p>既有规划预留 {money(quote.planning_reserved_micros)}；旧媒体请求预留 {money(quote.prior_media_reserved_micros)}，实际账单仍待核对。</p>}
              <div className="budget-amount">
                最多预留 {money(quote.maximum_micros)}
              </div>
              <p>
                {quote.bill_status}。本次测试总预算为{" "}
                {money(boot?.budget_micros || 0)}，由服务端统一限制。
              </p>
              {quote.baked.length > 0 && (
                <p>需局部烘焙：{quote.baked.join("、")}。导出前需另行确认。</p>
              )}
            </div>
            <div className="modal-foot">
              <button
                className="primary"
                disabled={busy}
                onClick={() =>
                  action(async () => {
                    await api(quote.id ? `/projects/${pid}/quotes/${quote.id}/confirm` : `/projects/${pid}/produce`, "POST", {
                      revision: quote.revision,
                      quote_hash: quote.quote_hash,
                      command_id: id(),
                    });
                    setQuote(null);
                    setTab("");
                    await refresh();
                  })
                }
              >
                授权此版本并开始
              </button>
            </div>
          </section>
        </div>
      )}
      {showSettings && (
        <div className="modal-backdrop">
          <section className="modal small">
            <div className="modal-head">
              <h2>运行配置</h2>
              <button
                className="icon"
                aria-label="关闭配置"
                onClick={() => setShowSettings(false)}
              >
                <X />
              </button>
            </div>
            <div className="modal-body">
              <p>官方 Codex：{boot?.codex_version}</p>
              <p>规划模型：{boot?.model || "未配置"}</p>
              <p>测试总上限：{money(boot?.budget_micros || 0)}</p>
              <p>控制层：{boot?.database}</p>
              <p>配置由本机 config.local.json 管理；网页不会接收供应商密钥。</p>
              <p>仅在本机运行。剪映实机兼容性需完成两轮验收。</p>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
