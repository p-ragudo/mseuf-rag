<script lang="ts">
  interface Props {
    color?: string;
  }

  let { color = "#59616E" }: Props = $props();
</script>

<svg
  width="15"
  height="15"
  viewBox="0 0 15 15"
  fill="none"
  xmlns="http://www.w3.org/2000/svg"
>
  <path
    d="M7.5 1.5V3"
    stroke={color}
    stroke-width="1.25"
    stroke-linecap="round"
  />

  <circle cx="7.5" cy="1.25" r="0.75" fill={color} />

  <rect
    x="2"
    y="3"
    width="11"
    height="9"
    rx="2.5"
    stroke={color}
    stroke-width="1.25"
  />

  <circle cx="5.5" cy="7" r="0.9" fill={color} />

  <circle cx="9.5" cy="7" r="0.9" fill={color} />

  <path
    d="M5 9.5C5.7 10.2 6.5 10.5 7.5 10.5C8.5 10.5 9.3 10.2 10 9.5"
    stroke={color}
    stroke-width="1.1"
    stroke-linecap="round"
  />
</svg>
