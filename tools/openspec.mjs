import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const args = process.argv.slice(2);
if (args[0] === "progress") {
  const changes = join(root, "openspec", "changes");
  for (const entry of readdirSync(changes, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.name === "archive") continue;
    const tasks = readFileSync(join(changes, entry.name, "tasks.md"), "utf8");
    const done = (tasks.match(/^- \[x\] /gm) || []).length;
    const remaining = (tasks.match(/^- \[ \] /gm) || []).length;
    const blocked = (tasks.match(/^- \[ \] .*\bBLOCKED:/gm) || []).length;
    console.log(`${entry.name}: ${done}/${done + remaining} verified; ${remaining} remaining; ${blocked} blocked`);
  }
} else {
  const result = spawnSync(process.execPath, [join(root, "node_modules", "@fission-ai", "openspec", "bin", "openspec.js"), ...args], {
    cwd: root,
    env: { ...process.env, OPENSPEC_TELEMETRY: "0", OPENSPEC_NO_UPDATE_CHECK: "1" },
    stdio: "inherit",
  });
  process.exit(result.status ?? 1);
}
