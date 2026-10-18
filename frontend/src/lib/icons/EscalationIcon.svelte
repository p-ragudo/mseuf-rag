<script lang="ts">
  interface Props {
    color?: string;
  }

  let { color = "#59616E" }: Props = $props();
</script>

<svg
  width="16"
  height="16"
  viewBox="0 0 16 16"
  fill="none"
  xmlns="http://www.w3.org/2000/svg"
>
  <g clip-path="url(#clip0_362_427)">
    <path
      d="M14.4777 11.9923L9.14766 2.66477C9.03144 2.4597 8.86291 2.28913 8.65925 2.17045C8.45559 2.05178 8.2241 1.98926 7.98838 1.98926C7.75267 1.98926 7.52118 2.05178 7.31752 2.17045C7.11386 2.28913 6.94533 2.4597 6.82911 2.66477L1.49911 11.9923C1.38164 12.1957 1.32004 12.4266 1.32056 12.6615C1.32108 12.8964 1.3837 13.1271 1.50207 13.33C1.62044 13.5329 1.79036 13.7009 1.9946 13.817C2.19883 13.9331 2.43013 13.9931 2.66505 13.991H13.325C13.5588 13.9908 13.7884 13.929 13.9908 13.812C14.1932 13.6949 14.3612 13.5267 14.478 13.3242C14.5948 13.1217 14.6562 12.892 14.6562 12.6582C14.6561 12.4244 14.5946 12.1947 14.4777 11.9923Z"
      stroke={color}
      stroke-width="1.33333"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <path
      d="M7.99512 5.99609V8.66171"
      stroke={color}
      stroke-width="1.33333"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <path
      d="M7.99512 11.3262H8.00178"
      stroke={color}
      stroke-width="1.33333"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
  </g>
  <defs>
    <clipPath id="clip0_362_427">
      <rect width="15.99" height="15.99" fill="white" />
    </clipPath>
  </defs>
</svg>
