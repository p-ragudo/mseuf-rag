<script lang="ts">
  type DocStatus = "indexed" | "processing" | "failed";
  type DocType = "pdf" | "web";

  interface Document {
    id: number;
    name: string;
    type: DocType;
    status: DocStatus;
    chunks: number;
    dateAdded: string;
  }

  let documents = $state<Document[]>([
    {
      id: 1,
      name: "Admission Guidelines 2026.pdf",
      type: "pdf",
      status: "indexed",
      chunks: 84,
      dateAdded: "2026-09-01",
    },
    {
      id: 2,
      name: "university.edu/admissions/scholarships",
      type: "web",
      status: "indexed",
      chunks: 32,
      dateAdded: "2026-09-03",
    },
    {
      id: 3,
      name: "Course Catalog 2026-2027.pdf",
      type: "pdf",
      status: "processing",
      chunks: 0,
      dateAdded: "2026-09-07",
    },
    {
      id: 4,
      name: "university.edu/registrar/transfer-credits",
      type: "web",
      status: "failed",
      chunks: 0,
      dateAdded: "2026-09-06",
    },
    {
      id: 5,
      name: "Student Handbook.pdf",
      type: "pdf",
      status: "indexed",
      chunks: 156,
      dateAdded: "2026-08-28",
    },
  ]);

  let urlInput = $state("");
  let isDragging = $state(false);
  let fileInputEl: HTMLInputElement;

  function statusColor(status: DocStatus) {
    if (status === "indexed") return "bg-green-100 text-green-700";
    if (status === "processing") return "bg-yellow-100 text-yellow-700";
    return "bg-red-100 text-red-700";
  }

  function typeIcon(type: DocType) {
    return type === "pdf" ? "📄" : "🔗";
  }

  function handleFiles(files: FileList | null) {
    if (!files) return;
    for (const file of files) {
      if (file.type !== "application/pdf") continue;
      let newDoc: Document = {
        id: Date.now() + Math.random(),
        name: file.name,
        type: "pdf",
        status: "processing",
        chunks: 0,
        dateAdded: new Date().toISOString().slice(0, 10),
      };
      documents = [newDoc, ...documents];
      // TODO: replace with real upload call, e.g.
      // await uploadPdf(file) then update status/chunks on response
    }
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    isDragging = false;
    handleFiles(e.dataTransfer?.files ?? null);
  }

  function handleUrlSubmit() {
    if (!urlInput.trim()) return;
    let newDoc: Document = {
      id: Date.now() + Math.random(),
      name: urlInput.trim(),
      type: "web",
      status: "processing",
      chunks: 0,
      dateAdded: new Date().toISOString().slice(0, 10),
    };
    documents = [newDoc, ...documents];
    urlInput = "";
    // TODO: replace with real scrape-trigger call, e.g.
    // await scrapeUrl(newDoc.name) then update status/chunks on response
  }

  function reprocess(id: number) {
    documents = documents.map((d) =>
      d.id === id ? { ...d, status: "processing", chunks: 0 } : d,
    );
    // TODO: trigger real reprocessing call
  }

  function removeDoc(id: number) {
    documents = documents.filter((d) => d.id !== id);
    // TODO: trigger real delete call
  }
</script>

<div class="p-6 bg-gray-50">
  <h1 class="text-2xl font-semibold text-gray-800 mb-6">Chunks</h1>

  <!-- Upload panel -->
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
    <!-- PDF upload -->
    <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
      <h2 class="text-sm font-medium text-gray-600 mb-4">
        Upload PDF Document
      </h2>
      <button
        type="button"
        ondragover={(e) => {
          e.preventDefault();
          isDragging = true;
        }}
        ondragleave={() => (isDragging = false)}
        ondrop={handleDrop}
        onclick={() => fileInputEl.click()}
        class="w-full border-2 border-dashed rounded-lg py-10 flex flex-col items-center justify-center gap-2 transition-colors {isDragging
          ? 'border-blue-400 bg-blue-50'
          : 'border-gray-300'}"
      >
        <span class="text-3xl">📄</span>
        <p class="text-sm text-gray-500">
          Drag & drop a PDF here, or click to browse
        </p>
        <p class="text-xs text-gray-400">Only .pdf files are accepted</p>
      </button>
      <input
        bind:this={fileInputEl}
        type="file"
        accept="application/pdf"
        multiple
        class="hidden"
        onchange={(e) => handleFiles((e.target as HTMLInputElement).files)}
      />
    </div>

    <!-- URL scrape -->
    <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
      <h2 class="text-sm font-medium text-gray-600 mb-4">
        Add from University Website
      </h2>
      <div class="flex flex-col gap-3 h-full justify-center">
        <label class="text-xs text-gray-500" for="url-input">Page URL</label>
        <div class="flex gap-2">
          <input
            id="url-input"
            type="url"
            bind:value={urlInput}
            placeholder="https://university.edu/admissions/requirements"
            class="flex-1 px-3 py-2 rounded-lg border border-gray-200 text-sm outline-none focus:border-blue-400"
            onkeydown={(e) => e.key === "Enter" && handleUrlSubmit()}
          />
          <button
            onclick={handleUrlSubmit}
            class="px-4 py-2 rounded-lg bg-gray-800 text-white text-sm hover:bg-gray-700 transition-colors"
          >
            Scrape
          </button>
        </div>
        <p class="text-xs text-gray-400">
          The page content will be scraped, chunked, and indexed automatically.
        </p>
      </div>
    </div>
  </div>

  <!-- Documents table -->
  <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
    <h2 class="text-sm font-medium text-gray-600 mb-4">
      Indexed Documents ({documents.length})
    </h2>
    <table class="w-full text-sm">
      <thead>
        <tr class="border-b border-gray-200 text-left text-gray-500">
          <th class="py-2 px-2 font-medium">Source</th>
          <th class="py-2 px-2 font-medium">Type</th>
          <th class="py-2 px-2 font-medium">Status</th>
          <th class="py-2 px-2 font-medium">Chunks</th>
          <th class="py-2 px-2 font-medium">Date Added</th>
          <th class="py-2 px-2 font-medium">Actions</th>
        </tr>
      </thead>
      <tbody>
        {#each documents as doc (doc.id)}
          <tr class="border-b border-gray-100 hover:bg-gray-50">
            <td class="py-2 px-2 text-gray-700 truncate max-w-[280px]">
              {typeIcon(doc.type)}
              {doc.name}
            </td>
            <td class="py-2 px-2 text-gray-500 uppercase text-xs">{doc.type}</td
            >
            <td class="py-2 px-2">
              <span
                class="text-xs px-2 py-0.5 rounded-full {statusColor(
                  doc.status,
                )}">{doc.status}</span
              >
            </td>
            <td class="py-2 px-2 text-gray-600">{doc.chunks || "—"}</td>
            <td class="py-2 px-2 text-gray-400 text-xs">{doc.dateAdded}</td>
            <td class="py-2 px-2">
              <div class="flex gap-2">
                <button
                  onclick={() => reprocess(doc.id)}
                  class="text-xs text-blue-600 hover:underline"
                >
                  Reprocess
                </button>
                <button
                  onclick={() => removeDoc(doc.id)}
                  class="text-xs text-red-600 hover:underline"
                >
                  Delete
                </button>
              </div>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</div>
