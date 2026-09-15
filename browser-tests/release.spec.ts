import { expect, test, type Page } from "@playwright/test";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawn, type ChildProcess } from "node:child_process";

let server: ChildProcess;
let root: string;
let dataDir: string;
let projectDir: string;

async function waitForServer(): Promise<void> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const response = await fetch("http://127.0.0.1:8878/api/health");
      if (response.ok) return;
    } catch {}
    await new Promise(resolveWait => setTimeout(resolveWait, 100));
  }
  throw new Error("Architecture Coach test server did not start");
}

async function csrf(page: Page): Promise<string> {
  return (await page.locator('meta[name="archcoach-token"]').getAttribute("content")) || "";
}

async function waitForJob(page: Page): Promise<void> {
  await expect(page.getByRole("link", { name: /Open review|Return to conversation/ })).toBeVisible({ timeout: 60_000 });
  await page.getByRole("link", { name: /Open review|Return to conversation/ }).click();
}

async function configureFakeCodex(page: Page): Promise<void> {
  await page.goto("/settings");
  await page.getByLabel("Codex executable").fill(resolve("tests/fixtures/fake_codex.py"));
  await page.getByLabel("Reasoning effort").selectOption("high");
  await page.getByRole("button", { name: "Save analysis settings" }).click();
  await expect(page.getByText("Project settings saved")).toBeVisible();
}

test.beforeAll(async () => {
  root = mkdtempSync(join(tmpdir(), "archcoach-browser-"));
  dataDir = join(root, "private data");
  projectDir = join(root, "project with spaces");
  mkdirSync(projectDir, { recursive: true });
  writeFileSync(join(projectDir, "main.py"), "def greet(): return 'hello'\n", "utf8");
  server = spawn(
    "python",
    ["-m", "archcoach.cli", "--data-dir", dataDir, "serve", "--port", "8878", "--no-browser"],
    { cwd: resolve("."), env: { ...process.env, PYTHONPATH: resolve("src") }, stdio: "pipe", windowsHide: true },
  );
  await waitForServer();
});

test.afterAll(async () => {
  try {
    const response = await fetch("http://127.0.0.1:8878/");
    const html = await response.text();
    const token = html.match(/name="archcoach-token" content="([^"]+)"/)?.[1];
    if (token) await fetch("http://127.0.0.1:8878/exit", { method: "POST", headers: { "X-ArchCoach-Token": token } });
  } catch {}
  if (server && server.exitCode === null) {
    await Promise.race([
      new Promise<void>(resolveExit => server.once("exit", () => resolveExit())),
      new Promise<void>(resolveWait => setTimeout(resolveWait, 5_000)),
    ]);
  }
  if (server && server.exitCode === null) {
    server.kill();
    await Promise.race([
      new Promise<void>(resolveExit => server.once("exit", () => resolveExit())),
      new Promise<void>(resolveWait => setTimeout(resolveWait, 5_000)),
    ]);
  }
  try {
    rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
  } catch {
    // Edge can briefly retain a generated HTML handle while its context closes.
    // The directory contains synthetic fixtures only and the OS temp cleaner can remove it later.
  }
});

test("project review, lesson, chat, settings, and comparison use saved evidence", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Add a project" }).first().click();
  await page.getByLabel("Local project folder").fill(projectDir);
  await page.getByLabel("Project name").fill("Browser fixture");
  await page.getByLabel("What does it do?").fill("Exercises the browser acceptance flow.");
  await page.getByRole("button", { name: "Add project" }).click();
  await expect(page.getByRole("heading", { name: "Browser fixture" })).toBeVisible();

  await configureFakeCodex(page);

  await page.getByRole("link", { name: "Projects" }).click();
  await page.locator(".project-card", { hasText: "Browser fixture" }).click();
  await page.getByRole("button", { name: "Review current files" }).click();
  await waitForJob(page);
  await expect(page.getByRole("heading", { name: /synthetic service/ })).toBeVisible();
  await expect(page.getByText("The entry point is short")).toBeVisible();
  await expect(page.getByRole("link", { name: "main.py:1" }).first()).toBeVisible();
  await page.getByLabel("Progress for Cohesion").selectOption("understood");
  await expect(page.locator("#toast")).toContainText("Lesson progress saved");

  await page.locator("#chat textarea").fill("Who owns the greeting?");
  await page.getByRole("button", { name: "Ask the coach" }).click();
  await waitForJob(page);
  await expect(page.getByText("The saved entry point owns the current greeting behavior.")).toBeVisible();

  writeFileSync(join(projectDir, "helper.py"), "def greet(): return 'hello'\n", "utf8");
  writeFileSync(join(projectDir, "main.py"), "from helper import greet\nprint(greet())\n", "utf8");
  await page.reload();
  await expect(page.locator("#current-file-status")).toContainText("Files changed since this review");
  await page.getByRole("link", { name: /Browser fixture/ }).first().click();
  await page.getByRole("button", { name: "Review current files" }).click();
  await waitForJob(page);
  await expect(page.getByText("Helper", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: /Browser fixture/ }).first().click();
  await page.getByRole("link", { name: "Compare reviews" }).click();
  await expect(page.getByText("helper", { exact: true })).toBeVisible();
});

test("a running review can be cancelled without publishing a review", async ({ page }) => {
  const stalledDir = join(root, "stalled fixture");
  mkdirSync(stalledDir, { recursive: true });
  writeFileSync(join(stalledDir, "main.py"), "# FIXTURE_STALL\nprint('wait')\n", "utf8");
  await configureFakeCodex(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Add a project" }).first().click();
  await page.getByLabel("Local project folder").fill(stalledDir);
  await page.getByLabel("Project name").fill("Cancellation fixture");
  await page.getByRole("button", { name: "Add project" }).click();
  await page.getByRole("button", { name: "Review current files" }).click();
  await expect(page.getByRole("button", { name: "Cancel" })).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByText("The job was cancelled.")).toBeVisible({ timeout: 30_000 });
  await page.getByRole("link", { name: "Back to projects" }).click();
  await page.locator(".project-card", { hasText: "Cancellation fixture" }).click();
  await expect(page.getByText("Your first review is ready to run")).toBeVisible();
});

test("malformed AI output leaves an explicit limited review", async ({ page }) => {
  const invalidDir = join(root, "invalid fixture");
  mkdirSync(invalidDir, { recursive: true });
  writeFileSync(join(invalidDir, "main.py"), "# FIXTURE_INVALID\nprint('fallback')\n", "utf8");
  await configureFakeCodex(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Add a project" }).first().click();
  await page.getByLabel("Local project folder").fill(invalidDir);
  await page.getByLabel("Project name").fill("Invalid output fixture");
  await page.getByRole("button", { name: "Add project" }).click();
  await page.getByRole("button", { name: "Review current files" }).click();
  await waitForJob(page);
  await expect(page.getByText(/limited/).first()).toBeVisible();
  await expect(page.getByText(/Architecture analysis used the deterministic fallback/)).toBeVisible();
});
