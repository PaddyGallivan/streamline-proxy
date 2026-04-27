// index.js
var SUPABASE_URL = "https://huvfgenbcaiicatvtxak.supabase.co/functions/v1/streamline";
var ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imh1dmZnZW5iY2FpaWNhdHZ0eGFrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDQwODExNjIsImV4cCI6MjA1OTY1NzE2Mn0.KrjLMqmUCRsHCbEBh4HqNGfyTtxScU4nOT4QDOOBGCE";
var CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "*", "Access-Control-Allow-Headers": "*" };
var index_default = {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    if (url.pathname === "/health" || url.pathname === "/ping") {
      return new Response(
        JSON.stringify({ ok: true, worker: "streamline-proxy", upstream: SUPABASE_URL }),
        { headers: { ...CORS, "Content-Type": "application/json" } }
      );
    }
    const targetUrl = SUPABASE_URL + url.pathname + url.search;
    const headers = new Headers(request.headers);
    headers.set("Authorization", `Bearer ${ANON_KEY}`);
    headers.set("apikey", ANON_KEY);
    headers.delete("host");
    try {
      const response = await fetch(targetUrl, {
        method: request.method,
        headers,
        body: request.method !== "GET" && request.method !== "HEAD" ? request.body : void 0
      });
      return new Response(response.body, {
        status: response.status,
        headers: { ...CORS, ...Object.fromEntries(response.headers) }
      });
    } catch (e) {
      return new Response(
        JSON.stringify({ error: "Upstream error", detail: e.message }),
        { status: 502, headers: { ...CORS, "Content-Type": "application/json" } }
      );
    }
  }
};
export {
  index_default as default
};
//# sourceMappingURL=index.js.map