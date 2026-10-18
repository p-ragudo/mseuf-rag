// src/lib/org.svelte.ts

const API_URL: string = import.meta.env.VITE_API_URL;

export interface Organization {
  id: number;
  name: string;
}

export interface GetOrgPayload {
  orgId: number | string;
}

export type GetOrgResponse = Organization;

interface OrgState {
  org: Organization | null;
  loading: boolean;
  error: string | null;
}

export const orgState: OrgState = $state({
  org: null,
  loading: false,
  error: null,
});

async function parseError(res: Response): Promise<string> {
  try {
    const data = await res.json();

    if (typeof data.detail === "string") {
      return data.detail;
    }

    if (Array.isArray(data.detail)) {
      return data.detail.map((error: { msg: string }) => error.msg).join(", ");
    }
  } catch {
    // Response is not JSON
  }

  return `Request failed (${res.status})`;
}

export async function getOrg(
  payload: GetOrgPayload,
): Promise<GetOrgResponse | null> {
  orgState.loading = true;
  orgState.error = null;

  try {
    const response = await fetch(`${API_URL}/orgs/public/${payload.orgId}`);

    if (!response.ok) {
      orgState.error = await parseError(response);
      return null;
    }

    const data: GetOrgResponse = await response.json();

    orgState.org = data;

    return data;
  } catch {
    orgState.error = "Cannot reach the server. Is the backend running?";
    return null;
  } finally {
    orgState.loading = false;
  }
}

export async function listUserOrganizations(): Promise<Organization[]> {
  orgState.loading = true;
  orgState.error = null;

  try {
    const response = await fetch(`${API_URL}/orgs/`, {
      credentials: "include",
    });

    if (!response.ok) {
      orgState.error = await parseError(response);
      return [];
    }

    const data: Organization[] = await response.json();

    return data;
  } catch {
    orgState.error = "Cannot reach the server. Is the backend running?";
    return [];
  } finally {
    orgState.loading = false;
  }
}

export function clearOrg(): void {
  orgState.org = null;
  orgState.error = null;
}
