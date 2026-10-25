"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState, useTransition } from "react";
import type { ActionResult } from "@/app/actions";
import { startStepUp } from "@/app/actions";
import { Icon } from "./Icon";
import { Snackbar, type Snack } from "./Snackbar";

interface Props {
  action: () => Promise<ActionResult>;
  label: string;
  icon?: string;
  variant?: "filled" | "tonal" | "outlined" | "text" | "danger";
  confirm?: string;
  // Set for step-up actions: after the forced MFA sign-in the page reloads with ?retry=<retryKey> and runs again once.
  retryKey?: string;
  className?: string;
  style?: React.CSSProperties;
}

export function ActionButton({ action, label, icon, variant = "tonal", confirm, retryKey, className = "", style }: Props) {
  const [pending, start] = useTransition();
  const [snack, setSnack] = useState<Snack | null>(null);
  const router = useRouter();
  const path = usePathname();
  const params = useSearchParams();
  const retried = useRef(false);

  const run = useCallback(
    (skipConfirm = false) => {
      if (confirm && !skipConfirm && !window.confirm(confirm)) return;
      start(async () => {
        const r = await action();
        if (r.ok) {
          setSnack({ text: r.message, href: r.href });
          router.refresh();
        } else if (r.stepUp && retryKey) {
          await startStepUp(`${path}?retry=${encodeURIComponent(retryKey)}`);
        } else {
          setSnack({ text: r.error, error: true });
        }
      });
    },
    [action, confirm, retryKey, path, router],
  );

  useEffect(() => {
    if (!retryKey || retried.current || params.get("retry") !== retryKey) return;
    retried.current = true;
    router.replace(path);
    run(true);
  }, [retryKey, params, path, router, run]);

  return (
    <>
      <button className={`btn ${variant} ${className}`} style={style} onClick={() => run()} disabled={pending}>
        {icon && <Icon n={pending ? "progress_activity" : icon} />}
        {label}
      </button>
      <Snackbar snack={snack} onClose={() => setSnack(null)} />
    </>
  );
}
