// Edge gateway: mobile/API -> Cloudflare Access -> tunnel -> command_hub.py (127.0.0.1:8090)
// Worker secrets: MOBILE_COMMAND_SECRET, CF_ACCESS_CLIENT_ID, CF_ACCESS_CLIENT_SECRET
function safeEqual(a, b) {
  const enc = new TextEncoder();
  const x = enc.encode(a);
  const y = enc.encode(b);
  let diff = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i] ?? 0) ^ (y[i] ?? 0);
  return diff === 0;
}

function accessHeaders(env) {
  return {
    "Content-Type": "application/json",
    "CF-Access-Client-Id": env.CF_ACCESS_CLIENT_ID,
    "CF-Access-Client-Secret": env.CF_ACCESS_CLIENT_SECRET,
  };
}

// Edge collection (Section 3.1): sources fetched from Cloudflare's network, forwarded with their fetch metadata to the
// hub's Access-protected /ingest/edge, which archives and parses them. Keys and URLs must match the hub's whitelist.
const EDGE_SOURCES = {
  cpc_heating: (y) => `https://ftp.cpc.ncep.noaa.gov/htdocs/degree_days/weighted/daily_data/${y}/Population.Heating.txt`,
  cpc_cooling: (y) => `https://ftp.cpc.ncep.noaa.gov/htdocs/degree_days/weighted/daily_data/${y}/Population.Cooling.txt`,
  eia_hh_spot: () => "https://www.eia.gov/dnav/ng/hist_xls/RNGWHHDd.xls",
  eia_wti: () => "https://www.eia.gov/dnav/pet/hist_xls/RWTCd.xls",
  eia_propane: () => "https://www.eia.gov/dnav/pet/hist_xls/EER_EPLLPA_PF4_Y44MB_DPGd.xls",
  eia_storage: () => "https://ir.eia.gov/ngs/wngsr.csv",
  rggi: () => "https://www.rggi.org/auctions/auction-results/prices-volumes",
};
// Per-cron schedule: daily sources at 13:30 UTC; the weekly storage report on Thursdays after its 15:30 UTC release.
const EDGE_SCHEDULE = {
  "30 13 * * *": ["cpc_heating", "cpc_cooling", "eia_hh_spot", "eia_wti", "eia_propane", "rggi"],
  "45 15 * * THU": ["eia_storage"],
};

function toBase64(buf) {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

async function edgeFetch(url) {
  // One polite retry on a 5xx or network error, after 20 s; sources are fetched at most once per scheduled run.
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const r = await fetch(url, { headers: { "User-Agent": "joeysvault-quant-edge/1 (scheduled, once daily)" }, cf: { cacheTtl: 0 } });
      if (r.status < 500 || attempt === 1) return r;
    } catch (e) {
      if (attempt === 1) throw e;
    }
    await new Promise((res) => setTimeout(res, 20000));
  }
}

async function collectAtEdge(key, env) {
  const url = EDGE_SOURCES[key](new Date().getUTCFullYear());
  const retrieved = new Date().toISOString().replace(/\.\d+Z$/, "Z");
  let status = 0, body = new ArrayBuffer(0), headers = {}, ctype = "";
  try {
    const r = await edgeFetch(url);
    status = r.status; ctype = r.headers.get("content-type") || "";
    for (const [k, v] of r.headers) headers[k] = v;
    body = await r.arrayBuffer();
  } catch (e) {
    console.log(`edge ${key}: fetch failed ${e}`);
  }
  const base = (env.INGEST_URL || "https://quant.joeysvault.app/ingest").replace(/\/ingest$/, "");
  const resp = await fetch(`${base}/ingest/edge`, {
    method: "POST", headers: accessHeaders(env),
    body: JSON.stringify({ key, url, status, content_type: ctype, retrieved_timestamp: retrieved, headers, colo: "", body_b64: toBase64(body) }),
  });
  console.log(`edge ${key}: source HTTP ${status}, ${body.byteLength} bytes -> hub HTTP ${resp.status}`);
  return resp.status;
}

// GitHub webhook (spec 4.5): HMAC-SHA256 over the raw body with GITHUB_WEBHOOK_SECRET, compared in constant time.
async function githubSignatureOk(env, body, header) {
  if (!env.GITHUB_WEBHOOK_SECRET || !header || !header.startsWith("sha256=")) return false;
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(env.GITHUB_WEBHOOK_SECRET), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body)));
  const hex = [...mac].map((b) => b.toString(16).padStart(2, "0")).join("");
  return safeEqual(header, "sha256=" + hex);
}

async function githubWebhook(request, env) {
  const body = await request.text();
  if (body.length > 1_000_000) return new Response("Payload Too Large", { status: 413 });
  if (!(await githubSignatureOk(env, body, request.headers.get("X-Hub-Signature-256")))) return new Response("Bad signature", { status: 401 });
  const ev = request.headers.get("X-GitHub-Event") || "";
  if (ev === "ping") return Response.json({ pong: true });
  if (ev !== "pull_request") return Response.json({ ignored: ev }, { status: 202 });
  let p;
  try { p = JSON.parse(body); } catch { return new Response("Bad JSON", { status: 400 }); }
  const pr = p.pull_request || {};
  const m = /^selfheal\/([a-z0-9_]+)\//.exec((pr.head && pr.head.ref) || "");
  const baseRef = env.SELFHEAL_BASE || "main";
  if (p.action !== "closed" || !pr.merged || !pr.base || pr.base.ref !== baseRef || !m || !pr.merge_commit_sha) {
    return Response.json({ ignored: `not a merged selfheal PR into ${baseRef}` }, { status: 202 });
  }
  const base = (env.ORIGIN_URL || "https://quant.joeysvault.app/execute").replace(/\/execute$/, "");
  const r = await fetch(`${base}/selfheal/rerun`, {
    method: "POST", headers: accessHeaders(env),
    body: JSON.stringify({ collector: m[1], sha: pr.merge_commit_sha, pr: pr.number, base: baseRef }),
  });
  const out = await r.text();
  console.log(`selfheal rerun ${m[1]} @ ${pr.merge_commit_sha}: hub HTTP ${r.status}`);
  return new Response(out, { status: r.status, headers: { "Content-Type": "application/json" } });
}

export default {
  async scheduled(event, env, ctx) {
    for (const key of EDGE_SCHEDULE[event.cron] || []) {
      try { await collectAtEdge(key, env); } catch (e) { console.log(`edge ${key}: ${e}`); }
    }
    // then the local run for the sources that need the workstation (GRIB weather models, bulk files) and the knowledge library
    const resp = await fetch(env.INGEST_URL || "https://quant.joeysvault.app/ingest", {
      method: "POST",
      headers: accessHeaders(env),
      body: "{}",
    });
    console.log(`ingest ${event.cron}: HTTP ${resp.status}`);
  },

  async queue(batch, env) {
    const target = (env.ORIGIN_URL || "https://quant.joeysvault.app/execute").replace(/\/execute$/, "/experiments/run");
    for (const msg of batch.messages) {
      try {
        const resp = await fetch(target, {
          method: "POST",
          headers: accessHeaders(env),
          body: JSON.stringify(msg.body),
        });
        if (resp.ok || resp.status === 422) {
          msg.ack();
        } else {
          msg.retry({ delaySeconds: resp.status === 409 ? 120 : 30 });   // 409 = an experiment is already running
        }
      } catch (err) {
        console.error("queue dispatch error:", err);
        msg.retry({ delaySeconds: 30 });
      }
    }
  },

  async fetch(request, env) {
    const _relUrl = new URL(request.url);
    if (request.method === "GET" && _relUrl.pathname === "/_release") {
      return new Response(JSON.stringify({
        service: "quant-gateway",
        version: env.RELEASE_VERSION || "dev",
        commit: env.RELEASE_COMMIT || "unknown",
        compatibility_date: "2026-11-01"
      }), { status: 200, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
    }

    if (request.method === "POST" && new URL(request.url).pathname === "/github/webhook") return githubWebhook(request, env);
    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405, headers: { Allow: "POST" } });
    }
    const auth = request.headers.get("Authorization") || "";
    if (!env.MOBILE_COMMAND_SECRET || !safeEqual(auth, `Bearer ${env.MOBILE_COMMAND_SECRET}`)) {
      return new Response("Unauthorized", { status: 401 });
    }
    if (!env.CF_ACCESS_CLIENT_ID || !env.CF_ACCESS_CLIENT_SECRET) {
      return new Response("Gateway misconfigured", { status: 500 });
    }
    const body = await request.text();
    if (body.length > 4096) return new Response("Payload Too Large", { status: 413 });

    const url = new URL(request.url);
    const edge = url.pathname.match(/^\/edge\/([a-z_]+)$/);
    if (edge) {
      if (!EDGE_SOURCES[edge[1]]) return new Response("Unknown edge source", { status: 404 });
      const st = await collectAtEdge(edge[1], env);
      return Response.json({ key: edge[1], hub_status: st }, { status: st === 200 ? 200 : 502 });
    }

    if (url.pathname === "/backtest" || url.pathname === "/enqueue") {
      const queue = env.BACKTEST_JOBS;   // bound in wrangler.toml
      if (!queue) return new Response("Queue not bound", { status: 500 });
      let payload;
      try { payload = JSON.parse(body); } catch { return new Response("Bad JSON", { status: 400 }); }
      const jobs = Array.isArray(payload) ? payload : [payload];
      if (!jobs.length || jobs.length > 50 || jobs.some((j) => !j || typeof j.model !== "string")) {
        return new Response("Expected 1-50 jobs with a model", { status: 422 });
      }
      await queue.sendBatch(jobs.map((j) => ({ body: j })));
      return Response.json({ queued: jobs.length }, { status: 202 });
    }

    const upstream = await fetch(env.ORIGIN_URL || "https://quant.joeysvault.app/execute", {
      method: "POST",
      headers: accessHeaders(env),
      body,
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("Content-Type") || "application/json" },
    });
  },
};
