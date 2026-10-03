<script lang="ts">
  interface UserProfile {
    id: string;
    name: string;
    initials: string;
  }

  interface Props {
    title?: string;
    profiles: UserProfile[];
    onSelect?: (profile: UserProfile) => void;
  }

  let { title = "User Menu", profiles, onSelect }: Props = $props();
</script>

<div
  class="absolute right-0 mt-2 w-48 rounded-md border border-outline bg-white shadow-lg z-10"
>
  <h3 class="px-4 py-2 text-sm font-bold">{title}</h3>
  <ul class="py-1">
    {#each profiles as profile (profile.id)}
      <li>
        <button
          class="w-full text-left px-4 py-2 text-sm hover:bg-accent hover:text-primary transition-colors duration-200"
          onclick={() => onSelect?.(profile)}
        >
          <span class="rounded-full bg-accent text-primary p-2 font-semibold"
            >{profile.initials}</span
          >
          {profile.name}
        </button>
      </li>
    {/each}
  </ul>
</div>
