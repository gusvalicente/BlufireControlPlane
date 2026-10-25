import { NextResponse, type NextRequest, type NextFetchEvent } from "next/server";
import { auth } from "@/auth";
import { isMock } from "@/lib/mode";

// Every route needs a signed-in user, except the sign-in page, the Auth.js endpoints and the heartbeat relay.
const requireAuth = auth((req) => {
  if (req.auth) return NextResponse.next();
  const url = new URL("/signin", req.nextUrl.origin);
  url.searchParams.set("callbackUrl", req.nextUrl.pathname + req.nextUrl.search);
  return NextResponse.redirect(url);
});

export default function middleware(req: NextRequest, event: NextFetchEvent) {
  if (isMock()) return NextResponse.next();
  const { pathname } = req.nextUrl;
  if (pathname.startsWith("/signin") || pathname.startsWith("/api/auth") || pathname === "/api/heartbeat") {
    return NextResponse.next();
  }
  // The auth() wrapper accepts (request, event) at runtime; its typing is narrower.
  return (requireAuth as unknown as (r: NextRequest, e: NextFetchEvent) => Promise<Response>)(req, event);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|icon.svg|healthz).*)"],
};
