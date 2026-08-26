# Phase 4 — Server, Cloudflare, and GitHub provisioning

**Plan:** [`plan.md`](plan.md) · **Depends on:** [Phase 2](phase-2.md), [Phase 3](phase-3.md)
**Effort:** S (~0.5 day) · **Operator-driven — no files in this repo change.**

## Goal

Create everything the staging stack needs that cannot live in git: the run directory and its
secrets on `server`, the Cloudflare tunnel ingress rule, and the `staging` branch on GitHub.

## Files owned

None. Every action here is on `server`, in the Cloudflare dashboard, or in GitHub settings. If you
find yourself editing a repo file during this phase, it belongs to Phase 2, 3, or 6.

## Why some of this cannot be automated

The cloudflared tunnel on `server` runs as
`cloudflared --no-autoupdate tunnel run --token eyJ…` — a **token-managed** tunnel. Its ingress
rules live in the Cloudflare Zero Trust dashboard, not in a config file: `/etc/cloudflared` does
not exist on the host. There is no file in this repo, and no command on the server, that can add
the hostname. It is a dashboard action, and the plan treats it as an explicit checklist item with
its own verification rather than pretending it is scriptable.

## Checklist

Work top to bottom; each step's verification must pass before the next.

### 1. Create the staging run directory

```bash
ssh server 'sudo mkdir -p /opt/plane-staging-app && sudo chown "$(id -u -n)":"$(id -g -n)" /opt/plane-staging-app'
```

Ownership must let the runner user write — the same user that owns `/opt/plane-fork-app`. Confirm
with `ssh server 'ls -ld /opt/plane-fork-app /opt/plane-staging-app'` and match the owner column.

**Verify:** the directory exists and is writable by the runner user.

### 2. Create `/opt/plane-staging-app/plane.env`

Copy `deployments/selfhost/plane.env.staging.example` (Phase 3) to the server and fill it in.

**Generate every secret fresh.** `SECRET_KEY`, `LIVE_SERVER_SECRET_KEY`, `POSTGRES_PASSWORD`,
`RABBITMQ_PASSWORD`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` must not be copied from
production — a shared `SECRET_KEY` means a session token minted in staging validates in
production. Use `openssl rand -hex 32` per value.

**Do not add any `AWS_S3_ENDPOINT_URL` or R2 credential.** Their absence is what makes it
structurally impossible for staging to write into production's `plane-uploads` bucket.

**Verify:**

```bash
ssh server 'grep -c . /opt/plane-staging-app/plane.env'                      # non-zero
ssh server 'grep -E "^(APP_DOMAIN|LISTEN_HTTP_PORT|USE_MINIO|APP_RELEASE)=" /opt/plane-staging-app/plane.env'
# expect: plane-staging.the1studio.org / 81 / 1 / staging
ssh server 'grep -iE "r2|workers\.dev|plane-uploads" /opt/plane-staging-app/plane.env'   # must be EMPTY
```

Cross-check that no secret matches production:

```bash
ssh server 'for k in SECRET_KEY LIVE_SERVER_SECRET_KEY POSTGRES_PASSWORD RABBITMQ_PASSWORD; do
  a=$(grep "^$k=" /opt/plane-fork-app/plane.env    | md5sum | cut -c1-8)
  b=$(grep "^$k=" /opt/plane-staging-app/plane.env | md5sum | cut -c1-8)
  [ "$a" = "$b" ] && echo "SHARED SECRET: $k" || echo "ok: $k"
done'
```

Every line must read `ok:`. (This compares hashes, so no secret value is printed.)

### 3. Confirm the ports are still free

They were verified free on 2026-08-26, but something may have claimed them since:

```bash
ssh server 'for p in 81 8543; do ss -ltn "sport = :$p" | grep -q LISTEN && echo "$p TAKEN" || echo "$p free"; done'
```

Both must read `free`. If either is taken, pick from the other verified-free ports (`8100`,
`8180`, `9080`, `8444`) and update **three** places in lockstep: `plane.env` on the server,
`HEALTH_HTTP_PORT` in `deploy-staging.yml`, and the Cloudflare ingress rule in step 4. A port
changed in only two of the three produces a green deploy behind an unreachable hostname.

### 4. Add the Cloudflare tunnel ingress rule

In the Cloudflare Zero Trust dashboard → Networks → Tunnels → the tunnel currently serving
`plane.the1studio.org` → Public Hostnames → **Add a public hostname**:

- **Subdomain:** `staging-plane`
- **Domain:** `the1studio.org`
- **Service:** `HTTP` → `localhost:81`

Do not use HTTPS as the service type: Caddy inside the staging proxy listens plain HTTP on the
container's port 80 (`SITE_ADDRESS=:80`), exactly as production does. Cloudflare terminates TLS at
its edge.

**No Cloudflare Access policy** — resolved decision 7, corrected. Production has none: verified
2026-08-26, `https://plane.the1studio.org/` returns 200 to an anonymous request with no CF-Access
headers, so Plane's own login is the only gate there. Staging matches it. Do not attach a policy
here unless you also decide to change production, which is out of scope for this work.

**Verify the route with one probe:**

```bash
curl -s -o /dev/null -w '%{http_code}\n' -L https://plane-staging.the1studio.org/
```

| Result                 | Meaning                                                                                 |
| ---------------------- | --------------------------------------------------------------------------------------- |
| **502**                | Correct **before** Phase 5 — the tunnel reaches the server, nothing listening on 81 yet |
| **200**                | Correct **after** Phase 5 — Plane's own sign-in page, same as production                |
| **1033 / DNS failure** | The public hostname was never created                                                   |
| **404 / wrong app**    | The ingress rule points at the wrong local port                                         |

### 5. Create the `staging` branch

```bash
git checkout master && git pull --ff-only
git checkout -b staging
git push -u origin staging
```

This first push **will** trigger `deploy-staging.yml`, which is intended — it is Phase 5's first
deploy. Do not create the branch until Phases 2 and 3 have merged to `master`, or the workflow
that would run does not exist yet on the branch.

**Verify:** `gh api repos/The1Studio/plane/branches/staging --jq .name` returns `staging`.

### 6. Discord thread — nothing to do

Resolved decision 6 sends staging notifications to the **same thread as production**
(`1524317964160204800`), and Phase 2 already wrote that literal into `deploy-staging.yml`. There is
no placeholder to fill and no `TODO` marker to clear.

**Verify:** `grep -n 'TODO' .github/workflows/deploy-staging.yml` returns nothing, and the
`DISCORD_THREAD_ID` value matches production's.

### 7. Branch protection on `staging` — deliberately none

Resolved decision 8: `staging` gets **no branch protection**. It is disposable by design and is
force-pushed after every upstream rebase, which protection would fight. PRs into `staging` still
run all four CI gates (Phase 2 widened them), so the checks are present either way — protection
would only add friction to the reset, not coverage.

**Verify** that nothing was inherited from an org-level ruleset:

```bash
gh api repos/The1Studio/plane/branches/staging --jq .protected    # expect: false
git push --force-with-lease origin staging --dry-run              # must not be rejected
```

If `protected` reports `true`, an organization ruleset is matching the branch — either exclude
`staging` from it or confirm force-push is permitted, or the post-rebase reset in
`docs/FORK.md` step 9 will be blocked.

## Success criteria

1. `/opt/plane-staging-app/plane.env` exists, is runner-writable, contains the staging values, and
   shares no secret with production (verified by the hash comparison in step 2).
2. Ports 81 and 8543 are free immediately before the first deploy.
3. The Cloudflare public hostname `plane-staging.the1studio.org` exists and points at
   `http://localhost:81`.
4. Branch `staging` exists on the origin remote.
5. `plane-staging.the1studio.org` routes through the tunnel (502 before deploy, 200 after), and
   `gh api repos/The1Studio/plane/branches/staging --jq .protected` returns `false`.
6. **Production is untouched:** `curl -s -o /dev/null -w '%{http_code}' https://plane.the1studio.org/`
   still returns 200, and `ssh server 'docker volume ls --format "{{.Name}}" | grep -c ^plane-fork-app_'`
   returns the same count as before this phase.

## Out of scope

- The first deploy and its smoke test — Phase 5.
- Documentation of any of this in `docs/FORK.md` — Phase 6.
- Adding a second GitHub Actions runner.
