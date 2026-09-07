<script lang="ts">
  import AdminHeader from "../components/AdminHeader.svelte";
  import AdminSideBar from "../components/AdminSideBar.svelte";
  import AdminDashboard from "../components/AdminDashboard.svelte";
  import ChunkUpdates from "../components/ChunkUpdates.svelte";

  let currentIndex: number = $state(0);
</script>

<main class="w-screen h-screen flex flex-col lg:flex-row overflow-hidden">
  <AdminHeader />
  <AdminSideBar bind:currentIndex />

  <div class="flex-1 overflow-y-auto">
    {#if currentIndex == 0}
      <AdminDashboard />
    {:else if currentIndex == 1}
      <ChunkUpdates />
    {:else if currentIndex == 2}
      <div>Setting</div>
    {:else if currentIndex == 3}
      <div>Avatar</div>
    {/if}
  </div>
</main>
