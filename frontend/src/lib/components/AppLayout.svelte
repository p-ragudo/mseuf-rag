<script lang="ts">
  import { onMount } from "svelte";
  import type { Snippet } from "svelte";
  import Sidebar from "./SideBar.svelte";
  import Heading from "./Heading.svelte";

  let { children }: { children: Snippet } = $props();
</script>

<div class="flex h-screen w-full">
  <Sidebar />

  <main class="min-w-0 flex-1 overflow-y-auto bg-[#f5f8fb]">
    <Heading />
    {@render children()}
  </main>
</div>
