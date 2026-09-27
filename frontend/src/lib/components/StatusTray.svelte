<script lang="ts">
  import InquiryIcon from "../icons/InquiryIcon.svelte";
  import ArrowUpIcon from "../icons/ArrowUpIcon.svelte";
  import ArrowDownIcon from "../icons/ArrowDownIcon.svelte";
  import SessionIcon from "../icons/SessionIcon.svelte";
  import ConfidentAnswersIcon from "../icons/ConfidentAnswersIcon.svelte";
  import SatisfactionIcon from "../icons/SatisfactionIcon.svelte";
  import LatencyIcon from "../icons/LatencyIcon.svelte";
  import WhiteCard from "./WhiteCard.svelte";
</script>

<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
  <WhiteCard>
    <div class="flex flex-row items-start justify-between">
      <h4 class="text-xs">Conversation sessions</h4>
      <div class="p-3 bg-accent rounded-lg"><SessionIcon /></div>
    </div>
    <h1 class="font-semibold text-2xl flex flex-row items-end gap-2">
      2,847 <span
        class="flex flex-row items-center text-sm font-normal text-[#097349]"
      >
        <ArrowUpIcon /> +12.8%</span
      >
    </h1>
    <p class="text-xs text-gray-500">2,050 external · 797 internal</p>
  </WhiteCard>

  <WhiteCard>
    <div class="flex flex-row items-start justify-between">
      <h4 class="text-xs">Inquiry & engagement</h4>
      <div class="p-3 bg-accent rounded-lg"><InquiryIcon /></div>
    </div>
    <h1 class="font-semibold text-2xl flex flex-row items-end gap-2">
      18,392
      <span
        class="flex flex-row items-center text-sm font-normal text-[#097349]"
      >
        <ArrowUpIcon /> +12.8%</span
      >
    </h1>
    <p class="text-xs text-gray-500">6.5 msgs / session · 2m 45s avg</p>
  </WhiteCard>

  <WhiteCard>
    <div class="flex flex-row items-start justify-between">
      <h4 class="text-xs">High-confidence answers</h4>
      <div class="p-3 bg-accent rounded-lg"><ConfidentAnswersIcon /></div>
    </div>
    <h1 class="font-semibold text-2xl flex flex-row items-end gap-2">
      87.4% <span
        class="flex flex-row items-center text-sm font-normal text-[#097349]"
      >
        <ArrowUpIcon /> +3.2%</span
      >
    </h1>
    <p class="text-xs text-gray-500">Above 85% RAG confidence · 12.6% low</p>
  </WhiteCard>

  <WhiteCard>
    <div class="flex flex-row items-start justify-between">
      <h4 class="text-xs">Cost & latency</h4>
      <div class="p-3 bg-accent rounded-lg"><SatisfactionIcon /></div>
    </div>
    <h1 class="font-semibold text-2xl flex flex-row items-end gap-2">
      92.1% <span
        class="flex flex-row items-center text-sm font-normal text-[#097349]"
      >
        <ArrowUpIcon /> +1.6%</span
      >
    </h1>
    <p class="text-xs text-gray-500">1,204 positive · 103 negative</p>
  </WhiteCard>

  <WhiteCard>
    <div class="flex flex-row items-start justify-between">
      <h4 class="text-xs">Cost & latency</h4>
      <div class="p-3 bg-accent rounded-lg"><LatencyIcon /></div>
    </div>
    <h1 class="font-semibold text-2xl flex flex-row items-end gap-2">
      620ms
      <span
        class="flex flex-row items-center text-sm font-normal text-[#097349]"
      >
        <ArrowDownIcon /> +12.8%</span
      >
    </h1>
    <p class="text-xs text-gray-500">2.4M tokens · 38% cache hits</p>
  </WhiteCard>
</div>
