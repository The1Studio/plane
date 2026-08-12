# plane-r2-proxy (Cloudflare Worker)

S3-facade in front of the `plane-uploads` R2 bucket. Plane uploads assets with
S3 **POST Object** (presigned multipart form), which Cloudflare R2 does not
implement (returns 501). This Worker accepts that POST and writes to R2 via the
bound bucket, and serves the other S3 verbs Plane uses (GET/HEAD/PUT/DELETE)
off the binding.

## Security
Every request Plane makes is signed with the R2 S3 credentials (SigV4 for
server-side + presigned GET; HMAC policy for POST uploads). Plane's S3 endpoint
is this Worker, so all signatures are computed for the Worker's host. The Worker
holds the same secret (`R2_SECRET_ACCESS_KEY`) and re-computes/compares the
signature; requests without a valid signature get 403.

## Config
- `AWS_S3_ENDPOINT_URL=https://plane-r2-proxy.tuha.workers.dev` in the Plane
  stack's `plane.env`.
- R2 bucket: `plane-uploads` (account Tuha).

## Deploy
```bash
# Worker secret (R2 S3 secret access key) — set once:
CLOUDFLARE_API_TOKEN=<scoped-token> CLOUDFLARE_ACCOUNT_ID=85a94d783d7c8ddf2a098d7e8e11cdef \
  npx wrangler@4 secret put R2_SECRET_ACCESS_KEY

# Deploy:
CLOUDFLARE_API_TOKEN=<scoped-token> CLOUDFLARE_ACCOUNT_ID=85a94d783d7c8ddf2a098d7e8e11cdef \
  npx wrangler@4 deploy
```
The scoped token needs: Workers Scripts:Edit, Workers R2 Storage:Edit/Read,
Account Settings:Read.
