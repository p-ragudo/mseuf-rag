<script lang="ts">
  import { untrack } from "svelte";
  import SelectDropdown from "./SelectDropdown.svelte";

  type Tab = "document" | "web";

  interface Props {
    eyebrow?: string;
    title?: string;
    subtitle?: string;
    categories: string[];
    crawlDepthOptions?: string[];
    footerNote?: string;
    onStageDocument?: (file: File, category: string) => void;
    onRunScraper?: (config: {
      url: string;
      crawlDepth: string;
      includeSubdomains: boolean;
    }) => void;
  }

  let {
    eyebrow = "SOURCE MANAGEMENT",
    title = "Knowledge ingestion center",
    subtitle = "Prepare trusted admissions sources for Rooney's retrieval pipeline.",
    categories,
    crawlDepthOptions = ["1 level", "2 levels", "3 levels"],
    footerNote = "Demo controls stage files and configure crawls locally; they do not upload, scrape, or update Qdrant.",
    onStageDocument,
    onRunScraper,
  }: Props = $props();

  let activeTab = $state<Tab>("document");
  let selectedCategory = $state(untrack(() => categories[0] ?? ""));
  let selectedFile = $state<File | null>(null);
  let isDraggingOver = $state(false);
  let fileInput = $state<HTMLInputElement>();

  // Web resource ingestion state
  let webUrl = $state("");
  let selectedCrawlDepth = $state(untrack(() => crawlDepthOptions[0] ?? ""));
  let includeSubdomains = $state(false);
  let showUrlError = $state(false);

  let canStageDocument = $derived(
    selectedFile !== null && selectedCategory !== "",
  );

  function isValidHttpUrl(value: string) {
    try {
      const parsed = new URL(value);
      return parsed.protocol === "http:" || parsed.protocol === "https:";
    } catch {
      return false;
    }
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    isDraggingOver = false;
    const file = e.dataTransfer?.files?.[0];
    if (file) selectedFile = file;
  }

  function handleFileInputChange(e: Event) {
    const target = e.target as HTMLInputElement;
    selectedFile = target.files?.[0] ?? null;
  }

  function stageDocument() {
    if (selectedFile && canStageDocument) {
      onStageDocument?.(selectedFile, selectedCategory);
      selectedFile = null;
      if (fileInput) {
        fileInput.value = "";
      }
    }
  }

  function runScraper() {
    if (!isValidHttpUrl(webUrl.trim())) {
      showUrlError = true;
      return;
    }
    showUrlError = false;
    onRunScraper?.({
      url: webUrl.trim(),
      crawlDepth: selectedCrawlDepth,
      includeSubdomains,
    });
  }
</script>

<div class="rounded-xl border border-outline bg-white p-6 shadow-sm">
  <h4 class="text-xs font-bold uppercase tracking-wider text-primary">
    {eyebrow}
  </h4>
  <h2 class="mt-1 text-2xl font-bold">{title}</h2>
  <p class="mt-1 text-sm text-gray-500">{subtitle}</p>

  <!-- Tabs -->
  <div class="mt-6 flex flex-row gap-6 border-b border-outline">
    <button
      class={`flex flex-row items-center gap-2 pb-3 text-sm font-semibold transition-colors duration-200 ${
        activeTab === "document"
          ? "border-b-2 border-primary text-primary"
          : "border-b-2 border-transparent text-gray-500 hover:text-gray-700"
      }`}
      onclick={() => (activeTab = "document")}
    >
      <svg
        width="18"
        height="18"
        viewBox="0 0 18 18"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path
          d="M10.5 1.5H4.5C4.10218 1.5 3.72064 1.65804 3.43934 1.93934C3.15804 2.22064 3 2.60218 3 3V15C3 15.3978 3.15804 15.7794 3.43934 16.0607C3.72064 16.342 4.10218 16.5 4.5 16.5H13.5C13.8978 16.5 14.2794 16.342 14.5607 16.0607C14.842 15.7794 15 15.3978 15 15V6L10.5 1.5Z"
          stroke="currentColor"
          stroke-width="1.25"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
        <path
          d="M10.5 1.5V6H15"
          stroke="currentColor"
          stroke-width="1.25"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
      Document Ingestion (PDF/Docs)
    </button>
    <button
      class={`flex flex-row items-center gap-2 pb-3 text-sm font-semibold transition-colors duration-200 ${
        activeTab === "web"
          ? "border-b-2 border-primary text-primary"
          : "border-b-2 border-transparent text-gray-500 hover:text-gray-700"
      }`}
      onclick={() => (activeTab = "web")}
    >
      <svg
        width="18"
        height="18"
        viewBox="0 0 18 18"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <circle
          cx="9"
          cy="9"
          r="7.5"
          stroke="currentColor"
          stroke-width="1.25"
        />
        <path d="M1.5 9H16.5" stroke="currentColor" stroke-width="1.25" />
        <path
          d="M9 1.5C10.864 3.454 11.917 6.152 11.917 9C11.917 11.848 10.864 14.546 9 16.5C7.136 14.546 6.083 11.848 6.083 9C6.083 6.152 7.136 3.454 9 1.5Z"
          stroke="currentColor"
          stroke-width="1.25"
        />
      </svg>
      Web Resource Ingestion
    </button>
  </div>

  {#if activeTab === "document"}
    <!-- Drop zone -->
    <div
      class={`mt-6 flex flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-14 transition-colors duration-200 ${
        isDraggingOver
          ? "border-primary bg-accent/40"
          : "border-gray-200 bg-gray-50/60"
      }`}
      ondragover={(e) => {
        e.preventDefault();
        isDraggingOver = true;
      }}
      ondragleave={() => (isDraggingOver = false)}
      ondrop={handleDrop}
      role="presentation"
    >
      <div
        class="flex h-14 w-14 items-center justify-center rounded-lg bg-accent"
      >
        <svg
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path
            d="M7 18a4.6 4.4 0 0 1 0-9 5 4.5 0 0 1 9.6-2 4.5 4 0 0 1 2.9 7.5"
            stroke="#7A1F2B"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
          <path
            d="M12 21V11M12 11L9 14M12 11L15 14"
            stroke="#7A1F2B"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </div>

      {#if selectedFile}
        <p class="mt-4 text-lg font-bold">{selectedFile.name}</p>
        <p class="mt-1 text-sm text-gray-500">
          {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
        </p>
        <button
          class="mt-4 text-sm font-semibold text-primary hover:underline"
          onclick={() => (selectedFile = null)}
        >
          Remove file
        </button>
      {:else}
        <p class="mt-4 text-lg font-bold">Drag and drop your document here</p>
        <p class="mt-1 text-sm text-gray-500">
          PDF, DOC, or DOCX · Up to 25 MB per file
        </p>
        <button
          class="mt-4 rounded-md border border-outline bg-[#F5F8FB] px-4 py-2 text-sm font-semibold hover:bg-accent hover:text-primary transition-colors duration-200"
          onclick={() => fileInput?.click()}
        >
          Browse files
        </button>
        <input
          bind:this={fileInput}
          type="file"
          accept=".pdf,.doc,.docx"
          class="hidden"
          onchange={handleFileInputChange}
        />
      {/if}
    </div>

    <div class="mt-6">
      <p class="mb-2 text-sm font-bold">Category tag</p>
      <SelectDropdown options={categories} bind:selected={selectedCategory} />
    </div>

    <button
      disabled={!canStageDocument}
      class="mt-4 flex flex-row items-center gap-2 rounded-md bg-primary px-5 py-3 text-sm font-semibold text-white transition-opacity duration-200 disabled:cursor-not-allowed disabled:opacity-50"
      onclick={stageDocument}
    >
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path
          d="M7 18a4.6 4.4 0 0 1 0-9 5 4.5 0 0 1 9.6-2 4.5 4 0 0 1 2.9 7.5"
          stroke="white"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
        <path
          d="M12 21V11M12 11L9 14M12 11L15 14"
          stroke="white"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
      Stage document
    </button>
  {:else}
    <!-- Web Resource Ingestion -->
    <div class="mt-6">
      <p class="mb-2 text-sm font-bold">Resource URL</p>
      <div
        class={`flex flex-row items-center gap-2 rounded-md border px-4 py-3 ${
          showUrlError ? "border-red-500" : "border-outline"
        }`}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          class="shrink-0 text-gray-400"
        >
          <path
            d="M6.667 9.333a2.667 2.667 0 0 0 4.022.288l1.667-1.667a2.667 2.667 0 0 0-3.771-3.771l-.957.951"
            stroke="currentColor"
            stroke-width="1.25"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
          <path
            d="M9.333 6.667a2.667 2.667 0 0 0-4.022-.288L3.644 8.046a2.667 2.667 0 0 0 3.771 3.771l.951-.951"
            stroke="currentColor"
            stroke-width="1.25"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
        <input
          type="text"
          bind:value={webUrl}
          oninput={() => (showUrlError = false)}
          placeholder="https://mseuf.edu.ph/admissions"
          class="w-full text-sm outline-none placeholder:text-gray-400"
        />
      </div>
    </div>

    <div class="mt-6 flex flex-row items-end gap-4">
      <div class="max-w-xs flex-1">
        <p class="mb-2 text-sm font-bold">Crawl depth</p>
        <SelectDropdown
          options={crawlDepthOptions}
          bind:selected={selectedCrawlDepth}
        />
      </div>
      <label class="flex flex-row items-center gap-2 pb-3 text-sm">
        <input
          type="checkbox"
          bind:checked={includeSubdomains}
          class="h-4 w-4 rounded border-outline text-primary accent-primary"
        />
        Include subdomains
      </label>
    </div>

    <button
      class="mt-6 flex flex-row items-center gap-2 rounded-md bg-primary px-5 py-3 text-sm font-semibold text-white hover:bg-primary/90 transition-colors duration-200"
      onclick={runScraper}
    >
      <svg
        width="16"
        height="16"
        viewBox="0 0 16 16"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <circle cx="8" cy="8" r="6.5" stroke="white" stroke-width="1.25" />
        <path d="M1.5 8H14.5" stroke="white" stroke-width="1.25" />
        <path
          d="M8 1.5C9.437 3.07 10.148 5.024 10.148 8C10.148 10.976 9.437 12.93 8 14.5C6.563 12.93 5.852 10.976 5.852 8C5.852 5.024 6.563 3.07 8 1.5Z"
          stroke="white"
          stroke-width="1.25"
        />
      </svg>
      Run scraper
    </button>

    {#if showUrlError}
      <p class="mt-2 text-sm text-red-600">Enter a valid http or https URL.</p>
    {/if}
  {/if}

  <hr class="mt-8 border-outline" />
  <p class="mt-4 text-sm text-gray-500">{footerNote}</p>
</div>
