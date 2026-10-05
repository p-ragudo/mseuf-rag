<script lang="ts">
  import { tick } from "svelte";

  type Source = { title?: string; url?: string };
  type Message = {
    id: string;
    role: "user" | "assistant";
    content: string;
    sources?: Source[];
    error?: boolean;
  };

  let { params = {} }: { params?: { id?: string } } = $props();

  const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
  const orgId = $derived(params.id);

  let messages = $state<Message[]>([]);
  let input = $state("");
  let loading = $state(false);
  let sessionId = $state("");
  let listEl = $state<HTMLDivElement>();
  let inputEl = $state<HTMLTextAreaElement>();

  // Reset the conversation whenever the org changes.
  $effect(() => {
    if (!orgId) return;
    messages = [];
    sessionId = getSessionId(orgId);
  });

  function getSessionId(org: string): string {
    const key = `chat-session:${org}`;
    try {
      const existing = localStorage.getItem(key);
      if (existing) return existing;
      const created = crypto.randomUUID();
      localStorage.setItem(key, created);
      return created;
    } catch {
      return crypto.randomUUID();
    }
  }

  function newChat() {
    if (!orgId) return;
    try {
      localStorage.removeItem(`chat-session:${orgId}`);
    } catch {}
    messages = [];
    sessionId = getSessionId(orgId);
    inputEl?.focus();
  }

  async function scrollToBottom() {
    await tick();
    listEl?.scrollTo({ top: listEl.scrollHeight, behavior: "smooth" });
  }

  function resizeInput() {
    if (!inputEl) return;
    inputEl.style.height = "auto";
    inputEl.style.height = `${Math.min(inputEl.scrollHeight, 160)}px`;
  }

  async function send() {
    const content = input.trim();
    if (!content || loading || !orgId) return;

    const currentOrg = orgId;

    messages.push({ id: crypto.randomUUID(), role: "user", content });
    input = "";
    loading = true;
    await tick();
    resizeInput();
    scrollToBottom();

    try {
      const res = await fetch(`${API_URL}/chat/${currentOrg}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: content, session_id: sessionId }),
      });
      if (!res.ok) throw new Error(`Request failed (${res.status})`);
      const data = await res.json();

      if (currentOrg !== orgId) return; // org changed mid-request
      messages.push({
        id: crypto.randomUUID(),
        role: "assistant",
        content: data.answer,
        sources: data.sources,
      });
    } catch {
      if (currentOrg !== orgId) return;
      messages.push({
        id: crypto.randomUUID(),
        role: "assistant",
        content: "Sorry, something went wrong. Please try again.",
        error: true,
      });
    } finally {
      loading = false;
      scrollToBottom();
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }
</script>

<div class="flex h-screen flex-col bg-[#F5F8FB]">
  <!-- Header -->
  <header
    class="flex flex-row items-center justify-between gap-4 border-b-2 border-b-outline bg-white px-4 py-3"
  >
    <div class="flex flex-col justify-center">
      <h2 class="text-xs font-bold uppercase tracking-wider text-primary">
        Admissions Intelligence Hub
      </h2>
      <h1 class="text-xl font-semibold">Chat Assistant</h1>
    </div>
    <button
      type="button"
      class="flex flex-row items-center gap-2 rounded-lg border border-outline bg-[#F5F8FB] px-3 py-2 text-sm font-semibold shadow-sm transition-colors duration-200 hover:cursor-pointer hover:bg-accent hover:text-primary"
      onclick={newChat}
    >
      New chat
    </button>
  </header>

  <!-- Messages -->
  <div bind:this={listEl} class="flex-1 overflow-y-auto px-4 py-6">
    <div class="mx-auto flex max-w-3xl flex-col gap-4">
      {#if messages.length === 0}
        <div class="mt-16 flex flex-col items-center text-center">
          <div
            class="flex h-12 w-12 items-center justify-center rounded-full bg-accent text-sm font-bold text-primary"
          >
            AI
          </div>
          <h2 class="mt-4 text-2xl font-bold">How can I help you today?</h2>
          <p class="mt-1 text-sm text-gray-500">
            Ask me anything and I'll find the answer for you.
          </p>
        </div>
      {/if}

      {#each messages as message (message.id)}
        <div
          class="flex flex-row items-end gap-2 {message.role === 'user'
            ? 'justify-end'
            : 'justify-start'}"
        >
          {#if message.role === "assistant"}
            <div
              class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-xs font-bold text-primary"
            >
              AI
            </div>
          {/if}

          <div
            class="max-w-[85%] whitespace-pre-wrap rounded-xl px-4 py-2.5 text-sm leading-relaxed
              {message.role === 'user'
              ? 'bg-primary text-white'
              : message.error
                ? 'border border-red-200 bg-red-50 text-red-700'
                : 'border border-outline bg-white text-gray-800 shadow-sm'}"
          >
            {message.content}

            {#if message.sources?.length}
              <div
                class="mt-3 border-t border-outline pt-2 text-xs text-gray-500"
              >
                <p class="mb-1 font-bold uppercase tracking-wider text-primary">
                  Sources
                </p>
                <ul class="space-y-0.5">
                  {#each message.sources as source}
                    <li>
                      {#if source.url}
                        <a
                          href={source.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          class="font-semibold text-primary hover:underline"
                        >
                          {source.title ?? source.url}
                        </a>
                      {:else}
                        {source.title}
                      {/if}
                    </li>
                  {/each}
                </ul>
              </div>
            {/if}
          </div>
        </div>
      {/each}

      {#if loading}
        <div class="flex flex-row items-end gap-2">
          <div
            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-xs font-bold text-primary"
          >
            AI
          </div>
          <div
            class="flex gap-1 rounded-xl border border-outline bg-white px-4 py-3 shadow-sm"
          >
            <span
              class="h-2 w-2 animate-bounce rounded-full bg-primary opacity-60"
            ></span>
            <span
              class="h-2 w-2 animate-bounce rounded-full bg-primary opacity-60 [animation-delay:150ms]"
            ></span>
            <span
              class="h-2 w-2 animate-bounce rounded-full bg-primary opacity-60 [animation-delay:300ms]"
            ></span>
          </div>
        </div>
      {/if}
    </div>
  </div>

  <!-- Input -->
  <footer class="border-t-2 border-t-outline bg-white px-4 py-3">
    <div class="mx-auto flex max-w-3xl flex-row items-end gap-2">
      <textarea
        bind:this={inputEl}
        bind:value={input}
        oninput={resizeInput}
        onkeydown={onKeydown}
        rows="1"
        placeholder="Type your question..."
        class="flex-1 resize-none rounded-md border border-outline px-4 py-2.5 text-sm outline-none focus:border-primary"
      ></textarea>
      <button
        type="button"
        onclick={send}
        disabled={loading || !input.trim()}
        class="rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-white transition-opacity duration-200 hover:cursor-pointer disabled:cursor-not-allowed disabled:opacity-60"
      >
        Send
      </button>
    </div>
    <p class="mx-auto mt-2 max-w-3xl text-xs text-gray-500">
      Press Enter to send, Shift + Enter for a new line.
    </p>
  </footer>
</div>
