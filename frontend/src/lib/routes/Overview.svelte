<script lang="ts">
  import FilterIcon from "../icons/FilterIcon.svelte";
  import CalendarIcon from "../icons/CalendarIcon.svelte";
  import AppLayout from "../components/AppLayout.svelte";
  import WhiteCard from "../components/WhiteCard.svelte";
  import StatCard from "../components/StatCard.svelte";
  import SelectDropdown from "../components/SelectDropdown.svelte";
  import RefreshIcon from "../icons/RefreshIcon.svelte";
  import TrendChart from "../components/TrendChart.svelte";
  import TopicsBarList from "../components/TopicsBarlist.svelte";
  import KnowledgeAssetsTable from "../components/KnowledgeAssestTable.svelte";
  import { push } from "svelte-spa-router";
  import { authFetch } from "../auth.svelte";

  type StatsResponse = {
    inquiry_count: number;
    satisfaction_rate: number; // percent, 0-100
    average_response_time: number; // milliseconds
    top_10_inquiries: Record<string, number>;
    top_10_chunks: Record<string, number>;
    top_10_chunks_access_time: Record<string, string>; // ISO timestamps (UTC)
    chart_data: { date: string; count: number }[]; // bucket start date + count
  };

  // TODO: replace with the logged-in user's organization id
  const orgId = 1;

  // Dropdown label -> value the backend accepts
  const rangeOptions = [
    { label: "Last 7 days", value: "last_7_days" },
    { label: "Last 30 days", value: "last_30_days" },
    { label: "Last 90 days", value: "last_90_days" },
    { label: "Last year", value: "last_year" },
    { label: "All time", value: "all_time" },
  ];
  const timeframeOptions: string[] = rangeOptions.map((o) => o.label);

  let selectedTimeframe = $state("Last 7 days");
  let rangeKey = $derived(
    rangeOptions.find((o) => o.label === selectedTimeframe)?.value ??
      "last_7_days",
  );

  let stats = $state<StatsResponse | null>(null);
  let loading = $state(false);
  let errorMessage = $state("");
  let lastRefreshed = $state<Date | null>(null);

  // Guards against an older request finishing after a newer one
  let requestId = 0;

  async function loadStats(range: string) {
    const current = ++requestId;
    loading = true;
    errorMessage = "";

    try {
      const res = await authFetch("/stats", {
        method: "POST",
        body: JSON.stringify({ org_id: orgId, range }),
      });

      if (!res.ok) {
        let message = `Request failed (${res.status})`;
        try {
          const data = await res.json();
          if (typeof data.detail === "string") message = data.detail;
        } catch {
          // not JSON
        }
        throw new Error(message);
      }

      const data: StatsResponse = await res.json();
      if (current !== requestId) return;

      stats = data;
      lastRefreshed = new Date();
    } catch (err) {
      if (current !== requestId) return;
      errorMessage =
        err instanceof Error ? err.message : "Could not load statistics.";
    } finally {
      if (current === requestId) loading = false;
    }
  }

  // Loads on mount and again whenever the timeframe changes
  $effect(() => {
    loadStats(rangeKey);
  });

  function refreshData() {
    loadStats(rangeKey);
  }

  // ---- formatting helpers ----

  function formatDuration(ms: number): string {
    if (!ms) return "—";
    return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
  }

  function formatTime(date: Date): string {
    return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }

  function formatAccessed(iso?: string): string {
    if (!iso) return "—";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "—";

    const now = new Date();
    if (date.toDateString() === now.toDateString()) {
      return `Today, ${formatTime(date)}`;
    }
    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    if (date.toDateString() === yesterday.toDateString()) {
      return `Yesterday, ${formatTime(date)}`;
    }
    return `${date.toLocaleDateString([], { month: "short", day: "numeric" })}, ${formatTime(date)}`;
  }

  function toItems(record: Record<string, number>) {
    return Object.entries(record)
      .map(([label, value]) => ({ label, value }))
      .sort((a, b) => b.value - a.value);
  }

  // ---- derived view data ----

  let inquiryItems = $derived(stats ? toItems(stats.top_10_inquiries) : []);

  // top_10_inquiries is empty until questions are stored on each response,
  // so fall back to the most referenced documents.
  let topicsAreInquiries = $derived(inquiryItems.length > 0);
  let topicItems = $derived(
    topicsAreInquiries
      ? inquiryItems
      : stats
        ? toItems(stats.top_10_chunks)
        : [],
  );

  let documents = $derived.by(() => {
    const s = stats;
    if (!s) return [];
    return Object.entries(s.top_10_chunks).map(([title, accessed]) => ({
      title,
      source: "—", // not provided by the stats API
      chunks: 0, // not provided by the stats API
      accessed,
      lastAccessed: formatAccessed(s.top_10_chunks_access_time[title]),
    }));
  });

  type Granularity = "day" | "week" | "month";

  // Must match the bucket sizes the backend uses (see granularity_for in stats.py)
  let granularity = $derived<Granularity>(
    rangeKey === "all_time" ? "month" : rangeKey === "last_year" ? "week" : "day",
  );

  function parseBucket(isoDate: string): Date | null {
    const date = new Date(`${isoDate}T00:00:00`); // local midnight, no timezone shift
    return Number.isNaN(date.getTime()) ? null : date;
  }

  // Short label for the x-axis
  function shortLabel(isoDate: string, g: Granularity): string {
    const date = parseBucket(isoDate);
    if (!date) return isoDate;
    return g === "month"
      ? date.toLocaleDateString([], { month: "short", year: "numeric" })
      : date.toLocaleDateString([], { month: "short", day: "numeric" });
  }

  // Longer label for the tooltip
  function fullLabel(isoDate: string, g: Granularity): string {
    const date = parseBucket(isoDate);
    if (!date) return isoDate;
    if (g === "month") {
      return date.toLocaleDateString([], { month: "long", year: "numeric" });
    }
    if (g === "week") {
      return `Week of ${date.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}`;
    }
    return date.toLocaleDateString([], {
      weekday: "short",
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  }

  // One point per day (per week for "Last year", per month for "All time")
  let chartData = $derived(
    (stats?.chart_data ?? []).map((point) => ({
      label: shortLabel(point.date, granularity),
      fullLabel: fullLabel(point.date, granularity),
      value: point.count,
    })),
  );
</script>

<AppLayout>
  <div class="flex-1 px-6 py-4 gap-1">
    <h3
      class="text-primary flex flex-row gap-2 font-semibold text-sm uppercase tracking-wider mb-2"
    >
      <span class="bg-primary w-1 rounded-2xl"></span>INSTITUTION COMMAND CENTER
    </h3>
    <h1 class="text-3xl font-bold">Overview</h1>
    <p class="text-gray-600">
      See what students ask, and where your team is needed.
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
      </div>
      <div class="flex flex-row items-center gap-3">
        <span class="text-sm font-medium text-gray-500">
          {#if loading}
            Refreshing...
          {:else if lastRefreshed}
            Last refreshed: {formatTime(lastRefreshed)}
          {:else}
            Not loaded yet
          {/if}
        </span>

        <button
          class="border border-outline bg-[#F5F8FB] px-3 py-2 text-sm shadow-sm rounded-lg hover:cursor-pointer flex flex-row items-center gap-2 disabled:cursor-not-allowed disabled:opacity-60"
          onclick={refreshData}
          disabled={loading}
        >
          <RefreshIcon /> Refresh
        </button>
      </div>
    </WhiteCard>

    {#if errorMessage}
      <div
        role="alert"
        class="mb-4 flex flex-row items-center justify-between gap-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        <span>{errorMessage}</span>
        <button
          type="button"
          class="font-semibold hover:cursor-pointer hover:underline"
          onclick={refreshData}
        >
          Try again
        </button>
      </div>
    {/if}

    {#snippet chatIcon()}
      <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z" />
      </svg>
    {/snippet}

    {#snippet thumbIcon()}
      <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M7 10v12" />
        <path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z" />
      </svg>
    {/snippet}

    {#snippet clockIcon()}
      <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="10" />
        <polyline points="12 6 12 12 16 14" />
      </svg>
    {/snippet}

    <!-- Key numbers -->
    <div class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <StatCard
        label="Total inquiries"
        value={stats ? stats.inquiry_count.toLocaleString() : "—"}
        hint={`In ${selectedTimeframe.toLowerCase()}`}
        {loading}
        icon={chatIcon}
      />

      <StatCard
        label="Satisfaction rate"
        value={stats ? `${stats.satisfaction_rate.toFixed(1)}%` : "—"}
        hint="Share of rated answers marked helpful"
        {loading}
        icon={thumbIcon}
      />

      <StatCard
        label="Average response time"
        value={stats ? formatDuration(stats.average_response_time) : "—"}
        hint="Average time to answer a question"
        {loading}
        icon={clockIcon}
      />
    </div>

    <div class="my-4 grid grid-cols-1 gap-4 lg:grid-cols-[3fr_2fr]">
      <TrendChart
        eyebrow="Conversation sessions"
        title={stats ? stats.inquiry_count.toLocaleString() : "—"}
        subtitle="Inquiries in the selected timeframe"
        periodLabel={selectedTimeframe}
        data={chartData}
        {loading}
      />

      <TopicsBarList
        eyebrow={topicsAreInquiries ? "QUESTION TOPICS" : "KNOWLEDGE BASE"}
        title={topicsAreInquiries
          ? "Most frequent inquiries"
          : "Most referenced documents"}
        subtitle={topicsAreInquiries
          ? "Top questions across student conversations"
          : "Documents used most often to answer questions"}
        items={topicItems}
        {loading}
      />
    </div>

    <KnowledgeAssetsTable
      {documents}
      {loading}
      onViewAll={() => push("/knowledge-base")}
    />
  </div>
</AppLayout>