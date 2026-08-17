// src/routes.ts
import type { RouteDefinition } from 'svelte-spa-router'
import Home from './routes/Home.svelte'
import About from './routes/About.svelte'

const routes: RouteDefinition = {
  '/': Home,
  '/about': About,
}

export default routes
