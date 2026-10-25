// Availability tests hit this. It must stay cheap and must not require sign-in.
export function GET() {
  return Response.json({ ok: true });
}
