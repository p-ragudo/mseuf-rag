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
  let organizationOwnerId = $state<number | null>(null);
  let currentUserId = $state<number | null>(null);
  let membersLoading = $state(false);
  let memberActionUserId = $state<number | null>(null);
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
        owner_id: number;
        current_user_id: number;
      } = await response.json();
      if (current !== membersRequestId || orgId !== selectedOrgId) return;
      organizationMembers = result.members;
      canManageMembers = result.can_manage;
      organizationOwnerId = result.owner_id;
      currentUserId = result.current_user_id;
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

  async function transferAdminship(member: OrganizationMember) {
    if (
      !selectedOrgId ||
      memberActionUserId !== null ||
      !window.confirm(
        `Transfer adminship to ${member.first_name} ${member.last_name}? You will become a member.`,
      )
    ) {
      return;
    }

    memberActionUserId = member.user_id;
    memberError = "";
    memberNotice = "";
    try {
      const response = await authFetch(
        `/orgs/${selectedOrgId}/members/${member.user_id}/transfer-admin`,
        { method: "POST" },
      );
      if (!response.ok) throw new Error(await responseError(response));

      memberNotice =
        currentUserId === organizationOwnerId
          ? `Admin access granted to ${member.first_name} ${member.last_name}. The organization owner retains admin access.`
          : `Adminship transferred to ${member.first_name} ${member.last_name}. Your role is now member.`;
      await loadMembers(selectedOrgId);
    } catch (error) {
      memberError =
        error instanceof Error
          ? error.message
          : "Could not transfer adminship.";
    } finally {
      memberActionUserId = null;
    }
  }

  async function removeMember(member: OrganizationMember) {
    if (
      !selectedOrgId ||
      memberActionUserId !== null ||
      !window.confirm(
        `Remove ${member.first_name} ${member.last_name} from this organization?`,
      )
    ) {
      return;
    }

    memberActionUserId = member.user_id;
    memberError = "";
    memberNotice = "";
    try {
      const response = await authFetch(
        `/orgs/${selectedOrgId}/members/${member.user_id}`,
        { method: "DELETE" },
      );
      if (!response.ok) throw new Error(await responseError(response));

      memberNotice = `${member.first_name} ${member.last_name} was removed from the organization.`;
      await loadMembers(selectedOrgId);
    } catch (error) {
      memberError =
        error instanceof Error ? error.message : "Could not remove this member.";
    } finally {
      memberActionUserId = null;
    }
  }
</script>

<AppLayout>
  <div class="flex-1 px-3 py-4 sm:px-6">
    <p class="text-sm font-semibold uppercase tracking-wider text-primary">
      Organization management
    </p>
    <h1 class="mt-1 text-2xl font-bold sm:text-3xl">Team</h1>
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
            <h2 class="text-lg font-bold">Team members</h2>
            <p class="mt-1 text-sm text-gray-500">
              Add existing accounts by email to grant access to this
              organization. Administrators can transfer adminship or remove
              members.
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
          <p class="mt-4 text-sm text-gray-500">
            Transferring adminship makes the selected member an administrator
            and changes your role to member. The organization owner always
            retains admin access.
          </p>
          <form
            class="mt-3 flex flex-col gap-2 sm:flex-row"
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
                class="flex flex-col gap-3 py-3 text-sm sm:flex-row sm:items-center sm:justify-between"
              >
                <div class="min-w-0 flex-1">
                  <p class="font-semibold">
                    {member.first_name} {member.last_name}
                    {#if member.user_id === currentUserId}
                      <span class="font-normal text-gray-500">(you)</span>
                    {/if}
                  </p>
                  <p class="text-gray-500">{member.email}</p>
                </div>
                <div class="flex flex-wrap items-center gap-2">
                  <span
                    class="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-semibold uppercase tracking-wide text-gray-600"
                  >
                    {member.user_id === organizationOwnerId
                      ? "Owner · Admin"
                      : member.role}
                  </span>
                  {#if canManageMembers && member.user_id !== organizationOwnerId}
                    {#if member.role !== "admin"}
                      <button
                        type="button"
                        class="rounded-md border border-outline px-3 py-2 text-xs font-semibold text-primary hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                        disabled={memberActionUserId !== null}
                        onclick={() => void transferAdminship(member)}
                      >
                        {memberActionUserId === member.user_id
                          ? "Updating…"
                          : "Transfer adminship"}
                      </button>
                    {/if}
                    {#if member.user_id !== currentUserId}
                      <button
                        type="button"
                        class="rounded-md px-3 py-2 text-xs font-semibold text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                        disabled={memberActionUserId !== null}
                        onclick={() => void removeMember(member)}
                      >
                        {memberActionUserId === member.user_id
                          ? "Updating…"
                          : "Remove"}
                      </button>
                    {/if}
                  {/if}
                </div>
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
