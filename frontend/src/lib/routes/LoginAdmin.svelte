<script lang="ts">
  import { replace } from "svelte-spa-router";

  let username = "";
  let password = "";

  function handleLogin() {
    replace("/admin");
  }
</script>

<main
  class="w-screen h-screen flex flex-row justify-center items-center bg-[#7F0000]"
>
  <div class="flex flex-col items-center gap-6 p-10">
    <img
      src="/mseuf_icon.jpg"
      alt="mseuf icon"
      class="rounded-full overflow-hidden max:w-xs w-xs shrink-0 object-cover"
    />
    <input
      type="text"
      bind:value={username}
      placeholder="Username"
      class="w-64 px-6 py-3 rounded-full bg-white text-center text-lg outline-none placeholder:text-gray-400"
    />
    <input
      type="password"
      bind:value={password}
      class="w-64 px-6 py-3 rounded-full bg-white text-center text-2xl tracking-widest outline-none"
    />
    <button
      on:click={handleLogin}
      class="w-40 py-2 rounded-full border-2 border-white text-Poppins text-white bg-transparent hover:bg-white hover:text-[#7F0000] transition-colors"
    >
      log-in
    </button>
  </div>
</main>
