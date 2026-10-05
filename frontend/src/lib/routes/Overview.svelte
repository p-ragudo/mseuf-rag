<script lang="ts">
  import StatusTray from "../components/StatusTray.svelte";
  import FilterIcon from "../icons/FilterIcon.svelte";
  import CalendarIcon from "../icons/CalendarIcon.svelte";
  import PersonsIcon from "../icons/PersonsIcon.svelte";
  import AppLayout from "../components/AppLayout.svelte";
  import WhiteCard from "../components/WhiteCard.svelte";
  import SelectDropdown from "../components/SelectDropdown.svelte";
  import RefreshIcon from "../icons/RefreshIcon.svelte";
  import TrendChart from "../components/TrendChart.svelte";
  import TopicsBarList from "../components/TopicsBarlist.svelte";
  import KnowledgeAssetsTable from "../components/KnowledgeAssestTable.svelte";
  import HumanHandoffCard from "../components/HumanHandOffCard.svelte";
  import { auth, logout } from "../auth.svelte";
  import { fade } from "svelte/transition";
  import { push } from "svelte-spa-router";

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

  const chartData = [
    { label: "Mon", handled: 205, escalated: 22 },
    { label: "Tue", handled: 244, escalated: 26 },
    { label: "Wed", handled: 226, escalated: 24 },
    { label: "Thu", handled: 288, escalated: 32 },
    { label: "Fri", handled: 316, escalated: 30 },
    { label: "Sat", handled: 254, escalated: 20 },
    { label: "Sun", handled: 300, escalated: 25 },
  ];

  const topics = [
    { label: "Tuition & payment options", value: 582 },
    { label: "BSCS & BSIT programs", value: 491 },
    { label: "Scholarships & OSAS", value: 438 },
    { label: "Admission requirements", value: 384 },
    { label: "Entrance exam schedules", value: 346 },
    { label: "Transferee policies", value: 271 },
    { label: "Enrollment deadlines", value: 223 },
    { label: "Engineering curricula", value: 187 },
    { label: "Campus facilities", value: 126 },
  ];

  const documents = [
    {
      title: "AY 2026–2027 Admissions Guide",
      source: "PDF",
      chunks: 84,
      accessed: 1248,
      lastAccessed: "Today, 10:42 AM",
    },
    {
      title: "BSCS Program Curriculum",
      source: "PDF",
      chunks: 56,
      accessed: 984,
      lastAccessed: "Today, 10:38 AM",
    },
    {
      title: "Tuition & Miscellaneous Fees",
      source: "Web Crawl",
      chunks: 32,
      accessed: 876,
      lastAccessed: "Today, 10:31 AM",
    },
    {
      title: "OSAS Scholarship Guidelines",
      source: "PDF",
      chunks: 41,
      accessed: 742,
      lastAccessed: "Today, 10:22 AM",
    },
    {
      title: "Transferee Admissions Policy",
      source: "Web Crawl",
      chunks: 28,
      accessed: 536,
      lastAccessed: "Today, 9:57 AM",
    },
  ];

  const pendingInquiries = [
    {
      question:
        "Can I transfer my BSIT credits from a different university after the second semester?",
      confidence: 42,
      category: "Transferee",
    },
    {
      question:
        "Is the OSAS scholarship available to working students with partial units?",
      confidence: 38,
      category: "Scholarships",
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
    <h1 class="text-3xl font-bold">Overview</h1>
    <p class=" text-gray-600">
      See what students ask, how (boot name here) responds, and where your team
      is needed.
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

    <StatusTray />

    <div class="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[3fr_2fr]">
      <TrendChart
        eyebrow="Conversation sessions"
        title="2,847"
        subtitle="2,050 external · 797 internal"
        periodLabel={selectedTimeframe}
        data={chartData}
      />

      <TopicsBarList
        eyebrow="QUESTION TOPICS"
        title="Most frequent inquiries"
        subtitle="Top categories across student conversations"
        items={topics}
      />

      <KnowledgeAssetsTable
        {documents}
        onViewAll={() => push("/knowledge-base")}
      />

      <HumanHandoffCard
        openCount={5}
        inquiries={pendingInquiries}
        onReview={() => push("/escalation")}
      />
    </div>
  </div>
</AppLayout>
