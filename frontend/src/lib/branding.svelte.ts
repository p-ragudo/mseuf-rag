// src/lib/branding.ts
import { authFetch } from "./auth.svelte";

const API_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export const DEFAULT_COLOR = "#7A1F2B";
export const MAX_MASCOT_BYTES = 512 * 1024; // keep in sync with the backend

export interface Branding {
  color: string;
  mascot_url: string | null; // absolute URL, ready to use in <img src>
}

interface BrandingResponse {
  color: string;
  mascot_url: string | null; // relative path from the API
}

function toBranding(data: BrandingResponse): Branding {
  return {
    color: data.color,
    mascot_url: data.mascot_url ? `${API_URL}${data.mascot_url}` : null,
  };
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) {
      return data.detail.map((d: { msg?: string }) => d.msg ?? "Invalid value").join(", ");
    }
  } catch {
    /* not JSON */
  }
  return `Request failed (${res.status})`;
}

/** Public: used by the chat page, so no login is needed. */
export async function fetchBranding(orgId: string | number): Promise<Branding> {
  const res = await fetch(`${API_URL}/branding/${orgId}`);
  if (!res.ok) throw new Error(await errorMessage(res));
  return toBranding(await res.json());
}

/** Authenticated: used by the Mascot page. */
export async function saveBranding(
  orgId: string | number,
  options: { color: string; mascot?: File | null; removeMascot?: boolean },
): Promise<Branding> {
  const form = new FormData();
  form.append("color", options.color);
  if (options.mascot) form.append("mascot", options.mascot);
  else if (options.removeMascot) form.append("remove_mascot", "true");

  const res = await authFetch(`/branding/${orgId}`, { method: "PUT", body: form });
  if (!res.ok) throw new Error(await errorMessage(res));
  return toBranding(await res.json());
}

/** Light tint of the brand color, used behind avatars. */
export function tint(color: string): string {
  return `${color}18`;
}

/** White or near-black text, whichever is readable on the given hex color. */
export function contrastColor(hex: string): "#FFFFFF" | "#111827" {
  const n = parseInt(hex.slice(1), 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return (r * 299 + g * 587 + b * 114) / 1000 > 160 ? "#111827" : "#FFFFFF";
}