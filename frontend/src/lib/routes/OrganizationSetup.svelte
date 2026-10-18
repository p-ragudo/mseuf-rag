<script lang="ts">
  import { replace } from "svelte-spa-router";
  import { authFetch } from "../auth.svelte";

  let organizationName = $state("");
  let creating = $state(false);
  let errorMessage = $state("");

  function checkMembershipAgain() {
    window.dispatchEvent(new Event("organization-membership-changed"));
  }

  async function createOrganization(event: SubmitEvent) {
    event.preventDefault();
    const name = organizationName.trim();
    if (!name || creating) return;

    creating = true;
    errorMessage = "";

    try {
      const response = await authFetch("/orgs/", {
        method: "POST",
        body: JSON.stringify({ name }),
      });

      if (!response.ok) {
        let message = `Could not create organization (${response.status}).`;
        try {
          const data = await response.json();
          if (typeof data.detail === "string") message = data.detail;
          else if (Array.isArray(data.detail)) {
            message = data.detail
              .map((item: { msg?: string }) => item.msg ?? "Invalid input")
              .join(", ");
          }
        } catch {
          // Keep the HTTP error message when the response is not JSON.
        }
        throw new Error(message);
      }

      window.dispatchEvent(new Event("organization-membership-changed"));
      replace("/overview");
    } catch (error) {
      errorMessage =
        error instanceof Error
          ? error.message
          : "Could not create your organization.";
    } finally {
      creating = false;
    }
  }
</script>

<main
  class="flex min-h-screen items-center justify-center bg-[#F5F8FB] px-4 py-10"
>
  <section
    class="w-full max-w-xl rounded-xl border border-outline bg-white p-8 shadow-sm"
  >
    <p class="text-xs font-bold uppercase tracking-wider text-primary">
      Organization access
    </p>
    <h1 class="mt-2 text-2xl font-bold">Join an organization to continue</h1>
    <p class="mt-3 text-sm leading-6 text-gray-600">
      Your account is not currently a member of an organization, so you cannot
      access its workspace or knowledge. Ask an organization administrator to
      add the email address you registered with, or create your own
      organization below.
    </p>

    <form class="mt-6" onsubmit={createOrganization}>
      <label for="organization-name" class="mb-2 block text-sm font-semibold">
        New organization name
      </label>
      <input
        id="organization-name"
        type="text"
        bind:value={organizationName}
        maxlength="255"
        required
        disabled={creating}
        placeholder="Example University"
        class="w-full rounded-md border border-outline px-4 py-3 text-sm outline-none focus:border-primary disabled:opacity-60"
      />

      {#if errorMessage}
        <p role="alert" class="mt-3 text-sm text-red-700">{errorMessage}</p>
      {/if}

      <button
        type="submit"
        disabled={creating || !organizationName.trim()}
        class="mt-4 w-full rounded-md bg-primary px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {creating ? "Creating organization…" : "Create organization"}
      </button>
    </form>

    <p class="mt-4 text-xs text-gray-500">
      Creating an organization makes you its administrator. You can add
      websites and manage its chat after setup.
    </p>

    <div class="mt-6 border-t border-outline pt-4 text-center">
      <p class="text-sm text-gray-600">Already have an account in a group?</p>
      <button
        type="button"
        class="mt-2 text-sm font-semibold text-primary hover:underline"
        onclick={checkMembershipAgain}
      >
        I was added; check my access
      </button>
    </div>
  </section>
</main>
