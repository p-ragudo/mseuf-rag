<!-- LowConfidenceQueryQueue.svelte -->
<script lang="ts">
  import { fly } from "svelte/transition";

  interface QueryItem {
    id: string;
    timestamp: string;
    question: string;
    confidence: number;
    category: string;
    status: string;
  }

  interface Props {
    eyebrow?: string;
    title?: string;
    subtitle?: string;
    items: QueryItem[];
    actions?: string[];
    onAction?: (item: QueryItem, action: string) => void;
  }

  let {
    eyebrow = "HUMAN IN THE LOOP",
    title = "Low-confidence query queue",
    subtitle = "Prioritize unresolved questions before they become admissions roadblocks.",
    items,
    actions = ["Assign to me", "Reassign", "Mark resolved", "Dismiss"],
    onAction,
  }: Props = $props();

  let searchTerm = $state("");
  let openActionId = $state<string | null>(null);

  let filteredItems = $derived(
    searchTerm.trim() === ""
      ? items
      : items.filter((item) =>
          item.question.toLowerCase().includes(searchTerm.trim().toLowerCase()),
        ),
  );

  function toggleAction(id: string) {
    openActionId = openActionId === id ? null : id;
  }

  function closeAction() {
    openActionId = null;
  }

  function selectAction(item: QueryItem, action: string) {
    onAction?.(item, action);
    closeAction();
  }
</script>

<svelte:window onclick={closeAction} />

<div class="rounded-xl border border-outline bg-white shadow-sm">
  <div class="flex items-start justify-between gap-4 p-6 pb-4">
    <div>
      <h4 class="text-xs font-bold uppercase tracking-wider text-primary">
        {eyebrow}
      </h4>
      <h2 class="mt-1 text-2xl font-bold">{title}</h2>
      <p class="mt-1 text-sm text-gray-500">{subtitle}</p>
    </div>

    <div class="relative w-72 shrink-0">
      <svg
        width="16"
        height="16"
        viewBox="0 0 16 16"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
      >
        <circle cx="7" cy="7" r="5" stroke="currentColor" stroke-width="1.25" />
        <path
          d="M11 11L14 14"
          stroke="currentColor"
          stroke-width="1.25"
          stroke-linecap="round"
        />
      </svg>
      <input
        type="text"
        bind:value={searchTerm}
        placeholder="Search inquiries..."
        class="w-full rounded-md border border-outline py-2 pl-9 pr-3 text-sm outline-none focus:border-primary"
      />
    </div>
  </div>

  <table class="w-full border-collapse">
    <thead>
      <tr class="border-y border-outline bg-gray-50/60">
        <th
          class="px-6 py-3 text-left text-xs font-bold uppercase tracking-wider text-gray-500"
          >Timestamp</th
        >
        <th
          class="px-6 py-3 text-left text-xs font-bold uppercase tracking-wider text-gray-500"
          >Student Question</th
        >
        <th
          class="px-6 py-3 text-left text-xs font-bold uppercase tracking-wider text-gray-500"
          >Confidence</th
        >
        <th
          class="px-6 py-3 text-left text-xs font-bold uppercase tracking-wider text-gray-500"
          >Category</th
        >
        <th
          class="px-6 py-3 text-left text-xs font-bold uppercase tracking-wider text-gray-500"
          >Status</th
        >
        <th
          class="px-6 py-3 text-right text-xs font-bold uppercase tracking-wider text-gray-500"
          >Action</th
        >
      </tr>
    </thead>
    <tbody>
      {#each filteredItems as item (item.id)}
        <tr class="border-b border-outline last:border-b-0">
          <td class="whitespace-nowrap px-6 py-4 text-sm text-gray-500"
            >{item.timestamp}</td
          >
          <td class="px-6 py-4 text-sm">{item.question}</td>
          <td class="px-6 py-4">
            <span
              class="inline-block rounded-md bg-[#FCEFCB] px-3 py-1 text-sm font-semibold text-[#8A6A1F]"
            >
              {item.confidence}%
            </span>
          </td>
          <td class="px-6 py-4">
            <span
              class="inline-block rounded-md border border-outline px-3 py-1 text-sm text-gray-600"
            >
              {item.category}
            </span>
          </td>
          <td class="px-6 py-4 text-sm text-gray-500">{item.status}</td>
          <td class="px-6 py-4 text-right">
            <div class="relative inline-block text-left">
              <button
                class="flex flex-row items-center gap-2 rounded-md border border-outline bg-[#F5F8FB] px-3 py-2 text-sm font-semibold hover:bg-accent hover:text-primary transition-colors duration-200"
                onclick={(e) => {
                  e.stopPropagation();
                  toggleAction(item.id);
                }}
              >
                Take action
                <svg
                  width="12"
                  height="12"
                  viewBox="0 0 12 12"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <path
                    d="M3 4.5L6 7.5L9 4.5"
                    stroke="currentColor"
                    stroke-width="1.25"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
              </button>

              {#if openActionId === item.id}
                <div
                  transition:fly={{ y: -8, duration: 150 }}
                  class="absolute right-0 mt-2 w-44 rounded-md border border-outline bg-white shadow-lg z-10"
                >
                  <ul class="py-1">
                    {#each actions as action}
                      <li>
                        <button
                          class="w-full text-left px-4 py-2 text-sm hover:bg-accent hover:text-primary transition-colors duration-200"
                          onclick={() => selectAction(item, action)}
                        >
                          {action}
                        </button>
                      </li>
                    {/each}
                  </ul>
                </div>
              {/if}
            </div>
          </td>
        </tr>
      {:else}
        <tr>
          <td colspan="6" class="px-6 py-8 text-center text-sm text-gray-500">
            No inquiries match your search
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>
