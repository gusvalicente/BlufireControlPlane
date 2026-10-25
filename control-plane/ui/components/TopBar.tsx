import Link from "next/link";
import type { ReactNode } from "react";
import { Icon } from "./Icon";

export function TopBar({ title, sub, back, actions }: { title: string; sub?: string; back?: string; actions?: ReactNode }) {
  return (
    <header className="appbar">
      {back && (
        <Link href={back} className="icon-btn" aria-label="Back">
          <Icon n="arrow_back" />
        </Link>
      )}
      <h1 className={`title ${sub ? "two" : ""}`} style={{ fontWeight: 400 }}>
        {title}
        {sub && <span className="sub">{sub}</span>}
      </h1>
      {actions}
    </header>
  );
}
