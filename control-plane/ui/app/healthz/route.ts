// Liveness probe for Container Apps. No auth, no API call.
export function GET() {
  return Response.json({ ok: true });
}
