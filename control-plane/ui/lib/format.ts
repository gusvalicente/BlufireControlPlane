import type { BackupLayer, Env, Health, Severity } from "./types";

const TZ = process.env.NEXT_PUBLIC_TIMEZONE ?? "America/New_York";

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Intl.DateTimeFormat("en-US", { timeZone: TZ, month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(new Date(iso));
}

export function fmtDay(iso: string | null | undefined): string {
  if (!iso) return "";
  // Date-only values (like end-of-life dates) are calendar days, not instants: format them in UTC.
  const tz = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? "UTC" : TZ;
  return new Intl.DateTimeFormat("en-US", { timeZone: tz, month: "short", day: "numeric", year: "numeric" }).format(new Date(iso));
}

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const s = Math.round((now - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export function dueIn(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const days = Math.ceil((new Date(iso).getTime() - now) / 86400000);
  if (days < 0) return `Overdue ${-days} d`;
  if (days === 0) return "Due today";
  return `Due in ${days} day${days === 1 ? "" : "s"}`;
}

export function usd(n: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

export function bytes(n: number | null | undefined): string {
  if (n == null) return "";
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  if (n < 1024 * 1024 * 1024) return `${Math.round(n / 1024 / 1024)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

export function shortDigest(ref: string | null | undefined): string {
  if (!ref) return "Not deployed";
  const m = ref.match(/sha256:([a-f0-9]+)/);
  return m ? `sha256:${m[1].slice(0, 4)}…${m[1].slice(-4)}` : ref;
}

export const ENV_LABEL: Record<Env, string> = { dev: "Dev", cert: "Cert", prod: "Prod" };

export function healthDot(h: Health): string {
  if (h === "healthy") return "dot";
  if (h === "degraded") return "dot warn";
  if (h === "down") return "dot err";
  return "dot off";
}

export function healthTag(h: Health): { cls: string; label: string; icon: string } {
  switch (h) {
    case "healthy": return { cls: "ok", label: "Up", icon: "check_circle" };
    case "degraded": return { cls: "warn", label: "Degraded", icon: "warning" };
    case "down": return { cls: "err", label: "Down", icon: "error" };
    case "scaled_to_zero": return { cls: "neutral", label: "Scaled to 0", icon: "bedtime" };
    case "not_deployed": return { cls: "neutral", label: "Not deployed", icon: "cloud_off" };
    default: return { cls: "neutral", label: "Unknown", icon: "help" };
  }
}

export const SEVERITY: Record<Severity, { cls: string; label: string; lead: string; icon: string }> = {
  critical: { cls: "err", label: "Critical", lead: "err", icon: "emergency_home" },
  high: { cls: "warn", label: "High", lead: "warn", icon: "warning" },
  medium: { cls: "neutral", label: "Medium", lead: "", icon: "info" },
  low: { cls: "neutral", label: "Low", lead: "", icon: "info" },
};

export const LAYER: Record<BackupLayer, { label: string; icon: string }> = {
  pitr: { label: "Point-in-time restore", icon: "history" },
  pre_promotion: { label: "Pre-promotion dump", icon: "sell" },
  nightly: { label: "Nightly, immutable Blob", icon: "cloud_done" },
  manual: { label: "Manual dump", icon: "touch_app" },
  off_cloud: { label: "Off-cloud, Mac Mini", icon: "hard_drive" },
};

// Approval rule names shown to people.
export function ruleLabel(rule: string): string {
  if (rule === "actor:agent") return "Proposed by Claude";
  if (rule === "files") return "Protected file";
  return rule;
}
