<script lang="ts">
  import { onMount } from "svelte";
  import { untrack } from "svelte";
  import SelectDropdown from "./SelectDropdown.svelte";
  import { authFetch } from "../auth.svelte";

  type Tab = "document" | "web";

  type Organization = {
    id: number;
    name: string;
  };

  type WebsiteStatus = "PENDING" | "IN_PROGRESS" | "COMPLETED" | "FAILED";

  type Website = {
    id: number;
    org_id: number;
    url: string;
    status: WebsiteStatus;
    error_message: string | null;
    checkpoints?: {
      pages: {
        total_discovered: number;
        pending: number;
        in_progress: number;
        completed: number;
        failed: number;
      };
      chunks: { total: number };
      questions: { total_generated: number; synced_active_model: number };
    };
  };

  interface Props {
    eyebrow?: string;
    title?: string;
    subtitle?: string;
    categories: string[];
    footerNote?: string;
    onStageDocument?: (file: File, category: string) => void;
  }

  let {
    eyebrow = "SOURCE MANAGEMENT",
    title = "Knowledge ingestion center",
    subtitle = "Prepare trusted admissions sources for Rooney's retrieval pipeline.",
    categories,
    footerNote = "Web ingestion crawls discovered pages and indexes their content. Recurring schedules and document uploads are not available yet.",
    onStageDocument,
  }: Props = $props();

  let activeTab = $state<Tab>("document");
  let selectedCategory = $state(untrack(() => categories[0] ?? ""));
  let selectedFile = $state<File | null>(null);
  let isDraggingOver = $state(false);
  let fileInput = $state<HTMLInputElement>();

  // Web resource ingestion state
  let webUrl = $state("");
  let showUrlError = $state(false);
  let organizations = $state<Organization[]>([]);
  let selectedOrgId = $state("");
  let websites = $state<Website[]>([]);
  let organizationsLoading = $state(true);
  let websitesLoading = $state(false);
  let submitting = $state(false);
  let actionWebsiteId = $state<number | null>(null);
  let pageError = $state("");
  let pageNotice = $state("");
  let websiteRequest = 0;

  let canStageDocument = $derived(
    selectedFile !== null && selectedCategory !== "",
  );

  onMount(() => {
    void loadOrganizations();
  });

  $effect(() => {
    const orgId = selectedOrgId;
    if (orgId) void loadWebsites(orgId);
    else websites = [];
  });

  $effect(() => {
    const hasRunningWebsite = websites.some(
      (website) => website.status === "IN_PROGRESS",
    );
    if (!hasRunningWebsite) return;

    const interval = window.setInterval(() => {
      if (selectedOrgId) void loadWebsites(selectedOrgId);
    }, 5000);

    return () => window.clearInterval(interval);
  });

  function isValidHttpUrl(value: string) {
    try {
      const parsed = new URL(value);
      return parsed.protocol === "http:" || parsed.protocol === "https:";
    } catch {
      return false;
    }
  }

  async function responseError(response: Response): Promise<string> {
    try {
      const data = await response.json();
      if (typeof data.detail === "string") return data.detail;
      if (Array.isArray(data.detail)) {
        return data.detail
          .map((item: { msg?: string }) => item.msg ?? "Invalid request")
          .join(", ");
      }
    } catch {
      // The response body was not JSON.
    }
    return `Request failed (${response.status})`;
  }

  async function loadOrganizations() {
    organizationsLoading = true;
    pageError = "";
    try {
      const response = await authFetch("/orgs/");
      if (!response.ok) throw new Error(await responseError(response));

      organizations = await response.json();
      if (organizations.length > 0 && !selectedOrgId) {
        selectedOrgId = String(organizations[0].id);
      }
    } catch (error) {
      pageError =
        error instanceof Error
          ? error.message
          : "Could not load your organizations.";
    } finally {
      organizationsLoading = false;
    }
  }

  async function loadWebsites(orgId: string) {
    const request = ++websiteRequest;
    websitesLoading = true;
    pageError = "";

    try {
      const response = await authFetch(`/websites/org/${orgId}`);
      if (!response.ok) throw new Error(await responseError(response));

      const registered: Website[] = await response.json();
      if (request !== websiteRequest || orgId !== selectedOrgId) return;

      const withStatus = await Promise.all(
        registered.map(async (website) => {
          const statusResponse = await authFetch(
            `/ingest/status/${website.id}`,
          );
          if (!statusResponse.ok) {
            throw new Error(await responseError(statusResponse));
          }
          return (await statusResponse.json()) as Website;
        }),
      );
      if (request === websiteRequest && orgId === selectedOrgId) {
        websites = withStatus;
      }
    } catch (error) {
      if (request === websiteRequest && orgId === selectedOrgId) {
        pageError =
          error instanceof Error ? error.message : "Could not load websites.";
      }
    } finally {
      if (request === websiteRequest) websitesLoading = false;
    }
  }

  async function addAndIngestWebsite() {
    const url = webUrl.trim();
    if (!isValidHttpUrl(url)) {
      showUrlError = true;
      return;
    }
    if (!selectedOrgId || submitting) return;

    showUrlError = false;
    pageError = "";
    pageNotice = "";
    submitting = true;

    try {
      const createResponse = await authFetch("/websites/", {
        method: "POST",
        body: JSON.stringify({ org_id: Number(selectedOrgId), url }),
      });
      if (!createResponse.ok) {
        throw new Error(await responseError(createResponse));
      }

      const website: Website = await createResponse.json();
      webUrl = "";
      pageNotice = "Website registered. Starting ingestion…";

      try {
        const runResponse = await authFetch(`/ingest/run/${website.id}`, {
          method: "POST",
        });
        if (!runResponse.ok) throw new Error(await responseError(runResponse));
        pageNotice = "Website registered and ingestion started.";
      } catch (error) {
        pageError =
          error instanceof Error
            ? `Website registered, but ingestion could not be started: ${error.message}`
            : "Website registered, but ingestion could not be started.";
      }

      await loadWebsites(selectedOrgId);
    } catch (error) {
      pageError =
        error instanceof Error ? error.message : "Could not register website.";
    } finally {
      submitting = false;
    }
  }

  async function runIngestion(website: Website, forceRefresh = false) {
    if (actionWebsiteId !== null) return;
    actionWebsiteId = website.id;
    pageError = "";
    pageNotice = "";

    try {
      const suffix = forceRefresh ? "?force_refresh=true" : "";
      const response = await authFetch(
        `/ingest/run/${website.id}${suffix}`,
        { method: "POST" },
      );
      if (!response.ok) throw new Error(await responseError(response));
      pageNotice = forceRefresh
        ? `Full refresh started for ${website.url}.`
        : `Ingestion started for ${website.url}.`;
      await loadWebsites(selectedOrgId);
    } catch (error) {
      pageError =
        error instanceof Error
          ? error.message
          : "Could not start website ingestion.";
    } finally {
      actionWebsiteId = null;
    }
  }

  async function deleteWebsite(website: Website) {
    if (
      actionWebsiteId !== null ||
      !window.confirm(`Remove ${website.url} and its indexed content?`)
    ) {
      return;
    }

    actionWebsiteId = website.id;
    pageError = "";
    pageNotice = "";
    try {
      const response = await authFetch(`/websites/${website.id}`, {
        method: "DELETE",
      });
      if (!response.ok) throw new Error(await responseError(response));
      pageNotice = "Website and its indexed content removed.";
      await loadWebsites(selectedOrgId);
    } catch (error) {
      pageError =
        error instanceof Error ? error.message : "Could not remove website.";
    } finally {
      actionWebsiteId = null;
    }
  }

  function statusLabel(status: WebsiteStatus): string {
    return status.replace("_", " ").toLowerCase();
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    isDraggingOver = false;

    const file = e.dataTransfer?.files?.[0];

    if (file) {
      selectedFile = file;
    }
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
          d="M10.5 1.5H4.5C4.10218 1.5 3.72064 1.65804 3.43934 1.93934C3.15804 2.22064 3 2.60218 3 3V15C3 15.3978 3.15804 15.7794 3.43934 16.0607C3.72064 16.342 4.10218 16.5 4.5 16.5H13.5C13.8978 16.5 14.2794 16.342 14.5607 16.0607 15V6L10.5 1.5Z"
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
            d="M7 18a4.6 4.4 0 0 1 0-9 5 4.5 4.5 0 0 1 9.6-2 4.5 4.5 0 0 1 2.9 7.5"
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
          class="mt-4 rounded-md border border-outline bg-[#F5F8FB] px-4 py-2 text-sm font-semibold transition-colors duration-200 hover:bg-accent hover:text-primary"
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
          d="M7 18a4.6 4.4 0 0 1 0-9 5 4.5 4.5 0 0 1 9.6-2 4.5 4.5 0 0 1 2.9 7.5"
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
      {#if organizationsLoading}
        <p class="text-sm text-gray-500">Loading your organizations…</p>
      {:else if organizations.length === 0}
        <div class="rounded-lg border border-outline bg-gray-50 p-4 text-sm text-gray-600">
          No organization is available for your account. Join or create an
          organization before adding a website.
        </div>
      {:else}
        <label class="block max-w-md">
          <span class="mb-2 block text-sm font-bold">Organization</span>
          <select
            bind:value={selectedOrgId}
            class="w-full rounded-md border border-outline bg-white px-3 py-2.5 text-sm outline-none focus:border-primary"
          >
            {#each organizations as organization (organization.id)}
              <option value={String(organization.id)}>{organization.name}</option>
            {/each}
          </select>
        </label>

        <form
          class="mt-5"
          onsubmit={(event) => {
            event.preventDefault();
            void addAndIngestWebsite();
          }}
        >
          <label class="mb-2 block text-sm font-bold" for="website-url">
            Website URL
          </label>
          <div class="flex flex-col gap-3 sm:flex-row">
            <input
              id="website-url"
              type="url"
              bind:value={webUrl}
              oninput={() => (showUrlError = false)}
              placeholder="https://example.edu/admissions"
              required
              class={`min-w-0 flex-1 rounded-md border bg-white px-4 py-3 text-sm outline-none placeholder:text-gray-400 focus:border-primary ${
                showUrlError ? "border-red-500" : "border-outline"
              }`}
            />
            <button
              type="submit"
              disabled={submitting || !selectedOrgId}
              class="rounded-md bg-primary px-5 py-3 text-sm font-semibold text-white transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? "Starting…" : "Add and start ingestion"}
            </button>
          </div>
          {#if showUrlError}
            <p class="mt-2 text-sm text-red-600">
              Enter a valid http or https URL.
            </p>
          {/if}
          <p class="mt-2 text-xs text-gray-500">
            The crawler discovers pages from the website’s sitemap or links.
            Ingestion runs in the background.
          </p>
        </form>
      {/if}
    </div>

    {#if pageError}
      <p
        role="alert"
        class="mt-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        {pageError}
      </p>
    {/if}
    {#if pageNotice}
      <p
        role="status"
        class="mt-4 rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800"
      >
        {pageNotice}
      </p>
    {/if}

    <div class="mt-8 border-t border-outline pt-6">
      <div class="mb-4 flex items-center justify-between gap-4">
        <div>
          <h3 class="text-lg font-bold">Registered websites</h3>
          <p class="mt-1 text-sm text-gray-500">
            Ingestion status and indexing checkpoints refresh automatically
            while a crawl is running.
          </p>
        </div>
        <button
          type="button"
          class="shrink-0 rounded-md border border-outline bg-white px-3 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          disabled={websitesLoading || !selectedOrgId}
          onclick={() => selectedOrgId && loadWebsites(selectedOrgId)}
        >
          Refresh list
        </button>
      </div>

      {#if websitesLoading && websites.length === 0}
        <p class="py-8 text-center text-sm text-gray-500">Loading websites…</p>
      {:else if websites.length === 0}
        <div class="rounded-lg border border-dashed border-outline px-4 py-10 text-center text-sm text-gray-500">
          No websites registered for this organization yet.
        </div>
      {:else}
        <div class="space-y-3">
          {#each websites as website (website.id)}
            <article class="rounded-lg border border-outline bg-white p-4">
              <div
                class="flex flex-col justify-between gap-4 md:flex-row md:items-start"
              >
                <div class="min-w-0 flex-1">
                  <a
                    href={website.url}
                    target="_blank"
                    rel="noreferrer"
                    class="break-all text-sm font-semibold text-primary hover:underline"
                  >
                    {website.url}
                  </a>
                  <div class="mt-2 flex flex-wrap items-center gap-2">
                    <span
                      class={`rounded-full px-2.5 py-1 text-xs font-bold uppercase ${
                        website.status === "COMPLETED"
                          ? "bg-green-100 text-green-800"
                          : website.status === "FAILED"
                            ? "bg-red-100 text-red-800"
                            : website.status === "IN_PROGRESS"
                              ? "bg-blue-100 text-blue-800"
                              : "bg-gray-100 text-gray-700"
                      }`}
                    >
                      {statusLabel(website.status)}
                    </span>
                    {#if website.checkpoints}
                      <span class="text-xs text-gray-500">
                        {website.checkpoints.pages.completed}/
                        {website.checkpoints.pages.total_discovered} pages ·
                        {website.checkpoints.chunks.total} chunks ·
                        {website.checkpoints.questions.synced_active_model}/
                        {website.checkpoints.questions.total_generated} questions indexed
                      </span>
                    {/if}
                  </div>
                  {#if website.status === "IN_PROGRESS"}
                    <p class="mt-2 text-xs text-blue-700" role="status">
                      Ingestion is running. This status updates automatically.
                    </p>
                  {/if}
                  {#if website.error_message}
                    <p class="mt-2 break-words text-sm text-red-700">
                      {website.error_message}
                    </p>
                  {/if}
                  {#if website.checkpoints?.pages.failed}
                    <p class="mt-1 text-xs text-amber-700">
                      {website.checkpoints.pages.failed} page(s) failed during
                      scraping.
                    </p>
                  {/if}
                </div>

                <div class="flex shrink-0 flex-wrap gap-2">
                  <button
                    type="button"
                    class="rounded-md border border-outline px-3 py-2 text-xs font-semibold hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={website.status === "IN_PROGRESS" ||
                      actionWebsiteId !== null}
                    onclick={() => void runIngestion(website)}
                  >
                    {actionWebsiteId === website.id
                      ? "Starting…"
                      : "Run ingestion"}
                  </button>
                  <button
                    type="button"
                    class="rounded-md border border-outline px-3 py-2 text-xs font-semibold hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={website.status === "IN_PROGRESS" ||
                      actionWebsiteId !== null}
                    onclick={() => void runIngestion(website, true)}
                  >
                    Full refresh
                  </button>
                  <button
                    type="button"
                    class="rounded-md px-3 py-2 text-xs font-semibold text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={website.status === "IN_PROGRESS" ||
                      actionWebsiteId !== null}
                    onclick={() => void deleteWebsite(website)}
                  >
                    Remove
                  </button>
                </div>
              </div>
            </article>
          {/each}
        </div>
      {/if}
    </div>
  {/if}

  <hr class="mt-8 border-outline" />

  <p class="mt-4 text-sm text-gray-500">{footerNote}</p>
</div>
