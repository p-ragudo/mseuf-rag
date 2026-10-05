// src/lib/auth.svelte.ts
import { replace } from "svelte-spa-router";

const API_URL: string = import.meta.env.VITE_API_URL;
const TOKEN_KEY = "token";

export interface User {
  id?: number | string;
  email: string;
  first_name: string;
  last_name: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface RegisterPayload extends LoginPayload {
  first_name: string;
  last_name: string;
}

// Adjust to match what your FastAPI /auth/login actually returns.
interface LoginResponse {
  access_token: string;
  token_type?: string;
  user?: User;
}

interface AuthState {
  token: string | null;
  user: User | null;
  loading: boolean;
  error: string | null;
}

function readToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function writeToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable, keep in-memory only */
  }
}

export const auth: AuthState = $state({
  token: readToken(),
  user: null,
  loading: false,
  error: null,
});

export function isAuthenticated(): boolean {
  return !!auth.token;
}

async function parseError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    // FastAPI: { detail: "message" } or { detail: [{ msg: "..." }] }
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail))
      return data.detail.map((d: { msg: string }) => d.msg).join(", ");
  } catch {
    /* not JSON */
  }
  return `Request failed (${res.status})`;
}

export async function login(payload: LoginPayload): Promise<boolean> {
  auth.loading = true;
  auth.error = null;
  try {
    const res = await fetch(`${API_URL}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      auth.error = await parseError(res);
      return false;
    }

    const data: LoginResponse = await res.json();
    auth.token = data.access_token;
    writeToken(data.access_token);

    if (data.user) auth.user = data.user;
    else await fetchMe();

    return true;
  } catch {
    auth.error = "Cannot reach the server. Is the backend running?";
    return false;
  } finally {
    auth.loading = false;
    replace("/overview");
  }
}

export async function register(payload: RegisterPayload): Promise<boolean> {
  auth.loading = true;
  auth.error = null;
  try {
    const res = await fetch(`${API_URL}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      auth.error = await parseError(res);
      return false;
    }
  } catch {
    auth.error = "Cannot reach the server. Is the backend running?";
    return false;
  } finally {
    auth.loading = false;
  }

  return true;
}

export function logout(): void {
  auth.token = null;
  auth.user = null;
  auth.error = null;
  writeToken(null);
}

/** fetch wrapper that attaches the token and logs out on 401. */
export async function authFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  if (auth.token) headers.set("Authorization", `Bearer ${auth.token}`);
  if (init.body && !headers.has("Content-Type"))
    headers.set("Content-Type", "application/json");

  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (res.status === 401) logout();
  return res;
}

/** Loads the current user. Assumes GET /auth/me exists; remove if it doesn't. */
export async function fetchMe(): Promise<void> {
  if (!auth.token) return;
  try {
    const res = await authFetch("/auth/me");
    if (res.ok) auth.user = await res.json();
  } catch {
    /* network error, keep the token and try again later */
  }
}

/** Call once on app start to validate the stored token with the server. */
export async function initAuth(): Promise<void> {
  if (auth.token) await fetchMe();
}
