<script lang="ts">
  import { fly } from "svelte/transition";
  import { replace } from "svelte-spa-router";
  import DropDownIcon from "../icons/DropDownIcon.svelte";
  import ProfileMenu from "./ProfileMenu.svelte";
  import { auth, logout } from "../auth.svelte";

  type Profile = { id: string; name: string; initials: string };

  let open = $state(false);
  let container: HTMLDivElement | undefined = $state();

  let displayName = $derived(
    auth.user
      ? `${auth.user.first_name} ${auth.user.last_name}`
      : "User Profile",
  );
  let initials = $derived(
    auth.user
      ? `${auth.user.first_name[0] ?? ""}${auth.user.last_name[0] ?? ""}`.toUpperCase()
      : "UP",
  );
  let subtitle = $derived(auth.user?.email ?? "Role");

  const profiles: Profile[] = [
    { id: "1", name: "User Profile 1", initials: "UP" },
    { id: "2", name: "User Profile 2", initials: "UP" },
    { id: "3", name: "User Profile 3", initials: "UP" },
  ];

  function handleSelect(profile: Profile) {
    console.log("selected", profile);
    open = false;
  }

  function handleLogout() {
    open = false;
    logout();
    replace("/login");
  }

  function handleWindowClick(e: MouseEvent) {
    if (open && container && !container.contains(e.target as Node)) {
      open = false;
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Escape") open = false;
  }
</script>

<svelte:window onclick={handleWindowClick} onkeydown={handleKeydown} />

<header
  class="flex flex-row items-center justify-between gap-4 border-b-2 border-b-outline bg-white px-4 py-2"
>
  <div class="flex flex-col justify-center">
    <h2 class="text-primary">UNI ORG</h2>
    <h1 class="text-xl font-semibold">
      Admissions Intelligence Hub
      <span class="font-normal text-[#59616E]">/ Rooney Admin</span>
    </h1>
  </div>

  <div class="relative" bind:this={container}>
    <button
      type="button"
      aria-haspopup="menu"
      aria-expanded={open}
      class="flex flex-row items-center gap-3 rounded-md px-3 py-1 transition-colors duration-200 hover:cursor-pointer hover:bg-accent hover:text-primary"
      onclick={() => (open = !open)}
    >
      <div
        class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-sm font-bold text-primary"
      >
        {initials}
      </div>
      <div class="flex min-w-0 max-w-40 flex-col items-start">
        <span class="w-full truncate text-sm font-bold">{displayName}</span>
        <span class="w-full truncate text-sm font-normal text-[#59616E]">
          {subtitle}
        </span>
      </div>
      <DropDownIcon />
    </button>

    {#if open}
      <div
        transition:fly={{ y: -8, duration: 150 }}
        class="absolute right-0 top-full z-50 mt-2 w-64 overflow-hidden rounded-lg border border-outline bg-white shadow-lg"
      >
        <div
          class="[&>*]:!static [&>*]:!inset-auto [&>*]:!m-0 [&>*]:!w-full [&>*]:!rounded-none [&>*]:!border-0 [&>*]:!shadow-none"
        >
          <ProfileMenu title="User Menu" {profiles} onSelect={handleSelect} />
        </div>

        <div class="border-t border-outline p-1">
          <button
            type="button"
            class="flex w-full flex-row items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-semibold text-red-600 transition-colors hover:cursor-pointer hover:bg-red-50"
            onclick={handleLogout}
          >
            <svg
              class="h-4 w-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
            Log out
          </button>
        </div>
      </div>
    {/if}
  </div>
</header>
