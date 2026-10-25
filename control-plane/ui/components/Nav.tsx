"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon } from "./Icon";

const MORE = ["/more", "/deployments", "/backups", "/drift", "/secrets", "/digest", "/audit", "/costs", "/clients"];

const ITEMS = [
  { href: "/", label: "Fleet", icon: "space_dashboard", match: (p: string) => p === "/" },
  { href: "/apps", label: "Apps", icon: "apps", match: (p: string) => p.startsWith("/apps") },
  { href: "/changes", label: "Changes", icon: "approval", match: (p: string) => p.startsWith("/changes") },
  { href: "/security", label: "Security", icon: "shield", match: (p: string) => p.startsWith("/security") },
  { href: "/more", label: "More", icon: "more_horiz", match: (p: string) => MORE.some((m) => p.startsWith(m)) },
];

function Items({ pending }: { pending: number }) {
  const path = usePathname();
  return (
    <>
      {ITEMS.map((it) => {
        const on = it.match(path);
        return (
          <Link key={it.href} href={it.href} className={`it ${on ? "on" : ""}`} aria-current={on ? "page" : undefined}>
            <span className="pill">
              <Icon n={it.icon} fill={on} />
              {it.href === "/changes" && pending > 0 && <span className="navbadge">{pending}</span>}
            </span>
            {it.label}
          </Link>
        );
      })}
    </>
  );
}

export function NavBar({ pending }: { pending: number }) {
  return (
    <nav className="navbar" aria-label="Main">
      <Items pending={pending} />
    </nav>
  );
}

export function NavRail({ pending }: { pending: number }) {
  return (
    <nav className="rail" aria-label="Main">
      <Link href="/" className="brand" aria-label="BluFire Ops home">
        <Icon n="local_fire_department" fill />
      </Link>
      <Items pending={pending} />
    </nav>
  );
}
