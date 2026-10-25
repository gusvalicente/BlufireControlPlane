import { runOp } from "@/app/actions";
import { ActionButton } from "@/components/ActionButton";
import { Empty } from "@/components/Empty";
import { FilterChips } from "@/components/FilterChips";
import { Icon } from "@/components/Icon";
import { TopBar } from "@/components/TopBar";
import { api, ENVS, type Backup, type BackupLayer, type Env } from "@/lib/api";
import { bytes, fmtDate, fmtDay, LAYER } from "@/lib/format";

export const metadata = { title: "Backups" };

const LAYERS: BackupLayer[] = ["pitr", "pre_promotion", "nightly", "manual", "off_cloud"];
const RESULT = {
  ok: { cls: "ok", label: "OK", lead: "ok" },
  late: { cls: "warn", label: "Late", lead: "warn" },
  failed: { cls: "err", label: "Failed", lead: "err" },
};

// Nightly layers are late when the newest copy is more than 36 hours old.
function status(b: Backup, now: number): keyof typeof RESULT {
  if (b.result === "failed") return "failed";
  const scheduled = b.layer === "nightly" || b.layer === "off_cloud";
  return scheduled && now - new Date(b.created_at).getTime() > 36 * 3600 * 1000 ? "late" : "ok";
}

export default async function BackupsPage({ searchParams }: { searchParams: Promise<{ app?: string; env?: string }> }) {
  const sp = await searchParams;
  const env = ENVS.includes(sp.env as Env) ? (sp.env as Env) : undefined;
  const [backups, tests, apps] = await Promise.all([api.backups(sp.app, env), api.restoreTests(sp.app), api.apps()]);

  // Group by app and env, newest backup per layer.
  const groups = new Map<string, Map<BackupLayer, Backup>>();
  for (const b of [...backups].sort((a, z) => z.created_at.localeCompare(a.created_at))) {
    const key = `${b.app}|${b.env}`;
    if (!groups.has(key)) groups.set(key, new Map());
    const g = groups.get(key)!;
    if (!g.has(b.layer)) g.set(b.layer, b);
  }
  const lastTest = tests[0];
  const now = Date.now();

  return (
    <div className="page">
      <TopBar title="Backups and restores" back="/more" />
      <div className="content">
        <FilterChips base="/backups" apps={apps.map((a) => a.id)} app={sp.app} env={env} />
        {groups.size === 0 && <Empty icon="backup" text="No backups recorded for this filter." />}
        {[...groups.entries()].map(([key, layers]) => {
          const [app, e] = key.split("|");
          return (
            <section key={key}>
              <div className="section-label">{app} · {e}</div>
              <div className="list">
                {LAYERS.filter((l) => layers.has(l)).map((l) => {
                  const b = layers.get(l)!;
                  const r = RESULT[status(b, now)];
                  return (
                    <div className="li" key={l}>
                      <span className={`lead ${r.lead}`}><Icon n={LAYER[l].icon} /></span>
                      <span className="txt">
                        <span className="h" style={{ display: "block" }}>{LAYER[l].label}</span>
                        <span className="s" style={{ display: "block" }}>
                          {fmtDate(b.created_at)}{b.size_bytes ? ` · ${bytes(b.size_bytes)}` : ""}{b.checksum ? " · checksum ✓" : ""}
                        </span>
                        <span className="s break" style={{ display: "block", fontSize: 12 }}>{b.location}</span>
                      </span>
                      <span className="trail"><span className={`tag ${r.cls}`}>{r.label}</span></span>
                    </div>
                  );
                })}
              </div>
              <div className="row" style={{ marginTop: 12 }}>
                <ActionButton action={runOp.bind(null, "backup", app, e as Env)} label="Back up now" icon="backup" variant="tonal" style={{ flex: 1 }} />
                <ActionButton action={runOp.bind(null, "restore_test", app, e as Env)} label="Test restore" icon="science" variant="outlined" style={{ flex: 1 }} />
              </div>
            </section>
          );
        })}

        <div className="section-label">Restore tests</div>
        {tests.length === 0 ? <Empty icon="science" text="No restore tests yet." /> : (
          <>
            {lastTest && (
              <div className="card tonal">
                <div className="spread">
                  <span className="title-s">Last {lastTest.result === "passed" ? "passed" : lastTest.result} {fmtDay(lastTest.started_at)}</span>
                  <span className={`tag ${lastTest.result === "passed" ? "ok" : lastTest.result === "failed" ? "err" : "info"}`}>
                    <Icon n={lastTest.result === "passed" ? "check_circle" : lastTest.result === "failed" ? "error" : "progress_activity"} />
                    {lastTest.result === "passed" ? "Passed" : lastTest.result === "failed" ? "Failed" : "Running"}
                  </span>
                </div>
                <div className="body-m muted" style={{ marginTop: 4 }}>
                  {lastTest.app}{lastTest.duration_s ? ` restored in ${Math.floor(lastTest.duration_s / 60)} min ${lastTest.duration_s % 60} s` : ""}. Checks: {lastTest.checks.join(", ")}.
                </div>
              </div>
            )}
            {tests.length > 1 && (
              <div className="list" style={{ marginTop: 8 }}>
                {tests.slice(1).map((t) => (
                  <div className="kv" key={t.id}>
                    <span className="k">{t.app} · {fmtDay(t.started_at)}</span>
                    <span className="v">{t.result === "passed" ? "Passed" : t.result === "failed" ? "Failed" : "Running"}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
