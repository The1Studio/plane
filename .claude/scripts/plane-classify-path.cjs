#!/usr/bin/env node
// plane-classify-path — deterministic fork path classifier.
//
// Given one or more repo-relative file paths, classify each as:
//   core | touch-point | custom-app | custom-package
// SSOT for "may this file carry a fork edit?" Consumed by plane-isolation-audit
// (leak detection), plane-rebase (conflict classification), plane-fork-doctor (drift).
//
// The convention DATA (touch-points, fork apps, never-edit prefixes) is parsed from the
// first ```json block in skills/_shared/references/fork-convention.md — which mirrors
// docs/FORK.md. There is NO inline convention map here: deleting the JSON block in that
// file changes behavior; deleting code here does not invent a fallback. (code-conventions
// §Data-Driven Over Hardcoded.)
//
// Usage:  node .claude/scripts/plane-classify-path.cjs <path> [<path> ...]
// Output: JSON array, one object per path: { path, category, touchPointId, reason }
// Exit:   0 always (classification is a fact, not a verdict; the caller sets policy).

const fs = require("node:fs");
const path = require("node:path");

const CONVENTION_MD = path.join(__dirname, "..", "skills", "_shared", "references", "fork-convention.md");

function loadConvention() {
  let md;
  try {
    md = fs.readFileSync(CONVENTION_MD, "utf8");
  } catch (e) {
    throw new Error(`cannot read fork-convention.md (SSOT) at ${CONVENTION_MD}: ${e.message}`, { cause: e });
  }
  const m = md.match(/```json\s*([\s\S]*?)```/);
  if (!m) {
    throw new Error("fork-convention.md is missing its ```json convention block (SSOT for the classifier)");
  }
  let data;
  try {
    data = JSON.parse(m[1]);
  } catch (e) {
    throw new Error(`fork-convention.md json block is invalid: ${e.message}`, { cause: e });
  }
  for (const key of ["touchPoints", "forkApps", "forkAppRoot", "forkPackageRoot", "forkPackageSuffix", "forkPaths"]) {
    if (!(key in data)) throw new Error(`fork-convention.md json block missing "${key}"`);
  }
  return data;
}

// Normalize to a repo-relative POSIX path: strip leading "./" and "/", collapse "\".
function normalize(p) {
  return String(p)
    .replace(/\\/g, "/")
    .replace(/^\.?\//, "")
    .replace(/^\/+/, "");
}

function classify(rawPath, conv) {
  const p = normalize(rawPath);

  // 1. touch-point — exact match of an SSOT path (most specific).
  for (const tp of conv.touchPoints) {
    if (tp.paths.map(normalize).includes(p)) {
      return {
        path: rawPath,
        category: "touch-point",
        touchPointId: tp.id,
        reason: `matches touch-point ${tp.id} (${p}) — fork edits allowed, append-only`,
      };
    }
  }

  const parts = p.split("/");

  // 2. custom-package — packages/<name>-ext/...  (fork frontend package convention).
  const pkgRoot = normalize(conv.forkPackageRoot).replace(/\/$/, "");
  if (parts[0] === pkgRoot && parts[1] && parts[1].endsWith(conv.forkPackageSuffix)) {
    return {
      path: rawPath,
      category: "custom-package",
      touchPointId: null,
      reason: `under ${pkgRoot}/${parts[1]} — fork frontend package`,
    };
  }

  // 3. custom-app — apps/api/plane/<app>/... where <app> is a fork-owned app.
  const appRoot = normalize(conv.forkAppRoot).replace(/\/$/, "").split("/"); // [apps,api,plane]
  const underAppRoot = appRoot.every((seg, i) => parts[i] === seg);
  if (underAppRoot) {
    const appName = parts[appRoot.length];
    if (appName && conv.forkApps.includes(appName)) {
      return {
        path: rawPath,
        category: "custom-app",
        touchPointId: null,
        reason: `under ${conv.forkAppRoot}${appName}/ — fork-owned Django app`,
      };
    }
  }

  // 3.5 custom-infra — a path the fork CREATED outright that is neither a Django app nor a
  // frontend package: deploy scripts, the fork's own CI workflows, the plan archive, and
  // docs/FORK.md itself. Without this the default-deny below called them "core — fork edits
  // forbidden", which was wrong and self-contradictory (it said that about the document defining
  // the convention), and made plane-isolation-audit report legitimate edits as violations.
  //
  // A prefix ending in "/" matches the directory and everything under it; one without a trailing
  // slash must match EXACTLY, so a single file can be listed without also capturing siblings that
  // merely share its name as a prefix ("docs/FORK.md" must not match "docs/FORK.md.bak"). Runs
  // after custom-app so touch-points and app/package rules keep priority, and before core so it
  // can override the default-deny.
  // forkPathExceptions are UPSTREAM files that live inside an otherwise fork-owned directory and
  // must keep classifying as core. `.claude/` is the case this exists for: upstream created it
  // (f1d567accc) with exactly two flat .md files, and every subdirectory beneath it since is
  // fork-authored — so the directory is whitelisted and those two files are carved back out.
  // Optional, mirroring how `neverEdit` is read below.
  const isUpstreamException = (conv.forkPathExceptions || []).map(normalize).includes(p);
  if (!isUpstreamException) {
    for (const raw of conv.forkPaths) {
      const prefix = normalize(raw);
      const isDir = prefix.endsWith("/");
      if (isDir ? p.startsWith(prefix) : p === prefix) {
        return {
          path: rawPath,
          category: "custom-infra",
          touchPointId: null,
          reason: `${isDir ? "under" : "is"} ${prefix} — fork-owned infrastructure`,
        };
      }
    }
  }

  // 4. core (default-deny) — everything else, incl. db/migrations, @plane/* packages, routes/core.ts.
  // A path traversal (../) is intentionally treated as core (default-deny), never rejected — the
  // classifier is advisory and never grants write, so unknown ⇒ core is the safe answer.
  const neverEdit = (conv.neverEdit || []).map(normalize);
  const hit = neverEdit.find((prefix) => p === prefix || p.startsWith(prefix));
  // Any non-"-ext" package under the workspace package root is an @plane/* core package
  // (the "-ext" fork packages were already returned as custom-package in step 2).
  const isWorkspacePkg = parts[0] === pkgRoot;
  let reason;
  if (hit) {
    reason = `never-edit core path (matches "${hit}") — relocate to a new app/package`;
  } else if (isWorkspacePkg) {
    reason = `@plane/* workspace package (not a "${conv.forkPackageSuffix}" fork package) — never edit in place, relocate`;
  } else {
    reason = "core file (not a touch-point / fork app / fork package) — fork edits forbidden, relocate";
  }
  return { path: rawPath, category: "core", touchPointId: null, reason };
}

function main(argv) {
  const inputs = argv.slice(2);
  if (inputs.length === 0) {
    process.stderr.write("Usage: node .claude/scripts/plane-classify-path.cjs <path> [<path> ...]\n");
    process.exit(2);
  }
  const conv = loadConvention();
  const out = inputs.map((p) => classify(p, conv));
  process.stdout.write(JSON.stringify(out, null, 2) + "\n");
  process.exit(0);
}

if (require.main === module) {
  main(process.argv);
}

module.exports = { classify, loadConvention, normalize };
