<script lang="ts">
  import { onMount } from "svelte";
  import Router, { location, replace } from "svelte-spa-router";
  import routes from "./routes";
  import { auth, initAuth } from "./lib/auth.svelte";

  onMount(() => {
    initAuth();
  });

  // Send the user to /login whenever the token disappears (logout or a 401)
  $effect(() => {
    if (!auth.token && !$location.startsWith("/chat/")) replace("/login");
  });
</script>

<Router {routes} />
