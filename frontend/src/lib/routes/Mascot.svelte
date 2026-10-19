<script lang="ts">
  import { onMount } from "svelte";
  import AppLayout from "../components/AppLayout.svelte";
  import WhiteCard from "../components/WhiteCard.svelte";
  import {
    DEFAULT_ASSISTANT_NAME,
    DEFAULT_COLOR,
    DEFAULT_HEADER_TAGLINE,
    MAX_MASCOT_BYTES,
    contrastColor,
    fetchBranding,
    saveBranding,
    type Branding,
  } from "../branding.svelte";
  import { authFetch } from "../auth.svelte";

  type Organization = { id: number; name: string };

  let organizations = $state<Organization[]>([]);
  let selectedOrgId = $state("");
  let organizationsLoading = $state(true);
  let organizationRequest = 0;
  let assistantName = $state(DEFAULT_ASSISTANT_NAME);
  let savedAssistantName = $state(DEFAULT_ASSISTANT_NAME);
  let headerTagline = $state(DEFAULT_HEADER_TAGLINE);
  let savedHeaderTagline = $state(DEFAULT_HEADER_TAGLINE);
  let mascotColor = $state(DEFAULT_COLOR);
  let mascotPreview = $state<string | null>(null);

  // What is saved on the server right now, used to detect unsaved changes
  let savedColor = $state(DEFAULT_COLOR);
  let savedMascotUrl = $state<string | null>(null);

  let pendingFile = $state<File | null>(null); // chosen but not uploaded yet
  let removeMascot = $state(false);

  let loading = $state(true);
  let saving = $state(false);
  let errorMessage = $state("");
  let successMessage = $state("");

  let dirty = $derived(
    assistantName !== savedAssistantName ||
      headerTagline !== savedHeaderTagline ||
      mascotColor.toLowerCase() !== savedColor.toLowerCase() ||
      pendingFile !== null ||
      removeMascot,
  );

  function applySaved(branding: Branding) {
    savedAssistantName = branding.assistant_name;
    assistantName = branding.assistant_name;
    savedHeaderTagline = branding.header_tagline;
    headerTagline = branding.header_tagline;
    savedColor = branding.color;
    savedMascotUrl = branding.mascot_url;
    mascotColor = branding.color;
    mascotPreview = branding.mascot_url;
    pendingFile = null;
    removeMascot = false;
  }

  async function load(orgId: string) {
    const request = ++organizationRequest;
    loading = true;
    errorMessage = "";
    try {
      const branding = await fetchBranding(orgId);
      if (request === organizationRequest) applySaved(branding);
    } catch (error) {
      if (request === organizationRequest) {
        errorMessage =
          error instanceof Error ? error.message : "Could not load your saved settings.";
      }
    } finally {
      if (request === organizationRequest) loading = false;
    }
  }

  onMount(async () => {
    try {
      const response = await authFetch("/orgs/");
      if (!response.ok) {
        throw new Error(`Could not load organizations (${response.status}).`);
      }
      organizations = await response.json();
      selectedOrgId = organizations.length > 0 ? String(organizations[0].id) : "";
      if (organizations.length === 0) {
        errorMessage = "Your account does not belong to an organization.";
        loading = false;
      }
    } catch (error) {
      errorMessage =
        error instanceof Error ? error.message : "Could not load organizations.";
      loading = false;
    } finally {
      organizationsLoading = false;
    }
  });

  $effect(() => {
    const orgId = selectedOrgId;
    if (orgId) void load(orgId);
  });

  function handleMascotUpload(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];

    if (!file) return;

    errorMessage = "";
    successMessage = "";

    if (file.type !== "image/png") {
      errorMessage = "The mascot must be a PNG image.";
      input.value = "";
      return;
    }

    if (file.size > MAX_MASCOT_BYTES) {
      errorMessage = "The mascot image must be 512 KB or smaller.";
      input.value = "";
      return;
    }

    const reader = new FileReader();

    reader.onload = () => {
      mascotPreview = reader.result as string;
      pendingFile = file;
      removeMascot = false;
    };

    reader.readAsDataURL(file);
    input.value = ""; // lets the same file be picked again later
  }

  function handleRemoveMascot() {
    mascotPreview = null;
    pendingFile = null;
    removeMascot = savedMascotUrl !== null;
    successMessage = "";
  }

  function discard() {
    assistantName = savedAssistantName;
    headerTagline = savedHeaderTagline;
    mascotColor = savedColor;
    mascotPreview = savedMascotUrl;
    pendingFile = null;
    removeMascot = false;
    errorMessage = "";
    successMessage = "";
  }

  async function save() {
    if (!dirty || saving || !selectedOrgId) return;

    saving = true;
    errorMessage = "";
    successMessage = "";

    try {
      applySaved(
        await saveBranding(selectedOrgId, {
          color: mascotColor,
          assistantName,
          headerTagline,
          mascot: pendingFile,
          removeMascot,
        }),
      );
      successMessage = "Chat customization saved.";
    } catch (err) {
      errorMessage =
        err instanceof Error ? err.message : "Could not save. Please try again.";
    } finally {
      saving = false;
    }
  }
</script>

<AppLayout>
  <div class="flex-1 px-3 py-4 sm:px-6">
    <!-- Page heading -->
    <div class="mb-5">
      <h3
        class="mb-2 flex flex-row gap-2 text-sm font-semibold uppercase tracking-wider text-primary"
      >
        <span class="w-1 rounded-2xl bg-primary"></span>
        ASSISTANT CUSTOMIZATION
      </h3>

      <h1 class="text-2xl font-bold sm:text-3xl">Chat Branding</h1>

      <p class="text-gray-600">
        Customize the name, appearance, and header message shown to people
        using your organization’s chat assistant.
      </p>
    </div>

    <label class="mb-5 block max-w-md">
      <span class="mb-2 block text-sm font-semibold">Organization</span>
      <select
        bind:value={selectedOrgId}
        disabled={organizationsLoading || organizations.length === 0 || saving}
        class="w-full rounded-md border border-outline bg-white px-3 py-2.5 text-sm outline-none focus:border-primary disabled:opacity-60"
      >
        {#each organizations as organization (organization.id)}
          <option value={String(organization.id)}>{organization.name}</option>
        {/each}
      </select>
    </label>

    <div class="grid grid-cols-1 gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
      <!-- Settings -->
      <div class="flex flex-col gap-5">
        <WhiteCard>
          <div class="mb-4">
            <h2 class="text-lg font-bold">Assistant appearance</h2>
            <p class="mt-1 text-sm text-gray-500">
              Set the assistant name, header message, mascot, and brand color.
            </p>
          </div>

          <div class="mb-5">
            <label
              for="header-tagline"
              class="mb-2 block text-sm font-semibold text-gray-800"
            >
              Header tagline
            </label>
            <input
              id="header-tagline"
              type="text"
              bind:value={headerTagline}
              maxlength="80"
              required
              disabled={loading || saving}
              oninput={() => (successMessage = "")}
              class="w-full rounded-md border border-outline bg-white px-3 py-2.5 text-sm outline-none focus:border-primary disabled:opacity-60"
              placeholder={DEFAULT_HEADER_TAGLINE}
            />
            <p class="mt-1 text-xs text-gray-500">
              Up to 80 characters. This appears above the chat name.
            </p>
          </div>

          <div class="mb-5">
            <label
              for="assistant-name"
              class="mb-2 block text-sm font-semibold text-gray-800"
            >
              Chat header name
            </label>
            <input
              id="assistant-name"
              type="text"
              bind:value={assistantName}
              maxlength="50"
              required
              disabled={loading || saving}
              oninput={() => (successMessage = "")}
              class="w-full rounded-md border border-outline bg-white px-3 py-2.5 text-sm outline-none focus:border-primary disabled:opacity-60"
              placeholder={DEFAULT_ASSISTANT_NAME}
            />
            <p class="mt-1 text-xs text-gray-500">
              Up to 50 characters. This name appears in the chat header.
            </p>
          </div>

          <!-- Color -->
          <div>
            <label
              for="mascot-color"
              class="mb-2 block text-sm font-semibold text-gray-800"
            >
              Mascot color
            </label>

            <div
              class="flex items-center gap-3 rounded-lg border border-outline bg-[#F5F8FB] p-2"
            >
              <input
                id="mascot-color"
                type="color"
                bind:value={mascotColor}
                oninput={() => (successMessage = "")}
                disabled={loading}
                class="h-10 w-12 cursor-pointer rounded-md border-0 bg-transparent p-0"
              />

              <div class="flex flex-col">
                <span class="text-sm font-semibold">{mascotColor}</span>
                <span class="text-xs text-gray-500">
                  Used for the chat accent
                </span>
              </div>
            </div>
          </div>

          <!-- PNG upload -->
          <div class="mt-5">
            <label
              for="mascot-upload"
              class="mb-2 block text-sm font-semibold text-gray-800"
            >
              Mascot PNG
            </label>

            <label
              for="mascot-upload"
              class="flex min-h-40 cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-outline bg-[#F5F8FB] px-4 py-6 text-center transition-colors hover:border-primary hover:bg-accent"
            >
              {#if mascotPreview}
                <img
                  src={mascotPreview}
                  alt="Mascot preview"
                  class="mb-3 h-24 w-24 object-contain"
                />

                <span class="text-sm font-semibold text-primary">
                  Replace mascot
                </span>

                <span class="mt-1 text-xs text-gray-500"> PNG files only </span>
              {:else}
                <div
                  class="mb-3 flex h-14 w-14 items-center justify-center rounded-full"
                  style={`background-color: ${mascotColor}18; color: ${mascotColor};`}
                >
                  <svg
                    class="h-7 w-7"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.8"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  >
                    <path d="M12 16V4" />
                    <path d="M7 9l5-5 5 5" />
                    <path d="M5 20h14" />
                  </svg>
                </div>

                <span class="text-sm font-semibold text-gray-800">
                  Upload mascot
                </span>

                <span class="mt-1 text-xs text-gray-500"> PNG files only </span>
              {/if}
            </label>

            <input
              id="mascot-upload"
              type="file"
              accept="image/png"
              disabled={loading}
              class="hidden"
              onchange={handleMascotUpload}
            />
          </div>

          <!-- Actions -->
          <div class="mt-6 flex flex-col gap-3 border-t border-outline pt-4">
            {#if errorMessage}
              <p role="alert" class="text-sm text-red-600">{errorMessage}</p>
            {/if}

            {#if successMessage}
              <p role="status" class="text-sm font-semibold text-green-700">
                {successMessage}
              </p>
            {/if}

            <div class="flex flex-row flex-wrap items-center gap-2">
              <button
                type="button"
                class="rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-white transition-opacity duration-200 hover:cursor-pointer disabled:cursor-not-allowed disabled:opacity-60"
                onclick={save}
                disabled={!dirty || saving || loading}
              >
                {saving ? "Saving..." : "Save changes"}
              </button>

              <button
                type="button"
                class="rounded-md border border-outline bg-[#F5F8FB] px-4 py-2.5 text-sm font-semibold transition-opacity duration-200 hover:cursor-pointer disabled:cursor-not-allowed disabled:opacity-60"
                onclick={discard}
                disabled={!dirty || saving}
              >
                Discard
              </button>

              {#if mascotPreview}
                <button
                  type="button"
                  class="ml-auto text-sm font-semibold text-red-600 hover:cursor-pointer hover:underline disabled:cursor-not-allowed disabled:opacity-60"
                  onclick={handleRemoveMascot}
                  disabled={saving}
                >
                  Remove mascot
                </button>
              {/if}
            </div>
          </div>
        </WhiteCard>

        <!-- Mascot preview -->
        <WhiteCard>
          <div class="mb-4">
            <h2 class="text-lg font-bold">Live preview</h2>
            <p class="mt-1 text-sm text-gray-500">
              This is how the mascot will appear in the chat.
            </p>
          </div>

          <div
            class="flex min-h-48 items-center justify-center rounded-lg bg-[#F5F8FB]"
          >
            <div
              class="flex h-32 w-32 items-center justify-center rounded-full"
              style={`background-color: ${mascotColor}18;`}
            >
              {#if mascotPreview}
                <img
                  src={mascotPreview}
                  alt="Organization mascot"
                  class="h-24 w-24 object-contain"
                />
              {:else}
                <span
                  class="text-4xl font-bold"
                  style={`color: ${mascotColor};`}
                >
                  AI
                </span>
              {/if}
            </div>
          </div>
        </WhiteCard>
      </div>

      <!-- Chat preview -->
      <WhiteCard style="p-0 overflow-hidden">
        <div class="border-b border-outline px-5 py-4">
          <div
            class="text-xs font-bold uppercase tracking-wider"
            style={`color: ${mascotColor};`}
          >
            CHAT PREVIEW
          </div>

          <h2 class="mt-1 text-lg font-bold">Organization chat</h2>

          <p class="mt-1 text-sm text-gray-500">
            Preview how your mascot and color will appear to visitors.
          </p>
        </div>

        <div class="overflow-hidden">
          <div class="flex min-h-[620px] flex-col bg-[#F5F8FB]">
            <!-- Chat header -->
            <header
              class="flex flex-row items-center justify-between gap-4 border-b-2 border-outline bg-white px-4 py-3"
            >
              <div class="flex min-w-0 flex-row items-center gap-2 sm:gap-3">
                <div
                  class="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-full"
                  style={`background-color: ${mascotColor}18;`}
                >
                  {#if mascotPreview}
                    <img
                      src={mascotPreview}
                      alt="Mascot"
                      class="h-8 w-8 object-contain"
                    />
                  {:else}
                    <span
                      class="text-xs font-bold"
                      style={`color: ${mascotColor};`}
                    >
                      AI
                    </span>
                  {/if}
                </div>

                <div class="flex flex-col">
                  <span
                    class="max-w-[55vw] truncate text-[10px] font-bold uppercase tracking-wider sm:max-w-none sm:text-xs"
                    style={`color: ${mascotColor};`}
                  >
                    {headerTagline.trim() || DEFAULT_HEADER_TAGLINE}
                  </span>

                  <span class="max-w-[55vw] truncate text-sm font-semibold sm:max-w-56 sm:text-base">
                    {assistantName.trim() || DEFAULT_ASSISTANT_NAME}
                  </span>
                </div>
              </div>
            </header>

            <!-- Messages -->
            <div class="flex-1 overflow-y-auto px-4 py-6">
              <div class="mx-auto flex max-w-2xl flex-col gap-4">
                <!-- Welcome -->
                <div class="mt-8 flex flex-col items-center text-center">
                  <div
                    class="flex h-12 w-12 items-center justify-center overflow-hidden rounded-full"
                    style={`background-color: ${mascotColor}18;`}
                  >
                    {#if mascotPreview}
                      <img
                        src={mascotPreview}
                        alt="Mascot"
                        class="h-10 w-10 object-contain"
                      />
                    {:else}
                      <span
                        class="text-sm font-bold"
                        style={`color: ${mascotColor};`}
                      >
                        AI
                      </span>
                    {/if}
                  </div>

                  <h2 class="mt-4 text-xl font-bold">
                    How can I help you today?
                  </h2>

                  <p class="mt-1 text-sm text-gray-500">
                    Ask me anything and I'll find the answer for you.
                  </p>
                </div>

                <!-- Assistant message -->
                <div class="flex flex-row items-end gap-2">
                  <div
                    class="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full"
                    style={`background-color: ${mascotColor}18;`}
                  >
                    {#if mascotPreview}
                      <img
                        src={mascotPreview}
                        alt="Mascot"
                        class="h-7 w-7 object-contain"
                      />
                    {:else}
                      <span
                        class="text-[10px] font-bold"
                        style={`color: ${mascotColor};`}
                      >
                        AI
                      </span>
                    {/if}
                  </div>

                  <div
                    class="max-w-[85%] rounded-xl border border-outline bg-white px-4 py-2.5 text-sm leading-relaxed text-gray-800 shadow-sm"
                  >
                    Hello! I'm your organization's virtual assistant. How can I
                    help you today?
                  </div>
                </div>

                <!-- User message -->
                <div class="flex flex-row items-end justify-end gap-2">
                  <div
                    class="max-w-[85%] rounded-xl px-4 py-2.5 text-sm leading-relaxed "
                    style={`background-color: ${mascotColor}; color: ${contrastColor(mascotColor)};`}
                  >
                    What programs does the university offer?
                  </div>
                </div>

                <!-- Assistant response -->
                <div class="flex flex-row items-end gap-2">
                  <div
                    class="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full"
                    style={`background-color: ${mascotColor}18;`}
                  >
                    {#if mascotPreview}
                      <img
                        src={mascotPreview}
                        alt="Mascot"
                        class="h-7 w-7 object-contain"
                      />
                    {:else}
                      <span
                        class="text-[10px] font-bold"
                        style={`color: ${mascotColor};`}
                      >
                        AI
                      </span>
                    {/if}
                  </div>

                  <div
                    class="max-w-[85%] rounded-xl border border-outline bg-white px-4 py-2.5 text-sm leading-relaxed text-gray-800 shadow-sm"
                  >
                    The university offers a variety of undergraduate and
                    graduate programs. I can help you find information about
                    admissions, tuition, scholarships, and program requirements.
                  </div>
                </div>
              </div>
            </div>

            <!-- Input -->
            <footer class="border-t-2 border-outline bg-white px-4 py-3">
              <div class="mx-auto flex max-w-2xl flex-col items-stretch gap-2 sm:flex-row sm:items-end">
                <div
                  class="flex-1 rounded-md border border-outline bg-white px-4 py-2.5 text-sm text-gray-400"
                >
                  Type your question...
                </div>

                <button
                  type="button"
                  class="rounded-md px-4 py-2.5 text-sm font-semibold sm:w-auto"
                  style={`background-color: ${mascotColor}; color: ${contrastColor(mascotColor)};`}
                >
                  Send
                </button>
              </div>

              <p class="mx-auto mt-2 max-w-2xl text-xs text-gray-500">
                Press Enter to send, Shift + Enter for a new line.
              </p>
            </footer>
          </div>
        </div>
      </WhiteCard>
    </div>
  </div>
</AppLayout>