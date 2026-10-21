import {chromium} from '@playwright/test';
import fs from 'node:fs/promises';
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto('http://127.0.0.1:8765');
await page.getByRole('heading',{name:'这次，我们拍什么？'}).waitFor();
await page.screenshot({path:'docs/evidence/browser-home.png',fullPage:true});
await page.getByLabel('消息',{exact:true}).fill('这是本地应用的真实验收样例。请直接保存一个 16:9、10 秒、2 个镜头的视频规划，主题为清晨花店的一位成年女店主，两个镜头各 5 秒，都使用模型生成，没有字幕和配音。先只保存规划，不请求制作、不调用 ask_user。人物设定固定：短黑发、深蓝围裙、白衬衫。镜头一整理白色雏菊，镜头二微笑打开店门。');
await page.getByRole('button',{name:'发送',exact:true}).click();
await page.waitForURL(/\/projects\/[a-f0-9]+/);
const pid=page.url().split('/').pop();
await fs.writeFile('docs/evidence/browser-project.json',JSON.stringify({project:pid,url:page.url(),phase:'planning'},null,2));
await page.getByRole('button',{name:'准备制作',exact:true}).waitFor({timeout:90000});
await page.waitForFunction(()=>!document.querySelector('button[disabled]')?.textContent?.includes('准备制作'),{timeout:90000}).catch(()=>{});
for(let i=0;i<90;i++){
 const p=await page.request.get(`http://127.0.0.1:8765/api/projects/${pid}`).then(r=>r.json());
 if(p.revision>0){break}
 if(p.status==='failed')throw Error('Real planning failed: '+JSON.stringify(p.messages.slice(-1)));
 await new Promise(r=>setTimeout(r,1000));
}
await page.reload();
await page.getByRole('button',{name:'准备制作',exact:true}).waitFor();
await page.screenshot({path:'docs/evidence/browser-planned.png',fullPage:true});
await page.getByRole('button',{name:'准备制作',exact:true}).click();
await page.getByRole('heading',{name:'确认制作范围'}).waitFor();
await page.screenshot({path:'docs/evidence/browser-budget.png',fullPage:true});
// User explicitly authorized real API/COS testing up to CNY 100 in this task.
await page.getByRole('button',{name:'授权此版本并开始',exact:true}).click();
await page.getByRole('heading',{name:'制作任务',exact:true}).waitFor();
await fs.writeFile('docs/evidence/browser-project.json',JSON.stringify({project:pid,url:page.url(),phase:'submitted',errors},null,2));
await page.screenshot({path:'docs/evidence/browser-task.png',fullPage:true});
await browser.close();
console.log(JSON.stringify({project:pid,errors}));
