"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { ackFinding } from "@/app/actions";
import { Icon } from "@/components/Icon";
import { Sheet } from "@/components/Sheet";
import { Snackbar, type Snack } from "@/components/Snackbar";

export function Ack({ id, title }: { id: string; title: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [fp, setFp] = useState(false);
  const [error, setError] = useState("");
  const [snack, setSnack] = useState<Snack | null>(null);
  const [pending, start] = useTransition();

  function save() {
    if (!note.trim()) return setError("Add a short note for the audit log.");
    start(async () => {
      const r = await ackFinding(id, note.trim(), fp);
      if (r.ok) {
        setOpen(false);
        setSnack({ text: r.message });
        router.refresh();
      } else setError(r.error);
    });
  }

  return (
    <>
      <button className="btn text" style={{ height: 32, padding: "0 8px" }} onClick={() => { setError(""); setNote(""); setFp(false); setOpen(true); }}>
        Acknowledge
      </button>
      <Sheet open={open} onClose={() => setOpen(false)} label="Acknowledge finding">
        <h2>Acknowledge</h2>
        <p className="body-m muted" style={{ margin: "4px 0 16px" }}>{title}</p>
        <label className="field">
          <span className="lab">Note</span>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="For example: fixed in v1.8.3, deploying Friday" />
        </label>
        <label className="check">
          <input type="checkbox" checked={fp} onChange={(e) => setFp(e.target.checked)} />
          False positive (closes the finding)
        </label>
        {error && <div className="helper err">{error}</div>}
        <div className="actions">
          <button className="btn text" onClick={() => setOpen(false)}>Cancel</button>
          <button className="btn filled" onClick={save} disabled={pending}><Icon n={pending ? "progress_activity" : "check"} />Save</button>
        </div>
      </Sheet>
      <Snackbar snack={snack} onClose={() => setSnack(null)} />
    </>
  );
}
