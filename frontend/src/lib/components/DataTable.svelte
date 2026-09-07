<script lang="ts">
  let {
    columns = [],
    rows = [],
  }: {
    columns: { key: string; label: string }[];
    rows: Record<string, any>[];
  } = $props();

  let sortKey = $state<string | null>(null);
  let sortAsc = $state(true);

  let sortedRows = $derived.by(() => {
    if (!sortKey) return rows;
    return [...rows].sort((a, b) => {
      let av = a[sortKey!],
        bv = b[sortKey!];
      if (av < bv) return sortAsc ? -1 : 1;
      if (av > bv) return sortAsc ? 1 : -1;
      return 0;
    });
  });

  function toggleSort(key: string) {
    if (sortKey === key) {
      sortAsc = !sortAsc;
    } else {
      sortKey = key;
      sortAsc = true;
    }
  }
</script>

<table class="w-full text-sm">
  <thead>
    <tr class="border-b border-gray-200">
      {#each columns as col}
        <th
          class="text-left py-2 px-3 text-gray-500 font-medium cursor-pointer select-none"
          onclick={() => toggleSort(col.key)}
        >
          {col.label}
          {#if sortKey === col.key}
            <span class="text-xs">{sortAsc ? "▲" : "▼"}</span>
          {/if}
        </th>
      {/each}
    </tr>
  </thead>
  <tbody>
    {#each sortedRows as row}
      <tr class="border-b border-gray-100 hover:bg-gray-50">
        {#each columns as col}
          <td class="py-2 px-3 text-gray-700">{row[col.key]}</td>
        {/each}
      </tr>
    {/each}
  </tbody>
</table>
