// src/lib/branding.ts
import { authFetch } from "./auth.svelte";

const API_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export const DEFAULT_COLOR = "#7A1F2B";
export const DEFAULT_ASSISTANT_NAME = "Chat Assistant";
export const DEFAULT_HEADER_TAGLINE = "Admissions Intelligence Hub";
export const MAX_MASCOT_BYTES = 512 * 1024; // keep in sync with the backend

/** An API error that keeps the HTTP status, so callers can tell a 404 from a network failure. */
export class HttpError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "HttpError";
    this.status = status;
  }
}

export interface Branding {
  color: string;
  mascot_url: string | null; // absolute URL, ready to use in <img src>
  assistant_name: string;
  header_tagline: string;
}

interface BrandingResponse {
  color: string;
  mascot_url: string | null; // relative path from the API
  assistant_name?: string;
  header_tagline?: string;
}

function toBranding(data: BrandingResponse): Branding {
  return {
    color: data.color,
    mascot_url: data.mascot_url ? `${API_URL}${data.mascot_url}` : null,
    assistant_name: data.assistant_name || DEFAULT_ASSISTANT_NAME,
    header_tagline: data.header_tagline || DEFAULT_HEADER_TAGLINE,
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
  if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
  return toBranding(await res.json());
}

/** Authenticated: used by the Mascot page. */
export async function saveBranding(
  orgId: string | number,
  options: {
    color: string;
    assistantName: string;
    headerTagline: string;
    mascot?: File | null;
    removeMascot?: boolean;
  },
): Promise<Branding> {
  const form = new FormData();
  form.append("color", options.color);
  form.append("assistant_name", options.assistantName);
  form.append("header_tagline", options.headerTagline);
  if (options.mascot) form.append("mascot", options.mascot);
  else if (options.removeMascot) form.append("remove_mascot", "true");

  const res = await authFetch(`/branding/${orgId}`, { method: "PUT", body: form });
  if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
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