<script lang="ts">
  import type { Snippet } from "svelte";

  let { children, style = "" }: { children?: Snippet; style?: string } =
    $props();
</script>

<div class={`bg-white rounded-lg border-outline border p-4 ${style}`}>
  {#if children}
    {@render children()}
  {/if}
</div>
