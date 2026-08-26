# Phase 5 — First deploy and smoke verification

**Plan:** [`plan.md`](plan.md) · **Depends on:** [Phase 4](phase-4.md)
**Effort:** S (~0.5 day) · **Verification only — no files in this repo change.**

## Goal

Prove the staging stack works, prove production is unharmed, and prove the two are actually
isolated. Every claim below is settled by running a command and reading its output — not by
inspecting a config file and concluding it should work.

## Files owned

None.

## The question every check here must answer

_If the thing this check guards were broken right now, would it go red?_ Two checks in this phase
exist specifically because their naive versions would not:

- Probing `http://localhost/` from the server would return 200 **from production** even if the
  staging stack never started. Every staging health probe below names port 81 explicitly.
- Counting containers proves nothing about volume isolation. The volume check below compares names
  directly, because a staging stack accidentally sharing production's `pgdata` would still show
  the right container count.

## Checklist

### 1. Watch the first staging deploy

The Phase 4 branch push triggers it. Follow it:

```bash
gh run watch "$(gh run list --workflow=deploy-staging.yml --limit=1 --json databaseId --jq '.[0].databaseId')"
```

Expect a long first run — all six images build from scratch, though the local layer cache shared
with production's builds helps where the commits overlap. The 90-minute timeout is the ceiling.

**Verify:** the run concludes `success`, and its log's `==> health:` line reports `web=200 api=200`
and names `http://localhost:81` as the probed base (the Phase 1 change added that).

If it fails, the health-failure branch dumps `migrator api web` logs for the
`plane-staging-app` project — read those before re-running.

### 2. Staging serves, over both paths

```bash
ssh server "curl -s -o /dev/null -w 'local  %{http_code}\n' http://localhost:81/"
ssh server "curl -s -o /dev/null -w 'localapi %{http_code}\n' http://localhost:81/api/instances/"
curl -s -o /dev/null -w 'public %{http_code}\n' -L https://plane-staging.the1studio.org/
```

All three must be `200`. Production is not behind Cloudflare Access (verified 2026-08-26 — it
returns 200 anonymously, with Plane's own login as the gate), and staging matches it, so the public
probe returns Plane's sign-in page rather than a challenge. Read the three together:

| local   | localapi | public          | Meaning                                                       |
| ------- | -------- | --------------- | ------------------------------------------------------------- |
| 200     | 200      | 200             | Correct — stack up, tunnel route works                        |
| 200     | 200      | 502             | Stack fine; the tunnel ingress points at the wrong local port |
| 200     | 200      | DNS fail / 1033 | The public hostname does not exist                            |
| non-200 | —        | —               | The stack itself is down; the route is not the problem        |

### 3. Production is unharmed — the volume-adoption check

This is the highest-impact check in the plan. Phase 1 made the compose project name explicit, and
a wrong value would have orphaned production's database volume.

```bash
curl -s -o /dev/null -w 'prod %{http_code}\n' -L https://plane.the1studio.org/
ssh server 'docker volume ls --format "{{.Name}}" | grep ^plane-fork-app_ | sort'
ssh server 'docker ps --format "{{.Names}}" | grep ^plane-fork-app | sort'
```

Production must return 200, and both listings must match what they were before Phase 1 — compare
against the baseline captured in that phase's success criteria. A **new** volume named
`plane-fork-app_pgdata` alongside an orphaned one, or an empty production database, is the failure
mode this check exists for.

Also confirm production still deploys: re-run `deploy-master.yml` via `workflow_dispatch` and
confirm it goes green with `==> health:` reporting port 80.

### 4. The two stacks are genuinely isolated

```bash
ssh server 'docker compose -p plane-fork-app    ps --format "{{.Name}}" | sort' > /tmp/prod.txt
ssh server 'docker compose -p plane-staging-app ps --format "{{.Name}}" | sort' > /tmp/stag.txt
comm -12 /tmp/prod.txt /tmp/stag.txt        # must be EMPTY

ssh server 'docker volume ls --format "{{.Name}}" | grep ^plane-fork-app_    | sed s/^plane-fork-app_//    | sort' > /tmp/pv.txt
ssh server 'docker volume ls --format "{{.Name}}" | grep ^plane-staging-app_ | sed s/^plane-staging-app_// | sort' > /tmp/sv.txt
diff /tmp/pv.txt /tmp/sv.txt                # same volume ROLES, different prefixes — this is correct
ssh server 'docker volume ls --format "{{.Name}}" | grep -E "^plane-(fork|staging)-app_" | sort | uniq -d'   # must be EMPTY
```

The container-name intersection must be empty. The volume roles being identical is expected and
correct — what matters is that every actual volume name is prefixed by its own project, so no
volume is shared.

Port check:

```bash
ssh server 'ss -ltnp | grep -E ":(80|81|8443|8543)\b"'
```

Four distinct listeners, no overlap.

### 5. Object storage is isolated

Log into `https://plane-staging.the1studio.org`, create a workspace, and attach a file to a work
item. Then:

```bash
ssh server 'docker run --rm -v plane-staging-app_uploads:/x alpine sh -c "find /x -type f | head"'
```

The uploaded file must appear there. Then confirm production's R2 bucket did not receive it —
compare the object count in `plane-uploads` before and after through the R2 dashboard or the
worker proxy. It must be unchanged.

Belt and braces, since this is a data-loss-shaped risk:

```bash
ssh server 'docker compose -p plane-staging-app exec -T api printenv | grep -iE "^AWS_|USE_MINIO"'
```

`USE_MINIO=1`, and no R2 endpoint or production key anywhere in that output.

### 6. Migrations ran from zero

Resolved decision 4 starts staging empty, and the whole point is that this exercises the
from-scratch migration path — the thing a rebase most often breaks.

```bash
ssh server 'docker compose -p plane-staging-app exec -T api python manage.py showmigrations | grep -c "\[ \]"'
```

Must be `0` — no unapplied migrations. Then, matching the repo's own CI gate:

```bash
ssh server 'docker compose -p plane-staging-app exec -T api python manage.py makemigrations --check --dry-run'
```

Must exit 0. A non-zero exit means a model change is missing its migration — the exact failure
`master-ci.yml` exists to catch, now confirmed against a real database.

Confirm `pgvector` is present, since `ai_ext` depends on it and `deploy.sh` patches the image in:

```bash
ssh server 'docker compose -p plane-staging-app exec -T plane-db psql -U plane -d plane -c "SELECT extname FROM pg_extension;"'
```

### 7. The clone script refuses to fire unarmed

```bash
ssh server 'cd /path/to/checkout && bash deployments/selfhost/clone-prod-db-to-staging.sh; echo "exit=$?"'
```

Must print its intent and exit **non-zero**, having run no `docker` command. Do **not** run it with
`--yes-wipe-staging` here — an actual clone is an on-demand operator action, not a plan step, and
running it now would discard the from-zero migration state step 6 just verified.

### 8. PR gates fire on `staging`

Open a throwaway PR against `staging` (a comment-only change is enough) and confirm its status
list shows `master CI`, the api lint, the web lint, and the copyright check. Close it without
merging.

### 9. Record the resource baseline

This is not a pass/fail gate; it is the number future capacity questions get answered against.
Capture it into the Phase 3 README:

```bash
ssh server 'free -g; echo; docker system df; echo; df -h /'
```

Compare against the pre-staging baseline (31G total / 8G used; 105 images / 30.68GB; 256G free).
If available memory has dropped below ~6G, note it and consider stopping the staging stack between
test cycles — that recommendation belongs in the README, not in a code change.

## Success criteria

Every command above produced its stated expected output, and specifically:

1. `deploy-staging.yml` green, health line reporting port 81.
2. `https://plane-staging.the1studio.org/` returns 200 and serves the staging build's sign-in page.
3. `https://plane.the1studio.org/` → 200, production volumes and container names unchanged, and a
   manual `deploy-master.yml` run still green.
4. Container-name intersection between the two projects is empty; four distinct port listeners.
5. A staging upload lands in `plane-staging-app_uploads`; production's `plane-uploads` object count
   unchanged; no R2 credential visible in the staging api container's environment.
6. `showmigrations` shows zero unapplied; `makemigrations --check` exits 0; `vector` extension
   present.
7. The clone script exits non-zero with no flag.
8. A PR into `staging` runs all four gates.

## Out of scope

- Running an actual production→staging data clone.
- Load or performance testing either stack.
- Documentation updates — Phase 6.
