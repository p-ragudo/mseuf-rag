<script lang="ts">
  import { link } from "svelte-spa-router";
  import { onMount, type Component } from "svelte";

  interface Props {
    href: string;
    text: string;
    icon?: Component<{ color?: string }>;
  }

  let { href, text, icon: Icon }: Props = $props();

  let currentRoute = $state(normalizePath(window.location.hash.slice(1)));

  function normalizePath(path: string) {
    const withoutQuery = path.split("?")[0];
    const trimmed = withoutQuery.replace(/\/+$/, "");
    return trimmed || "/";
  }

  function updateCurrentRoute() {
    currentRoute = normalizePath(window.location.hash.slice(1));
  }

  onMount(() => {
    window.addEventListener("hashchange", updateCurrentRoute);
    return () => window.removeEventListener("hashchange", updateCurrentRoute);
  });

  let active = $derived(currentRoute === normalizePath(href));
</script>

<li class="min-w-0 flex-1 md:flex-none">
  <a
    {href}
    use:link
    aria-current={active ? "page" : undefined}
    class={`flex w-full flex-col items-center justify-center gap-1 rounded-md px-1 py-2 text-[10px] leading-tight transition-colors duration-200 md:flex-row md:justify-start md:gap-3 md:p-2 md:text-sm ${
      active ? "bg-accent text-primary" : "text-gray-700 hover:bg-gray-200"
    }`}
  >
    {#if Icon}
      <span class="flex h-5 w-5 shrink-0 items-center justify-center">
        <Icon color={active ? "#760a15" : "#59616E"} />
      </span>
    {/if}
    <span>{text}</span>
  </a>
</li>
