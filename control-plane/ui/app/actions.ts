"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { PROVIDER_ID, signIn } from "@/auth";
import { api, ApiError, type ChangeRequestIn, type Env, type OpAction } from "@/lib/api";
import { isMock } from "@/lib/mode";

export type ActionResult =
  | { ok: true; message: string; href?: string }
  | { ok: false; error: string; stepUp?: boolean };

function fail(e: unknown): ActionResult {
  if (e instanceof ApiError && e.status === 403 && e.code === "step_up_required") {
    return { ok: false, stepUp: true, error: "Confirm with MFA to continue." };
  }
  const err = e as { message?: string; code?: string };
  return { ok: false, error: err?.message || "Request failed" };
}

export async function proposeChange(input: ChangeRequestIn): Promise<ActionResult> {
  try {
    const c = await api.createChange(input);
    revalidatePath("/", "layout");
    return c.risk === "low"
      ? { ok: true, message: "Saved", href: `/changes/${c.id}` }
      : { ok: true, message: "Sent for approval", href: `/changes/${c.id}` };
  } catch (e) {
    return fail(e);
  }
}

export async function approveChange(id: string): Promise<ActionResult> {
  try {
    await api.approve(id);
    revalidatePath("/", "layout");
    return { ok: true, message: "Approved. CI is applying the change." };
  } catch (e) {
    return fail(e);
  }
}

export async function rejectChange(id: string, reason: string): Promise<ActionResult> {
  try {
    await api.reject(id, reason);
    revalidatePath("/", "layout");
    return { ok: true, message: "Rejected" };
  } catch (e) {
    return fail(e);
  }
}

export async function ackFinding(id: string, note: string, falsePositive: boolean): Promise<ActionResult> {
  try {
    await api.ackFinding(id, note, falsePositive);
    revalidatePath("/security");
    return { ok: true, message: falsePositive ? "Marked as false positive" : "Acknowledged" };
  } catch (e) {
    return fail(e);
  }
}

const OP_MESSAGES: Record<OpAction, string> = {
  backup: "Backup queued",
  restore_test: "Restore test queued",
  scan: "Scan queued",
  drift_check: "Drift check queued",
  digest: "Digest queued",
};

export async function runOp(action: OpAction, app?: string, env?: Env): Promise<ActionResult> {
  try {
    await api.op(action, app, env);
    revalidatePath("/", "layout");
    return { ok: true, message: OP_MESSAGES[action] };
  } catch (e) {
    return fail(e);
  }
}

export async function adoptDrift(id: string): Promise<ActionResult> {
  try {
    const c = await api.adoptDrift(id);
    revalidatePath("/", "layout");
    return { ok: true, message: c.risk === "low" ? "Adopted into git" : "Sent for approval", href: `/changes/${c.id}` };
  } catch (e) {
    return fail(e);
  }
}

export async function revertDrift(id: string): Promise<ActionResult> {
  try {
    await api.revertDrift(id);
    revalidatePath("/drift");
    return { ok: true, message: "Revert queued" };
  } catch (e) {
    return fail(e);
  }
}

export async function rotateSecret(id: string): Promise<ActionResult> {
  try {
    await api.rotateSecret(id);
    revalidatePath("/secrets");
    return { ok: true, message: "Rotation queued" };
  } catch (e) {
    return fail(e);
  }
}

export async function graduateApp(id: string, subscriptionId: string): Promise<ActionResult> {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(subscriptionId.trim())) {
    return { ok: false, error: "Enter the client subscription ID (a GUID)." };
  }
  try {
    const c = await api.graduate(id, subscriptionId.trim());
    revalidatePath("/", "layout");
    return { ok: true, message: "Graduation sent for approval", href: `/changes/${c.id}` };
  } catch (e) {
    return fail(e);
  }
}

// Re-authenticates with a forced MFA prompt, then returns to `returnTo` (which carries ?retry=...).
export async function startStepUp(returnTo: string): Promise<void> {
  const safe = returnTo.startsWith("/") && !returnTo.startsWith("//") ? returnTo : "/";
  if (isMock()) redirect(safe);
  await signIn(PROVIDER_ID, { redirectTo: safe }, { prompt: "login", max_age: "0" });
}

// Promotion is a registry change: copy the images and release running in the previous environment.
export async function promoteApp(id: string, to: Exclude<Env, "dev">): Promise<ActionResult> {
  try {
    const detail = await api.app(id);
    const from = to === "cert" ? "dev" : "cert";
    const src = detail.registry.environments[from];
    if (!src.images?.frontend && !src.images?.backend) return { ok: false, error: `Nothing is deployed in ${from} yet.` };
    return await proposeChange({
      title: `Promote ${id} ${src.release ?? ""} to ${to}`.replace("  ", " "),
      file: detail.path,
      patch: { environments: { [to]: { images: src.images, release: src.release ?? null } } },
    });
  } catch (e) {
    return fail(e);
  }
}
