<script lang="ts">
  let {
    data = [],
    labels = [],
    color = "#3b82f6",
  }: { data: number[]; labels: string[]; color?: string } = $props();
  let max = $derived(Math.max(...data, 1));
</script>

<div class="flex items-end gap-3 h-40">
  {#each data as v, i}
    <div class="flex-1 flex flex-col items-center gap-2 group">
      <span
        class="text-xs text-gray-500 opacity-0 group-hover:opacity-100 transition-opacity"
        >{v}</span
      >
      <div
        class="w-full rounded-t-md transition-all"
        style="height: {(v / max) * 100}%; background-color: {color}"
      ></div>
      <span class="text-xs text-gray-400">{labels[i]}</span>
    </div>
  {/each}
</div>
