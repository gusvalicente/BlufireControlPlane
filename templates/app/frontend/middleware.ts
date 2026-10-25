export { auth as middleware } from "@/auth";

export const config = { matcher: ["/((?!api/health|api/auth|_next/static|_next/image|favicon.ico).*)"] };
