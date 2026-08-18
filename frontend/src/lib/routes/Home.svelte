<script lang="ts">
  import Header from "../components/Header.svelte";
  import SendIcon from "../icons/SendIcon.svelte";
  import ErrorChatBubble from "../components/ErrorChatBubble.svelte";
  import ChatBubble from "../components/ChatBubble.svelte";
  import { Sender } from "../../types/sender";

  let message: string = "";
  let textareaEl: HTMLTextAreaElement;

  // Responsize textarea
  function autoResize() {
    textareaEl.style.height = "auto";
    textareaEl.style.height = Math.min(textareaEl.scrollHeight, 160) + "px";
  }
  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }
  function handleSubmit() {
    if (!message.trim()) return;
    console.log("Sending:", message);
    message = "";
    requestAnimationFrame(autoResize);
  }
</script>

<main class="flex flex-col h-dvh">
  <Header />

  <div class="flex-1 min-h-0 overflow-y-auto">
    <div class="flex min-h-full flex-col justify-end"></div>
  </div>

  <footer class="flex flex-row items-end gap-2 p-3 border-t border-gray-200">
    <textarea
      bind:this={textareaEl}
      bind:value={message}
      on:input={autoResize}
      on:keydown={handleKeydown}
      placeholder="Type your message..."
      name="prompt"
      id="promptMessage"
      rows="1"
      class="flex-1 resize-none overflow-y-auto rounded-lg border border-gray-300 p-3 font-sans text-sm focus:outline-none focus:ring-2 focus:ring-red-900"
    ></textarea>

    <button
      on:click={handleSubmit}
      class="shrink-0 flex items-center justify-center p-2"
    >
      <SendIcon size={28} />
    </button>
  </footer>
</main>
