// src/routes.ts
import type { RouteDefinition } from 'svelte-spa-router'
import Home from './lib/routes/Home.svelte'
import About from './lib/routes/About.svelte'

const routes: RouteDefinition = {
  '/': Home,
  '/about': About,
}

export default routes
