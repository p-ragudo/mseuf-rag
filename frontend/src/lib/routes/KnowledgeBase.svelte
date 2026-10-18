<script lang="ts">
  import WhiteCard from "../components/WhiteCard.svelte";
  import FilterIcon from "../icons/FilterIcon.svelte";
  import CalendarIcon from "../icons/CalendarIcon.svelte";
  import PersonsIcon from "../icons/PersonsIcon.svelte";
  import SelectDropdown from "../components/SelectDropdown.svelte";
  import RefreshIcon from "../icons/RefreshIcon.svelte";
  import { fade } from "svelte/transition";
  import AppLayout from "../components/AppLayout.svelte";
  import KnowledgeIngestionCenter from "../components/KnowledgeIngestionCenter.svelte";

  let selectedTimeframe: string = "Last 24 hours";
  const timeframeOptions: string[] = [
    "Last 24 hours",
    "Last 7 days",
    "Last 30 days",
    "Semester-to-date",
  ];

  let selectedVisitor: string = "All Visitors";
  const visitorOptions: string[] = [
    "All Visitors",
    "Prospective / External",
    "Enrolled / Internal",
  ];

  let isRefreshed: boolean = false;
  function refreshData() {
    isRefreshed = true;
  }

  const categories = [
    "Admissions Requirements",
    "Tuition & Fees",
    "Scholarships",
    "Transferee Policies",
  ];
</script>

<AppLayout>
  <div class="flex-1 px-6 py-4 gap-1">
    <h3
      class="text-primary flex flex-row gap-2 font-semibold text-sm uppercase tracking-wider mb-2"
    >
      <span class="bg-primary w-1 rounded-2xl"></span>INSTITUTION COMMAND CENTER
    </h3>
    <h1 class="text-3xl font-bold">Knowledge & ingestion</h1>
    <p class="mb-4 text-gray-600">
      Review the content powering Rooney’s answers and prepare new sources.
    </p>

    <KnowledgeIngestionCenter {categories} />
  </div>
</AppLayout>
