import Link from "next/link";
import { Empty } from "@/components/Empty";
import { Icon } from "@/components/Icon";
import { TopBar } from "@/components/TopBar";
import { api, type AuditEvent } from "@/lib/api";
import { fmtDate } from "@/lib/format";

export const metadata = { title: "Audit log" };

const ACTOR_ICON: Record<AuditEvent["actor_kind"], string> = { admin: "person", agent: "smart_toy", ci: "build", worker: "schedule" };
const PAGE = 50;

export default async function AuditPage({ searchParams }: { searchParams: Promise<{ before?: string }> }) {
  const sp = await searchParams;
  const events = await api.audit(PAGE, sp.before);
  return (
    <div className="page">
      <TopBar title="Audit log" back="/more" />
      <div className="content">
        {events.length === 0 ? <Empty icon="receipt_long" text="No audit events." /> : (
          <div className="list">
            {events.map((e) => (
              <div className="li" key={e.id}>
                <span className={`lead ${e.result === "denied" ? "warn" : e.result === "error" ? "err" : ""}`}><Icon n={ACTOR_ICON[e.actor_kind]} /></span>
                <span className="txt">
                  <span className="h mono" style={{ display: "block", fontSize: 14 }}>{e.action}</span>
                  <span className="s break" style={{ display: "block" }}>{e.actor} · {e.target}</span>
                  <span className="s" style={{ display: "block", fontSize: 12 }}>{fmtDate(e.at)}{e.source_ip ? ` · ${e.source_ip}` : ""}</span>
                </span>
                <span className="trail">
                  <span className={`tag ${e.result === "ok" ? "ok" : e.result === "denied" ? "warn" : "err"}`}>{e.result}</span>
                </span>
              </div>
            ))}
          </div>
        )}
        <div className="actions">
          {sp.before && <Link className="btn text" href="/audit">Newest</Link>}
          {events.length === PAGE && <Link className="btn tonal" href={`/audit?before=${events.at(-1)!.id}`}>Older<Icon n="chevron_right" /></Link>}
        </div>
      </div>
    </div>
  );
}
