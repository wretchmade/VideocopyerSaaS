import {chromium} from '@playwright/test';
import fs from 'node:fs/promises';
const record=JSON.parse(await fs.readFile('docs/evidence/browser-project.json','utf8'));
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto(record.url);
await page.getByLabel('消息',{exact:true}).fill('请调用 ask_user 问我“是否保持当前标题？”，等待我回答。不要修改规划，不生成媒体。');
await page.getByRole('button',{name:'发送',exact:true}).click();
await page.getByLabel('澄清答案').waitFor({timeout:90000});
await page.reload();await page.getByLabel('澄清答案').waitFor();
await page.screenshot({path:'docs/evidence/browser-clarification.png',fullPage:true});
await page.getByRole('button',{name:'停止',exact:true}).click();
await page.waitForFunction(()=>!document.querySelector('.question'),{timeout:30000});
await page.getByLabel('消息',{exact:true}).fill('继续。保持当前标题，仅回复已保持，不修改规划、不生成媒体。');
await page.getByRole('button',{name:'发送',exact:true}).click();
for(let i=0;i<90;i++){
 const p=await page.request.get(`http://127.0.0.1:8765/api/projects/${record.project}`).then(r=>r.json());
 if(p.status==='completed')break;
 if(p.status==='failed')throw Error('Resume failed');
 await new Promise(r=>setTimeout(r,1000));
}
await page.reload();
await page.getByRole('button',{name:'交付版本',exact:true}).click();
await page.locator('.delivery video').first().evaluate(async v=>{v.muted=true;await v.play();v.currentTime=2});
await page.waitForFunction(()=>document.querySelector('.delivery video')?.readyState>=3);
await page.screenshot({path:'docs/evidence/browser-final.png',fullPage:true});
const p=await page.request.get(`http://127.0.0.1:8765/api/projects/${record.project}`).then(r=>r.json());
const requests=[];for(const t of p.tasks){requests.push(...await page.request.get(`http://127.0.0.1:8765/api/projects/${record.project}/tasks/${t.id}/requests`).then(r=>r.json()))}
await fs.writeFile('docs/evidence/conversation-recovery.json',JSON.stringify({project:record.project,status:p.status,revision:p.revision,questionStatuses:p.questions.map(q=>q.status),deliveryIds:p.deliveries.map(d=>d.id),requests,errors,verified:['refresh pending clarification','stop active turn','resume persisted official Codex thread','old and new deliveries retained','actual revised video playback']},null,2));
await browser.close();console.log(JSON.stringify({status:p.status,errors}));
