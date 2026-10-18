<script lang="ts">
  import WhiteCard from "./WhiteCard.svelte";
  import { fade, scale } from "svelte/transition";

  interface DataPoint {
    label: string; // short label for the x-axis, e.g. "Oct 13"
    fullLabel?: string; // longer label for the tooltip, e.g. "Tue, Oct 13, 2026"
    value: number;
  }

  interface Props {
    eyebrow?: string;
    title?: string;
    subtitle?: string;
    periodLabel?: string;
    seriesLabel?: string;
    data: DataPoint[];
    loading?: boolean;
  }

  let {
    eyebrow = "CONVERSATION PATTERNS",
    title = "Inquiry volume",
    subtitle = "Questions asked over the selected period",
    periodLabel = "Last 7 Days",
    seriesLabel = "Inquiries",
    data,
    loading = false,
  }: Props = $props();

  const width = 1200;
  const height = 420;
  const padding = { top: 20, right: 20, bottom: 40, left: 60 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;

  // Never show more than this many x-axis labels, however many points there are
  const MAX_X_LABELS = 7;

  let count = $derived(data.length);
  let maxValue = $derived(count ? Math.max(...data.map((d) => d.value)) : 0);

  // Round the top of the y-axis up to a tidy number so ticks are whole values
  function niceMaxFor(max: number): number {
    if (max <= 0) return 4;
    const rough = max / 4;
    const pow = Math.pow(10, Math.floor(Math.log10(rough)));
    const step =
      [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= rough) ??
      10 * pow;
    return Math.max(1, step) * 4;
  }

  let niceMax = $derived(niceMaxFor(maxValue));
  let ticks = $derived(Array.from({ length: 5 }, (_, i) => (niceMax / 4) * i));

  // Evenly spaced label positions, always including the first and last point
  let labelIndices = $derived.by(() => {
    if (count <= MAX_X_LABELS) return data.map((_, i) => i);
    return Array.from({ length: MAX_X_LABELS }, (_, k) =>
      Math.round((k * (count - 1)) / (MAX_X_LABELS - 1)),
    );
  });

  function xFor(index: number) {
    if (count <= 1) return padding.left + chartWidth / 2;
    return padding.left + (index / (count - 1)) * chartWidth;
  }

  function yFor(value: number) {
    return padding.top + chartHeight - (value / niceMax) * chartHeight;
  }

  const yMin = padding.top;
  const yMax = padding.top + chartHeight;
  const clampY = (y: number) => Math.min(Math.max(y, yMin), yMax);

  function smoothPath(points: { x: number; y: number }[]) {
    if (points.length === 0) return "";
    if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;

    let d = `M ${points[0].x} ${points[0].y}`;
    for (let i = 0; i < points.length - 1; i++) {
      const p0 = points[i - 1] ?? points[i];
      const p1 = points[i];
      const p2 = points[i + 1];
      const p3 = points[i + 2] ?? p2;

      const cp1x = p1.x + (p2.x - p0.x) / 6;
      // Clamped so the curve can't dip below zero or above the top
      const cp1y = clampY(p1.y + (p2.y - p0.y) / 6);
      const cp2x = p2.x - (p3.x - p1.x) / 6;
      const cp2y = clampY(p2.y - (p3.y - p1.y) / 6);

      d += ` C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${p2.x} ${p2.y}`;
    }
    return d;
  }

  let linePath = $derived(
    smoothPath(data.map((d, i) => ({ x: xFor(i), y: yFor(d.value) }))),
  );

  // Point markers only make sense while there are few points
  let showDots = $derived(count > 0 && count <= 31);

  let hoveredIndex = $state<number | null>(null);
  let hoveredPoint = $derived(
    hoveredIndex !== null ? (data[hoveredIndex] ?? null) : null,
  );

  // Keep the tooltip inside the card near the left and right edges
  let tooltipLeftPct = $derived(
    hoveredIndex !== null
      ? Math.min(Math.max((xFor(hoveredIndex) / width) * 100, 12), 88)
      : 0,
  );
  let tooltipTopPct = $derived(
    hoveredPoint ? (yFor(hoveredPoint.value) / height) * 100 : 0,
  );

  let hoverWidth = $derived(count > 1 ? chartWidth / (count - 1) : chartWidth);
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
      <span class="text-sm text-gray-600">{seriesLabel}</span>
    </div>
  </div>

  <div class="relative mt-4">
    {#if loading}
      <div
        class="aspect-[1200/420] w-full animate-pulse rounded-lg bg-gray-100"
        aria-busy="true"
        aria-label="Loading chart"
      ></div>
    {:else if count === 0}
      <div
        class="flex h-48 items-center justify-center text-sm text-gray-500"
      >
        No data for this period yet.
      </div>
    {:else}
      <svg
        viewBox="0 0 {width} {height}"
        class="w-full"
        role="img"
        aria-label="{seriesLabel} over time, {count} data points, highest value {maxValue}"
      >
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
            {tick.toLocaleString()}
          </text>
        {/each}

        {#each labelIndices as i, k}
          <text
            x={xFor(i)}
            y={height - 10}
            text-anchor={k === 0
              ? "start"
              : k === labelIndices.length - 1
                ? "end"
                : "middle"}
            class="fill-gray-500"
            font-size="14"
          >
            {data[i].label}
          </text>
        {/each}

        <path d={linePath} fill="none" stroke="#7A1F2B" stroke-width="3" />

        {#if showDots}
          {#each data as d, i}
            <circle cx={xFor(i)} cy={yFor(d.value)} r="3" fill="#7A1F2B" />
          {/each}
        {/if}

        {#if hoveredIndex !== null && hoveredPoint}
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
              cy={yFor(hoveredPoint.value)}
              r="5"
              fill="#7A1F2B"
            />
          </g>
        {/if}

        {#each data as d, i}
          <rect
            x={xFor(i) - hoverWidth / 2}
            y={padding.top}
            width={hoverWidth}
            height={chartHeight}
            fill="transparent"
            role="presentation"
            onmouseenter={() => (hoveredIndex = i)}
            onmouseleave={() => (hoveredIndex = null)}
          />
        {/each}
      </svg>

      {#if hoveredPoint}
        <div
          transition:fade={{ duration: 120 }}
          class="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-md border border-outline bg-white px-3 py-2 text-xs shadow-lg transition-[left,top] duration-150 ease-out"
          style="left: {tooltipLeftPct}%; top: {tooltipTopPct}%; margin-top: -10px;"
        >
          <div class="font-semibold">
            {hoveredPoint.fullLabel ?? hoveredPoint.label}
          </div>
          <div class="mt-1 flex items-center gap-1.5">
            <span class="h-2 w-2 rounded-full bg-primary"></span>
            <span class="text-gray-600">{seriesLabel}:</span>
            <span class="font-semibold">
              {hoveredPoint.value.toLocaleString()}
            </span>
          </div>
        </div>
      {/if}
    {/if}
  </div>
</WhiteCard>