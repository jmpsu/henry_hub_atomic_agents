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

export default {
  async scheduled(event, env, ctx) {
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
          msg.retry({ delaySeconds: resp.status === 409 ? 15 : 30 });
        }
      } catch (err) {
        console.error("queue dispatch error:", err);
        msg.retry({ delaySeconds: 30 });
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

    const url = new URL(request.url);
    if (url.pathname === "/backtest" || url.pathname === "/enqueue") {
      const queue = env.BACKTEST_QUEUE || env.BACKTEST_JOBS;   // wrangler.toml binds BACKTEST_JOBS
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
