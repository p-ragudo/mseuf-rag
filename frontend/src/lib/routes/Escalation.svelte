<script lang="ts">
  import WhiteCard from "../components/WhiteCard.svelte";
  import FilterIcon from "../icons/FilterIcon.svelte";
  import CalendarIcon from "../icons/CalendarIcon.svelte";
  import PersonsIcon from "../icons/PersonsIcon.svelte";
  import SelectDropdown from "../components/SelectDropdown.svelte";
  import RefreshIcon from "../icons/RefreshIcon.svelte";
  import { fade } from "svelte/transition";
  import AppLayout from "../components/AppLayout.svelte";
  import LowConfidenceQueryQueue from "../components/LowConfidenceQueryQueue.svelte";

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

  const queryItems = [
    {
      id: "1",
      timestamp: "Today, 10:24 AM",
      question:
        "Can I transfer my BSIT credits from a different university after the second semester?",
      confidence: 42,
      category: "Transferee",
      status: "Unassigned",
    },
    {
      id: "2",
      timestamp: "Today, 9:48 AM",
      question:
        "Is the OSAS scholarship available to working students with partial units?",
      confidence: 38,
      category: "Scholarships",
      status: "Unassigned",
    },
    {
      id: "3",
      timestamp: "Today, 9:12 AM",
      question:
        "When is the special entrance exam schedule for late applicants?",
      confidence: 51,
      category: "Entrance Exam",
      status: "Unassigned",
    },
    {
      id: "4",
      timestamp: "Yesterday, 4:36 PM",
      question:
        "Are there installment plans for first-year engineering laboratory fees?",
      confidence: 46,
      category: "Tuition",
      status: "Unassigned",
    },
    {
      id: "5",
      timestamp: "Yesterday, 2:14 PM",
      question:
        "Can an international applicant submit an alternative to Form 138?",
      confidence: 34,
      category: "Requirements",
      status: "Unassigned",
    },
  ];
</script>

<AppLayout>
  <div class="flex-1 px-6 py-4 gap-1">
    <h3
      class="text-primary flex flex-row gap-2 font-semibold text-sm uppercase tracking-wider mb-2"
    >
      <span class="bg-primary w-1 rounded-2xl"></span>INSTITUTION COMMAND CENTER
    </h3>
    <h1 class="text-3xl font-bold">Unanswered inquiries</h1>
    <p class=" text-gray-600">
      Review questions that need a human answer or a better knowledge source.
    </p>

    <WhiteCard style="my-4 flex flex-row justify-between gap-4">
      <div class="flex flex-row gap-4 items-center">
        <FilterIcon />
        <SelectDropdown
          label="Timeframe"
          options={timeframeOptions}
          bind:selected={selectedTimeframe}
          icon={CalendarIcon}
        />
        <SelectDropdown
          label="Visitor Type"
          options={visitorOptions}
          bind:selected={selectedVisitor}
          icon={PersonsIcon}
        />
      </div>
      <div class="flex flex-row items-center gap-3">
        <span
          transition:fade={{ duration: 150 }}
          class="text-sm font-medium text-gray-500"
        >
          {#if isRefreshed}
            Data refreshed!
          {:else}
            Last refreshed: 5 minutes ago
          {/if}
        </span>

        <button
          class="border border-outline bg-[#F5F8FB] px-3 py-2 text-sm shadow-sm rounded-lg hover:cursor-pointer flex flex-row items-center gap-2"
          onclick={refreshData}
        >
          <RefreshIcon /> Refresh
        </button>
      </div>
    </WhiteCard>

    <LowConfidenceQueryQueue
      items={queryItems}
      onAction={(item, action) => console.log(action, "on", item.id)}
    />
  </div>
</AppLayout>
