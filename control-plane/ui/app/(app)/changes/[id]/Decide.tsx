"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { approveChange, rejectChange } from "@/app/actions";
import { ActionButton } from "@/components/ActionButton";
import { Icon } from "@/components/Icon";
import { Sheet } from "@/components/Sheet";
import { Snackbar, type Snack } from "@/components/Snackbar";

export function Decide({ id }: { id: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [snack, setSnack] = useState<Snack | null>(null);
  const [pending, start] = useTransition();

  function reject() {
    if (!reason.trim()) return setError("Say why, so the requester knows what to change.");
    start(async () => {
      const r = await rejectChange(id, reason.trim());
      if (r.ok) {
        setOpen(false);
        setSnack({ text: r.message });
        router.refresh();
      } else setError(r.error);
    });
  }

  return (
    <>
      <div className="bottom-actions">
        <button className="btn danger" style={{ flex: 1 }} onClick={() => { setError(""); setOpen(true); }}>Reject</button>
        <ActionButton
          action={approveChange.bind(null, id)}
          retryKey="approve"
          label="Approve with MFA"
          icon="verified_user"
          variant="filled"
          style={{ flex: 2 }}
        />
      </div>
      <Sheet open={open} onClose={() => setOpen(false)} label="Reject change">
        <h2>Reject this change?</h2>
        <p className="body-m muted" style={{ margin: "4px 0 16px" }}>The pull request is closed and nothing is applied.</p>
        <label className="field">
          <span className="lab">Reason</span>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="For example: wrong CIDR for the branch office" />
        </label>
        {error && <div className="helper err">{error}</div>}
        <div className="actions">
          <button className="btn text" onClick={() => setOpen(false)}>Cancel</button>
          <button className="btn filled" onClick={reject} disabled={pending}><Icon n={pending ? "progress_activity" : "block"} />Reject</button>
        </div>
      </Sheet>
      <Snackbar snack={snack} onClose={() => setSnack(null)} />
    </>
  );
}
