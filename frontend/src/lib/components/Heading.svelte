<script lang="ts">
  import { fly } from "svelte/transition";
  import { replace } from "svelte-spa-router";
  import DropDownIcon from "../icons/DropDownIcon.svelte";
  import ProfileMenu from "./ProfileMenu.svelte";
  import { auth, logout } from "../auth.svelte";

  type Profile = {
    id: string;
    name: string;
    initials: string;
  };

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
    {
      id: "1",
      name: "MSEUF",
      initials: "MS",
    },
    {
      id: "2",
      name: "UNI Org",
      initials: "UN",
    },
    {
      id: "3",
      name: "Test Organization",
      initials: "TO",
    },
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
  class="flex h-16 min-w-0 shrink-0 flex-row items-center justify-between gap-2 border-b-2 border-b-outline bg-white px-3 sm:gap-4 sm:px-4"
>
  <div class="flex flex-col justify-center">
    <h2 class="hidden text-xs font-bold uppercase tracking-wider text-primary sm:block">MSEUF RAG</h2>

    <h1 class="max-w-[60vw] text-sm font-semibold leading-tight sm:max-w-none sm:text-xl">
      Admissions Intelligence Hub
      <span class="hidden font-normal text-[#59616E] sm:inline">/ Admin workspace</span>
    </h1>
  </div>

  <div class="relative" bind:this={container}>
    <button
      type="button"
      aria-haspopup="menu"
      aria-expanded={open}
      class="flex min-w-0 flex-row items-center gap-2 rounded-md px-1 py-1 transition-colors duration-200 hover:cursor-pointer hover:bg-accent hover:text-primary sm:gap-3 sm:px-3"
      onclick={() => (open = !open)}
    >
      <div
        class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-xs font-bold text-primary sm:h-9 sm:w-9 sm:text-sm"
      >
        {initials}
      </div>

      <div class="hidden min-w-0 max-w-40 flex-col items-start sm:flex">
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
        <!-- <div
          class="[&>*]:!static [&>*]:!inset-auto [&>*]:!m-0 [&>*]:!w-full [&>*]:!rounded-none [&>*]:!border-0 [&>*]:!shadow-none"
        >
          <ProfileMenu title="User Menu" {profiles} onSelect={handleSelect} />
        </div> -->

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
