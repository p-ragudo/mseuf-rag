import { wrap } from "svelte-spa-router/wrap";
import { replace } from "svelte-spa-router";
import type { RouteDefinition } from "svelte-spa-router";
import { auth } from "./lib/auth.svelte";
import Overview from "./lib/routes/Overview.svelte";
import KnowledgeBase from "./lib/routes/KnowledgeBase.svelte";
import Escalation from "./lib/routes/Escalation.svelte";
import Mascot from "./lib/routes/Mascot.svelte";
import Login from "./lib/routes/Login.svelte";
import NotFound from "./lib/routes/NotFound.svelte";
import Chat from "./lib/routes/Chat.svelte";

function requireAuth(): boolean {
  if (auth.token) return true;
  replace("/login");
  return false;
}

function requireGuest(): boolean {
  if (!auth.token) return true;
  replace("/overview");
  return false;
}

const protectedRoute = (component: any) =>
  wrap({ component, conditions: [requireAuth] });

const routes: RouteDefinition = {
  "/overview": protectedRoute(Overview),
  "/knowledge-base": protectedRoute(KnowledgeBase),
  "/escalation": protectedRoute(Escalation),
  "/mascot": protectedRoute(Mascot),
  "/login": wrap({ component: Login, conditions: [requireGuest] }),
  "/chat/:id": Chat,
  "*": NotFound,
};

export default routes;
