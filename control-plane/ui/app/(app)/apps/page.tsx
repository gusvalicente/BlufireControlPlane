import { AppCard } from "@/components/AppCard";
import { Empty } from "@/components/Empty";
import { TopBar } from "@/components/TopBar";
import { api } from "@/lib/api";

export const metadata = { title: "Apps" };

export default async function AppsPage() {
  const apps = await api.apps();
  const graduated = apps.filter((a) => a.stage === "graduated");
  const incubating = apps.filter((a) => a.stage === "incubating");
  return (
    <div className="page">
      <TopBar title="Apps" />
      <div className="content">
        {apps.length === 0 && <Empty icon="apps" text="No apps in the registry yet." />}
        {graduated.length > 0 && (
          <>
            <div className="section-label" style={{ marginTop: 4 }}>Graduated · client subscriptions</div>
            <div className="app-grid">{graduated.map((a) => <AppCard key={a.id} app={a} />)}</div>
          </>
        )}
        {incubating.length > 0 && (
          <>
            <div className="section-label">Incubating · shared sandbox</div>
            <div className="app-grid">{incubating.map((a) => <AppCard key={a.id} app={a} />)}</div>
          </>
        )}
      </div>
    </div>
  );
}
