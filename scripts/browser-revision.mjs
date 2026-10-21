import {chromium} from '@playwright/test';
import fs from 'node:fs/promises';
const record=JSON.parse(await fs.readFile('docs/evidence/browser-project.json','utf8'));
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
const state=()=>page.request.get(`http://127.0.0.1:8765/api/projects/${record.project}`).then(r=>r.json());
await page.goto(record.url);await page.getByRole('button',{name:'人物与分镜',exact:true}).click();
const before=await state();
await page.locator('.shot').first().click();
await page.getByLabel('消息',{exact:true}).fill('只给选中的第一个镜头添加字幕“清晨，让花先醒来”。保留所有人物、提示词、时长、镜头 ID 和生成选项不变。请保存新规划，不请求生成。');
await page.getByRole('button',{name:'发送',exact:true}).click();
let revised;
for(let i=0;i<100;i++){
 revised=await state();if(revised.revision>before.revision&&revised.status==='completed')break;
 if(revised.status==='failed')throw Error('revision failed');
 await new Promise(r=>setTimeout(r,1000));
}
if(revised.revision<=before.revision)throw Error('No new immutable revision');
await page.reload();await page.getByRole('button',{name:'准备制作',exact:true}).click();
await page.getByRole('heading',{name:'确认制作范围'}).waitFor();
const quote=await page.request.get(`http://127.0.0.1:8765/api/projects/${record.project}/quote?revision=${revised.revision}`).then(r=>r.json());
if(quote.paid_tasks!==0)throw Error('Unchanged generation was not reused; refusing extra paid call');
await page.screenshot({path:'docs/evidence/browser-reuse.png',fullPage:true});
await page.getByRole('button',{name:'授权此版本并开始',exact:true}).click();
for(let i=0;i<90;i++){
 revised=await state();const task=revised.tasks.find(t=>t.revision===revised.revision);
 if(task?.status==='succeeded')break;
 if(task?.status==='failed')throw Error(task.error);
 await new Promise(r=>setTimeout(r,1000));
}
await page.reload();await page.getByRole('button',{name:/制作任务/}).click();
await page.getByRole('button',{name:'生成配套交付',exact:true}).first().click();
await page.getByRole('heading',{name:'交付版本',exact:true}).waitFor();
await page.locator('.delivery video').first().evaluate(v=>{v.currentTime=2});
await page.screenshot({path:'docs/evidence/browser-revision-delivery.png',fullPage:true});
const final=await state();
await fs.writeFile('docs/evidence/revision-verification.json',JSON.stringify({project:record.project,beforeRevision:before.revision,afterRevision:final.revision,quote,deliveries:final.deliveries,oldDeliveryRetained:final.deliveries.some(d=>d.revision===before.revision),errors},null,2));
await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'制作画布',exact:true}).click();await page.screenshot({path:'docs/evidence/browser-mobile.png',fullPage:true});
await browser.close();console.log(JSON.stringify({reused:true,oldDeliveryRetained:true,errors}));
