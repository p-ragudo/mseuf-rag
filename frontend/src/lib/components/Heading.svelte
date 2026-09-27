<script lang="ts">
  import { fly } from "svelte/transition";
  import DropDownIcon from "../icons/DropDownIcon.svelte";
  import ProfileMenu from "./ProfileMenu.svelte";

  let open: boolean = $state(false);

  const profiles = [
    { id: "1", name: "User Profile 1", initials: "UP" },
    { id: "2", name: "User Profile 2", initials: "UP" },
    { id: "3", name: "User Profile 3", initials: "UP" },
  ];

  function toggleDropdown() {
    open = !open;
  }

  function closeDropdown() {
    open = false;
  }

  function handleSelect(profile: (typeof profiles)[number]) {
    console.log("selected", profile);
    // e.g. switch active profile, close dropdown, etc.
  }
</script>

<svelte:window onclick={closeDropdown} />

<header
  class="flex flex-row items-center justify-between gap-4 border-b-2 border-b-outline px-4 py-2 bg-white"
>
  <div class="flex flex-col justify-center">
    <h2 class="text-primary">UNI ORG</h2>
    <h1 class="text-xl font-semibold">
      Admissions Intelligence Hub <span class="font-normal text-[#59616E]"
        >/ Rooney Admin</span
      >
    </h1>
  </div>
  <div class="relative">
    <button
      class="flex flex-row items-center gap-3 hover:bg-accent hover:text-primary hover:cursor-pointer rounded-md transition-colors duration-200 px-3 py-1"
      onclick={(e) => {
        e.stopPropagation();
        toggleDropdown();
      }}
    >
      <div class="font-bold text-primary rounded-full bg-accent p-2">UP</div>
      <div class="flex flex-col items-start">
        <h1 class="text-sm font-bold">User Profile</h1>
        <h2 class="text-sm font-normal text-[#59616E]">Role</h2>
      </div>
      <DropDownIcon />
    </button>

    {#if open}
      <div transition:fly={{ y: -8, duration: 150 }}>
        <ProfileMenu title="User Menu" {profiles} onSelect={handleSelect} />
      </div>
    {/if}
  </div>
</header>
