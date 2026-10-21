import {chromium,expect} from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import {spawn} from "node:child_process";
import net from "node:net";

const root=process.cwd(), work=path.join(root,".local","template-browser-"+crypto.randomUUID());
const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,"127.0.0.1",()=>{const p=s.address().port;s.close(()=>resolve(p))})});
const server=spawn(path.join(root,".venv","Scripts","python.exe"),["scripts/template_browser_fixture.py"],
  {cwd:root,env:{...process.env,VC_TEMPLATE_FIXTURE:work,VC_TEMPLATE_PORT:String(port)},windowsHide:true,stdio:["ignore","pipe","pipe"]});
let log="";server.stdout.on("data",b=>log+=b);server.stderr.on("data",b=>log+=b);
const base=`http://127.0.0.1:${port}`;
let browser,page;
const exchanges=[];
const evidence="docs/evidence/template-browser";await fs.mkdir(evidence,{recursive:true});
try {
  for(let i=0;i<100;i++){if(server.exitCode!==null)throw Error(log);try{if((await fetch(base+"/api/bootstrap")).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));if(i===99)throw Error("Fixture startup timeout: "+log)}
  browser=await chromium.launch({channel:"chrome",headless:true});
  page=await browser.newPage({viewport:{width:1500,height:1000}});
  page.on("response",async r=>{if(r.url().includes("/template-composers/"))exchanges.push({url:r.url(),method:r.request().method(),status:r.status(),body:await r.json().catch(()=>null)})});
  const errors=[];page.on("pageerror",e=>errors.push(e.message));
  await page.goto(base);
  await page.getByRole("button",{name:"模板库",exact:true}).click();
  await page.getByText("暂无已发布模板。真实试作与审核通过后才会展示在这里。").waitFor();
  await page.getByLabel("显示作者草稿与历史版本").check();
  await page.getByRole("heading",{name:"浏览器测试夹具（非制作样片）"}).click();
  await page.getByRole("heading",{name:/最终播放顺序/}).waitFor();
  const first=await page.locator(".template-playback>div").count();
  await page.getByLabel("模板片长").fill("20");
  await page.waitForFunction(()=>document.querySelectorAll(".template-playback>div").length>3);
  const expanded=await page.locator(".template-playback>div").count();
  await page.getByRole("button",{name:/hook_video/}).first().click();
  await page.getByText("固定能力：reference_guided_video_v1；作用段：hook").waitFor();
  await page.screenshot({path:evidence+"/detail.png",fullPage:true});
  await page.getByRole("button",{name:"使用此模板",exact:true}).click();
  await page.locator(".template-mount").waitFor();
  // Actual decoded PNG, fixture only.
  await page.getByLabel("上传产品图片").setInputFiles(path.join(work,"product.png"));
  await page.getByText(/产品图片（1\/1～3）/).waitFor();
  // Wait on observable durable state, then prove reload restoration.
  const composerId=await page.locator(".template-mount").getAttribute("data-composer");
  await expect.poll(async()=>{const d=await page.request.get(base+"/api/template-composers/"+composerId).then(r=>r.json());
    return d.template_mount?.bindings?.product?.length}).toBe(1);
  await page.reload();await page.getByText(/产品图片（1\/1～3）/).waitFor();
  await page.screenshot({path:evidence+"/mount.png",fullPage:true});
  // Simulate a lost response AFTER successful commit. Retry must keep same command.
  let intercepted=false;
  await page.route("**/api/template-messages",async route=>{
    if(!intercepted){intercepted=true;await route.fetch();await route.abort("failed")}else await route.continue();
  });
  await page.getByRole("button",{name:"发送",exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('button[aria-label="发送"]').disabled);
  await page.reload();await page.getByText(/产品图片（1\/1～3）/).waitFor();
  await page.getByRole("button",{name:"发送",exact:true}).click();
  await page.waitForURL(/\/projects\/[a-f0-9]+/);
  const pid=page.url().split("/").pop();
  const snapshot=await page.request.get(base+"/api/projects/"+pid).then(r=>r.json());
  if(snapshot.messages.length!==1||!snapshot.messages[0].template_instance)throw Error("Lost-response retry duplicated or detached the message");
  await page.getByRole("button",{name:/查看当时的骨架与绑定/}).click();
  await page.getByRole("heading",{name:/最终播放顺序/}).waitFor();
  if(await page.getByRole("button",{name:"使用此模板",exact:true}).count())throw Error("Historical view is editable");
  await page.screenshot({path:evidence+"/history.png",fullPage:true});
  await page.getByRole("button",{name:"关闭模板详情"}).click();
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:evidence+"/mobile.png",fullPage:true});
  const budget=await page.request.get(base+"/api/bootstrap").then(r=>r.json());
  if(budget.reserved_micros!==0)throw Error("Preview or mount reserved budget");
  if(errors.length)throw Error(errors.join("\n"));
  await fs.writeFile(evidence+"/result.json",JSON.stringify({fixture:"isolated synthetic media; no Agent or Worker; NOT runtime acceptance",
    first_occurrences:first,expanded_occurrences:expanded,refresh_restores_bindings:true,lost_response_retry_exactly_once:true,
    history_exact_instance:true,paid_calls:0,reserved_micros:budget.reserved_micros,page_errors:errors,project:pid,work},null,2));
  console.log("Template browser checks passed; zero budget reserved; fixture only.");
}catch(error){
  if(page){await page.screenshot({path:evidence+"/failure.png",fullPage:true}).catch(()=>{});await fs.writeFile(evidence+"/failure.json",JSON.stringify({error:String(error),work,exchanges,text:await page.locator("body").innerText()},null,2))}
  throw error;
}finally{if(browser)await browser.close();server.kill();}
