<script lang="ts">
  let {
    data = [],
  }: { data: { label: string; value: number; color: string }[] } = $props();

  let total = $derived(data.reduce((sum, d) => sum + d.value, 0));

  let segments = $derived.by(() => {
    let cumulative = 0;
    return data.map((d) => {
      let startAngle = (cumulative / total) * 360;
      cumulative += d.value;
      let endAngle = (cumulative / total) * 360;
      return {
        ...d,
        startAngle,
        endAngle,
        percent: ((d.value / total) * 100).toFixed(1),
      };
    });
  });

  function polarToCartesian(
    cx: number,
    cy: number,
    r: number,
    angleDeg: number,
  ) {
    let angleRad = ((angleDeg - 90) * Math.PI) / 180;
    return { x: cx + r * Math.cos(angleRad), y: cy + r * Math.sin(angleRad) };
  }

  function arcPath(
    startAngle: number,
    endAngle: number,
    r = 80,
    cx = 100,
    cy = 100,
  ) {
    let start = polarToCartesian(cx, cy, r, endAngle);
    let end = polarToCartesian(cx, cy, r, startAngle);
    let largeArc = endAngle - startAngle > 180 ? 1 : 0;
    return `M ${cx} ${cy} L ${start.x} ${start.y} A ${r} ${r} 0 ${largeArc} 0 ${end.x} ${end.y} Z`;
  }
</script>

<div class="flex items-center gap-6">
  <svg viewBox="0 0 200 200" class="w-40 h-40">
    {#each segments as seg}
      <path d={arcPath(seg.startAngle, seg.endAngle)} fill={seg.color} />
    {/each}
    <circle cx="100" cy="100" r="45" fill="white" />
  </svg>
  <ul class="space-y-2">
    {#each segments as seg}
      <li class="flex items-center gap-2 text-sm">
        <span class="w-3 h-3 rounded-full" style="background-color: {seg.color}"
        ></span>
        <span class="text-gray-600">{seg.label}</span>
        <span class="text-gray-400 text-xs">({seg.percent}%)</span>
      </li>
    {/each}
  </ul>
</div>
