<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    label,
    value,
    hint = "",
    loading = false,
    icon,
  }: {
    label: string;
    value: string;
    hint?: string;
    loading?: boolean;
    icon: Snippet;
  } = $props();
</script>

<div
  class="flex flex-col justify-between rounded-xl border border-outline bg-white p-4 shadow-sm"
>
  <div class="flex flex-row items-start justify-between gap-3">
    <span class="text-sm">{label}</span>

    <div
      class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent text-primary"
    >
      {@render icon()}
    </div>
  </div>

  <div class="mt-3">
    <p
      class="text-3xl font-bold {loading ? 'animate-pulse text-gray-300' : ''}"
    >
      {value}
    </p>

    {#if hint}
      <p class="mt-1 text-xs text-gray-500">{hint}</p>
    {/if}
  </div>
</div>