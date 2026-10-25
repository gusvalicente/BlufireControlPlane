// Approval rules are dotted paths where "*" matches one segment. A rule matches a field when the rule is a
// segment-wise prefix of the field path (same semantics as policies/approvals.yaml app_paths).
export function ruleMatches(rule: string, path: string): boolean {
  const r = rule.split(".");
  const p = path.split(".");
  if (r.length > p.length) return false;
  return r.every((seg, i) => seg === "*" || seg === p[i]);
}

export function needsApproval(approvalFields: string[], path: string): boolean {
  return approvalFields.some((rule) => ruleMatches(rule, path));
}

export function matchedRules(approvalFields: string[], paths: string[]): string[] {
  return approvalFields.filter((rule) => paths.some((p) => ruleMatches(rule, p)));
}

type Json = null | boolean | number | string | Json[] | { [k: string]: Json };

// RFC 7386 JSON merge patch.
export function mergePatch<T>(target: T, patch: unknown): T {
  if (patch === null || typeof patch !== "object" || Array.isArray(patch)) return patch as T;
  const base: Record<string, Json> =
    target && typeof target === "object" && !Array.isArray(target) ? { ...(target as Record<string, Json>) } : {};
  for (const [key, value] of Object.entries(patch as Record<string, Json>)) {
    if (value === null) delete base[key];
    else base[key] = mergePatch(base[key], value);
  }
  return base as T;
}

// Leaf paths touched by a merge patch (arrays and nulls count as leaves).
export function patchPaths(patch: unknown, prefix = ""): string[] {
  if (patch === null || typeof patch !== "object" || Array.isArray(patch)) return prefix ? [prefix] : [];
  return Object.entries(patch as Record<string, unknown>).flatMap(([k, v]) =>
    patchPaths(v, prefix ? `${prefix}.${k}` : k),
  );
}
