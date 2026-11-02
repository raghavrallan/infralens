import { NextResponse } from "next/server";

export function proxy(request) {
  const { pathname } = request.nextUrl;
  const session = request.cookies.get("il_session")?.value;
  const isPublic =
    pathname === "/login" ||
    pathname === "/signup" ||
    pathname === "/accept-invite" ||
    pathname === "/approve-member" ||
    pathname.startsWith("/api/login") ||
    pathname.startsWith("/api/signup") ||
    pathname.startsWith("/api/invites/") ||
    pathname.startsWith("/suite-api");
  if (!session && !isPublic) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)"],
};
