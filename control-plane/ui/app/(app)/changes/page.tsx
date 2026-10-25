import Link from "next/link";
import { Empty } from "@/components/Empty";
import { Icon } from "@/components/Icon";
import { TopBar } from "@/components/TopBar";
import { api } from "@/lib/api";
import { ago, fmtDate } from "@/lib/format";

export const metadata = { title: "Changes" };

const STATUSES = ["pending", "applied", "rejected", "all"] as const;
type Status = (typeof STATUSES)[number];
const LABEL: Record<Status, string> = { pending: "Pending", applied: "Applied", rejected: "Rejected", all: "All" };

export default async function ChangesPage({ searchParams }: { searchParams: Promise<{ status?: string }> }) {
  const sp = await searchParams;
  const status: Status = STATUSES.includes(sp.status as Status) ? (sp.status as Status) : "pending";
  const [changes, pending] = await Promise.all([api.changes(status), status === "pending" ? null : api.changes("pending")]);
  const pendingCount = (pending ?? changes).length;

  return (
    <div className="page">
      <TopBar title="Changes" />
      <div className="content">
        <nav className="tabs">
          {STATUSES.map((s) => (
            <Link key={s} href={`/changes?status=${s}`} className={s === status ? "on" : ""}>
              {LABEL[s]}
              {s === "pending" && pendingCount > 0 && <span className="b">{pendingCount}</span>}
            </Link>
          ))}
        </nav>
        {changes.length === 0 ? (
          <Empty icon="task_alt" text={status === "pending" ? "Nothing is waiting for your approval." : "No changes here yet."} />
        ) : (
          <div className="list">
            {changes.map((c) => (
              <Link key={c.id} href={`/changes/${c.id}`} className="li">
                <span className={`lead ${c.status === "pending" ? "warn" : c.status === "applied" ? "ok" : c.status === "rejected" ? "" : "err"}`}>
                  <Icon n={c.actor.kind === "agent" ? "smart_toy" : c.status === "pending" ? "approval" : c.status === "applied" ? "check" : c.status === "rejected" ? "block" : "error"} />
                </span>
                <span className="txt">
                  <span className="h" style={{ display: "block" }}>{c.title}</span>
                  <span className="s" style={{ display: "block" }}>
                    {c.file.replace(/^registry\/apps\//, "").replace(/\.yaml$/, "")} · {c.actor.kind === "agent" ? "Claude" : c.actor.name}
                  </span>
                </span>
                <span className="trail">
                  {c.risk === "approval" ? <span className="tag warn">Approval</span> : <span className="tag neutral">Low risk</span>}
                  <span title={fmtDate(c.created_at)}>{ago(c.created_at)}</span>
                </span>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
