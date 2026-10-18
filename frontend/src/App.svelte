<!-- src/App.svelte -->
<script lang="ts">
  import { onMount } from "svelte";
  import Router, { replace } from "svelte-spa-router";
  import routes from "./routes";
  import { auth, authFetch, initAuth } from "./lib/auth.svelte";

  type MembershipState = "idle" | "checking" | "member" | "none" | "error";

  let currentHash = $state(window.location.hash.slice(1) || "/");
  let membershipState = $state<MembershipState>("idle");
  let membershipError = $state("");
  let membershipRequest = 0;

  onMount(() => {
    const refreshMembership = () => {
      if (auth.token) void checkMembership(auth.token);
    };
    window.addEventListener(
      "organization-membership-changed",
      refreshMembership,
    );

    void (async () => {
      await initAuth();
      if (auth.token) await checkMembership(auth.token);
    })();

    return () => {
      window.removeEventListener(
        "organization-membership-changed",
        refreshMembership,
      );
    };
  });

  async function checkMembership(token: string) {
    const request = ++membershipRequest;
    membershipState = "checking";
    membershipError = "";

    try {
      const response = await authFetch("/orgs/");
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(
          typeof data?.detail === "string"
            ? data.detail
            : `Could not check organization membership (${response.status}).`,
        );
      }

      const organizations: unknown = await response.json();
      if (request !== membershipRequest || auth.token !== token) return;
      if (!Array.isArray(organizations)) {
        throw new Error("The organization membership response was invalid.");
      }
      membershipState = organizations.length > 0 ? "member" : "none";
    } catch (error) {
      if (request !== membershipRequest || auth.token !== token) return;
      if (!auth.token) {
        membershipState = "idle";
        return;
      }
      membershipError =
        error instanceof Error
          ? error.message
          : "Could not check organization membership.";
      membershipState = "error";
    }
  }

  function syncRoute() {
    currentHash = window.location.hash.slice(1) || "/";
  }

  // Gate every authenticated workspace route on an actual organization membership.
  $effect(() => {
    const token = auth.token;
    const route = currentHash;
    const isPublicRoute = route.startsWith("/chat/") || route.startsWith("/login");
    const isSetupRoute = route === "/organization-setup";

    if (!token) {
      membershipState = "idle";
      if (!isPublicRoute) {
        replace("/login");
      }
      return;
    }

    if (isPublicRoute) {
      if (membershipState === "idle") void checkMembership(token);
      return;
    }

    if (membershipState === "idle") {
      void checkMembership(token);
      return;
    }

    if (membershipState === "checking" || membershipState === "error") return;

    if (membershipState === "none" && !isSetupRoute) {
      replace("/organization-setup");
    } else if (membershipState === "member" && isSetupRoute) {
      replace("/overview");
    }
  });

  let waitingForMembership = $derived(
    !!auth.token &&
      !currentHash.startsWith("/chat/") &&
      !currentHash.startsWith("/login") &&
      currentHash !== "/organization-setup" &&
      (membershipState === "checking" || membershipState === "idle"),
  );

  let needsMembershipSetup = $derived(
    !!auth.token &&
      !currentHash.startsWith("/chat/") &&
      !currentHash.startsWith("/login") &&
      currentHash !== "/organization-setup" &&
      membershipState === "none",
  );

  let membershipCheckFailed = $derived(
    !!auth.token &&
      !currentHash.startsWith("/chat/") &&
      !currentHash.startsWith("/login") &&
      currentHash !== "/organization-setup" &&
      membershipState === "error",
  );

  function retryMembershipCheck() {
    if (auth.token) void checkMembership(auth.token);
  }
</script>

<svelte:window onhashchange={syncRoute} />

{#if waitingForMembership}
  <main
    class="flex min-h-screen items-center justify-center bg-[#F5F8FB]"
    aria-busy="true"
    aria-label="Checking organization membership"
  >
    <div class="h-12 w-12 animate-pulse rounded-full bg-gray-200"></div>
  </main>
{:else if membershipCheckFailed}
  <main class="flex min-h-screen items-center justify-center bg-[#F5F8FB] p-4">
    <section class="w-full max-w-lg rounded-xl border border-outline bg-white p-8 shadow-sm">
      <h1 class="text-xl font-bold">Could not check organization access</h1>
      <p class="mt-2 text-sm text-gray-600">{membershipError}</p>
      <button
        type="button"
        class="mt-5 rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-white hover:bg-primary/90"
        onclick={retryMembershipCheck}
      >
        Try again
      </button>
    </section>
  </main>
{:else if needsMembershipSetup}
  <main
    class="flex min-h-screen items-center justify-center bg-[#F5F8FB]"
    aria-busy="true"
    aria-label="Opening organization setup"
  >
    <div class="h-12 w-12 animate-pulse rounded-full bg-gray-200"></div>
  </main>
{:else}
  <Router {routes} />
{/if}