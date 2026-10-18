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
    class="hidden flex-row items-center gap-4 border-b-2 border-b-outline px-4 py-2 md:flex"
  >
    <div
      class="flex h-10 w-10 items-center justify-center rounded-md bg-primary font-bold text-white"
    >
      S
    </div>

    <div class="mt-2">
      <h2 class="text-base font-bold">
        Org name <span class="text-primary">mascot</span>
      </h2>
      <p class="text-sm font-semibold text-gray-500">Admission Intelligence</p>
    </div>
  </div>

  <nav
    aria-label="Workspace navigation"
    class="w-full p-1 text-sm font-semibold text-gray-500 md:p-4"
  >
    <h3 class="hidden md:block">WORKSPACE</h3>

    <ul class="flex items-stretch justify-around gap-1 overflow-x-auto md:mt-2 md:block md:space-y-1">
      <NavItem href="/overview" text="Overview" icon={OverviewIcon} />
      <NavItem href="/members" text="Members" icon={PersonsIcon} />
      <NavItem
        href="/knowledge-base"
        text="Knowledge Base"
        icon={KnowledgeBaseIcon}
      />
      <!-- <NavItem href="/escalation" text="Escalation" icon={EscalationIcon} /> -->
      <NavItem href="/mascot" text="Mascot" icon={MascotIcon} />
    </ul>
  </nav>

  <footer class="mt-auto hidden md:block"></footer>
</aside>
