<script>
  let apiResponse = "";
  let loading = false;
  let error = "";

  async function callBackend() {
    loading = true;
    error = "";
    apiResponse = "";

    try {
      // Adjust the URL if your FastAPI endpoint is different
      const res = await fetch("http://127.0.0.1:8000/");
      
      if (!res.ok) {
        throw new Error(`Server returned status: ${res.status}`);
      }

      const data = await res.json();
      apiResponse = JSON.stringify(data, null, 2);
    } catch (err) {
      if (err instanceof Error) {
        error = err.message;
      } else {
        error = "Failed to connect to backend";
      }
    } finally {
      loading = false;
    }
  }
</script>

<main class="container">
  <h1>FastAPI + Svelte Test</h1>

  <button on:click={callBackend} disabled={loading}>
    {loading ? "Connecting..." : "Test API Connection"}
  </button>

  {#if error}
    <p class="error"><strong>Error:</strong> {error}</p>
  {/if}

  {#if apiResponse}
    <div class="response-box">
      <h3>Response:</h3>
      <pre>{apiResponse}</pre>
    </div>
  {/if}
</main>

<style>
  .container {
    max-width: 600px;
    margin: 40px auto;
    padding: 20px;
    font-family: system-ui, sans-serif;
  }

  button {
    padding: 10px 20px;
    font-size: 16px;
    cursor: pointer;
    border-radius: 6px;
    border: none;
    background-color: #0066cc;
    color: white;
  }

  button:disabled {
    background-color: #cccccc;
    cursor: not-allowed;
  }

  .response-box {
    margin-top: 20px;
    padding: 15px;
    background: #f4f4f4;
    border-radius: 6px;
    text-align: left;
  }

  pre {
    margin: 0;
    font-family: monospace;
    white-space: pre-wrap;
  }

  .error {
    color: #d9534f;
    margin-top: 15px;
  }
</style>