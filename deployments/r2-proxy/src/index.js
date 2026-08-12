// S3-facade proxy for Plane -> Cloudflare R2 (bucket "plane-uploads").
//
// Why: Plane uploads via S3 "POST Object" (multipart form), which R2 does NOT
// implement (501). This Worker accepts that POST and writes to R2 via the bound
// bucket, and serves the other S3 verbs Plane uses (GET/HEAD/PUT/DELETE) off the
// binding.
//
// Security: every request Plane sends is signed with the R2 S3 credentials
// (AWS SigV4 for server-side + presigned GET, HMAC policy for POST uploads).
// Because Plane's S3 endpoint is THIS worker, all signatures are computed for
// this worker's host, so the worker — holding the same secret (R2_SECRET_ACCESS_KEY)
// — re-computes and compares them. Requests without a valid signature get 403.
// Secrets: R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY (wrangler secrets). Region "auto".

const REGION = "auto";
const SERVICE = "s3";
const ALLOW_ORIGIN = "https://plane.the1studio.org";

const CORS = {
  "Access-Control-Allow-Origin": ALLOW_ORIGIN,
  "Access-Control-Allow-Methods": "GET,PUT,POST,HEAD,DELETE,OPTIONS",
  "Access-Control-Allow-Headers": "*",
  "Access-Control-Expose-Headers": "ETag,Content-Length,Content-Type",
  "Access-Control-Max-Age": "3600",
  "Vary": "Origin",
};
const withCors = (h = {}) => ({ ...CORS, ...h });

const enc = new TextEncoder();
const toHex = (buf) =>
  [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");

async function sha256Hex(data) {
  const buf = await crypto.subtle.digest("SHA-256", typeof data === "string" ? enc.encode(data) : data);
  return toHex(buf);
}
async function hmac(keyBytes, msg) {
  const key = await crypto.subtle.importKey("raw", keyBytes, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(msg)));
}
async function signingKey(secret, dateStamp) {
  const kDate = await hmac(enc.encode("AWS4" + secret), dateStamp);
  const kRegion = await hmac(kDate, REGION);
  const kService = await hmac(kRegion, SERVICE);
  return hmac(kService, "aws4_request");
}
// constant-time-ish compare
function safeEq(a, b) {
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}
function deny(msg) {
  return new Response(msg || "Forbidden", { status: 403, headers: withCors() });
}

// Canonical query string with one param removed, sorted, RFC3986-encoded.
function canonicalQuery(url, omit) {
  const parts = [];
  for (const [k, v] of url.searchParams) {
    if (k === omit) continue;
    parts.push([encodeRfc3986(k), encodeRfc3986(v)]);
  }
  parts.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  return parts.map(([k, v]) => `${k}=${v}`).join("&");
}
function encodeRfc3986(s) {
  return encodeURIComponent(s).replace(/[!'()*]/g, (c) => "%" + c.charCodeAt(0).toString(16).toUpperCase());
}

// Validate a presigned (query-string) SigV4 GET/HEAD request.
async function validateQuerySig(url, method, host, secret) {
  const q = url.searchParams;
  const algo = q.get("X-Amz-Algorithm");
  const cred = q.get("X-Amz-Credential");
  const amzDate = q.get("X-Amz-Date");
  const expires = q.get("X-Amz-Expires");
  const signedHeaders = q.get("X-Amz-SignedHeaders");
  const sig = q.get("X-Amz-Signature");
  if (algo !== "AWS4-HMAC-SHA256" || !cred || !amzDate || !expires || !signedHeaders || !sig) return false;
  // expiry check
  const t = Date.parse(
    amzDate.replace(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/, "$1-$2-$3T$4:$5:$6Z")
  );
  if (!Number.isNaN(t) && Date.now() > t + parseInt(expires, 10) * 1000 + 300000) return false; // +5m skew
  const dateStamp = amzDate.slice(0, 8);
  const scope = `${dateStamp}/${REGION}/${SERVICE}/aws4_request`;
  const canonicalHeaders = signedHeaders
    .split(";")
    .map((h) => (h === "host" ? `host:${host}\n` : ""))
    .join("");
  const canonicalReq = [
    method,
    url.pathname,
    canonicalQuery(url, "X-Amz-Signature"),
    canonicalHeaders,
    signedHeaders,
    "UNSIGNED-PAYLOAD",
  ].join("\n");
  const strToSign = ["AWS4-HMAC-SHA256", amzDate, scope, await sha256Hex(canonicalReq)].join("\n");
  const key = await signingKey(secret, dateStamp);
  const expected = toHex(await hmac(key, strToSign));
  return safeEq(expected, sig);
}

// Validate a SigV4 Authorization-header request (server-side boto3).
async function validateHeaderSig(request, url, host, secret) {
  const auth = request.headers.get("Authorization") || "";
  const m = auth.match(/^AWS4-HMAC-SHA256 Credential=([^,]+),\s*SignedHeaders=([^,]+),\s*Signature=([0-9a-f]+)$/);
  if (!m) return false;
  const scopePart = m[1].split("/").slice(1).join("/"); // date/region/service/aws4_request
  const signedHeaders = m[2];
  const sig = m[3];
  const amzDate = request.headers.get("x-amz-date");
  if (!amzDate) return false;
  const dateStamp = amzDate.slice(0, 8);
  const payloadHash = request.headers.get("x-amz-content-sha256") || "UNSIGNED-PAYLOAD";
  const canonicalHeaders = signedHeaders
    .split(";")
    .map((h) => {
      if (h === "host") return `host:${host}\n`;
      const val = request.headers.get(h) || "";
      return `${h}:${val.trim()}\n`;
    })
    .join("");
  const canonicalReq = [
    request.method,
    url.pathname,
    canonicalQuery(url, null),
    canonicalHeaders,
    signedHeaders,
    payloadHash,
  ].join("\n");
  const strToSign = ["AWS4-HMAC-SHA256", amzDate, scopePart, await sha256Hex(canonicalReq)].join("\n");
  const key = await signingKey(secret, dateStamp);
  const expected = toHex(await hmac(key, strToSign));
  return safeEq(expected, sig);
}

// Validate an S3 POST-policy upload (browser multipart).
async function validatePostPolicy(policyB64, xAmzSig, xAmzCred, secret) {
  if (!policyB64 || !xAmzSig || !xAmzCred) return false;
  const dateStamp = xAmzCred.split("/")[1];
  if (!/^\d{8}$/.test(dateStamp || "")) return false;
  const key = await signingKey(secret, dateStamp);
  const expected = toHex(await hmac(key, policyB64));
  return safeEq(expected, xAmzSig);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const method = request.method;
    const host = request.headers.get("host") || url.host;
    const secret = env.R2_SECRET_ACCESS_KEY;

    if (method === "OPTIONS") return new Response(null, { status: 204, headers: withCors() });
    if (!secret) return new Response("worker not configured", { status: 500, headers: withCors() });

    let p = decodeURIComponent(url.pathname).replace(/^\/+/, "");
    const slash = p.indexOf("/");
    const key = slash === -1 ? "" : p.slice(slash + 1);

    // ---- bucket-level (no key): browser POST upload + server-side bucket check ----
    if (!key) {
      if (method === "POST") {
        const form = await request.formData();
        const objectKey = form.get("key");
        const file = form.get("file");
        const ok = await validatePostPolicy(
          form.get("policy"), form.get("x-amz-signature"), form.get("x-amz-credential"), secret
        );
        if (!ok) return deny("invalid upload signature");
        if (!objectKey || !file || typeof file === "string") return deny("missing key or file");
        const contentType = form.get("Content-Type") || file.type || "application/octet-stream";
        await env.BUCKET.put(objectKey, file.stream(), { httpMetadata: { contentType } });
        return new Response(null, { status: 204, headers: withCors({ ETag: '"uploaded"' }) });
      }
      // bucket check (head_bucket) is server-side & signed
      if (method === "GET" || method === "HEAD") {
        if (!(await validateHeaderSig(request, url, host, secret))) return deny();
        return new Response(method === "HEAD" ? null : "", { status: 200, headers: withCors() });
      }
      return new Response("method not allowed", { status: 405, headers: withCors() });
    }

    // ---- object-level: authenticate via query-sig (presigned) or header-sig (server-side) ----
    const authed = url.searchParams.has("X-Amz-Signature")
      ? await validateQuerySig(url, method, host, secret)
      : await validateHeaderSig(request, url, host, secret);
    if (!authed) return deny();

    if (method === "GET") {
      const obj = await env.BUCKET.get(key);
      if (!obj) return new Response("Not Found", { status: 404, headers: withCors() });
      const h = new Headers(withCors());
      obj.writeHttpMetadata(h);
      h.set("ETag", obj.httpEtag);
      const rct = url.searchParams.get("response-content-type");
      if (rct) h.set("Content-Type", rct);
      const rcd = url.searchParams.get("response-content-disposition");
      if (rcd) h.set("Content-Disposition", rcd);
      return new Response(obj.body, { status: 200, headers: h });
    }
    if (method === "HEAD") {
      const obj = await env.BUCKET.head(key);
      if (!obj) return new Response(null, { status: 404, headers: withCors() });
      const h = new Headers(withCors());
      obj.writeHttpMetadata(h);
      h.set("ETag", obj.httpEtag);
      h.set("Content-Length", String(obj.size));
      return new Response(null, { status: 200, headers: h });
    }
    if (method === "PUT") {
      const contentType = request.headers.get("content-type") || "application/octet-stream";
      const obj = await env.BUCKET.put(key, request.body, { httpMetadata: { contentType } });
      return new Response(null, { status: 200, headers: withCors({ ETag: obj.httpEtag }) });
    }
    if (method === "DELETE") {
      await env.BUCKET.delete(key);
      return new Response(null, { status: 204, headers: withCors() });
    }
    return new Response("method not allowed", { status: 405, headers: withCors() });
  },
};
