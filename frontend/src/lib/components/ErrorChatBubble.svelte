<script lang="ts">
  import { Sender } from "../../types/sender";
  import UnfilledRequiredParameters from "../../errors/UnfilledRequiredParameters";

  export let sender: Sender;
  export let message: string;

  function validate() {
    const missingParameters: string[] = [];
    if (!message?.trim()) missingParameters.push("message");
    if (sender === null || sender === undefined)
      missingParameters.push("sender");
    if (missingParameters.length > 0) {
      const error = new UnfilledRequiredParameters(missingParameters);
      console.error(error);
      throw error;
    }
  }
  validate();
</script>

<div
  class="flex items-end gap-2 px-3 py-1.5 {sender === Sender.ME
    ? 'flex-row-reverse'
    : 'flex-row'}"
>
  <div
    class="flex max-w-[75%] items-start gap-3 rounded-2xl border border-red-200
      bg-red-50 px-4 py-3 shadow-sm
      {sender === Sender.ME ? 'rounded-br-md' : 'rounded-bl-md'}"
  >
    <div
      class="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center
        rounded-full bg-red-100 text-red-600"
    >
      <svg
        class="h-4 w-4"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        stroke-width="2"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          d="M12 9v3.75m0 3.75h.008v.008H12v-.008ZM21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"
        />
      </svg>
    </div>

    <div class="min-w-0">
      <p class="text-sm font-semibold text-red-800">Something went wrong</p>
      <p class="mt-1 text-sm leading-relaxed text-red-700">
        {message}
      </p>
    </div>
  </div>
</div>
