<!-- src/App.svelte -->
<script lang="ts">
  import { onMount } from "svelte";
  import Router, { replace } from "svelte-spa-router";
  import routes from "./routes";
  import { auth, initAuth } from "./lib/auth.svelte";

  onMount(() => {
    initAuth();
  });

  // Watch for token loss (logout or 401) without relying on the location store
  $effect(() => {
    const currentHash = window.location.hash.slice(1) || "/";

    // Allow /chat/ routes and /login to remain accessible without a token
    const isPublicRoute =
      currentHash.startsWith("/chat/") || currentHash.startsWith("/login");

    if (!auth.token && !isPublicRoute) {
      replace("/login");
    }
  });
</script>

<Router {routes} />