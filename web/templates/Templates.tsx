import React, {useEffect, useRef, useState} from "react";
import "./templates.css";

type Api = (path:string, method?:string, body?:any)=>Promise<any>;
export type Mount = {template_id:string;revision:number;content_hash:string;bindings:Record<string,string[]>;parameters:Record<string,string>;component_selections:Record<string,string>;output:{duration_seconds:number;aspect_ratio:string}};
export function mountOf(row:any):Mount {
  const c=row.candidate;
  return {template_id:row.template_id,revision:row.revision,content_hash:row.content_hash,bindings:{},
    parameters:Object.fromEntries(c.parameters.map((p:any)=>[p.id,p.default])),
    component_selections:Object.fromEntries(c.component_slots.map((s:any)=>[s.id,s.default_component_id])),
    output:{duration_seconds:c.output_policy.default_seconds,aspect_ratio:c.output_policy.aspect_ratios[0]}};
}
function opts(m:Mount) {return {output:m.output,parameters:m.parameters,component_selections:m.component_selections,bindings:m.bindings};}

function TemplateSkeleton({candidate,expanded,value,selected,onSelect}:{candidate:any;expanded:any;value:Mount;selected:string;onSelect:(id:string)=>void}) {
  const definitions=new Map<string,any>(candidate.nodes.map((n:any)=>[n.id,n]));
  const nodes:any[]=[
    ...candidate.input_slots.map((s:any)=>({id:"slot:"+s.id,label:s.label,detail:`${s.min_items}～${s.max_items} 个 · 已选 ${value.bindings[s.id]?.length||0}`,deps:[],slot:true})),
    ...expanded.graph.map((n:any)=>({id:n.id,label:n.template_node_id,detail:n.occurrence_id||n.kind,templateId:n.template_node_id,
      deps:[...n.depends_on,...new Set(definitions.get(n.template_node_id).slot_inputs.map((s:any)=>"slot:"+s.slot_id))]}))
  ];
  const byId=new Map<string,any>(nodes.map(n=>[n.id,n]));
  for(let i=0;i<nodes.length;i++)for(const n of nodes)if(n.depth===undefined&&n.deps.every((id:string)=>byId.get(id)?.depth!==undefined))
    n.depth=n.deps.length?Math.max(...n.deps.map((id:string)=>byId.get(id).depth))+1:0;
  const rows=new Map<number,number>();let maxDepth=0,maxRows=0;
  for(const n of nodes){const depth=n.depth??0,index=rows.get(depth)||0;rows.set(depth,index+1);n.x=16+depth*240;n.y=16+index*112;maxDepth=Math.max(maxDepth,depth);maxRows=Math.max(maxRows,index+1)}
  const width=(maxDepth+1)*240+16,height=maxRows*112+16;
  return <div className="template-skeleton-scroll"><div className="template-skeleton" style={{width,height}}>
    <svg width={width} height={height} role="img" aria-label="模板骨架依赖图"><defs><marker id="template-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#6c957b"/></marker></defs>
      {nodes.flatMap(n=>n.deps.map((id:string)=>{const p=byId.get(id);if(!p)return null;const x=p.x+200,y=p.y+40;return <path key={`${id}:${n.id}`} d={`M ${x} ${y} C ${x+20} ${y}, ${n.x-20} ${n.y+40}, ${n.x} ${n.y+40}`} fill="none" stroke="#6c957b" strokeWidth="1.5" markerEnd="url(#template-arrow)"/>}))}
    </svg>
    {nodes.map(n=>n.slot?<article key={n.id} style={{left:n.x,top:n.y}}><b>{n.label}</b><small>{n.detail}</small></article>:
      <button key={n.id} style={{left:n.x,top:n.y}} aria-pressed={selected===n.templateId} onClick={()=>onSelect(n.templateId)}><b>{n.label}</b><small>{n.detail}</small><span>{n.deps.length} 项输入 / 依赖</span></button>)}
  </div></div>;
}

export function TemplateDetail({api,row,initial,onMount,onClose}:{api:Api;row:any;initial?:Mount;onMount?:(m:Mount)=>void;onClose:()=>void}) {
  const [value,setValue]=useState<Mount>(initial||mountOf(row));
  const [expanded,setExpanded]=useState<any>(null),[error,setError]=useState(""),[mode,setMode]=useState("expanded"),[selected,setSelected]=useState("");
  const c=row.candidate;
  useEffect(()=>{let active=true;setError("");
    api(`/templates/${row.template_id}/revisions/${row.revision}/preview`,"POST",mode==="default"?{}:opts(value))
      .then(x=>{if(active)setExpanded(x)}).catch(e=>{if(active){setError(e.message);setExpanded(null)}});
    return()=>{active=false};
  },[JSON.stringify(value),mode]);
  const node=c.nodes.find((n:any)=>n.id===selected);
  const recipe=node?.prompt_recipe_id?structuredClone(c.prompt_recipes.find((p:any)=>p.id===node.prompt_recipe_id)):null;
  if(recipe)for(const cid of Object.values((mode==="default"?mountOf(row):value).component_selections)){
    const comp=c.components.find((v:any)=>v.id===cid);
    if(comp?.target_segment_ids.includes(node.segment_id))for(const override of comp.recipe_overrides)
      if(override.recipe_id===recipe.id)recipe.sections[override.section]=override.text;
  }
  return <div className="template-dialog" role="dialog" aria-label="模板详情" aria-modal="true">
    <header><div><small>{row.state==="published"?"可用模板":"试作模板"} · 辅助制作 · v{row.revision}</small><h2>{c.catalog.title}</h2></div><button onClick={onClose} aria-label="关闭模板详情">关闭</button></header>
    <p>{c.catalog.summary}</p>
    {row.sample?<video controls src={`/api/templates/${row.template_id}/revisions/${row.revision}/sample`}/>:<div className="template-empty">{c.preview.kind==="source_reference"?"参考原片 · 尚无系统制作样片":"尚无真实制作样片"}<small>结构预览不代表制作或视觉检查通过</small></div>}
    <div className="template-options">
      <label>片长（秒）<input aria-label="模板片长" type="number" min={c.output_policy.min_seconds} max={c.output_policy.max_seconds} value={value.output.duration_seconds} onChange={e=>setValue({...value,output:{...value.output,duration_seconds:Number(e.target.value)}})}/></label>
      <label>画幅<select value={value.output.aspect_ratio} onChange={e=>setValue({...value,output:{...value.output,aspect_ratio:e.target.value}})}>{c.output_policy.aspect_ratios.map((a:string)=><option key={a}>{a}</option>)}</select></label>
      {c.component_slots.map((s:any)=><label key={s.id}>{s.id}<select aria-label={`组件 ${s.id}`} value={value.component_selections[s.id]} onChange={e=>setValue({...value,component_selections:{...value.component_selections,[s.id]:e.target.value}})}>{s.allowed_component_ids.map((id:string)=><option key={id} value={id}>{c.components.find((v:any)=>v.id===id)?.label}</option>)}</select></label>)}
      {c.parameters.map((p:any)=><label key={p.id}>{p.label}{p.type==="enum"?<select value={value.parameters[p.id]} onChange={e=>setValue({...value,parameters:{...value.parameters,[p.id]:e.target.value}})}>{p.values.map((v:string)=><option key={v}>{v}</option>)}</select>:<input maxLength={p.max_length} value={value.parameters[p.id]} onChange={e=>setValue({...value,parameters:{...value.parameters,[p.id]:e.target.value}})}/>}</label>)}
    </div>
    <div className="template-tabs"><button aria-pressed={mode==="default"} onClick={()=>setMode("default")}>默认骨架</button><button aria-pressed={mode==="expanded"} onClick={()=>setMode("expanded")}>按当前选项展开</button></div>
    {error&&<p role="alert">{error}</p>}
    {expanded&&<>
      <h3>最终播放顺序 · {expanded.frames} 帧 / {expanded.actual_seconds.toFixed(3)} 秒</h3>
      <div className="template-playback">{expanded.playback.map((p:any)=><div key={p.occurrence_id} style={{flexGrow:p.frames}}><b>{p.label}</b><span>{p.occurrence_id}</span><small>{p.start}–{p.end} 帧</small></div>)}</div>
      <h3>工作流骨架</h3><p className="template-note">连线表示依赖；最终播放顺序以上方段落条为准。预览不调用模型。</p>
      <p className="template-note">{c.segments.map((s:any)=>`${s.label}：${s.min_count}～${s.max_count} 段，每段 ${s.min_seconds}～${s.max_seconds} 秒`).join(" · ")}</p>
      <TemplateSkeleton candidate={c} expanded={expanded} value={value} selected={selected} onSelect={setSelected}/>
      <h3>节点与提示词详情</h3>
      {node?<article className="template-node"><b>{node.id} · {node.kind}</b><p>固定能力：{node.capability_id}；作用段：{node.segment_id||"全片"}</p>
        <p>参考输入：{node.slot_inputs.map((s:any)=>`${s.slot_id} / ${s.role} / ${s.selection}`).join("、")||"无"}</p>
        <p>检查要求：{node.requirement_ids.join("、")}</p>
        {recipe&&<pre>{JSON.stringify(recipe,null,2)}</pre>}
        <p>允许修改参数：{c.adaptation_policy.editable_parameter_ids.join("、")||"无"}。组件仅替换声明的创意、环境及动作配方。</p>
      </article>:<p>点击骨架节点查看固定规则、输入角色和提示词配方。</p>}
    </>}
    {onMount&&<footer><button disabled={!expanded||row.state==="retired"} onClick={()=>onMount(value)}>使用此模板</button><span>挂载不会授权付费制作；报价后另行确认。</span></footer>}
  </div>;
}

export function TemplateLibrary({api,onMount,onClose}:{api:Api;onMount:(m:Mount)=>void;onClose:()=>void}) {
  const [rows,setRows]=useState<any[]>([]),[author,setAuthor]=useState(false),[selected,setSelected]=useState<any>(null),[error,setError]=useState("");
  useEffect(()=>{let active=true;api("/templates?author="+author).then(r=>{if(active)setRows(r)}).catch(e=>setError(e.message));return()=>{active=false}},[author]);
  return <div className="template-overlay">{selected?<TemplateDetail api={api} row={selected} onClose={()=>setSelected(null)} onMount={onMount}/>:<section className="template-dialog" role="dialog" aria-label="模板库" aria-modal="true">
    <header><h2>模板库</h2><button onClick={onClose}>关闭</button></header><p>选择可参数化的工作流，绑定你的素材，再开始规划。</p>
    <label><input type="checkbox" checked={author} onChange={e=>setAuthor(e.target.checked)}/> 显示作者草稿与历史版本</label>
    {error&&<p role="alert">{error}</p>}
    {!rows.length&&<div className="template-empty">{author?"暂无模板草稿。通过准入接口提交带真实注册资源的候选。":"暂无已发布模板。真实试作与审核通过后才会展示在这里。"}</div>}
    <div className="template-cards">{rows.map(r=><button key={`${r.template_id}:${r.revision}`} onClick={()=>setSelected(r)}><small>{r.state} · 辅助制作 · v{r.revision}</small><h3>{r.candidate.catalog.title}</h3><p>{r.candidate.catalog.summary}</p><span>{r.candidate.output_policy.min_seconds}～{r.candidate.output_policy.max_seconds} 秒 · {r.candidate.input_slots.map((s:any)=>s.label).join("、")}</span></button>)}</div>
  </section>}</div>;
}

export function TemplateMount({api,mount,onChange,onRemove,onDetail,composerId,files,upload,onError}:{api:Api;mount:Mount;onChange:(m:Mount)=>void|Promise<void>;onRemove:()=>void;onDetail:(row:any)=>void;composerId:string;files:any[];upload:(file:File)=>Promise<any>;onError:(s:string)=>void}) {
  const [row,setRow]=useState<any>(null),[uploading,setUploading]=useState(false);
  const current=useRef(mount);current.current=mount;
  useEffect(()=>{let active=true;api(`/templates/${mount.template_id}/revisions/${mount.revision}`).then(r=>{if(active)setRow(r)}).catch(e=>onError(e.message));return()=>{active=false}},[mount.template_id,mount.revision]);
  if(!row)return <div className="template-mount">正在读取固定模板版本…</div>;
  return <div className="template-mount" data-composer={composerId}>
    <div><b>{row.candidate.catalog.title}</b><small>v{mount.revision} · {mount.output.duration_seconds} 秒 · {row.state==="published"?"辅助制作":"试作模板"}</small><button onClick={()=>onDetail(row)}>展开骨架</button><button onClick={onRemove}>移除</button></div>
    {row.candidate.input_slots.map((s:any)=><div className="template-slot" key={s.id}><label>{s.label}（{mount.bindings[s.id]?.length||0}/{s.min_items}～{s.max_items}）</label>
      <div>{files.filter(f=>f.kind===s.media_kind).map(f=><label key={f.id}><input type="checkbox" checked={mount.bindings[s.id]?.includes(f.id)||false} onChange={e=>{
        const refs=mount.bindings[s.id]||[];onChange({...mount,bindings:{...mount.bindings,[s.id]:e.target.checked?[...refs,f.id]:refs.filter(id=>id!==f.id)}})
      }}/>{f.name}</label>)}</div>
      <label className="template-upload">{uploading?"正在上传…":"上传并绑定"}<input aria-label={`上传${s.label}`} type="file" disabled={uploading} accept={s.media_kind+"/*"} onChange={async e=>{
        const file=e.target.files?.[0];e.target.value="";if(!file)return;
        setUploading(true);try{const f=await upload(file);const m=current.current;await onChange({...m,bindings:{...m.bindings,[s.id]:[...(m.bindings[s.id]||[]),f.id]}})}catch(err:any){onError(err.message)}finally{setUploading(false)}
      }}/></label>
    </div>)}
  </div>;
}
