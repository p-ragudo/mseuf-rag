<script lang="ts">
  interface TopicItem {
    label: string;
    value: number;
  }

  interface Props {
    eyebrow?: string;
    title?: string;
    subtitle?: string;
    items: TopicItem[];
  }

  let {
    eyebrow = "QUESTION TOPICS",
    title = "Most frequent inquiries",
    subtitle = "Top categories across student conversations",
    items,
  }: Props = $props();

  let maxValue = $derived(Math.max(...items.map((i) => i.value), 1));
</script>

<div class="rounded-xl border border-outline bg-white p-6 shadow-sm">
  <h4 class="text-xs font-bold uppercase tracking-wider text-primary">
    {eyebrow}
  </h4>
  <h2 class="mt-1 text-2xl font-bold">{title}</h2>
  <p class="mt-1 text-sm text-gray-500">{subtitle}</p>

  <ul class="mt-6 flex flex-col gap-5">
    {#each items as item (item.label)}
      <li>
        <div class="flex flex-row items-baseline justify-between">
          <span class="text-[15px]">{item.label}</span>
          <span class="text-[15px] font-semibold text-gray-700"
            >{item.value}</span
          >
        </div>
        <div class="mt-2 h-2 w-full overflow-hidden rounded-full bg-gray-100">
          <div
            class="h-full rounded-full bg-primary transition-[width] duration-500 ease-out"
            style="width: {(item.value / maxValue) * 100}%"
          ></div>
        </div>
      </li>
    {/each}
  </ul>
</div>
