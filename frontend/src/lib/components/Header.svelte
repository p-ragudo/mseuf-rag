<script lang="ts">
  import { push, pop } from "svelte-spa-router";
  import InfoIcon from "../icons/InfoIcon.svelte";
  import ExitIcon from "../icons/ExitIcon.svelte";

  export let disableInfo: boolean = false;
  export let pageIsToPop: boolean = false;

  function goToAbout() {
    push("/about");
  }

  function goBack() {
    pop();
  }
</script>

<header
  class="flex flex-row bg-red-900 text-white py-2 px-5  items-center"
>
  <div class="flex flex-row items-center">
    <img src="/icon.png" alt="icon" class="w-14" />
    <h1 class="font-heading text-mg font-semibold">MSEUF - CHATBOT</h1>
  </div>

  <!--ACTIONS-->
  <div class="fixed right-0 mr-5 items-center">
    {#if !disableInfo}
      <button on:click={goToAbout}>
        <InfoIcon size={30} />
      </button>
    {/if}
    {#if pageIsToPop}
      <button on:click={goBack}>
        <ExitIcon size={30} />
      </button>
    {/if}
  </div>
</header>
