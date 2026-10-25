import { rotateSecret } from "@/app/actions";
import { ActionButton } from "@/components/ActionButton";
import { Empty } from "@/components/Empty";
import { FilterChips } from "@/components/FilterChips";
import { Icon } from "@/components/Icon";
import { TopBar } from "@/components/TopBar";
import { api, ENVS, type Env } from "@/lib/api";
import { dueIn, fmtDay } from "@/lib/format";

export const metadata = { title: "Secrets" };

export default async function SecretsPage({ searchParams }: { searchParams: Promise<{ app?: string; env?: string }> }) {
  const sp = await searchParams;
  const env = ENVS.includes(sp.env as Env) ? (sp.env as Env) : undefined;
  const [secrets, apps] = await Promise.all([api.secrets(sp.app, env), api.apps()]);
  const soon = (iso: string | null) => !!iso && new Date(iso).getTime() - Date.now() < 30 * 86400000;

  return (
    <div className="page">
      <TopBar title="Secrets" back="/more" />
      <div className="content">
        <div className="banner info"><Icon n="visibility_off" /><div>Values are never shown here or sent to Claude. Rotation needs MFA.</div></div>
        <div className="spacer" />
        <FilterChips base="/secrets" apps={apps.map((a) => a.id)} app={sp.app} env={env} />
        {secrets.length === 0 ? <Empty icon="key" text="No secrets for this filter." /> : (
          <div className="list" style={{ marginTop: 12 }}>
            {secrets.map((s) => (
              <div className="li" key={s.id}>
                <span className={`lead ${soon(s.expires) ? "warn" : ""}`}><Icon n="key" /></span>
                <span className="txt">
                  <span className="h mono" style={{ display: "block", fontSize: 15 }}>{s.name}</span>
                  <span className="s" style={{ display: "block" }}>{s.app} · {s.env} · {s.vault}</span>
                  <span className="s" style={{ display: "block" }}>
                    {s.last_rotated ? `Rotated ${fmtDay(s.last_rotated)}` : "Never rotated"}
                    {s.expires ? ` · ${soon(s.expires) ? dueIn(s.expires).replace("Due", "Expires") : `expires ${fmtDay(s.expires)}`}` : ""}
                  </span>
                </span>
                <span className="trail">
                  <ActionButton action={rotateSecret.bind(null, s.id)} retryKey={`rotate:${s.id}`} label="Rotate" icon="autorenew" variant="text" confirm={`Rotate ${s.name}? Apps pick up the new value on their next revision.`} />
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
