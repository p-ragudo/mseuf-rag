<!-- src/pages/NotFound.svelte -->
<script lang="ts">
  import { replace } from "svelte-spa-router";

  function goHome() {
    replace("/overview");
  }
</script>

<main
  class="flex min-h-screen flex-1 flex-col items-center justify-center bg-[#F5F8FB] px-4"
>
  <div
    class="w-full max-w-md rounded-xl border border-outline bg-white p-8 text-center shadow-sm"
  >
    <div
      class="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-accent"
    >
      <svg
        width="28"
        height="28"
        viewBox="0 0 28 28"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <circle cx="14" cy="14" r="10.5" stroke="#7A1F2B" stroke-width="1.5" />
        <path
          d="M10.5 10.5L17.5 17.5"
          stroke="#7A1F2B"
          stroke-width="1.5"
          stroke-linecap="round"
        />
        <path
          d="M17.5 10.5L10.5 17.5"
          stroke="#7A1F2B"
          stroke-width="1.5"
          stroke-linecap="round"
        />
      </svg>
    </div>

    <h2 class="mt-4 text-xs font-bold uppercase tracking-wider text-primary">
      Error 404
    </h2>
    <h1 class="mt-1 text-2xl font-bold">Page not found</h1>
    <p class="mt-2 text-sm text-gray-500">
      The page you're looking for doesn't exist or may have been moved.
    </p>

    <button
      on:click={goHome}
      class="mt-6 inline-flex flex-row items-center gap-2 rounded-md bg-primary px-5 py-3 text-sm font-semibold text-white hover:cursor-pointer hover:bg-primary/90 transition-colors duration-200"
    >
      <svg
        width="16"
        height="16"
        viewBox="0 0 16 16"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path
          d="M2 8.5L8 3L14 8.5"
          stroke="white"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
        <path
          d="M4 7.5V13.5H12V7.5"
          stroke="white"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
      Back to Overview
    </button>
  </div>
</main>
