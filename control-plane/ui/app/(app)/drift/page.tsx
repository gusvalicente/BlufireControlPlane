import { adoptDrift, revertDrift, runOp } from "@/app/actions";
import { ActionButton } from "@/components/ActionButton";
import { Empty } from "@/components/Empty";
import { Icon } from "@/components/Icon";
import { TopBar } from "@/components/TopBar";
import { api } from "@/lib/api";
import { ago, fmtDate, fmtDay } from "@/lib/format";

export const metadata = { title: "Drift" };

export default async function DriftPage() {
  const all = await api.drift();
  const open = all.filter((d) => d.status === "open");
  const resolved = all.filter((d) => d.status !== "open");

  return (
    <div className="page">
      <TopBar title="Drift" back="/more" actions={<ActionButton action={runOp.bind(null, "drift_check", undefined, undefined)} label="Check now" icon="refresh" variant="text" />} />
      <div className="content">
        {open.length > 0 ? (
          <div className="banner err">
            <Icon n="difference" />
            <div><b style={{ fontWeight: 500 }}>{open.length} change{open.length === 1 ? "" : "s"} made outside git.</b> Adopt keeps the live value; revert re-applies git.</div>
          </div>
        ) : (
          <div className="banner ok"><Icon n="check_circle" /><div>Live Azure matches git.</div></div>
        )}

        {open.map((d) => (
          <div className="card outlined" style={{ marginTop: 12 }} key={d.id}>
            <div className="spread"><span className="title-m">{d.app} · {d.env}</span><span className="tag err">Open</span></div>
            <div className="body-s muted break" style={{ margin: "2px 0 12px" }}>{d.resource} · detected {fmtDate(d.detected_at)} ({ago(d.detected_at)})</div>
            <div className="list" style={{ background: "var(--surface-container)" }}>
              <div className="kv"><span className="k">Property</span><span className="v mono" style={{ fontSize: 13 }}>{d.property}</span></div>
              <div className="kv"><span className="k">In git</span><span className="v mono">{d.desired}</span></div>
              <div className="kv"><span className="k">Live in Azure</span><span className="v mono" style={{ color: "var(--error)" }}>{d.live}</span></div>
              <div className="kv"><span className="k">Changed by</span><span className="v">{d.changed_by ?? "Unknown"}</span></div>
            </div>
            <div className="row" style={{ marginTop: 14 }}>
              <ActionButton action={revertDrift.bind(null, d.id)} label="Revert to git" icon="undo" variant="outlined" style={{ flex: 1 }} confirm={`Re-apply git and set ${d.property} back to ${d.desired}?`} />
              <ActionButton action={adoptDrift.bind(null, d.id)} label="Adopt into git" icon="merge" variant="filled" style={{ flex: 1 }} />
            </div>
            {d.env === "prod" && <div className="body-s muted" style={{ marginTop: 8, textAlign: "center" }}>Both need approval in prod</div>}
          </div>
        ))}

        <div className="section-label">Recently resolved</div>
        {resolved.length === 0 ? <Empty icon="history" text="Nothing resolved yet." /> : (
          <div className="list">
            {resolved.map((d) => (
              <div className="li" key={d.id}>
                <span className="lead ok"><Icon n={d.status === "adopted" ? "merge" : "undo"} /></span>
                <span className="txt">
                  <span className="h" style={{ display: "block" }}>{d.app} · {d.env}</span>
                  <span className="s" style={{ display: "block" }}>{d.property} {d.status === "adopted" ? `adopted as ${d.live}` : `reverted to ${d.desired}`}</span>
                </span>
                <span className="trail">{fmtDay(d.detected_at)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
