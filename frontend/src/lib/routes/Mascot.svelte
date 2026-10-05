<script lang="ts">
  import AppLayout from "../components/AppLayout.svelte";
  import WhiteCard from "../components/WhiteCard.svelte";

  let mascotColor = $state("#7A1F2B");
  let mascotPreview = $state<string | null>(null);

  function handleMascotUpload(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];

    if (!file) return;

    if (file.type !== "image/png") {
      input.value = "";
      return;
    }

    const reader = new FileReader();

    reader.onload = () => {
      mascotPreview = reader.result as string;
    };

    reader.readAsDataURL(file);
  }
</script>

<AppLayout>
  <div class="flex-1 px-6 py-4">
    <!-- Page heading -->
    <div class="mb-5">
      <h3
        class="mb-2 flex flex-row gap-2 text-sm font-semibold uppercase tracking-wider text-primary"
      >
        <span class="w-1 rounded-2xl bg-primary"></span>
        CHAT CUSTOMIZATION
      </h3>

      <h1 class="text-3xl font-bold">Mascot</h1>

      <p class="text-gray-600">
        Customize the mascot and color used by your organization's chat
        assistant.
      </p>
    </div>

    <div class="grid grid-cols-1 gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
      <!-- Settings -->
      <div class="flex flex-col gap-5">
        <WhiteCard>
          <div class="mb-4">
            <h2 class="text-lg font-bold">Mascot settings</h2>
            <p class="mt-1 text-sm text-gray-500">
              Choose a mascot and the primary color for your chat.
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
              class="hidden"
              onchange={handleMascotUpload}
            />
          </div>
        </WhiteCard>

        <!-- Mascot preview -->
        <WhiteCard>
          <div class="mb-4">
            <h2 class="text-lg font-bold">Mascot preview</h2>
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
              <div class="flex flex-row items-center gap-3">
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
                    class="text-xs font-bold uppercase tracking-wider"
                    style={`color: ${mascotColor};`}
                  >
                    Admissions Intelligence Hub
                  </span>

                  <span class="text-base font-semibold"> Chat Assistant </span>
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
                    class="max-w-[85%] rounded-xl px-4 py-2.5 text-sm leading-relaxed text-white"
                    style={`background-color: ${mascotColor};`}
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
              <div class="mx-auto flex max-w-2xl flex-row items-end gap-2">
                <div
                  class="flex-1 rounded-md border border-outline bg-white px-4 py-2.5 text-sm text-gray-400"
                >
                  Type your question...
                </div>

                <button
                  type="button"
                  class="rounded-md px-4 py-2.5 text-sm font-semibold text-white"
                  style={`background-color: ${mascotColor};`}
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
