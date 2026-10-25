"use client";

import Link from "next/link";
import { useEffect } from "react";
import { Icon } from "./Icon";

export interface Snack {
  text: string;
  href?: string;
  error?: boolean;
}

export function Snackbar({ snack, onClose }: { snack: Snack | null; onClose: () => void }) {
  useEffect(() => {
    if (!snack) return;
    const t = setTimeout(onClose, snack.error ? 8000 : 5000);
    return () => clearTimeout(t);
  }, [snack, onClose]);
  if (!snack) return null;
  return (
    <div className="snackbar" role="status" aria-live="polite">
      {snack.error && <Icon n="error" size="sm" />}
      <span>{snack.text}</span>
      {snack.href && <Link href={snack.href}>View</Link>}
    </div>
  );
}
