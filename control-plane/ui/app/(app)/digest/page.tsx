import Link from "next/link";
import { runOp } from "@/app/actions";
import { ActionButton } from "@/components/ActionButton";
import { Empty } from "@/components/Empty";
import { Icon } from "@/components/Icon";
import { TopBar } from "@/components/TopBar";
import { api, type DigestItem } from "@/lib/api";
import { fmtDate } from "@/lib/format";

export const metadata = { title: "Digest" };

function Items({ items, lead, icon }: { items: DigestItem[]; lead: string; icon: string }) {
  return (
    <div className="list">
      {items.map((it, i) => {
        const body = (
          <>
            <span className={`lead ${lead}`}><Icon n={icon} /></span>
            <span className="txt">
              <span className="h" style={{ display: "block" }}>{it.title}</span>
              {(it.detail || it.app) && <span className="s" style={{ display: "block" }}>{[it.detail, it.app].filter(Boolean).join(" · ")}</span>}
            </span>
            {it.link && <Icon n="chevron_right" className="muted" />}
          </>
        );
        return it.link?.startsWith("/") ? (
          <Link className="li" href={it.link} key={i}>{body}</Link>
        ) : (
          <div className="li" key={i}>{body}</div>
        );
      })}
    </div>
  );
}

export default async function DigestPage() {
  const d = await api.digest();
  return (
    <div className="page">
      <TopBar title="Daily digest" sub={`Generated ${fmtDate(d.generated_at)}`} back="/more" />
      <div className="content">
        <div className="card tonal body-m">{d.text}</div>
        <div className="section-label">P1 · paged</div>
        {d.p1.length === 0 ? <Empty icon="notifications_off" text="No P1s in the last 24 hours." /> : <Items items={d.p1} lead="err" icon="notifications_active" />}
        <div className="section-label">P2 · needs attention</div>
        {d.p2.length === 0 ? <Empty icon="task_alt" text="Nothing needs attention." /> : <Items items={d.p2} lead="warn" icon="priority_high" />}
        <div className="section-label">P3 · for your information</div>
        {d.p3.length === 0 ? <Empty icon="info" text="No updates." /> : <Items items={d.p3} lead="" icon="info" />}
        <div className="actions">
          <ActionButton action={runOp.bind(null, "digest", undefined, undefined)} label="Build digest now" icon="summarize" variant="tonal" />
        </div>
      </div>
    </div>
  );
}
