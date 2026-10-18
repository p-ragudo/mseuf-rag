<script lang="ts">
  import type { Snippet } from "svelte";
  import Sidebar from "./SideBar.svelte";
  import Heading from "./Heading.svelte";

  let { children }: { children: Snippet } = $props();
</script>

<div class="flex h-dvh w-full flex-col-reverse md:flex-row">
  <Sidebar />

  <main class="min-h-0 min-w-0 flex-1 overflow-y-auto bg-[#f5f8fb]">
    <Heading />
    {@render children()}
  </main>
</div>
