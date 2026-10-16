import { test, expect } from '@playwright/test';
import { spawn, type ChildProcess } from 'node:child_process';
import { existsSync, mkdtempSync, mkdirSync, openSync, closeSync, writeFileSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';

let server: ChildProcess;
let logs: number[] = [];
let root: string;
let ids: {project: string; before: string; after: string};
const localPython = resolve('.venv/Scripts/python.exe');
const python = existsSync(localPython) ? localPython : 'python';

test('expanded map keeps quiz and contextual instructor reachable', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto(`/reviews/${ids.before}`);
  await expect(page.frameLocator("#learning-map").locator(".node[data-id=\"service\"]")).toBeVisible();
  await Promise.all([page.waitForURL(`**/reviews/${ids.before}/map`),page.getByRole("link", {name:"Expand diagram",exact:true}).click()]);
  await expect(page.getByRole('navigation', {name:'Saved review learning'})).toBeVisible();
  await expect(page.getByRole('link', {name:'Quiz',exact:true})).toBeVisible();
  const map = page.frameLocator('#learning-map');
  await map.locator('.edge[data-relationship="0"]').press('Enter');
  await expect(page.locator('#map-selection')).toContainText('Entry boundary → Greeting coordinator');
  await page.getByRole('button', {name:'Ask about this connection',exact:true}).click();
  await expect(page.locator('#instructor-selection-label')).toContainText('source: main.py');
  expect(JSON.parse(await page.locator('#chat [name="selection"]').inputValue())).toEqual({kind:'source',path:'main.py',line:1,end_line:1});
  await page.locator('#chat .chat-form textarea').fill('');
  await page.getByRole('button', {name:'Clear selected context'}).click();
  await page.getByRole('button', {name:'Close instructor',exact:true}).click();
  await page.locator('#learning-map').evaluate((frame: HTMLIFrameElement)=>window.postMessage({type:'archcoach-selected',kind:'source',review_id:frame.src.split('/')[4],id:'main.py',line:1,end_line:1,source:'entry',target:'store',inferred:false},'*'));
  await expect(page.locator('#map-selection')).toContainText('Entry boundary → Greeting coordinator');
  await map.locator('body').evaluate(()=>window.parent.postMessage({type:'archcoach-selected',kind:'source',review_id:location.pathname.split('/')[2],id:'store.py',line:1,end_line:1,source:'entry',target:'store',inferred:false},'*'));
  await expect(page.locator('#map-selection')).toContainText('Entry boundary → Greeting coordinator');
  await map.locator('.node[data-id="service"]').press('Enter');
  await expect(page.locator('#map-selection')).toContainText('Greeting coordinator');
  await page.getByRole('button', {name:'Ask about this component'}).click();
  await expect(page.locator('#chat')).toBeVisible();
  await expect(page.locator('#instructor-selection-label')).toContainText('service');
  const answerRequest = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/chat'));
  await page.getByRole('button', {name:'Ask the coach'}).click();
  expect((await answerRequest).postDataJSON().selection).toEqual({kind:'component',id:'service'});
  await expect(page.locator('.instructor-progress')).toContainText('Answer saved');
  await page.locator('#chat .chat-form textarea').press('Escape');
  await page.getByRole('link', {name:'Quiz',exact:true}).click();
  await expect(page.getByRole('heading', {name:'Repository quiz'})).toBeVisible();
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('button', {name:'Ask instructor',exact:true}).click();
  await expect(page.locator('#chat')).toBeVisible();
  await page.locator('#chat .chat-form textarea').press('Escape');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  expect(errors).toEqual([]);
});

test.beforeAll(async () => {
  // Refuse an occupied port before creating the task-owned server.
  await new Promise<void>((done, reject) => {
    const probe = createServer(); probe.once('error', reject);
    probe.listen(8878, '127.0.0.1', () => probe.close(() => done()));
  });
  mkdirSync('.test-data', {recursive: true});
  root = mkdtempSync(join(tmpdir(),'archcoach-learning-browser-'));
  writeFileSync(resolve('.test-data/last-learning-browser-root.txt'),root);
  logs = [openSync(join(root, 'stdout.log'), 'w'), openSync(join(root, 'stderr.log'), 'w')];
  server = spawn(python, ['-m', 'tests.fixtures.learning_profile', root], {
    cwd: resolve('.'), env: {...process.env, PYTHONPATH: resolve('src')}, windowsHide: true,
    stdio: ['ignore', logs[0], logs[1]],
  });
  writeFileSync(join(root, 'server.pid'), String(server.pid));
  for (let i = 0; i < 100; i++) {
    if (server.exitCode !== null) throw new Error(`Synthetic server exited: ${server.exitCode}`);
    try {
      const result = await fetch('http://127.0.0.1:8878/api/learning-fixture');
      if (result.ok) {ids = await result.json(); return;}
    } catch {}
    await new Promise(done => setTimeout(done, 100));
  }
  throw new Error('Synthetic learning server did not become ready within ten seconds');
});

test.afterAll(async () => {
  if (ids && server?.exitCode === null) {
    try {
      const html = await (await fetch('http://127.0.0.1:8878/learning')).text();
      const token = html.match(/name="archcoach-token" content="([^"]+)"/)?.[1];
      if (token) await fetch('http://127.0.0.1:8878/exit', {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({_csrf:token})});
    } catch {}
    await Promise.race([new Promise(done => server.once('exit', done)), new Promise(done => setTimeout(done, 5000))]);
  }
  if (server?.exitCode === null) {
    server.kill(); // Only the PID spawned by this fixture; no process-name termination.
    await Promise.race([new Promise(done => server.once('exit', done)), new Promise(done => setTimeout(done, 5000))]);
  }
  for (const fd of logs) closeSync(fd);
});

test('uncertainty, session draft and position survive a server restart', async ({page}) => {
  const errors: string[]=[];page.on('pageerror',error=>errors.push(error.message));
  const original=readFileSync(join(root,'synthetic repo with spaces','service.py'),'utf8');
  await page.goto(`/reviews/${ids.after}#quiz`);
  const question=page.locator('#saved-quiz .quiz-card:visible');
  await question.getByRole('button',{name:'Not sure',exact:true}).click();
  await expect(question.locator('.quiz-feedback')).toContainText('Not sure recorded');
  await page.getByRole('button',{name:'Next question',exact:true}).click();
  await expect(page.locator('#quiz-position')).toHaveText('Question 2 of 10');
  await page.getByRole('button',{name:'Ask instructor',exact:true}).click();
  await page.locator('#chat .chat-form textarea').fill('Why does service ask the store to save?');
  await page.getByRole('button',{name:'Close instructor',exact:true}).click();
  await page.getByRole('link',{name:'Short session',exact:true}).click();
  await page.locator('#session-next-step').fill('Explain the storage boundary.');
  await page.locator('#session-next-step').blur();
  await expect(page.locator('#session-save-status')).toContainText('saved locally');
  await page.getByRole('button',{name:'Ask instructor',exact:true}).click();
  await page.locator('#chat .chat-form textarea').fill('Why should storage survive a restart?');
  const exitResponse=page.waitForResponse(response=>response.request().method()==='POST' && response.url().endsWith('/exit') && response.status()===200);
  await page.getByRole('button',{name:'Exit app',exact:true}).click();
  await (await exitResponse).finished();
  await new Promise<void>((done,reject)=>{if(server.exitCode!==null)return done();const timer=setTimeout(()=>reject(new Error('Owned fixture did not exit')),8000);server.once('exit',()=>{clearTimeout(timer);done();});});
  await new Promise<void>((done,reject)=>{const probe=createServer();probe.once('error',reject);probe.listen(8878,'127.0.0.1',()=>probe.close(()=>done()));});
  server=spawn(python,['-m','tests.fixtures.learning_profile',root,'--reuse'],{cwd:resolve('.'),env:{...process.env,PYTHONPATH:resolve('src')},windowsHide:true,stdio:['ignore',logs[0],logs[1]]});
  writeFileSync(join(root,'restarted-server.pid'),String(server.pid));
  await expect.poll(async()=>{try{return (await fetch('http://127.0.0.1:8878/api/health')).status;}catch{return 0;}}).toBe(200);
  await page.goto(`/reviews/${ids.after}#quiz`);
  await expect(page.locator('#quiz-position')).toHaveText('Question 2 of 10');
  await page.getByRole('button',{name:'Ask instructor',exact:true}).click();
  await expect(page.locator('#chat .chat-form textarea')).toHaveValue('Why should storage survive a restart?');
  await page.getByRole('button',{name:'Close instructor',exact:true}).click();
  await page.getByRole('link',{name:'Short session',exact:true}).click();
  await expect(page.locator('#session-next-step')).toHaveValue('Explain the storage boundary.');
  const attempts=await (await page.request.get(`/api/reviews/${ids.after}/quiz/fact-0/attempts`)).json();
  expect(attempts[0].outcome).toBe('not_sure');expect(attempts[0].correct).toBe(0);
  expect(readFileSync(join(root,'synthetic repo with spaces','service.py'),'utf8')).toBe(original);
  expect(errors).toEqual([]);
});

test('saved teaching, cross-module map, recall and change lesson', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto(`/reviews/${ids.before}`);
  await expect(page.getByRole('heading', {name:'Follow the validation boundary'})).toBeVisible();
  const lessonCode = page.locator('.lesson .saved-example').first();
  await expect(lessonCode.locator('pre')).toBeHidden();
  await lessonCode.getByText('Show the saved code', {exact:true}).click();
  await expect(lessonCode.locator('pre')).toBeVisible();
  await expect(lessonCode.locator('pre')).toContainText('def handle');
  await expect(page.locator('.quiz-card')).toHaveCount(10);
  await page.getByRole('button',{name:'Previous question',exact:true}).click();
  await page.locator('.quiz-card').first().getByText('Read the captured example', {exact:true}).click();
  await expect(page.locator('.quiz-card').first().locator('pre')).toContainText('def handle');
  await page.getByRole('link', {name:'Follow a feature',exact:true}).click();
  await page.getByLabel('Feature boundary').selectOption({label:'main.py · main'});
  await expect(page.locator('#step-code')).toContainText('def main');
  await page.getByRole('button', {name:'Next step'}).click();
  await page.getByRole('button', {name:'Next step'}).click();
  await expect(page.locator('#step-code')).toContainText('def handle');
  await expect(page.locator('.walkthrough-active')).toContainText('Greeting coordinator');
  await expect(page.frameLocator('#walkthrough-map').locator('.node.active')).toHaveAttribute('data-id', 'service');
  await page.getByRole('button', {name:'Ask about this step',exact:true}).click();
  const selected = JSON.parse(await page.locator('#chat [name="selection"]').inputValue());
  expect(selected).toEqual({kind:'walkthrough',id:'main.py:2',step:2,outline_version:3});
  await page.getByRole('button', {name:'Ask the coach'}).click();
  await expect(page.locator('.instructor-progress')).toContainText('Answer saved');
  await page.getByRole('button', {name:'Close instructor',exact:true}).click();
  await page.goto('/learning?practice=true');
  const question = page.locator('.quiz-card').first();
  await question.locator('input[value="0"]').check();
  await question.getByRole('button', {name:'Check answer', exact:true}).click();
  await expect(question.locator('.quiz-feedback')).toContainText('Correct');
  await question.getByRole('link', {name:'Discuss in the originating review'}).click();
  await expect(page.locator('#chat')).toBeVisible();
  await page.goto(`/projects/${ids.project}/change-lesson?before=${ids.before}&after=${ids.after}`);
  await expect(page.getByText('Predict before revealing', {exact:true})).toBeVisible();
  await page.getByText('Reveal observed structural changes').click();
  await expect(page.getByText(/No component or dependency change/)).toBeVisible();
  await expect(page.locator('pre').filter({hasText:'Hello'})).toBeVisible();
  await expect(page.locator('pre').filter({hasText:'Welcome'})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  expect(errors).toEqual([]);
});

test('instructor modes preserve drafts, cancellation and focus on narrow screens', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({width:390,height:844});
  await page.goto(`/reviews/${ids.before}#quiz`);
  const chatRequests: string[] = [];
  page.on('request', request => {if (request.method() === 'POST' && request.url().endsWith('/chat')) chatRequests.push(request.url());});
  await page.getByRole('button', {name:'Explain this simply',exact:true}).click();
  const area = page.locator('#chat .chat-form textarea');
  await expect(page.getByLabel('Instructor mode')).toHaveValue('simpler');
  await expect(page.getByLabel('Saved question (optional)')).toHaveValue('');
  await expect(area).toHaveValue(/plain language/);
  expect(chatRequests).toEqual([]);
  await area.fill('Keep this draft');
  await page.getByRole('button', {name:'Close instructor'}).click();
  await page.getByRole('button', {name:'Explain this simply',exact:true}).click();
  await expect(area).toHaveValue('Keep this draft');
  await page.getByRole('button', {name:'Close instructor'}).click();
  await page.locator('.quiz-card').first().getByRole('button', {name:'Explain it back'}).click();
  await expect(area).toHaveValue('Keep this draft');
  await area.fill('');
  await page.getByRole('button', {name:'Close instructor'}).click();
  await page.locator('.quiz-card').first().getByRole('button', {name:'Explain it back'}).click();
  await expect(page.getByLabel('Instructor mode')).toHaveValue('explain_back');
  await expect(page.getByLabel('Saved question (optional)')).toHaveValue('fact-0');
  await area.fill('My explanation: handle accepts a name.');
  await page.getByRole('button', {name:'Ask the coach'}).click();
  await expect(page.locator('.instructor-progress')).toContainText('Answer saved');
  await expect(page.locator('.chat-log')).toContainText('Missing reasoning');
  await expect(page.locator('.chat-log')).toContainText('One next question: What does the empty-name branch declare?');
  await area.fill('FAIL_FIXTURE');
  await page.getByRole('button', {name:'Ask the coach'}).click();
  await expect(page.locator('.instructor-progress')).toContainText('failed:');
  await expect(area).toHaveValue('FAIL_FIXTURE');
  await area.fill('STALL_FIXTURE');
  await page.getByRole('button', {name:'Ask the coach'}).click();
  await page.getByRole('button', {name:'Cancel answer'}).click();
  await expect(page.locator('.instructor-progress')).toContainText('cancelled:');
  await expect(area).toHaveValue('STALL_FIXTURE');
  await area.press('Escape');
  await expect(page.locator('#chat')).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  expect(errors).toEqual([]);
});


test('an earlier step context blocks sending and keeps the unsent draft', async ({page}) => {
  const url = `http://127.0.0.1:8878/reviews/${ids.before}`;
  await page.route(url, async route => {
    const response = await route.fetch();
    const body = (await response.text()).replace(/(<script id="learning-session-data" type="application\/json">)(.*?)(<\/script>)/s, (_, start, data, end) => {
      const saved = JSON.parse(data);
      saved.state.selection = {kind:'walkthrough',id:'main.py:2',step:1};
      saved.state.draft = 'Keep the earlier step question';
      return start + JSON.stringify(saved) + end;
    });
    await route.fulfill({response,body});
  });
  await page.goto(url);
  await page.unroute(url);
  await page.getByRole('button',{name:'Ask instructor',exact:true}).click();
  await expect(page.locator('#instructor-selection-label')).toContainText('Earlier reading format');
  const area = page.locator('#chat .chat-form textarea');
  await expect(area).toHaveValue('Keep the earlier step question');
  const patch = page.waitForRequest(request => request.method()==='PATCH' && request.url().endsWith('/session') && request.postDataJSON().draft==='Keep this updated draft');
  const savedDraft = page.waitForResponse(response => response.request().method()==='PATCH' && response.url().endsWith('/session') && response.request().postDataJSON().draft==='Keep this updated draft' && response.status()===200);
  await area.fill('Keep this updated draft');
  expect((await patch).postDataJSON()).not.toHaveProperty('selection');
  await savedDraft;
  let sent = 0;
  page.on('request',request=>{if(request.method()==='POST' && request.url().endsWith('/chat')) sent++;});
  await page.getByRole('button',{name:'Ask the coach'}).click();
  await expect(page.locator('.instructor-progress')).toContainText('Select the saved step again');
  expect(sent).toBe(0);
  await page.reload();
  await page.getByRole('button',{name:'Ask instructor',exact:true}).click();
  await expect(area).toHaveValue('Keep this updated draft');
  await page.getByRole('button',{name:'Clear selected context'}).click();
  await area.fill('');
  await page.getByRole('button',{name:'Close instructor',exact:true}).click();
});


test('saved quotations repair their line evidence and keep failed drafts', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto(`/reviews/${ids.after}`);
  await page.getByRole('button', {name:'Ask instructor',exact:true}).click();
  const area = page.locator('#chat .chat-form textarea');
  await page.getByLabel('Instructor mode').selectOption('answer');
  await page.getByRole('button', {name:'Clear selected context'}).click();
  await area.fill('MISLOCATED_QUOTE');
  await page.getByRole('button', {name:'Ask the coach'}).click();
  await expect(page.locator('.instructor-progress')).toContainText('Answer saved');
  const answer = page.locator('.chat-log .message.assistant').last();
  await expect(answer).toContainText('def handle(name):');
  await expect(answer.getByRole('link',{name:'service.py:2',exact:true})).toHaveAttribute('href',/path=service.py&line=2/);
  await area.fill('UNREPAIRED_QUOTE');
  await page.getByRole('button', {name:'Ask the coach'}).click();
  await expect(page.locator('.instructor-progress')).toContainText('failed:');
  await expect(area).toHaveValue('UNREPAIRED_QUOTE');
  await expect(page.locator('.chat-log .message.assistant').last()).toContainText('Coach · failed');
  await expect(page.locator('.chat-log .message.assistant').last().locator('a.evidence')).toHaveCount(0);
  await page.reload();
  await page.getByRole('button', {name:'Ask instructor',exact:true}).click();
  await expect(area).toHaveValue('UNREPAIRED_QUOTE');
  await expect(page.locator('.chat-log')).toContainText('def handle(name):');
  await area.fill('');
  await page.getByRole('button', {name:'Close instructor',exact:true}).click();
  expect(errors).toEqual([]);
});


test('private correction pauses practice until explicitly reviewed', async ({page}) => {
  await page.goto(`/reviews/${ids.after}#quiz`);
  const question=page.locator('#saved-quiz .quiz-card:visible');
  await question.getByText('This seems wrong',{exact:true}).click();
  await question.locator('textarea[name="note"]').fill('Check the explanation against this saved source.');
  await question.getByRole('button',{name:'Save private issue',exact:true}).click();
  await expect(question).toContainText('Issue saved privately');
  await page.reload();
  await expect(page.locator('#saved-quiz .quiz-card:visible')).toContainText('paused');
  await page.getByRole('button',{name:'Ask instructor',exact:true}).click();
  await page.getByText(/Private corrections/).click();
  await Promise.all([page.waitForEvent('load'),page.getByRole('button',{name:'Mark reviewed and resolve',exact:true}).click()]);
  await expect(page.locator('#chat')).toBeHidden();
  await page.getByRole('button',{name:'Ask instructor',exact:true}).click();
  await expect(page.locator('#chat')).toBeVisible();
  await page.getByText(/Private corrections/).click();
  await expect(page.locator('#chat')).toContainText('Reviewed');
  await page.getByRole('button',{name:'Close instructor',exact:true}).click();
  await expect(page.locator('#saved-quiz .quiz-card:visible').getByRole('button',{name:'Not sure',exact:true})).toBeEnabled();
});
