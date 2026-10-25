import { notFound } from "next/navigation";
import { DiffView } from "@/components/DiffView";
import { Icon } from "@/components/Icon";
import { TopBar } from "@/components/TopBar";
import { api } from "@/lib/api";
import { ago, fmtDate, ruleLabel } from "@/lib/format";
import { Decide } from "./Decide";

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  return { title: `Change ${(await params).id}` };
}

const STATUS = {
  pending: { cls: "warn", label: "Waiting for approval", icon: "hourglass_top" },
  applied: { cls: "ok", label: "Applied", icon: "check_circle" },
  rejected: { cls: "neutral", label: "Rejected", icon: "block" },
  failed: { cls: "err", label: "Failed", icon: "error" },
} as const;

export default async function ChangePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let change;
  try {
    change = await api.change(id);
  } catch (e) {
    if ((e as { status?: number }).status === 404) notFound();
    throw e;
  }
  const me = await api.me();
  const st = STATUS[change.status];
  const prod = change.matched_rules.some((r) => r.includes("prod"));
  const security = change.matched_rules.some((r) => /origins|auth|secrets|stage|client_data|files/.test(r));
  const app = change.file.split("/").at(-1)?.replace(/\.yaml$/, "") ?? change.file;
  const canDecide = change.status === "pending" && me.roles.includes("Admin");

  return (
    <div className="page">
      <TopBar
        title={`Change request ${change.pr_number ? "#" + change.pr_number : change.id}`}
        sub={`Opened ${ago(change.created_at)} · ${change.pr_number ? "platform repo PR" : "direct commit"}`}
        back="/changes"
        actions={
          change.pr_url ? (
            <a className="icon-btn" href={change.pr_url} target="_blank" rel="noreferrer" aria-label="Open pull request"><Icon n="open_in_new" /></a>
          ) : undefined
        }
      />
      <div className="content">
        <div className="title-l" style={{ margin: "4px 0 8px" }}>{change.title}</div>
        <div className="tags">
          <span className={`tag ${st.cls}`}><Icon n={st.icon} />{st.label}</span>
          {change.risk === "approval" ? <span className="tag warn"><Icon n="lock" />Needs approval</span> : <span className="tag neutral">Low risk</span>}
          {security && <span className="tag warn"><Icon n="shield" />Security</span>}
          {prod && <span className="tag err"><Icon n="warning" />Prod</span>}
          <span className="tag neutral">{app}</span>
        </div>

        <div className="list" style={{ marginTop: 16 }}>
          <div className="kv"><span className="k">Requested by</span><span className="v">{change.actor.kind === "agent" ? "Claude via MCP" : change.actor.kind === "ci" ? "CI" : `${change.actor.name} via admin UI`}</span></div>
          <div className="kv"><span className="k">File</span><span className="v mono" style={{ fontSize: 12 }}>{change.file}</span></div>
          {change.reason && <div className="kv"><span className="k">Reason</span><span className="v">{change.reason}</span></div>}
          <div className="kv"><span className="k">Created</span><span className="v">{fmtDate(change.created_at)}</span></div>
          {change.decided_at && <div className="kv"><span className="k">Decided</span><span className="v">{fmtDate(change.decided_at)} by {change.decided_by}</span></div>}
          {change.commit_sha && <div className="kv"><span className="k">Commit</span><span className="v mono">{change.commit_sha.slice(0, 7)}</span></div>}
        </div>

        {change.matched_rules.length > 0 && (
          <>
            <div className="section-label">Why it needs approval</div>
            <div className="tags">
              {change.matched_rules.map((r) => (
                <span className="tag info" key={r}>{r === "actor:agent" && <Icon n="smart_toy" />}{ruleLabel(r)}</span>
              ))}
            </div>
          </>
        )}

        <div className="section-label">What changes</div>
        <DiffView diff={change.diff} />

        {canDecide && (
          <div className="banner info" style={{ marginTop: 16 }}>
            <Icon n="fingerprint" />
            <div>Approving asks for MFA again, merges the PR, and CI applies it in a few minutes.</div>
          </div>
        )}
        <div className="spacer" />
      </div>
      {canDecide && <Decide id={change.id} />}
    </div>
  );
}
