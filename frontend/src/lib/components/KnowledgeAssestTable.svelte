<!-- KnowledgeAssetsTable.svelte -->
<script lang="ts">
  interface DocumentAsset {
    title: string;
    source: string;
    chunks: number;
    accessed: number;
    lastAccessed: string;
  }

  interface Props {
    eyebrow?: string;
    title?: string;
    subtitle?: string;
    viewAllLabel?: string;
    onViewAll?: () => void;
    documents: DocumentAsset[];
  }

  let {
    eyebrow = "KNOWLEDGE PERFORMANCE",
    title = "Top retrieved knowledge assets",
    subtitle = "Documents most often cited in AI responses",
    viewAllLabel = "View library",
    onViewAll,
    documents,
  }: Props = $props();

  function formatNumber(n: number) {
    return n.toLocaleString();
  }
</script>

<div class="rounded-xl border border-outline bg-white shadow-sm">
  <div class="flex items-start justify-between p-6 pb-4">
    <div>
      <h4 class="text-xs font-bold uppercase tracking-wider text-primary">
        {eyebrow}
      </h4>
      <h2 class="mt-1 text-2xl font-bold">{title}</h2>
      <p class="mt-1 text-sm text-gray-500">{subtitle}</p>
    </div>
    {#if onViewAll}
      <button
        class="flex flex-row items-center gap-1 text-sm font-semibold text-primary hover:bg-accent hover:cursor-pointer px-3 py-2 rounded-lg transition-colors duration-150"
        onclick={onViewAll}
      >
        {viewAllLabel}
        <svg
          width="14"
          height="14"
          viewBox="0 0 14 14"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path
            d="M2.917 7H11.083"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
          <path
            d="M7 2.917L11.083 7L7 11.083"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </button>
    {/if}
  </div>

  <table class="w-full border-collapse">
    <thead>
      <tr class="border-y border-outline bg-gray-50/60">
        <th
          class="px-6 py-3 text-left text-xs font-bold uppercase tracking-wider text-gray-500"
          >Document Title</th
        >
        <th
          class="px-6 py-3 text-left text-xs font-bold uppercase tracking-wider text-gray-500"
          >Source</th
        >
        <th
          class="px-6 py-3 text-right text-xs font-bold uppercase tracking-wider text-gray-500"
          >Chunks</th
        >
        <th
          class="px-6 py-3 text-right text-xs font-bold uppercase tracking-wider text-gray-500"
          >Accessed</th
        >
        <th
          class="px-6 py-3 text-right text-xs font-bold uppercase tracking-wider text-gray-500"
          >Last Accessed</th
        >
      </tr>
    </thead>
    <tbody>
      {#each documents as doc (doc.title)}
        <tr class="border-b border-outline last:border-b-0">
          <td class="px-6 py-4">
            <div class="flex flex-row items-center gap-3">
              <svg
                width="18"
                height="18"
                viewBox="0 0 18 18"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
                class="shrink-0"
              >
                <path
                  d="M10.5 1.5H4.5C4.10218 1.5 3.72064 1.65804 3.43934 1.93934C3.15804 2.22064 3 2.60218 3 3V15C3 15.3978 3.15804 15.7794 3.43934 16.0607C3.72064 16.342 4.10218 16.5 4.5 16.5H13.5C13.8978 16.5 14.2794 16.342 14.5607 16.0607C14.842 15.7794 15 15.3978 15 15V6L10.5 1.5Z"
                  stroke="#7A1F2B"
                  stroke-width="1.25"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
                <path
                  d="M10.5 1.5V6H15"
                  stroke="#7A1F2B"
                  stroke-width="1.25"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
              <span class="text-sm font-semibold">{doc.title}</span>
            </div>
          </td>
          <td class="px-6 py-4">
            <span
              class="inline-block rounded-md border border-outline px-3 py-1 text-xs text-gray-500"
              >{doc.source}</span
            >
          </td>
          <td class="px-6 py-4 text-right text-sm">{doc.chunks}</td>
          <td class="px-6 py-4 text-right text-sm"
            >{formatNumber(doc.accessed)}</td
          >
          <td class="px-6 py-4 text-right text-sm text-gray-500"
            >{doc.lastAccessed}</td
          >
        </tr>
      {:else}
        <tr>
          <td colspan="5" class="px-6 py-8 text-center text-sm text-gray-500">
            No documents yet
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>
