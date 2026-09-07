<script lang="ts">
  let {
    data = [],
    labels = [],
    color = "#3b82f6",
  }: { data: number[]; labels: string[]; color?: string } = $props();

  let width = 500;
  let height = 200;
  let padding = 30;

  let max = $derived(Math.max(...data, 1));
  let min = $derived(Math.min(...data, 0));

  let points = $derived(
    data
      .map((v, i) => {
        let x = padding + (i / (data.length - 1)) * (width - padding * 2);
        let y =
          height -
          padding -
          ((v - min) / (max - min || 1)) * (height - padding * 2);
        return `${x},${y}`;
      })
      .join(" "),
  );
</script>

<svg viewBox="0 0 {width} {height}" class="w-full h-auto">
  <!-- gridlines -->
  {#each [0, 0.25, 0.5, 0.75, 1] as t}
    <line
      x1={padding}
      x2={width - padding}
      y1={padding + t * (height - padding * 2)}
      y2={padding + t * (height - padding * 2)}
      stroke="#e5e7eb"
      stroke-width="1"
    />
  {/each}

  <polyline {points} fill="none" stroke={color} stroke-width="2" />

  {#each data as v, i}
    {@const x = padding + (i / (data.length - 1)) * (width - padding * 2)}
    {@const y =
      height -
      padding -
      ((v - min) / (max - min || 1)) * (height - padding * 2)}
    <circle cx={x} cy={y} r="3" fill={color} />
  {/each}

  {#each labels as label, i}
    {@const x = padding + (i / (labels.length - 1)) * (width - padding * 2)}
    <text {x} y={height - 8} font-size="10" fill="#9ca3af" text-anchor="middle"
      >{label}</text
    >
  {/each}
</svg>
