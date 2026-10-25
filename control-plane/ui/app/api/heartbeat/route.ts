// Public relay for the Mac Mini off-cloud heartbeat. platform-api has internal ingress only, so the Mini reaches it
// through the UI (whose ingress already allows only the static IP). The heartbeat token is checked by platform-api.
export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const base = process.env.PLATFORM_API_URL;
  if (!base) return Response.json({ ok: false, error: "PLATFORM_API_URL not set" }, { status: 503 });
  const res = await fetch(`${base}/api/v1/heartbeat`, {
    headers: { Authorization: req.headers.get("authorization") ?? "" },
    cache: "no-store",
  });
  return new Response(await res.text(), { status: res.status, headers: { "content-type": "application/json" } });
}
