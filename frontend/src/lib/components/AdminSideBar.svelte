<script lang="ts">
  let { currentIndex = $bindable(0) } = $props();

  const navItems = [
    { label: "Dashboard", index: 0 },
    { label: "Chunks", index: 1 },
    { label: "Settings", index: 2 },
  ];

  function changeScreen(index: number): void {
    currentIndex = index;
  }
</script>

<aside
  class="hidden lg:flex flex-col bg-red-900 text-white py-8 px-4 items-center min-w-56 w-2/12 h-screen shrink-0 z-10"
>
  <img
    src="/mseuf_icon.jpg"
    alt="MSEUF icon"
    class="rounded-full overflow-hidden w-24 h-24 shrink-0 object-cover"
  />
  <h1
    class="font-heading text-sm font-semibold mt-4 text-center leading-snug tracking-wide text-red-100"
  >
    MSEUF - CHATBOT ADMIN DASHBOARD
  </h1>

  <nav class="w-full mt-8">
    <ul class="w-full flex flex-col gap-1">
      {#each navItems as item}
        <li class="w-full">
          <button
            type="button"
            class="cursor-pointer w-full text-left px-4 py-2.5 rounded-lg text-sm font-medium transition-colors duration-150
              {currentIndex === item.index
              ? 'bg-white text-red-900'
              : 'text-red-100 hover:bg-red-800'}"
            onclick={() => changeScreen(item.index)}
          >
            {item.label}
          </button>
        </li>
      {/each}
    </ul>

    <hr class="w-full border-red-700 my-5" />

    <ul class="w-full flex flex-col gap-1">
      <li class="w-full">
        <button
          type="button"
          class="cursor-pointer w-full text-left px-4 py-2.5 rounded-lg text-sm font-medium transition-colors duration-150
            {currentIndex === 3
            ? 'bg-white text-red-900'
            : 'text-red-100 hover:bg-red-800'}"
          onclick={() => changeScreen(3)}
        >
          Avatar
        </button>
      </li>
    </ul>
  </nav>
</aside>
