---
name: plane-rebrand
description: White-label a self-hosted Plane deployment: browser-tab title (build-time), instance name, workspace name/slug. Use for "rebrand plane", "white-label plane", "set instance name".
keywords: [rebrand, white-label, brand, vite-app-title, instance-name, workspace, plane-deploy]
metadata:
  author: the1studio
  version: "1.0.0"
---

# plane-rebrand

White-label a self-hosted Plane deployment to a given brand across its three independent
surfaces: the browser-tab/PWA title (build-time), the God-mode instance name (DB), and the
workspace name/slug (DB, opt-in). Repeatable per brand — the brand table below is the only
thing that grows when a new brand is added.

**Code seam (SSOT, do not re-edit):** `docs/FORK.md` touch-point 7 — `VITE_APP_TITLE` is already
wired into `apps/web/app/root.tsx`, `apps/admin/app/root.tsx`, `apps/web/Dockerfile.web`,
`apps/admin/Dockerfile.admin`. This skill sets the **value**, never the code.
**Deploy repo:** `/mnt/Work/1M/15. Plane/plane-deploy` — owns the env templates and compose
`build.args` that carry the value in; owns the rebuild.

---

## When to Use

Invoke this skill when the user wants to:

- Rebrand a self-hosted Plane instance for a new or existing brand
- Change the browser-tab title of a running Plane deployment
- Set or update the God-mode instance name
- Rename a workspace's display name (and, explicitly, its slug)

Do NOT use this skill to:

- Edit `apps/web/app/root.tsx`, `apps/admin/app/root.tsx`, or either `Dockerfile.*` — touch-point 7
  is already wired; re-editing it is a redundant fork edit (see `docs/FORK.md`)
- Add a new endpoint or field — a pure rebrand has no MCP/SDK propagation obligation (CLAUDE.md
  "STANDING RULE" only fires on new endpoints/fields/behavior; renaming a title/name is neither)

---

## Activation

Trigger phrases (any of these should activate this skill):

- "rebrand plane"
- "white-label plane"
- "change plane title to X"
- "set instance name"
- "rename the plane workspace"

---

## Brand Table (data-driven — add a brand by adding one row)

| Brand key          | `VITE_APP_TITLE`      | Instance name         |
| ------------------ | --------------------- | --------------------- |
| `theonegamestudio` | `The One Game Studio` | `The One Game Studio` |
| `playablelabs`     | `PlayableLabs`        | `PlayableLabs`        |

```json
{
  "brands": {
    "theonegamestudio": { "viteAppTitle": "The One Game Studio", "instanceName": "The One Game Studio" },
    "playablelabs": { "viteAppTitle": "PlayableLabs", "instanceName": "PlayableLabs" }
  }
}
```

A brand not yet in this table is fine — ask the user for the two values (title, instance name)
via `AskUserQuestion` and, once confirmed, append a row here so the next rebrand is a table
lookup instead of a fresh interview.

---

## Decision Tree

### Step 1 — HARD-GATE: confirm brand + surfaces

**See `<HARD-GATE>` block below. Do NOT edit any file or run any SQL before this passes.**

Ask via `AskUserQuestion`:

1. Which brand? (pick from the Brand Table, or supply a new key + `VITE_APP_TITLE` + instance
   name to add)
2. Which surfaces to change — any combination of:
   - Browser-tab/PWA title only
   - - Instance name (God-mode)
   - - Workspace display name (`workspaces.name`)
   - - Workspace slug (`workspaces.slug`) — **destructive, opt-in only, see Gotchas**
3. Which deploy profile — local (`plane-deploy/env/.env.local.example`, rebuilds against
   `http://localhost:20080`) or prod (`plane-deploy/env/.env.prod.example`)?

### Step 2 — Set `VITE_APP_TITLE` in `plane-deploy`

Edit the env **template** for the chosen profile in the sibling repo
(`/mnt/Work/1M/15. Plane/plane-deploy`):

```bash
# local profile
plane-deploy/env/.env.local.example   # VITE_APP_TITLE="<brand title>"
# prod profile
plane-deploy/env/.env.prod.example    # VITE_APP_TITLE="<brand title>"
```

**If the fork's `.env` has already been rendered** (`FORK_DIR/.env` exists — for local that's
this repo's own root `.env`; for prod it's `/opt/plane/.env`), edit the `VITE_APP_TITLE=` line
in that rendered file **directly** too. Do NOT run `deploy.sh --render-env` just for this — that
flag re-renders from the template and **rotates every secret** in the file, which is unrelated
blast radius for a title change.

This is an edit inside the `plane-deploy` sibling repo's own working tree — commit/push it there
separately; it is not part of this repo's history.

### Step 3 — Rebuild web + admin

```bash
cd "/mnt/Work/1M/15. Plane/plane-deploy" && ./scripts/deploy.sh --local   # local profile
# or, for prod:
cd "/mnt/Work/1M/15. Plane/plane-deploy" && ./scripts/deploy.sh          # prod profile
```

Default behavior rebuilds images (do not pass `--no-build` — that reuses the cached image, which
still has the OLD title baked in). This is the only step that actually changes what a browser
tab shows.

### Step 4 — DB updates (only the surfaces confirmed in Step 1)

**Instance name:**

```bash
docker exec plane-db psql -U plane -d plane -c \
  "UPDATE instances SET instance_name='<brand instance name>';"
```

(Equivalently settable in the God-mode admin UI.)

**Workspace display name** (only if confirmed):

```bash
docker exec plane-db psql -U plane -d plane -c "SELECT id, name, slug FROM workspaces;"
# then, targeted:
docker exec plane-db psql -U plane -d plane -c \
  "UPDATE workspaces SET name='<brand workspace name>' WHERE id='<id>';"
```

**Workspace slug** — only if the user explicitly confirmed this in Step 1's HARD-GATE (see the
nested slug gate below). Same `UPDATE` pattern on the `slug` column.

### Step 5 — Verify

- Local: open `http://localhost:20080` and confirm the browser tab shows the new title.
- Prod: open the deployed FQDN and confirm the browser tab title.
- `docker exec plane-db psql -U plane -d plane -c "SELECT instance_name FROM instances;"` returns
  the new brand instance name.
- If workspace name/slug changed:
  `docker exec plane-db psql -U plane -d plane -c "SELECT id, name, slug FROM workspaces;"`
  reflects the change.

---

<HARD-GATE>
## HARD-GATE — Before any file edit or SQL write

**Cite:** `rules/workflow-gates.md` (universal contract).

**Condition:** the skill MUST NOT edit `plane-deploy` env files, run `deploy.sh`, or run any
`docker exec plane-db psql` write before `AskUserQuestion` has confirmed: brand, which of the
four surfaces (title / instance name / workspace name / workspace slug), and deploy profile
(local / prod).

**Override:** explicit user confirmation to the `AskUserQuestion` prompt. No other override —
not a flag, not "the brand table default is obviously fine."

**Nested gate — workspace slug only:** if (and only if) the user asks to change the workspace
**slug**, a SECOND, separate `AskUserQuestion` confirmation is required before the `UPDATE
workspaces SET slug=...` runs. Present the destructive-change list first (see Gotchas — every
surface that breaks) and require an explicit "yes, break the old slug" style confirmation. The
default answer when unclear is **do not touch the slug** — only `name` changes.
</HARD-GATE>

---

## Gotchas

- **Title is BUILD-TIME, not runtime.** `VITE_APP_TITLE` is a Docker build ARG baked into the
  static JS bundle at `docker build` time (touch-point 7). Restarting the `web`/`admin`
  containers without rebuilding (`docker compose restart`, or `deploy.sh --no-build`) will NOT
  pick up a new title — you must rebuild.
- **Slug change is destructive.** `workspaces.slug` is embedded in every workspace URL, API path,
  browser bookmark, and any external config that hardcodes the slug — notably
  `plane-mcp-server`'s workspace config and any `plane-node-sdk`/`plane-python-sdk` example
  scripts. Changing it breaks all of those until updated. Default: leave the slug alone; only
  change `workspaces.name` unless the user explicitly asked for the slug.
- **Empty `VITE_APP_TITLE`** falls back to the upstream Plane default title — this is the
  intended "no white-label" state, not a bug.
- **Don't re-edit the code seam.** `root.tsx` / `Dockerfile.web` / `Dockerfile.admin` already
  consume `VITE_APP_TITLE` (touch-point 7 in `docs/FORK.md`). This skill only ever changes the
  _value_ in `plane-deploy`'s env files — editing the consuming code again would be a redundant,
  unreviewable fork edit.
- **`--render-env` rotates secrets.** Never force a full env re-render just to change one value;
  edit the already-rendered `.env` directly (Step 2).
- **No propagation needed.** Per the project `CLAUDE.md` standing rule, propagation to
  `plane-mcp-server` / SDKs / docs is required for new endpoints, fields, or behavior — a pure
  rebrand (title/instance-name/workspace-name) is none of those. Skip `plane-propagate` for this
  work unless the slug change requires updating sibling-repo config (see above), which is a
  manual follow-up in those repos, not a propagation issue to file.

---

## Verify

After completing all steps, confirm:

- [ ] HARD-GATE was satisfied: brand + surfaces + profile confirmed via `AskUserQuestion` before
      any edit
- [ ] If slug change was requested: the nested slug HARD-GATE was separately confirmed
- [ ] `plane-deploy/env/.env.<profile>.example` has the new `VITE_APP_TITLE`
- [ ] The rendered `.env` (if it existed) was edited directly — no `--render-env` was run
- [ ] `deploy.sh` rebuilt (not `--no-build`) web + admin
- [ ] Browser tab title confirmed changed at the deployment URL
- [ ] `SELECT instance_name FROM instances` returns the new brand name
- [ ] If workspace name/slug changed: `SELECT id, name, slug FROM workspaces` reflects it
- [ ] `root.tsx` / `Dockerfile.web` / `Dockerfile.admin` were NOT touched (value-only change)
