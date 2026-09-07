// src/routes.ts
import type { RouteDefinition } from "svelte-spa-router";
import Home from "./lib/routes/Home.svelte";
import About from "./lib/routes/About.svelte";
import Admin from "./lib/routes/Admin.svelte";
import LoginAdmin from "./lib/routes/LoginAdmin.svelte";

const routes: RouteDefinition = {
  "/": Home,
  "/about": About,
  "/admin": Admin,
  "/loginAdmin": LoginAdmin,
};

export default routes;
