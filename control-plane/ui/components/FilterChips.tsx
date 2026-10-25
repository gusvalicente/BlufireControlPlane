import Link from "next/link";
import { Icon } from "./Icon";

// App and environment filter chips that keep other query params.
export function FilterChips({ base, apps, app, env }: { base: string; apps: string[]; app?: string; env?: string }) {
  const href = (a?: string, e?: string) => {
    const q = new URLSearchParams();
    if (a) q.set("app", a);
    if (e) q.set("env", e);
    const s = q.toString();
    return s ? `${base}?${s}` : base;
  };
  return (
    <>
      <div className="chips">
        <Link href={href(undefined, env)} className={`chip ${!app ? "sel" : ""}`}>{!app && <Icon n="check" />}All apps</Link>
        {apps.map((a) => (
          <Link key={a} href={href(a, env)} className={`chip ${app === a ? "sel" : ""}`}>{app === a && <Icon n="check" />}{a}</Link>
        ))}
      </div>
      <div className="chips" style={{ marginTop: 8 }}>
        <Link href={href(app, undefined)} className={`chip ${!env ? "sel" : ""}`}>{!env && <Icon n="check" />}All envs</Link>
        {["dev", "cert", "prod"].map((e) => (
          <Link key={e} href={href(app, e)} className={`chip ${env === e ? "sel" : ""}`}>{env === e && <Icon n="check" />}{e}</Link>
        ))}
      </div>
    </>
  );
}
