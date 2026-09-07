<script lang="ts">
  import LineChart from "./LineChart.svelte";
  import BarChart from "./BarChart.svelte";
  import DonutChart from "./DonutChart.svelte";
  import DataTable from "./DataTable.svelte";

  let stats = $state([
    { label: "Total Enquiries", value: "9,842", change: "+6.4%" },
    { label: "Avg Retrieval Latency", value: "310ms", change: "-20ms" },
    { label: "Documents Indexed", value: "1,268", change: "+37" },
    { label: "Fallback Rate", value: "3.7%", change: "-0.4%" },
  ]);

  let recentQueries = $state([
    {
      query: "What are the admission requirements for BS CS?",
      confidence: "0.93",
      status: "resolved",
      time: "3m ago",
    },
    {
      query: "When does enrollment open for next semester?",
      confidence: "0.90",
      status: "resolved",
      time: "9m ago",
    },
    {
      query: "How do I apply for a scholarship?",
      confidence: "0.87",
      status: "resolved",
      time: "16m ago",
    },
    {
      query: "What's the tuition fee for the Nursing program?",
      confidence: "0.58",
      status: "flagged",
      time: "24m ago",
    },
    {
      query: "Can I transfer credits from another university?",
      confidence: "0.42",
      status: "unresolved",
      time: "35m ago",
    },
  ]);

  let topFaqs = $state([
    {
      question: "What are the admission requirements?",
      frequency: 312,
      lastAsked: "2026-09-07",
    },
    {
      question: "When does enrollment open?",
      frequency: 267,
      lastAsked: "2026-09-07",
    },
    {
      question: "How do I apply for a scholarship?",
      frequency: 198,
      lastAsked: "2026-09-06",
    },
    {
      question: "What programs/courses are offered?",
      frequency: 176,
      lastAsked: "2026-09-07",
    },
    {
      question: "What is the tuition fee?",
      frequency: 154,
      lastAsked: "2026-09-06",
    },
    {
      question: "How do I apply for admission online?",
      frequency: 132,
      lastAsked: "2026-09-05",
    },
    {
      question: "Is there a dormitory or housing option?",
      frequency: 108,
      lastAsked: "2026-09-04",
    },
    {
      question: "Can I transfer credits from another school?",
      frequency: 91,
      lastAsked: "2026-09-06",
    },
    {
      question: "What are the entrance exam requirements?",
      frequency: 79,
      lastAsked: "2026-09-03",
    },
    {
      question: "How do I contact the registrar's office?",
      frequency: 64,
      lastAsked: "2026-09-05",
    },
  ]);

  let faqLimit = $state(10);

  let weeklyVolume = [58, 72, 65, 90, 110, 48, 40];
  let weekLabels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  // Avg retrieval confidence score per day (0-1 scale)
  let dailyConfidence = [0.85, 0.87, 0.81, 0.89, 0.92, 0.88, 0.9];

  let documentSources = [
    { label: "Admission Guidelines", value: 420, color: "#3b82f6" },
    { label: "Course Catalog", value: 310, color: "#8b5cf6" },
    { label: "Student Handbook", value: 275, color: "#f97316" },
    { label: "Scholarship & Financial Aid", value: 180, color: "#22c55e" },
    { label: "Enrollment FAQs", value: 83, color: "#eab308" },
  ];

  let statusColor = (status: string) =>
    status === "resolved"
      ? "bg-green-100 text-green-700"
      : status === "flagged"
        ? "bg-yellow-100 text-yellow-700"
        : "bg-red-100 text-red-700";

  let confidenceColor = (c: string) => {
    let n = parseFloat(c);
    if (n >= 0.8) return "text-green-600";
    if (n >= 0.5) return "text-yellow-600";
    return "text-red-600";
  };
</script>

<div class="p-6 bg-gray-50">
  <h1 class="text-2xl font-semibold text-gray-800 mb-6">Dashboard</h1>

  <!-- Stat cards -->
  <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
    {#each stats as stat}
      <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-4">
        <p class="text-sm text-gray-500">{stat.label}</p>
        <p class="text-2xl font-semibold text-gray-800 mt-1">{stat.value}</p>
        <p class="text-xs text-gray-400 mt-1">{stat.change} this week</p>
      </div>
    {/each}
  </div>

  <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
    <!-- Enquiry volume line chart -->
    <div
      class="lg:col-span-2 bg-white rounded-xl shadow-sm border border-gray-100 p-5"
    >
      <h2 class="text-sm font-medium text-gray-600 mb-4">
        Enquiry Volume (Last 7 Days)
      </h2>
      <LineChart data={weeklyVolume} labels={weekLabels} />
    </div>

    <!-- Document source breakdown -->
    <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
      <h2 class="text-sm font-medium text-gray-600 mb-4">
        Chunks by Document Source
      </h2>
      <DonutChart data={documentSources} />
    </div>
  </div>

  <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
    <!-- Avg retrieval confidence bar chart -->
    <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
      <h2 class="text-sm font-medium text-gray-600 mb-4">
        Avg Retrieval Confidence
      </h2>
      <BarChart
        data={dailyConfidence.map((c) => Math.round(c * 100))}
        labels={weekLabels}
        color="#22c55e"
      />
    </div>

    <!-- Recent queries table -->
    <div
      class="lg:col-span-2 bg-white rounded-xl shadow-sm border border-gray-100 p-5"
    >
      <h2 class="text-sm font-medium text-gray-600 mb-4">Recent Enquiries</h2>
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-gray-200 text-left text-gray-500">
            <th class="py-2 px-2 font-medium">Enquiry</th>
            <th class="py-2 px-2 font-medium">Confidence</th>
            <th class="py-2 px-2 font-medium">Status</th>
            <th class="py-2 px-2 font-medium">Time</th>
          </tr>
        </thead>
        <tbody>
          {#each recentQueries as q}
            <tr class="border-b border-gray-100 hover:bg-gray-50">
              <td class="py-2 px-2 text-gray-700 truncate max-w-[220px]"
                >{q.query}</td
              >
              <td class="py-2 px-2 font-medium {confidenceColor(q.confidence)}"
                >{q.confidence}</td
              >
              <td class="py-2 px-2">
                <span
                  class="text-xs px-2 py-0.5 rounded-full {statusColor(
                    q.status,
                  )}">{q.status}</span
                >
              </td>
              <td class="py-2 px-2 text-gray-400 text-xs">{q.time}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Top FAQs -->
  <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-sm font-medium text-gray-600">
        Top Frequently Asked Questions
      </h2>
      <div class="flex gap-2">
        <button
          onclick={() => (faqLimit = 5)}
          class="text-xs px-3 py-1 rounded-full border {faqLimit === 5
            ? 'bg-gray-800 text-white border-gray-800'
            : 'border-gray-300 text-gray-500'}"
        >
          Top 5
        </button>
        <button
          onclick={() => (faqLimit = 10)}
          class="text-xs px-3 py-1 rounded-full border {faqLimit === 10
            ? 'bg-gray-800 text-white border-gray-800'
            : 'border-gray-300 text-gray-500'}"
        >
          Top 10
        </button>
      </div>
    </div>
    <DataTable
      columns={[
        { key: "question", label: "Question" },
        { key: "frequency", label: "Frequency" },
        { key: "lastAsked", label: "Last Asked" },
      ]}
      rows={topFaqs.slice(0, faqLimit)}
    />
  </div>
</div>
