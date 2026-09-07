<script lang="ts">
  let width = $state(0);
</script>

<svelte:window bind:innerWidth={width} />

<header
  class="flex lg:hidden flex-row bg-red-900 text-white py-2 px-5 md:px-10 items-center"
>
  <div class="flex flex-row items-center">
    <img
      src="/mseuf_icon.jpg"
      alt="MSEUF icon"
      class="rounded-full overflow-hidden w-14 h-14 shrink-0 object-cover"
    />
    <h1 class="font-heading text-mg font-semibold ml-7">
      MSEUF - CHATBOT ADMIN DASHBOARD
    </h1>
  </div>
</header>
