import Link from "next/link";
import { Empty } from "@/components/Empty";
import { Icon } from "@/components/Icon";
import { TopBar } from "@/components/TopBar";
import { api } from "@/lib/api";
import { usd } from "@/lib/format";

export const metadata = { title: "Costs" };

function shift(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

function label(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(Date.UTC(y, m - 1, 1)));
}

export default async function CostsPage({ searchParams }: { searchParams: Promise<{ month?: string }> }) {
  const sp = await searchParams;
  const now = new Date();
  const current = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}`;
  const month = /^\d{4}-\d{2}$/.test(sp.month ?? "") ? sp.month! : current;
  const costs = await api.costs(month);
  const max = Math.max(1, ...costs.by_client.map((c) => c.usd));
  const rows = [...costs.by_client].sort((a, b) => b.usd - a.usd);

  return (
    <div className="page">
      <TopBar title="Costs" back="/more" />
      <div className="content">
        <div className="spread" style={{ marginBottom: 12 }}>
          <Link className="icon-btn" href={`/costs?month=${shift(month, -1)}`} aria-label="Previous month"><Icon n="chevron_left" /></Link>
          <span className="title-m">{label(month)}</span>
          {month < current ? <Link className="icon-btn" href={`/costs?month=${shift(month, 1)}`} aria-label="Next month"><Icon n="chevron_right" /></Link> : <span style={{ width: 48 }} />}
        </div>
        <div className="card tonal">
          <div className="body-s muted">{month === current ? "Month to date" : "Month total"}</div>
          <div className="display-s">{usd(costs.total_usd)}</div>
        </div>
        <div className="section-label">By client</div>
        {rows.length === 0 ? <Empty icon="payments" text="No cost data for this month." /> : (
          <div className="list">
            {rows.map((c) => (
              <div className="li" key={c.client} style={{ flexDirection: "column", alignItems: "stretch", gap: 8 }}>
                <div className="spread"><span className="h">{c.client}</span><span className="title-s">{usd(c.usd)}</span></div>
                <div className="meter"><i style={{ width: `${(c.usd / max) * 100}%` }} /></div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
