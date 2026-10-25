import Link from "next/link";
import { Empty } from "@/components/Empty";
import { Icon } from "@/components/Icon";
import { TopBar } from "@/components/TopBar";
import { api, type Finding, type Severity } from "@/lib/api";
import { ago, dueIn, fmtDate, SEVERITY } from "@/lib/format";
import { Ack } from "./Ack";

export const metadata = { title: "Security" };

const TABS = ["findings", "incidents", "posture"] as const;
type Tab = (typeof TABS)[number];
const SEVS: Severity[] = ["critical", "high", "medium", "low"];
const SOURCE_ICON: Record<Finding["source"], string> = { trivy: "deployed_code", dependabot: "package_2", defender: "cloud", runtime_eol: "schedule" };
const SOURCE_LABEL: Record<Finding["source"], string> = { trivy: "Trivy", dependabot: "Dependabot", defender: "Defender", runtime_eol: "Runtime" };

function FindingRow({ f }: { f: Finding }) {
  const sev = SEVERITY[f.severity];
  const where = [SOURCE_LABEL[f.source], f.cve, f.app, f.env].filter(Boolean).join(" · ");
  return (
    <div className="li">
      <span className={`lead ${sev.lead}`}><Icon n={f.severity === "critical" ? "emergency_home" : SOURCE_ICON[f.source]} /></span>
      <span className="txt">
        <span className="h" style={{ display: "block" }}>
          {f.link && !f.link.startsWith("/") ? <a href={f.link} target="_blank" rel="noreferrer">{f.title}</a> : f.title}
        </span>
        <span className="s" style={{ display: "block" }}>{where}</span>
        {f.note && <span className="s" style={{ display: "block", fontStyle: "italic" }}>{f.note}</span>}
        {f.status === "open" && <span style={{ display: "block", marginLeft: -8 }}><Ack id={f.id} title={f.title} /></span>}
      </span>
      <span className="trail">
        <span className={`tag ${sev.cls}`}>{sev.label}</span>
        {f.status === "acknowledged" ? <span>Acknowledged</span> : <span>{f.due_at ? dueIn(f.due_at) : "No due date"}</span>}
      </span>
    </div>
  );
}

export default async function SecurityPage({ searchParams }: { searchParams: Promise<{ tab?: string; severity?: string }> }) {
  const sp = await searchParams;
  const tab: Tab = TABS.includes(sp.tab as Tab) ? (sp.tab as Tab) : "findings";
  const severity = SEVS.includes(sp.severity as Severity) ? (sp.severity as Severity) : undefined;
  const [allOpen, incidents] = await Promise.all([api.findings("open"), api.incidents()]);
  const findings = severity ? allOpen.filter((f) => f.severity === severity) : allOpen;
  const counts = Object.fromEntries(SEVS.map((s) => [s, allOpen.filter((f) => f.severity === s).length]));
  const openIncidents = incidents.filter((i) => i.status === "open");
  const posture = allOpen.filter((f) => f.source === "defender" || f.source === "runtime_eol");

  return (
    <div className="page">
      <TopBar title="Security" />
      <div className="content">
        <nav className="tabs">
          <Link href="/security?tab=findings" className={tab === "findings" ? "on" : ""}>Findings{allOpen.length > 0 && <span className="b">{allOpen.length}</span>}</Link>
          <Link href="/security?tab=incidents" className={tab === "incidents" ? "on" : ""}>Incidents{openIncidents.length > 0 && <span className="b">{openIncidents.length}</span>}</Link>
          <Link href="/security?tab=posture" className={tab === "posture" ? "on" : ""}>Posture</Link>
        </nav>

        {tab === "findings" && (
          <>
            <div className="chips">
              <Link href="/security" className={`chip ${!severity ? "sel" : ""}`}>{!severity && <Icon n="check" />}Open {allOpen.length}</Link>
              {SEVS.filter((s) => counts[s] > 0).map((s) => (
                <Link key={s} href={`/security?severity=${s}`} className={`chip ${severity === s ? "sel" : ""}`}>
                  {severity === s && <Icon n="check" />}{SEVERITY[s].label} {counts[s]}
                </Link>
              ))}
            </div>
            {findings.length === 0 ? <Empty icon="verified_user" text="No open findings." /> : (
              <div className="list" style={{ marginTop: 8 }}>{findings.map((f) => <FindingRow key={f.id} f={f} />)}</div>
            )}
          </>
        )}

        {tab === "incidents" && (
          incidents.length === 0 ? <Empty icon="notifications_off" text="No incidents." /> : (
            <div className="list">
              {incidents.map((i) => (
                <div className="li" key={i.id}>
                  <span className={`lead ${i.status === "open" ? (i.severity === "p1" ? "err" : "warn") : "ok"}`}>
                    <Icon n={i.source === "sentinel" ? "policy" : i.source === "heartbeat" ? "monitor_heart" : "speed"} />
                  </span>
                  <span className="txt">
                    <span className="h" style={{ display: "block" }}>{i.title}</span>
                    <span className="s" style={{ display: "block" }}>
                      {i.source === "app_insights" ? "App Insights" : i.source === "sentinel" ? "Sentinel" : "Heartbeat"} · opened {fmtDate(i.opened_at)}
                    </span>
                    {i.note && <span className="s" style={{ display: "block", fontStyle: "italic" }}>{i.note}</span>}
                  </span>
                  <span className="trail">
                    <span className={`tag ${i.severity === "p1" ? "err" : i.severity === "p2" ? "warn" : "neutral"}`}>{i.severity.toUpperCase()}</span>
                    <span>{i.status === "open" ? ago(i.opened_at) : "Closed"}</span>
                  </span>
                </div>
              ))}
            </div>
          )
        )}

        {tab === "posture" && (
          <>
            <div className="card tonal" style={{ display: "flex", gap: 16, alignItems: "center" }}>
              <div style={{ flex: 1 }}>
                <div className="body-s muted">Defender and runtime findings</div>
                <div className="display-s">{posture.length}</div>
                <div className="body-s muted">open posture items</div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div className="body-s muted">Sentinel</div>
                <div className="title-m">{openIncidents.filter((i) => i.source === "sentinel").length} open</div>
                <div className="body-s muted">incidents</div>
              </div>
            </div>
            <div className="body-s muted" style={{ margin: "8px 4px" }}>Secure Score is shown in Defender for Cloud until the API exposes it.</div>
            {posture.length === 0 ? <Empty icon="cloud_done" text="No posture findings." /> : (
              <div className="list">{posture.map((f) => <FindingRow key={f.id} f={f} />)}</div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
