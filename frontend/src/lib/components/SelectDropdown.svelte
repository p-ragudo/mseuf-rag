<script lang="ts">
  import { fly } from "svelte/transition";
  import type { Component } from "svelte";
  import DropDownIcon from "../icons/DropDownIcon.svelte";

  interface Props {
    label?: string;
    options: string[];
    selected?: string;
    onSelect?: (option: string) => void;
    icon?: Component<any>;
  }

  let {
    label = "Select",
    options,
    selected = $bindable(),
    onSelect,
    icon: Icon,
  }: Props = $props();

  let open = $state(false);

  function toggle() {
    open = !open;
  }

  function close() {
    open = false;
  }

  function choose(option: string) {
    selected = option;
    onSelect?.(option);
    close();
  }
</script>

<svelte:window onclick={close} />

<div class="relative inline-block">
  <button
    class="w-60 flex flex-row items-center gap-2 rounded-md border border-outline bg-[#F5F8FB] px-3 py-2 text-sm shadow-sm hover:cursor-pointer transition-colors duration-200"
    onclick={(e) => {
      e.stopPropagation();
      toggle();
    }}
  >
    {#if Icon}
      <span class="flex h-4 w-4 shrink-0 items-center justify-center">
        <Icon />
      </span>
    {/if}
    <span class="flex-1 text-left">{selected ?? label}</span>
    <DropDownIcon />
  </button>

  {#if open}
    <div
      transition:fly={{ y: -8, duration: 150 }}
      class="absolute left-0 mt-2 w-48 rounded-md border border-outline bg-white shadow-lg z-10"
    >
      <ul class="py-1 px-1 max-h-60 overflow-y-auto">
        {#each options as option (option)}
          <li>
            <button
              class="w-full flex flex-row items-center justify-between gap-2 text-left px-4 py-2 text-sm hover:bg-accent hover:text-primary transition-colors duration-200"
              onclick={() => choose(option)}
            >
              <span>{option}</span>
              {#if selected === option}
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 14 14"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                  class="shrink-0"
                >
                  <path
                    d="M12 3.5L5.25 10.25L2 7"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
              {/if}
            </button>
          </li>
        {:else}
          <li class="px-4 py-2 text-sm text-gray-500">No options</li>
        {/each}
      </ul>
    </div>
  {/if}
</div>
