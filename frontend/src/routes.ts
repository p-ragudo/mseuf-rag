// src/routes.ts
import type { RouteDefinition } from "svelte-spa-router";
import Overview from "./lib/routes/Overview.svelte";
import KnowledgeBase from "./lib/routes/KnowledgeBase.svelte";
import Escalation from "./lib/routes/Escalation.svelte";
import Login from "./lib/routes/Login.svelte";

const routes: RouteDefinition = {
  "/": Overview,
  "/knowledge-base": KnowledgeBase,
  "/escalation": Escalation,
  "/login": Login,
};

export default routes;
