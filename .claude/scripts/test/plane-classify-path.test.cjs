// Unit tests for plane-classify-path — table-driven, zero deps (node:test + node:assert).
// Run: node .claude/scripts/test/plane-classify-path.test.cjs
const test = require("node:test");
const assert = require("node:assert");
const { classify, loadConvention } = require("../plane-classify-path.cjs");

const conv = loadConvention();

const cases = [
  // [path, expectedCategory, expectedTouchPointId]
  // --- all 6 touch-points (each → correct touchPointId) ---
  ["apps/api/plane/settings/common.py", "touch-point", 1],
  ["apps/api/plane/urls.py", "touch-point", 2],
  ["apps/api/plane/celery.py", "touch-point", 3],
  ["apps/api/plane/app/views/external/base.py", "touch-point", 4],
  ["apps/api/requirements/base.txt", "touch-point", 5],
  ["apps/api/Dockerfile.api", "touch-point", 5],
  ["apps/web/app/routes/extended.ts", "touch-point", 6],
  ["apps/web/package.json", "touch-point", 6],
  // --- core (default-deny) ---
  ["apps/api/plane/db/models/issue.py", "core", null],
  // --- never-edit core cases ---
  ["apps/api/plane/db/migrations/0001_initial.py", "core", null],
  ["apps/web/app/routes/core.ts", "core", null],
  // --- @plane/* and other workspace packages are core (not -ext) ---
  ["packages/editor/src/index.ts", "core", null],
  ["packages/ui/src/button.tsx", "core", null],
  // --- custom-app (fork-owned Django apps) ---
  ["apps/api/plane/workload/models.py", "custom-app", null],
  ["apps/api/plane/ai_ext/views.py", "custom-app", null],
  ["apps/api/plane/clickup_migrate/tasks.py", "custom-app", null],
  // --- custom-package (fork frontend packages) ---
  ["packages/workload-ext/src/index.ts", "custom-package", null],
  // --- path-normalization variants resolve identically ---
  ["./apps/api/plane/urls.py", "touch-point", 2],
  ["/apps/api/plane/urls.py", "touch-point", 2],
  // --- custom-infra (fork-created infrastructure: neither app nor package) ---
  ["deployments/selfhost/deploy.sh", "custom-infra", null],
  ["deployments/selfhost/notify-discord.sh", "custom-infra", null],
  ["plans/260822-1102-views-workitem-search/plan.md", "custom-infra", null],
  ["docs/FORK.md", "custom-infra", null],
  [".github/workflows/master-ci.yml", "custom-infra", null],
  [".github/workflows/deploy-master.yml", "custom-infra", null],
  ["./docs/FORK.md", "custom-infra", null], // normalization variant
  // --- the negative half: a too-broad forkPaths prefix would silently grant fork-edit
  //     approval to UPSTREAM files. These four pin the boundary and are the point of the
  //     custom-infra cases above; do not delete them when adding a new forkPaths entry.
  ["deployments/cli/community/docker-compose.yml", "core", null], // only selfhost/ is ours
  [".github/workflows/codeql.yml", "core", null], // upstream workflow
  // --- .claude/ is fork-owned EXCEPT the two files upstream put there ---
  [".claude/scripts/plane-classify-path.cjs", "custom-infra", null],
  [".claude/skills/plane-isolation-audit/SKILL.md", "custom-infra", null],
  [".claude/rules/plane-fork-discipline.md", "custom-infra", null],
  [".claude/skills/_shared/references/fork-convention.md", "custom-infra", null],
  // the carve-out: upstream's own two files must stay core even though .claude/ is whitelisted
  [".claude/skills/pr-description.md", "core", null],
  [".claude/skills/release-notes.md", "core", null],
  ["docs/linting.md", "core", null], // only docs/FORK.md is listed, not all of docs/
  ["docs/FORK.md.bak", "core", null], // exact-match prefix must not match a longer name
  // --- out-of-tree / unknown → core (default-deny) ---
  ["some/random/file.py", "core", null],
];

for (const [p, expectedCat, expectedTp] of cases) {
  test(`${p} → ${expectedCat}${expectedTp ? ` (TP${expectedTp})` : ""}`, () => {
    const r = classify(p, conv);
    assert.strictEqual(r.category, expectedCat, `category for ${p}: ${r.reason}`);
    assert.strictEqual(r.touchPointId, expectedTp, `touchPointId for ${p}`);
  });
}

// db/migrations and @plane both classify core but with the explicit never-edit reason.
test("db/migrations carries the never-edit reason", () => {
  const r = classify("apps/api/plane/db/migrations/0001_initial.py", conv);
  assert.match(r.reason, /never-edit/);
});

test("a fork app that is NOT in forkApps is core (default-deny)", () => {
  // e.g. a core plane app like apps/api/plane/app/ — not a fork app
  const r = classify("apps/api/plane/app/serializers/issue.py", conv);
  assert.strictEqual(r.category, "core");
});
