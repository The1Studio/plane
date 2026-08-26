# Phase 2 — Staging deploy workflow + CI gate widening

**Plan:** [`plan.md`](plan.md) · **Depends on:** [Phase 1](phase-1.md) · **Parallel-safe with:** [Phase 3](phase-3.md)
**Effort:** S (~0.5 day)

## Goal

Add a `deploy-staging.yml` workflow that drives the staging stack through the same scripts
production uses, and widen the existing PR gates so work targeting `staging` is checked as
thoroughly as work targeting `master`.

## Files owned

- `.github/workflows/deploy-staging.yml` **(new)**
- `.github/workflows/deploy-master.yml` (one small change — see §3)
- `.github/workflows/master-ci.yml`
- `.github/workflows/pull-request-build-lint-api.yml`
- `.github/workflows/pull-request-build-lint-web-apps.yml`
- `.github/workflows/copyright-check.yml`
- `.github/workflows/codeql.yml`

Do not touch `deployments/selfhost/*` — Phase 1 and Phase 3 own those. Do not touch
`feature-deployment.yml` or `upstream-sync-check.yml`.

## Inherited contract from Phase 1

`deployments/selfhost/deploy.sh` reads exactly these, with these defaults:

| Variable           | Default                  | Meaning                                                        |
| ------------------ | ------------------------ | -------------------------------------------------------------- |
| `RUN_DIR`          | `/opt/plane-fork-app`    | Directory holding `plane.env` + the synced compose file        |
| `IMAGE_TAG`        | `companymain`            | Tag applied to the 6 built images, mirrored into `APP_RELEASE` |
| `HEALTH_HTTP_PORT` | `80`                     | Host port the post-deploy health checks probe                  |
| `COMPOSE_PROJECT`  | `$(basename "$RUN_DIR")` | Explicit `docker compose -p` value                             |

`deployments/selfhost/notify-discord.sh` additionally reads:

| Variable    | Default                        | Meaning                                                  |
| ----------- | ------------------------------ | -------------------------------------------------------- |
| `ENV_LABEL` | `production`                   | Appears in the embed title and as an `Environment` field |
| `SITE_URL`  | `https://plane.the1studio.org` | The `Site` field value                                   |

These names are exact. Do not rename or abbreviate them at the call site.

## Changes

### 1. New `.github/workflows/deploy-staging.yml`

Model it on `deploy-master.yml` — same runner, same script, same Discord step — with these
differences:

**Triggers**

```yaml
on:
  push:
    branches: [staging]
    paths-ignore:
      - "**/*.md"
      - "docs/**"
  workflow_dispatch:
    inputs:
      ref:
        description: "Git ref to deploy to staging (branch, tag, or SHA)"
        required: false
        default: "staging"
```

The `workflow_dispatch` `ref` input is what makes staging useful beyond the merge queue: it lets
an operator deploy a rebase candidate or an arbitrary feature branch without force-pushing
`staging` first. Wire it into the checkout step as
`ref: ${{ github.event.inputs.ref || github.ref }}`.

**Concurrency**

```yaml
concurrency:
  group: deploy-staging
  cancel-in-progress: false
```

A **separate group** from production's `deploy-master`. Sharing a group would let a staging deploy
cancel or queue behind a production one at the workflow level, on top of the runner-level
serialization that already exists. `cancel-in-progress: false` matches production: a deploy that
is halfway through `docker compose up` must never be killed.

**Job**

```yaml
runs-on: [self-hosted, sv-0]
timeout-minutes: 90
```

Same runner and timeout as production. There is only one runner, so jobs serialize — that is
accepted (see the plan's risk table) and needs no workaround here.

**Deploy step env**

```yaml
env:
  RUN_DIR: /opt/plane-staging-app
  IMAGE_TAG: staging
  HEALTH_HTTP_PORT: "8081"
  COMPOSE_PROJECT: plane-staging-app
run: bash deployments/selfhost/deploy.sh
```

`COMPOSE_PROJECT` is passed explicitly even though the basename default would produce the same
value. Being explicit here is the documentation: a reader of this workflow can see which docker
project it drives without deriving it from a path.

**Discord step** — same `if: always()` shape as production, plus:

```yaml
ENV_LABEL: staging
SITE_URL: https://staging-plane.the1studio.org
DISCORD_THREAD_ID: "1524317964160204800"
```

Staging posts into the **same thread as production** (resolved decision 6). The `ENV_LABEL` value
and the `Environment` embed field added in Phase 1 are what tell the two apart, so one thread
carries both without ambiguity. This is a decided value, not a placeholder — do not leave a TODO
marker here.

### 2. Widen the four PR gates and CodeQL to `staging`

Each of these currently filters `branches: ["master"]`. Add `staging` alongside it — add only the
branch name; change nothing else in the `on:` block:

| File                                   | Block to widen                                   |
| -------------------------------------- | ------------------------------------------------ |
| `master-ci.yml`                        | both `push.branches` and `pull_request.branches` |
| `pull-request-build-lint-api.yml`      | `pull_request.branches`                          |
| `pull-request-build-lint-web-apps.yml` | `pull_request.branches`                          |
| `copyright-check.yml`                  | `pull_request.branches`                          |
| `codeql.yml`                           | both `push.branches` and `pull_request.branches` |

> **Do not add a `paths:` filter to `master-ci.yml`.** It has none today, deliberately — its header
> comment cites `ci-cd-trigger-design` §3: a path-filtered required check reports as
> `Expected — Waiting` forever on a PR that skips it, which deadlocks the merge. Widening the
> branch list is safe; adding a path filter is not. `pull-request-build-lint-api.yml` already has
> a `paths: ["apps/api/**"]` filter and keeps it — it is not a required check.

`master-ci.yml`'s job names stay as they are. Renaming the workflow to something environment-neutral
is tempting and is explicitly **out of scope**: the name is what any existing branch-protection
rule on `master` matches against, and renaming it would silently drop that protection.

### 3. `deploy-master.yml` — make the production contract explicit

Add the two new variables to the existing deploy step's `env:` block with their production values,
so both workflows read the same way and neither depends on a default:

```yaml
HEALTH_HTTP_PORT: "80"
COMPOSE_PROJECT: plane-fork-app
```

and to the Discord step:

```yaml
ENV_LABEL: production
SITE_URL: https://plane.the1studio.org
```

These are all identical to the Phase 1 defaults, so behaviour is unchanged. The value is that a
future edit to one workflow can no longer silently diverge from the other through a default nobody
re-reads.

## Success criteria

1. `actionlint .github/workflows/*.yml` passes with no new findings (or, if actionlint is not
   installed, every changed file parses: `python3 -c "import yaml,sys;[yaml.safe_load(open(f)) for f in sys.argv[1:]]" .github/workflows/*.yml`).
2. `deploy-staging.yml` and `deploy-master.yml` differ **only** in: workflow name, trigger branch,
   the `workflow_dispatch.ref` input and its use in checkout, the concurrency group, and the six
   env values (`RUN_DIR`, `IMAGE_TAG`, `HEALTH_HTTP_PORT`, `COMPOSE_PROJECT`, `ENV_LABEL`,
   `SITE_URL`, plus the thread id). Confirm with
   `diff <(sed 's/staging/master/g' .github/workflows/deploy-staging.yml) .github/workflows/deploy-master.yml`
   and read the remaining hunks — anything unexpected is drift, not intent.
3. `grep -c 'staging' .github/workflows/master-ci.yml` ≥ 2 (push and pull_request).
4. `grep -n 'paths:' .github/workflows/master-ci.yml` returns nothing.
5. A PR opened against `staging` (Phase 5 will do this for real) shows `master CI`, the api lint,
   the web lint, and the copyright check in its status list.

## Out of scope

- Creating the `staging` branch itself — Phase 4.
- Branch protection settings on `staging` — decided against (plan decision 8); nothing to configure.
- Any change to `feature-deployment.yml` (upstream's Kubernetes preview path, unrelated) or
  `upstream-sync-check.yml` (a scheduled cron with no branch filter to widen).
