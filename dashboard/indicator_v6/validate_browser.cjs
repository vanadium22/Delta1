// Headless local page validation. Isolated profile; no user browser/session access.
const {createRequire}=require('node:module');
const req=createRequire(process.env.DELTA1_PLAYWRIGHT_PACKAGE || 'C:/Users/inani/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json');
const {chromium}=req('playwright');const fs=require('node:fs');const path=require('node:path');
const output=path.resolve(__dirname,'../outputs/2026-10-23/app_v6_validation');
let server,browser;
(async()=>{
 const {spawn}=require('node:child_process');
 server=spawn(process.env.DELTA1_TEST_PYTHON || 'P:/code_content/python_work_env/conda_env/swhy_delta1/python.exe',['-m','dashboard.indicator_v6.web','--port','8767'],{cwd:path.resolve(__dirname,'../..'),windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});
 await new Promise((resolve,reject)=>{server.stdout.once('data',resolve);server.once('error',reject);server.once('exit',code=>reject(Error('Server exited '+code)));});
 browser=await chromium.launch({executablePath:process.env.DELTA1_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1100},deviceScaleFactor:1});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8767');await page.waitForFunction(()=>window.lastResult?.id==='A01');
 const checks=[];
 async function select(code,x){const group=code[0];await page.locator(`nav button[data-group="${group}"]`).click();await page.selectOption('#indicator',code);if(x)await page.selectOption('#variant',x);await page.waitForFunction(({code,x})=>window.lastResult?.id===code&&(!x||window.lastResult.variant===x)&&document.body.dataset.ready===window.lastResult.cache_key,{code,x},{timeout:60000});}
 for(const [group,count] of [['A',12],['B',10],['C',10]]){await page.locator(`nav button[data-group="${group}"]`).click();const n=await page.locator('#indicator option').count();if(n!==count)throw Error('Entry count '+group);checks.push({group,entries:n})}
 await select('A02','b');await page.selectOption('#day','2026-04-10');await page.waitForFunction(()=>window.lastResult?.series.b_pct?.at(-1).value===90);const bkey=await page.evaluate(()=>window.lastResult.cache_key);
 await page.selectOption('#variant','a');await page.waitForFunction(()=>window.lastResult?.variant==='a'&&window.lastResult.series.a_pct.at(-1).value===15);if(await page.evaluate(()=>window.lastResult.cache_key)===bkey)throw Error('cache identity');
 await page.screenshot({path:path.join(output,'browser_A02_1440.png'),fullPage:true});await page.locator('#details summary').click();await page.screenshot({path:path.join(output,'browser_A02_formula.png'),fullPage:true});
 await page.selectOption('#day','');await select('B08','ac');await page.locator('.chart svg').first().hover({position:{x:70,y:110}});const hint=await page.locator('.tooltip').first().textContent();if(!hint.includes('2026-10-09')||!hint.includes('IF2610'))throw Error('tooltip metadata');
 const seam=await page.evaluate(()=>window.lastResult.series.B_resid.slice(119,121).map(p=>[p.trade_minute_index,p.timestamp.slice(11,16),p.value]));if(seam[0][0]!==119||seam[1][1]!=='13:01'||seam[1][2]!==null)throw Error('noon reset');
 await page.screenshot({path:path.join(output,'browser_B08_1440.png'),fullPage:true});
 await select('A11','b');const zero=await page.locator('[data-field="C2"] b').textContent();if(!zero.startsWith('0'))throw Error('valid zero hidden');
 for(const width of [1100,768,390]){await page.setViewportSize({width,height:1000});await select('C04');const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);if(overflow)throw Error('page overflow '+width);await page.screenshot({path:path.join(output,`browser_C04_${width}.png`),fullPage:true});checks.push({width,overflow})}
 // Rapid changes must never apply an earlier result to the latest selector.
 await select('B02','cal');await page.selectOption('#variant','ac');await page.selectOption('#variant','l');await page.waitForFunction(()=>window.lastResult?.variant==='l');
 if(errors.length)throw Error(errors.join('\n'));checks.push({switch:'full-history',original_percentile:90,annual_percentile:15,seam,tooltip:true,valid_zero:true,console_errors:errors});
 fs.writeFileSync(path.join(output,'browser_validation.json'),JSON.stringify(checks,null,2));console.log(JSON.stringify(checks));
})().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{if(browser)await browser.close();if(server)server.kill()});
