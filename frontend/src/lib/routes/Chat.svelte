<script lang="ts">
  import { tick } from "svelte";
  import { marked } from "marked";
  import DOMPurify from "dompurify";

  type Source = {
    title?: string;
    url?: string;
  };

  type Message = {
    id: string;
    role: "user" | "assistant";
    content: string;
    sources?: Source[];
    error?: boolean;
  };

  type QueryResponse = {
    query: string;
    answer: string;
    is_cached?: boolean;
    source?: string;
    sources?: Source[];
    contexts?: unknown[];
  };

  // Gets :id from the svelte-spa-router route
  let { params = {} }: { params?: { id?: string } } = $props();

  const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

  // Organization ID from the route
  const orgId = $derived(params.id);

  let messages = $state<Message[]>([]);
  let input = $state("");
  let loading = $state(false);
  let sessionId = $state("");
  let listEl = $state<HTMLDivElement>();
  let inputEl = $state<HTMLTextAreaElement>();

  // Reset the conversation whenever the organization changes.
  $effect(() => {
    if (!orgId) return;

    console.log("Current organization ID:", orgId);

    messages = [];
    sessionId = getSessionId(orgId);
  });

  function getSessionId(org: string): string {
    const key = `chat-session:${org}`;

    try {
      const existing = localStorage.getItem(key);

      if (existing) {
        return existing;
      }

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

    listEl?.scrollTo({
      top: listEl.scrollHeight,
      behavior: "smooth",
    });
  }

  function resizeInput() {
    if (!inputEl) return;

    inputEl.style.height = "auto";
    inputEl.style.height = `${Math.min(inputEl.scrollHeight, 160)}px`;
  }

  function renderMarkdown(content: string): string {
    const html = marked.parse(content, {
      breaks: true,
      gfm: true,
    });

    return DOMPurify.sanitize(html as string);
  }

  async function send() {
    const content = input.trim();

    if (!content || loading || !orgId) return;

    // Keep the values used by this request.
    // This prevents an old request from updating a new organization chat.
    const currentOrg = orgId;
    const currentSession = sessionId;

    // Add user's message immediately.
    messages.push({
      id: crypto.randomUUID(),
      role: "user",
      content,
    });

    // Clear input.
    input = "";

    // Start loading state.
    loading = true;

    await tick();

    resizeInput();
    scrollToBottom();

    try {
      const response = await fetch(`${API_URL}/query/${currentOrg}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query: content,
          org_1: Number(currentOrg),
          top_k: 5,
          session_id: currentSession,
        }),
      });

      if (!response.ok) {
        let errorMessage = `Request failed (${response.status})`;

        try {
          const errorData = await response.json();

          if (typeof errorData.detail === "string") {
            errorMessage = errorData.detail;
          } else if (Array.isArray(errorData.detail)) {
            errorMessage = errorData.detail
              .map((error: { msg?: string }) => error.msg ?? "Validation error")
              .join(", ");
          }
        } catch {
          // Response wasn't JSON.
        }

        throw new Error(errorMessage);
      }

      const data: QueryResponse = await response.json();

      // Don't update the old chat if the user changed organizations.
      if (currentOrg !== orgId) return;

      messages.push({
        id: crypto.randomUUID(),
        role: "assistant",
        content: data.answer,
        sources: data.sources,
      });
    } catch (error) {
      // Don't update the old chat if the user changed organizations.
      if (currentOrg !== orgId) return;

      messages.push({
        id: crypto.randomUUID(),
        role: "assistant",
        content:
          error instanceof Error
            ? error.message
            : "Sorry, something went wrong. Please try again.",
        error: true,
      });
    } finally {
      loading = false;

      await scrollToBottom();
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

      <span class="text-xs text-gray-500">
        Organization ID: {orgId ?? "Unknown"}
      </span>
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
            class="max-w-[85%] rounded-xl px-4 py-3 text-sm leading-relaxed
              {message.role === 'user'
              ? 'bg-primary text-white'
              : message.error
                ? 'border border-red-200 bg-red-50 text-red-700'
                : 'border border-outline bg-white text-gray-800 shadow-sm'}"
          >
            {#if message.role === "assistant" && !message.error}
              <div class="markdown-content">
                {@html renderMarkdown(message.content)}
              </div>
            {:else}
              <div class="whitespace-pre-wrap">
                {message.content}
              </div>
            {/if}

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
        disabled={loading || !input.trim() || !orgId}
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

<style>
  :global(.markdown-content) {
    line-height: 1.7;
  }

  :global(.markdown-content p) {
    margin: 0 0 0.75rem;
  }

  :global(.markdown-content p:last-child) {
    margin-bottom: 0;
  }

  :global(.markdown-content h1) {
    margin: 1rem 0 0.5rem;
    font-size: 1.25rem;
    font-weight: 700;
  }

  :global(.markdown-content h2) {
    margin: 1rem 0 0.5rem;
    font-size: 1.125rem;
    font-weight: 700;
  }

  :global(.markdown-content h3) {
    margin: 1rem 0 0.5rem;
    font-size: 1rem;
    font-weight: 700;
    color: #7a1f2b;
  }

  :global(.markdown-content ul) {
    margin: 0.5rem 0 0.75rem;
    padding-left: 1.5rem;
    list-style-type: disc;
  }

  :global(.markdown-content ol) {
    margin: 0.5rem 0 0.75rem;
    padding-left: 1.5rem;
    list-style-type: decimal;
  }

  :global(.markdown-content li) {
    margin: 0.25rem 0;
  }

  :global(.markdown-content strong) {
    font-weight: 700;
  }

  :global(.markdown-content em) {
    font-style: italic;
  }

  :global(.markdown-content code) {
    border-radius: 0.25rem;
    background: #f1f3f5;
    padding: 0.125rem 0.35rem;
    font-family: monospace;
    font-size: 0.85em;
  }

  :global(.markdown-content pre) {
    margin: 0.75rem 0;
    overflow-x: auto;
    border-radius: 0.5rem;
    background: #f1f3f5;
    padding: 0.75rem;
  }

  :global(.markdown-content pre code) {
    background: transparent;
    padding: 0;
  }

  :global(.markdown-content blockquote) {
    margin: 0.75rem 0;
    border-left: 3px solid #7a1f2b;
    padding-left: 0.75rem;
    color: #59616e;
  }

  :global(.markdown-content hr) {
    margin: 1rem 0;
    border: 0;
    border-top: 1px solid #e5e7eb;
  }

  :global(.markdown-content a) {
    color: #7a1f2b;
    font-weight: 600;
    text-decoration: underline;
  }
</style>
