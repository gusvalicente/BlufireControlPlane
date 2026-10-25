import Link from "next/link";
import { Empty } from "@/components/Empty";
import { Icon } from "@/components/Icon";
import { TopBar } from "@/components/TopBar";
import { api } from "@/lib/api";

export const metadata = { title: "Clients" };

export default async function ClientsPage() {
  const clients = await api.clients();
  return (
    <div className="page">
      <TopBar title="Clients" back="/more" />
      <div className="content">
        {clients.length === 0 && <Empty icon="domain" text="No clients in the registry yet." />}
        {clients.map((c) => (
          <div className="card tonal" key={c.id}>
            <div className="spread">
              <span className="title-m">{c.name}</span>
              {c.subscription_id ? <span className="tag ok"><Icon n="cloud_done" />Subscription</span> : <span className="tag neutral"><Icon n="science" />Sandbox only</span>}
            </div>
            <div className="list" style={{ marginTop: 12, background: "var(--surface-container-low)" }}>
              <div className="kv"><span className="k">Client ID</span><span className="v mono">{c.id}</span></div>
              <div className="kv"><span className="k">Entra tenant</span><span className="v mono" style={{ fontSize: 12 }}>{c.tenant_id}</span></div>
              <div className="kv"><span className="k">Subscription</span><span className="v mono" style={{ fontSize: 12 }}>{c.subscription_id ?? "Created at graduation"}</span></div>
              {c.postgres?.prod_sku && <div className="kv"><span className="k">Postgres</span><span className="v">Prod {c.postgres.prod_sku.replace("Standard_", "")} · non-prod {c.postgres.nonprod_sku?.replace("Standard_", "") ?? "B1ms"}</span></div>}
              {(c.contacts ?? []).map((p) => (
                <div className="kv" key={p.name}><span className="k">{p.role}</span><span className="v">{p.name}{p.email ? ` · ${p.email}` : ""}</span></div>
              ))}
              <div className="kv">
                <span className="k">Apps</span>
                <span className="v">{c.apps.length === 0 ? "None" : c.apps.map((a, i) => <span key={a}>{i > 0 && ", "}<Link href={`/apps/${a}`} style={{ color: "var(--primary)" }}>{a}</Link></span>)}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
