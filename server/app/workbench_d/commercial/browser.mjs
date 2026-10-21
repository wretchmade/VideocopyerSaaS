// D browser adapter. Playwright is resolved from an explicit, separately installed dependency.
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const modulePath=process.env.D_PLAYWRIGHT_MODULE || 'playwright';
const {chromium}=require(modulePath);
const spec=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const output=path.resolve(process.argv[3]);fs.mkdirSync(output,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.D_BROWSER||chromium.executablePath()});
try {
  // No persistent user directory, cookies or login storage is reused or exported.
  const context=await browser.newContext({viewport:{width:spec.width,height:spec.height},deviceScaleFactor:1,serviceWorkers:'block',acceptDownloads:false});
  const origins=new Set([new URL(spec.url).origin,...spec.allowed_origins]);
  const blocked=[];
  await context.route('**/*',route=>{
    const url=route.request().url();
    if(url.startsWith('data:')||url.startsWith('blob:')||origins.has(new URL(url).origin))return route.continue();
    blocked.push(url);return route.abort();
  });
  const page=await context.newPage();page.setDefaultTimeout(spec.timeout_ms);
  const response=await page.goto(spec.url,{waitUntil:'networkidle',timeout:spec.timeout_ms});
  if(!response?.ok())throw new Error(`Page failed: ${response?.status()}`);
  if(spec.wait_selector)await page.locator(spec.wait_selector).waitFor({state:'visible'});
  await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(img=>img.decode()));});
  await page.clock.install({time:new Date('2026-01-01T00:00:00Z')});
  await page.clock.pauseAt(new Date('2026-01-01T00:00:00Z'));
  let elapsed=0;
  for(let n=0;n<spec.frames;n++){
    const target=Math.round(n*1000*spec.fps.den/spec.fps.num);
    if(target>elapsed)await page.clock.runFor(target-elapsed);elapsed=target;
    for(const a of spec.actions.filter(a=>a.at===n)){
      if(a.action==='click')await page.locator(a.selector).click({timeout:spec.timeout_ms});
      else if(a.action==='fill')await page.locator(a.selector).fill(a.text);
      else await page.evaluate(y=>window.scrollBy(0,y),a.y);
    }
    // CSS animations are sampled at program time; JS timers use Playwright's clock.
    await page.evaluate(ms=>{for(const a of document.getAnimations()){a.pause();a.currentTime=ms;}},target);
    await page.screenshot({path:path.join(output,`${String(n).padStart(8,'0')}.png`),animations:'allow',timeout:spec.timeout_ms});
  }
  fs.writeFileSync(path.join(output,'capture.json'),JSON.stringify({frames:spec.frames,fps:spec.fps,width:spec.width,height:spec.height,
    url:spec.url,blocked,isolated:true,clock:'fixed-step',browser:browser.version(),playwright:require(path.join(path.dirname(require.resolve(modulePath)),'package.json')).version},null,2));
  await context.close();
} finally {await browser.close();}
