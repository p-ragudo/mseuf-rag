<script lang="ts">
  import { onMount } from "svelte";
  import type { Snippet } from "svelte";
  import Sidebar from "./SideBar.svelte";
  import Heading from "./Heading.svelte";
  import {
    listUserOrganizations,
    orgState,
    setActiveOrganization,
  } from "../org.svelte";

  let { children }: { children: Snippet } = $props();

  onMount(async () => {
    const organizations = await listUserOrganizations();
    const activeOrganization =
      organizations.find((org) => org.id === orgState.org?.id) ??
      organizations[0] ??
      null;
    setActiveOrganization(activeOrganization);
  });
</script>

<div class="flex h-dvh w-full flex-col-reverse md:flex-row">
  <Sidebar />

  <main class="min-h-0 min-w-0 flex-1 overflow-y-auto bg-[#f5f8fb]">
    <Heading />
    {@render children()}
  </main>
</div>
