<script lang="ts">
  import WhiteCard from "./WhiteCard.svelte";
  import { fade, scale } from "svelte/transition";

  interface DataPoint {
    label: string;
    handled: number;
    escalated: number;
  }

  interface Props {
    eyebrow?: string;
    title?: string;
    subtitle?: string;
    periodLabel?: string;
    data: DataPoint[];
  }

  let {
    eyebrow = "CONVERSATION PATTERNS",
    title = "Inquiry volume & escalation trends",
    subtitle = "Handled by Rooney versus escalated to admissions staff",
    periodLabel = "Last 7 Days",
    data,
  }: Props = $props();

  const width = 1200;
  const height = 420;
  const padding = { top: 20, right: 20, bottom: 40, left: 60 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;

  let maxValue = $derived(
    Math.max(...data.map((d) => Math.max(d.handled, d.escalated))),
  );

  let niceMax = $derived(Math.ceil(maxValue / 80) * 80 || 80);
  let ticks = $derived(Array.from({ length: 5 }, (_, i) => (niceMax / 4) * i));

  function xFor(index: number) {
    return padding.left + (index / (data.length - 1)) * chartWidth;
  }

  function yFor(value: number) {
    return padding.top + chartHeight - (value / niceMax) * chartHeight;
  }

  function smoothPath(points: { x: number; y: number }[]) {
    if (points.length < 2) return "";
    let d = `M ${points[0].x} ${points[0].y}`;
    for (let i = 0; i < points.length - 1; i++) {
      const p0 = points[i - 1] ?? points[i];
      const p1 = points[i];
      const p2 = points[i + 1];
      const p3 = points[i + 2] ?? p2;

      const cp1x = p1.x + (p2.x - p0.x) / 6;
      const cp1y = p1.y + (p2.y - p0.y) / 6;
      const cp2x = p2.x - (p3.x - p1.x) / 6;
      const cp2y = p2.y - (p3.y - p1.y) / 6;

      d += ` C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${p2.x} ${p2.y}`;
    }
    return d;
  }

  let handledPath = $derived(
    smoothPath(data.map((d, i) => ({ x: xFor(i), y: yFor(d.handled) }))),
  );
  let escalatedPath = $derived(
    smoothPath(data.map((d, i) => ({ x: xFor(i), y: yFor(d.escalated) }))),
  );

  let hoveredIndex = $state<number | null>(null);

  let hoveredPoint = $derived(
    hoveredIndex !== null ? data[hoveredIndex] : null,
  );

  let tooltipLeftPct = $derived(
    hoveredIndex !== null ? (xFor(hoveredIndex) / width) * 100 : 0,
  );
  let tooltipTopPct = $derived(
    hoveredIndex !== null
      ? (Math.min(yFor(hoveredPoint!.handled), yFor(hoveredPoint!.escalated)) /
          height) *
          100
      : 0,
  );
</script>

<WhiteCard>
  <div class="flex items-start justify-between">
    <div>
      <h4 class="text-xs font-bold uppercase tracking-wider text-primary">
        {eyebrow}
      </h4>
      <h2 class="mt-1 text-2xl font-bold">{title}</h2>
      <p class="mt-1 text-sm text-gray-500">{subtitle}</p>
    </div>
    <span class="text-sm text-gray-500">{periodLabel}</span>
  </div>

  <div class="mt-4 flex flex-row items-center gap-6">
    <div class="flex flex-row items-center gap-2">
      <span class="h-2.5 w-2.5 rounded-full bg-primary"></span>
      <span class="text-sm text-gray-600">Total handled</span>
    </div>
    <div class="flex flex-row items-center gap-2">
      <span class="h-2.5 w-2.5 rounded-full bg-[#C89B3C]"></span>
      <span class="text-sm text-gray-600">Escalated to staff</span>
    </div>
  </div>

  <div class="relative mt-4">
    <svg viewBox="0 0 {width} {height}" class="w-full">
      {#each ticks as tick}
        <line
          x1={padding.left}
          x2={width - padding.right}
          y1={yFor(tick)}
          y2={yFor(tick)}
          stroke="#E5E7EB"
          stroke-dasharray="4 4"
        />
        <text
          x={padding.left - 12}
          y={yFor(tick)}
          text-anchor="end"
          dominant-baseline="middle"
          class="fill-gray-500"
          font-size="14"
        >
          {tick}
        </text>
      {/each}

      {#each data as d, i}
        <text
          x={xFor(i)}
          y={height - 10}
          text-anchor={i === 0
            ? "start"
            : i === data.length - 1
              ? "end"
              : "middle"}
          class="fill-gray-500"
          font-size="14"
        >
          {d.label}
        </text>
      {/each}

      <path d={escalatedPath} fill="none" stroke="#C89B3C" stroke-width="3" />
      <path d={handledPath} fill="none" stroke="#7A1F2B" stroke-width="3" />

      {#if hoveredIndex !== null}
        <g transition:fade={{ duration: 120 }}>
          <line
            x1={xFor(hoveredIndex)}
            x2={xFor(hoveredIndex)}
            y1={padding.top}
            y2={height - padding.bottom}
            stroke="#D1D5DB"
            stroke-width="1"
          />
          <circle
            transition:scale={{ duration: 150, start: 0.3 }}
            cx={xFor(hoveredIndex)}
            cy={yFor(data[hoveredIndex].handled)}
            r="5"
            fill="#7A1F2B"
          />
          <circle
            transition:scale={{ duration: 150, start: 0.3 }}
            cx={xFor(hoveredIndex)}
            cy={yFor(data[hoveredIndex].escalated)}
            r="5"
            fill="#C89B3C"
          />
        </g>
      {/if}

      {#each data as d, i}
        {#each data as d, i}
          <rect
            x={xFor(i) - chartWidth / (data.length - 1) / 2}
            y={padding.top}
            width={chartWidth / (data.length - 1)}
            height={chartHeight}
            fill="transparent"
            role="button"
            tabindex="0"
            aria-label="{d.label}: {d.handled} total handled, {d.escalated} escalated"
            onmouseenter={() => (hoveredIndex = i)}
            onmouseleave={() => (hoveredIndex = null)}
            onfocus={() => (hoveredIndex = i)}
            onblur={() => (hoveredIndex = null)}
          />
        {/each}
      {/each}
    </svg>

    {#if hoveredPoint}
      <div
        transition:fade={{ duration: 120 }}
        class="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-md border border-outline bg-white px-3 py-2 text-xs shadow-lg transition-[left,top] duration-150 ease-out"
        style="left: {tooltipLeftPct}%; top: {tooltipTopPct}%; margin-top: -10px;"
      >
        <div class="font-semibold">{hoveredPoint.label}</div>
        <div class="mt-1 flex items-center gap-1.5">
          <span class="h-2 w-2 rounded-full bg-primary"></span>
          <span class="text-gray-600">Total handled:</span>
          <span class="font-semibold">{hoveredPoint.handled}</span>
        </div>
        <div class="mt-0.5 flex items-center gap-1.5">
          <span class="h-2 w-2 rounded-full bg-[#C89B3C]"></span>
          <span class="text-gray-600">Escalated:</span>
          <span class="font-semibold">{hoveredPoint.escalated}</span>
        </div>
      </div>
    {/if}
  </div>
</WhiteCard>
