<script lang="ts">
  import type { Snippet } from "svelte";
  import { Sender } from "../../types/sender";

  let { sender, children }: { sender: Sender; children: Snippet } = $props();
</script>

<div
  class="flex items-end gap-2 mx-2 my-1 {sender === Sender.ME
    ? 'flex-row-reverse'
    : 'flex-row'}"
>
  {#if sender === Sender.AI}
    <img
      src="/icon.png"
      alt="AI"
      class="h-8 w-8 shrink-0 rounded-full ring-2 ring-red-100 overflow-visible"
    />
  {/if}

  <div
    class="max-w-[75%] px-3.5 py-2.5 rounded-2xl text-sm leading-relaxed wrap-break-word shadow-sm
      {sender === Sender.ME
      ? 'bg-sky-500 text-white rounded-br-md'
      : 'bg-gray-100 text-gray-900 rounded-bl-md'}"
  >
    {@render children()}
  </div>
</div>
