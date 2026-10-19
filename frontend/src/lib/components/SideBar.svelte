<script lang="ts">
  import NavItem from "./NavItem.svelte";
  import EscalationIcon from "../icons/EscalationIcon.svelte";
  import KnowledgeBaseIcon from "../icons/KnowledgeBaseIcon.svelte";
  import MascotIcon from "../icons/MascotIcon.svelte";
  import OverviewIcon from "../icons/OverviewIcon.svelte";
  import PersonsIcon from "../icons/PersonsIcon.svelte";

  interface Props {
    currentRoute: string;
  }
</script>

<aside
  class="flex h-auto w-full shrink-0 flex-col border-t-2 border-outline bg-white pb-[env(safe-area-inset-bottom)] md:h-full md:w-64 md:border-r-2 md:border-t-0"
>
  <div
    class="hidden h-16 shrink-0 flex-row items-center gap-4 border-b-2 border-b-outline px-4 md:flex"
  >
    <div
      class="flex h-10 w-10 items-center justify-center rounded-md bg-primary text-xs font-bold tracking-wide text-white"
    >
      RAG
    </div>

    <div>
      <h2 class="text-base font-bold">MSEUF RAG</h2>
      <p class="text-sm font-semibold text-gray-500">Admissions Assistant</p>
    </div>
  </div>

  <nav
    aria-label="Workspace navigation"
    class="w-full p-1 text-sm font-semibold text-gray-500 md:p-4"
  >
    <h3 class="hidden text-xs font-bold uppercase tracking-wider text-gray-400 md:block">Workspace</h3>

    <ul class="flex items-stretch justify-around gap-1 overflow-x-auto md:mt-2 md:block md:space-y-1">
      <NavItem href="/overview" text="Dashboard" icon={OverviewIcon} />
      <NavItem href="/members" text="Team" icon={PersonsIcon} />
      <NavItem
        href="/knowledge-base"
        text="Knowledge Base"
        icon={KnowledgeBaseIcon}
      />
      <!-- <NavItem href="/escalation" text="Escalation" icon={EscalationIcon} /> -->
      <NavItem href="/mascot" text="Chat Branding" icon={MascotIcon} />
    </ul>
  </nav>

  <footer class="mt-auto hidden md:block"></footer>
</aside>
