import { test, expect } from '@playwright/test';
import { spawn, type ChildProcess } from 'node:child_process';
import { existsSync, mkdtempSync, mkdirSync, openSync, closeSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { createServer } from 'node:net';

let server: ChildProcess;
let logs: number[] = [];
let ids: {project: string; before: string; after: string};

test.beforeAll(async () => {
  // Refuse an occupied port before creating the task-owned server.
  await new Promise<void>((done, reject) => {
    const probe = createServer(); probe.once('error', reject);
    probe.listen(8878, '127.0.0.1', () => probe.close(() => done()));
  });
  mkdirSync('.test-data', {recursive: true});
  const root = mkdtempSync(resolve('.test-data/learning-browser-'));
  logs = [openSync(join(root, 'stdout.log'), 'w'), openSync(join(root, 'stderr.log'), 'w')];
  const localPython = resolve('.venv/Scripts/python.exe');
  server = spawn(existsSync(localPython) ? localPython : 'python', ['-m', 'tests.fixtures.learning_profile', root], {
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

test('saved teaching, cross-module map, recall and change lesson', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto(`/reviews/${ids.before}`);
  await expect(page.getByRole('heading', {name:'Follow the validation boundary'})).toBeVisible();
  await expect(page.locator('.quiz-card')).toHaveCount(10);
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
  await page.getByRole('button', {name:'Ask instructor',exact:true}).click();
  const area = page.locator('#chat textarea');
  await area.fill('Keep this draft');
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
