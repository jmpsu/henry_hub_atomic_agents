// Edge gateway: mobile/API -> Cloudflare Access -> tunnel -> command_hub.py (127.0.0.1:8090)
// Worker secrets: MOBILE_COMMAND_SECRET, CF_ACCESS_CLIENT_ID, CF_ACCESS_CLIENT_SECRET
// Var: ORIGIN_URL (tunnel hostname routed to local port 8090)
function safeEqual(a, b) {
  const enc = new TextEncoder();
  const x = enc.encode(a);
  const y = enc.encode(b);
  let diff = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i] ?? 0) ^ (y[i] ?? 0);
  return diff === 0;
}

export default {
  // Scheduled collection: Cron Trigger -> Access-protected tunnel -> hub /ingest (no gist, no LLM).
  async scheduled(event, env, ctx) {
    const resp = await fetch(env.INGEST_URL || "https://quant.joeysvault.app/ingest", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "CF-Access-Client-Id": env.CF_ACCESS_CLIENT_ID,
        "CF-Access-Client-Secret": env.CF_ACCESS_CLIENT_SECRET,
      },
      body: "{}",
    });
    console.log(`ingest ${event.cron}: HTTP ${resp.status}`);
  },
  // Queue consumer: each backtest job is forwarded to the hub (local compute) through the Access tunnel.
  // 200/422 -> ack (done, or permanently invalid); anything else -> retry, then the dead-letter queue.
  async queue(batch, env) {
    const base = (env.ORIGIN_URL || "https://quant.joeysvault.app/execute").replace(/\/execute$/, "");
    for (const msg of batch.messages) {
      try {
        const resp = await fetch(`${base}/experiments/run`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "CF-Access-Client-Id": env.CF_ACCESS_CLIENT_ID,
            "CF-Access-Client-Secret": env.CF_ACCESS_CLIENT_SECRET,
          },
          body: JSON.stringify(msg.body),
        });
        console.log(`backtest job ${msg.id}: HTTP ${resp.status}`);
        if (resp.status === 200 || resp.status === 422) msg.ack();
        else msg.retry({ delaySeconds: 60 });
      } catch (e) {
        console.log(`backtest job ${msg.id}: ${e}`);
        msg.retry({ delaySeconds: 60 });
      }
    }
  },
  async fetch(request, env) {
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

    if (new URL(request.url).pathname === "/enqueue") {
      let job;
      try { job = JSON.parse(body); } catch { return new Response("Bad JSON", { status: 400 }); }
      const jobs = Array.isArray(job) ? job : [job];
      if (!jobs.length || jobs.length > 50 || jobs.some((j) => !j || typeof j.model !== "string")) {
        return new Response("Expected 1-50 jobs with a model", { status: 422 });
      }
      await env.BACKTEST_JOBS.sendBatch(jobs.map((j) => ({ body: j })));
      return new Response(JSON.stringify({ enqueued: jobs.length }), { status: 202, headers: { "Content-Type": "application/json" } });
    }

    // Bearer header is dropped: only Content-Type and the Access service-token pair go upstream.
    const upstream = await fetch(env.ORIGIN_URL || "https://quant.joeysvault.app/execute", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "CF-Access-Client-Id": env.CF_ACCESS_CLIENT_ID,
        "CF-Access-Client-Secret": env.CF_ACCESS_CLIENT_SECRET,
      },
      body,
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("Content-Type") || "application/json" },
    });
  },
};
