<script lang="ts">
  import NavItem from "./NavItem.svelte";
  import EscalationIcon from "../icons/EscalationIcon.svelte";
  import KnowledgeBaseIcon from "../icons/KnowledgeBaseIcon.svelte";
  import MascotIcon from "../icons/MascotIcon.svelte";
  import OverviewIcon from "../icons/OverviewIcon.svelte";

  interface Props {
    currentRoute: string;
  }
</script>

<aside class="flex h-full w-64 shrink-0 flex-col border-r-2 border-r-outline">
  <div
    class="flex flex-row items-center gap-4 border-b-2 border-b-outline px-4 py-2"
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

  <nav class="w-full p-4 text-sm font-semibold text-gray-500">
    <h3>WORKSPACE</h3>

    <ul class="space-y-1">
      <NavItem href="/overview" text="Overview" icon={OverviewIcon} />
      <NavItem
        href="/knowledge-base"
        text="Knowledge Base"
        icon={KnowledgeBaseIcon}
      />
      <NavItem href="/escalation" text="Escalation" icon={EscalationIcon} />
      <NavItem href="/mascot" text="Mascot" icon={MascotIcon} />
    </ul>
  </nav>

  <footer class="mt-auto"></footer>
</aside>
