<script lang="ts">
  import { onMount } from "svelte";
  import AppLayout from "../components/AppLayout.svelte";
  import WhiteCard from "../components/WhiteCard.svelte";
  import { authFetch } from "../auth.svelte";

  type Organization = { id: number; name: string };
  type OrganizationMember = {
    user_id: number;
    email: string;
    first_name: string;
    last_name: string;
    role: string;
  };

  let organizations = $state<Organization[]>([]);
  let selectedOrgId = $state("");
  let organizationsLoading = $state(true);
  let organizationError = $state("");
  let organizationMembers = $state<OrganizationMember[]>([]);
  let canManageMembers = $state(false);
  let membersLoading = $state(false);
  let memberEmail = $state("");
  let memberError = $state("");
  let memberNotice = $state("");
  let membersRequestId = 0;

  onMount(async () => {
    try {
      const response = await authFetch("/orgs/");
      if (!response.ok) throw new Error(await responseError(response));
      organizations = await response.json();
      selectedOrgId =
        organizations.length > 0 ? String(organizations[0].id) : "";
    } catch (error) {
      organizationError =
        error instanceof Error ? error.message : "Could not load organizations.";
    } finally {
      organizationsLoading = false;
    }
  });

  async function responseError(response: Response): Promise<string> {
    try {
      const data = await response.json();
      if (typeof data.detail === "string") return data.detail;
      if (Array.isArray(data.detail)) {
        return data.detail
          .map((item: { msg?: string }) => item.msg ?? "Invalid input")
          .join(", ");
      }
    } catch {
      // Preserve the HTTP status when the response is not JSON.
    }
    return `Request failed (${response.status}).`;
  }

  async function loadMembers(orgId: string) {
    const current = ++membersRequestId;
    membersLoading = true;
    memberError = "";
    try {
      const response = await authFetch(`/orgs/${orgId}/members`);
      if (!response.ok) throw new Error(await responseError(response));

      const result: {
        members: OrganizationMember[];
        can_manage: boolean;
      } = await response.json();
      if (current !== membersRequestId || orgId !== selectedOrgId) return;
      organizationMembers = result.members;
      canManageMembers = result.can_manage;
    } catch (error) {
      if (current !== membersRequestId || orgId !== selectedOrgId) return;
      memberError =
        error instanceof Error
          ? error.message
          : "Could not load organization members.";
    } finally {
      if (current === membersRequestId) membersLoading = false;
    }
  }

  $effect(() => {
    const orgId = selectedOrgId;
    if (orgId) void loadMembers(orgId);
    else organizationMembers = [];
  });

  async function addMember(event: SubmitEvent) {
    event.preventDefault();
    const email = memberEmail.trim();
    if (!email || !selectedOrgId) return;

    memberError = "";
    memberNotice = "";
    try {
      const response = await authFetch(
        `/orgs/${selectedOrgId}/members`,
        {
          method: "POST",
          body: JSON.stringify({ email }),
        },
      );
      if (!response.ok) throw new Error(await responseError(response));

      memberEmail = "";
      memberNotice = "Member added to the organization.";
      await loadMembers(selectedOrgId);
    } catch (error) {
      memberError =
        error instanceof Error ? error.message : "Could not add this member.";
    }
  }
</script>

<AppLayout>
  <div class="flex-1 px-3 py-4 sm:px-6">
    <p class="text-sm font-semibold uppercase tracking-wider text-primary">
      Organization management
    </p>
    <h1 class="mt-1 text-2xl font-bold sm:text-3xl">Members</h1>
    <p class="mt-2 text-gray-600">
      Manage who can access each organization. Members must have a registered
      account before an administrator can add them.
    </p>

    {#if organizationError}
      <p
        role="alert"
        class="mt-5 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        {organizationError}
      </p>
    {:else if organizationsLoading}
      <p class="mt-5 text-sm text-gray-500">Loading organizations…</p>
    {:else if organizations.length === 0}
      <p class="mt-5 text-sm text-gray-600">
        You are not a member of any organization.
      </p>
    {:else}
      <label class="mt-5 block max-w-lg">
        <span class="mb-2 block text-sm font-semibold">Organization</span>
        <select
          bind:value={selectedOrgId}
          class="w-full rounded-md border border-outline bg-white px-3 py-2.5 text-sm outline-none focus:border-primary"
        >
          {#each organizations as organization (organization.id)}
            <option value={String(organization.id)}>{organization.name}</option>
          {/each}
        </select>
      </label>

      <WhiteCard style="mt-5">
        <div
          class="flex flex-col justify-between gap-4 sm:flex-row sm:items-start"
        >
          <div>
            <h2 class="text-lg font-bold">Organization members</h2>
            <p class="mt-1 text-sm text-gray-500">
              Add existing accounts by email to grant access to this
              organization.
            </p>
          </div>
          <span class="text-sm text-gray-500">
            {membersLoading
              ? "Loading…"
              : `${organizationMembers.length} member${organizationMembers.length === 1 ? "" : "s"}`}
          </span>
        </div>

        {#if memberError}
          <p role="alert" class="mt-3 text-sm text-red-700">{memberError}</p>
        {/if}
        {#if memberNotice}
          <p role="status" class="mt-3 text-sm text-green-700">{memberNotice}</p>
        {/if}

        {#if canManageMembers}
          <form
            class="mt-4 flex flex-col gap-2 sm:flex-row"
            onsubmit={addMember}
          >
            <input
              type="email"
              bind:value={memberEmail}
              required
              placeholder="person@example.edu"
              aria-label="Registered user's email address"
              class="min-w-0 flex-1 rounded-md border border-outline px-3 py-2.5 text-sm outline-none focus:border-primary"
            />
            <button
              type="submit"
              disabled={!memberEmail.trim()}
              class="rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-white hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Add member
            </button>
          </form>
        {:else}
          <p class="mt-4 text-sm text-gray-500">
            Contact an organization administrator to add another member.
          </p>
        {/if}

        {#if organizationMembers.length > 0}
          <ul class="mt-4 divide-y divide-outline border-t border-outline">
            {#each organizationMembers as member (member.user_id)}
              <li
                class="flex flex-col gap-1 py-3 text-sm sm:flex-row sm:items-center sm:justify-between"
              >
                <span class="font-semibold">
                  {member.first_name} {member.last_name}
                </span>
                <span class="text-gray-500">{member.email}</span>
                <span
                  class="text-xs font-semibold uppercase tracking-wide text-gray-500"
                >
                  {member.role}
                </span>
              </li>
            {/each}
          </ul>
        {:else if !membersLoading}
          <p class="mt-4 border-t border-outline py-6 text-center text-sm text-gray-500">
            No members found.
          </p>
        {/if}
      </WhiteCard>
    {/if}
  </div>
</AppLayout>
