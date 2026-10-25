import Link from "next/link";
import { notFound } from "next/navigation";
import { Icon } from "@/components/Icon";
import { TopBar } from "@/components/TopBar";
import { api, ApiError, ENVS, type Env, type OriginCidr } from "@/lib/api";
import { ENV_LABEL, fmtDate, fmtDay, healthTag, shortDigest } from "@/lib/format";
import { ActionButton } from "@/components/ActionButton";
import { promoteApp } from "@/app/actions";
import { AppConfig } from "./AppConfig";

// Networks the platform always adds when origin restriction is on. They cannot be removed here.
function lockedOrigins(adminStaticIp: string): OriginCidr[] {
  return [
    { cidr: adminStaticIp, label: "BluFire static IP, always included" },
    { cidr: "Availability tests", label: "Ranges from platform settings, so uptime checks pass" },
  ];
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  return { title: (await params).id };
}

export default async function AppDetailPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ env?: string }> }) {
  const { id } = await params;
  const sp = await searchParams;
  const env: Env = ENVS.includes(sp.env as Env) ? (sp.env as Env) : "prod";

  let detail;
  try {
    detail = await api.app(id);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    if ((e as { status?: number }).status === 404) notFound();
    throw e;
  }
  const [runtime, me] = await Promise.all([api.runtime(id, env), api.me()]);
  const { registry, summary } = detail;
  const status = summary.envs.find((s) => s.env === env)!;
  const tag = healthTag(status.health);
  const eol = Object.entries(registry.stack?.runtime_eol ?? {});

  return (
    <div className="page">
      <TopBar
        title={registry.name}
        sub={`${summary.client_name} · ${registry.id}`}
        back="/apps"
        actions={
          <a className="icon-btn" href={`https://github.com/${registry.repo}`} target="_blank" rel="noreferrer" aria-label="Open repository">
            <Icon n="open_in_new" />
          </a>
        }
      />
      <div className="content">
        <nav className="seg" aria-label="Environment">
          {ENVS.map((e) => (
            <Link key={e} href={`/apps/${id}?env=${e}`} className={e === env ? "on" : ""} aria-current={e === env ? "page" : undefined}>
              {e === env && <Icon n="check" />}
              {ENV_LABEL[e]}
            </Link>
          ))}
        </nav>

        <div className="card tonal">
          <div className="spread">
            <span className="title-s">Health now</span>
            <span className={`tag ${tag.cls}`}><Icon n={tag.icon} />{tag.label}</span>
          </div>
          <div className="body-m muted" style={{ margin: "4px 0 12px" }}>{status.summary}</div>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div><div className="body-s muted">p95 latency</div><div className="title-m">{status.p95_ms != null ? `${status.p95_ms} ms` : "None"}</div></div>
            <div><div className="body-s muted">Error rate</div><div className="title-m">{status.error_rate_pct != null ? `${status.error_rate_pct}%` : "None"}</div></div>
            <div style={{ textAlign: "right" }}><div className="body-s muted">Replicas</div><div className="title-m">{status.replicas ? `${status.replicas.current} of ${status.replicas.max}` : "None"}</div></div>
          </div>
        </div>

        <AppConfig
          app={registry}
          path={detail.path}
          env={env}
          approvalFields={detail.approval_fields}
          lockedOrigins={lockedOrigins(detail.admin_static_ip)}
          isAdmin={me.roles.includes("Admin")}
        />

        <div className="section-label">Running now <span className="ro-badge">READ ONLY</span></div>
        <div className="list">
          <div className="kv"><span className="k">Release</span><span className="v">{runtime.release ?? "Not deployed"}</span></div>
          <div className="kv"><span className="k">Frontend image</span><span className="v mono" style={{ fontSize: 13 }}>{shortDigest(runtime.images.frontend)}</span></div>
          <div className="kv"><span className="k">Backend image</span><span className="v mono" style={{ fontSize: 13 }}>{shortDigest(runtime.images.backend)}</span></div>
          <details className="kvd">
            <summary className="kv"><span className="k">Bicep parameters</span><span className="v" style={{ color: "var(--primary)", display: "flex", alignItems: "center", gap: 4 }}>View {Object.keys(runtime.bicep_params).length}<Icon n="expand_more" size="sm" /></span></summary>
            <div className="kvd-body">
              {Object.entries(runtime.bicep_params).map(([k, v]) => (
                <div className="kv" key={k}><span className="k mono">{k}</span><span className="v mono">{typeof v === "string" ? v : JSON.stringify(v)}</span></div>
              ))}
            </div>
          </details>
          <details className="kvd">
            <summary className="kv"><span className="k">Env variables</span><span className="v" style={{ color: "var(--primary)", display: "flex", alignItems: "center", gap: 4 }}>View {Object.keys(runtime.env_vars).length}<Icon n="expand_more" size="sm" /></span></summary>
            <div className="kvd-body">
              {Object.keys(runtime.env_vars).length === 0 && <div className="kv"><span className="k">None set</span></div>}
              {Object.entries(runtime.env_vars).map(([k, v]) => (
                <div className="kv" key={k}><span className="k mono">{k}</span><span className="v mono">{v}</span></div>
              ))}
            </div>
          </details>
          <details className="kvd">
            <summary className="kv"><span className="k">Secrets</span><span className="v" style={{ display: "flex", alignItems: "center", gap: 4 }}>{runtime.secrets.length} · values hidden<Icon n="expand_more" size="sm" /></span></summary>
            <div className="kvd-body">
              {runtime.secrets.length === 0 && <div className="kv"><span className="k">No secrets referenced</span></div>}
              {runtime.secrets.map((s) => (
                <div className="kv" key={s.name}>
                  <span className="k mono">{s.name}</span>
                  <span className="v">{s.last_rotated ? `Rotated ${fmtDay(s.last_rotated)}` : "Never rotated"}</span>
                </div>
              ))}
              <div className="kv"><Link href={`/secrets?app=${id}&env=${env}`} style={{ color: "var(--primary)" }}>Manage secrets</Link></div>
            </div>
          </details>
          <div className="kv"><span className="k">Repository</span><span className="v">{registry.repo}</span></div>
          <div className="kv"><span className="k">Registry file</span><span className="v mono" style={{ fontSize: 12 }}>{detail.path}</span></div>
          {eol.map(([rt, date]) => (
            <div className="kv" key={rt}><span className="k">{rt} end of life</span><span className="v">{fmtDay(date)}</span></div>
          ))}
        </div>

        <div className="row wrap" style={{ marginTop: 16 }}>
          {env !== "dev" && (
            <ActionButton
              action={promoteApp.bind(null, id, env)}
              label={`Promote ${env === "cert" ? "dev" : "cert"} to ${env}`}
              icon="upgrade"
              variant="filled"
              confirm={`Copy the images running in ${env === "cert" ? "dev" : "cert"} to ${env}? This opens a change for approval.`}
            />
          )}
          <Link className="btn outlined" href={`/deployments?app=${id}&env=${env}`}><Icon n="rocket_launch" />Deployments</Link>
          <Link className="btn outlined" href={`/backups?app=${id}&env=${env}`}><Icon n="backup" />Backups</Link>
        </div>
        <div className="body-s muted" style={{ marginTop: 12 }}>Updated {fmtDate(new Date().toISOString())}</div>
      </div>
    </div>
  );
}
