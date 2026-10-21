"""Self-contained local review copy; no network scripts or remote uploads."""
import json,zipfile
from pathlib import Path

def write(folder,review):
    public={k:v for k,v in review.items() if k!='media'}
    encoded=json.dumps(public,ensure_ascii=False).replace('<','\\u003c')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>D 离线审片</title>
<style>body{background:#18222a;color:#eef2ee;font:16px system-ui;max-width:960px;margin:40px auto;padding:20px}video{width:100%}button,textarea,input{font:inherit;padding:10px;margin:8px 0}textarea{display:block;width:95%}li{margin:12px 0}small{overflow-wrap:anywhere}</style>
<h1>D 离线审片副本</h1><small id="binding"></small><video id="movie" controls src="MEDIA"></video>
<label>反馈帧 <input id="frame" type="number" min="0"></label><button id="seek">定位</button>
<textarea id="body" placeholder="写下这帧的反馈" maxlength="4000"></textarea><button id="add">添加本地反馈</button><button id="download">导出反馈 JSON</button><ol id="comments"></ol>
<p>反馈保存在本机浏览器。导出 JSON 后，在 D 审片工作台同步；视频和旧修订不会被改写。</p>
<script>const review=REVIEW, key='d-review-'+review.reviewId;let comments=JSON.parse(localStorage.getItem(key)||'[]');
const $=id=>document.getElementById(id);$('binding').textContent='项目 '+review.projectId+' · 修订 '+review.revision+' · 构建 '+review.buildId+' · '+review.documentHash;
$('frame').max=review.frames-1;const fps=review.fps.num/review.fps.den;$('movie').ontimeupdate=()=>{$('frame').value=Math.min(review.frames-1,Math.floor($('movie').currentTime*fps+0.001))};
$('seek').onclick=()=>{$('movie').pause();$('movie').currentTime=Math.max(0,Math.min(review.frames-1,Number($('frame').value)))/fps};
function draw(){$('comments').replaceChildren();for(const c of comments){const li=document.createElement('li');li.textContent='F'+c.frame+' · '+c.body;$('comments').append(li)}}
$('add').onclick=()=>{const frame=Number($('frame').value),body=$('body').value.trim();if(!Number.isInteger(frame)||frame<0||frame>=review.frames||!body)return;comments.push({externalId:crypto.randomUUID(),frame,body});localStorage.setItem(key,JSON.stringify(comments));$('body').value='';draw()};
$('download').onclick=()=>{const blob=new Blob([JSON.stringify({reviewId:review.reviewId,documentHash:review.documentHash,comments},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='d-review-feedback.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};draw();</script></html>'''
    page=page.replace('MEDIA',Path(review['media']['path']).name).replace('REVIEW',encoded)
    (folder/'review.html').write_text(page,encoding='utf8')
    target=folder/'review-copy.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as out:
        for name in ('review.html','review.json',Path(review['media']['path']).name):out.write(folder/name,name)
    return target
