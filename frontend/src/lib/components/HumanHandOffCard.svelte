<!-- HumanHandoffCard.svelte -->
<script lang="ts">
  interface PendingInquiry {
    question: string;
    confidence: number;
    category: string;
  }

  interface Props {
    eyebrow?: string;
    title?: string;
    subtitle?: string;
    openCount: number;
    inquiries: PendingInquiry[];
    reviewLabel?: string;
    onReview?: () => void;
  }

  let {
    eyebrow = "NEEDS ATTENTION",
    title = "Human handoff",
    subtitle = "Low-confidence questions waiting for review",
    openCount,
    inquiries,
    reviewLabel = "Review escalation queue",
    onReview,
  }: Props = $props();
</script>

<div class="rounded-xl border border-outline bg-white p-6 shadow-sm">
  <h4 class="text-xs font-bold uppercase tracking-wider text-primary">
    {eyebrow}
  </h4>
  <h2 class="mt-1 text-2xl font-bold">{title}</h2>
  <p class="mt-1 text-sm text-gray-500">{subtitle}</p>

  <div class="mt-6 flex flex-row items-baseline gap-2">
    <span class="text-5xl font-bold text-gray-900">{openCount}</span>
    <span class="text-sm text-gray-500">open inquiries</span>
  </div>

  <div class="mt-6 flex flex-col gap-3">
    {#each inquiries as item}
      <div
        class="border-l-4 border-[#C89B3C] bg-[#FCEFCB] py-3 pl-4 pr-4 rounded-r-md"
      >
        <p class="text-sm font-medium text-gray-900">{item.question}</p>
        <p class="mt-1.5 text-sm text-[#8A6A1F]">
          {item.confidence}% confidence · {item.category}
        </p>
      </div>
    {/each}
  </div>

  {#if onReview}
    <button
      class="mt-4 flex w-full flex-row items-center justify-center gap-2 rounded-md border border-outline bg-[#F5F8FB] px-4 py-3 text-sm font-semibold hover:bg-accent hover:text-primary transition-colors duration-200"
      onclick={onReview}
    >
      {reviewLabel}
      <svg
        width="16"
        height="16"
        viewBox="0 0 16 16"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path
          d="M3.333 8H12.667"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
        <path
          d="M8 3.333L12.667 8L8 12.667"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    </button>
  {/if}
</div>
