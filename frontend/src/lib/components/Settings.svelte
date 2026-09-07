<script lang="ts">
  let botName = $state("UniBot");
  let welcomeMessage = $state(
    "Hi! I'm here to help with admissions, enrollment, and general university enquiries. What would you like to know?",
  );
  let fallbackMessage = $state(
    "I'm not confident I have the right answer for that. Would you like me to connect you with the registrar's office?",
  );

  let confidenceThreshold = $state(0.6);
  let topK = $state(4);
  let temperature = $state(0.3);

  let enableWebScrapeAutoRefresh = $state(true);
  let scrapeFrequency = $state("weekly");

  let notifyOnFailedIndex = $state(true);
  let notifyOnLowConfidence = $state(true);
  let notifyEmail = $state("admin@university.edu");

  let currentPassword = $state("");
  let newPassword = $state("");
  let confirmPassword = $state("");

  let savedMessage = $state("");

  function saveGeneral() {
    // TODO: persist to backend
    savedMessage = "General settings saved.";
    setTimeout(() => (savedMessage = ""), 2500);
  }

  function saveRetrieval() {
    // TODO: persist to backend
    savedMessage = "Retrieval settings saved.";
    setTimeout(() => (savedMessage = ""), 2500);
  }

  function saveNotifications() {
    // TODO: persist to backend
    savedMessage = "Notification settings saved.";
    setTimeout(() => (savedMessage = ""), 2500);
  }

  function changePassword() {
    if (newPassword !== confirmPassword) {
      savedMessage = "New passwords don't match.";
      return;
    }
    // TODO: call auth endpoint
    currentPassword = "";
    newPassword = "";
    confirmPassword = "";
    savedMessage = "Password updated.";
    setTimeout(() => (savedMessage = ""), 2500);
  }
</script>

<div class="p-6 bg-gray-50">
  <div class="flex items-center justify-between mb-6">
    <h1 class="text-2xl font-semibold text-gray-800">Settings</h1>
    {#if savedMessage}
      <span class="text-sm text-green-600">{savedMessage}</span>
    {/if}
  </div>

  <div class="flex flex-col gap-6 max-w-3xl">
    <!-- General / chatbot identity -->
    <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
      <h2 class="text-sm font-medium text-gray-600 mb-4">Chatbot Identity</h2>
      <div class="flex flex-col gap-4">
        <div>
          <label class="text-xs text-gray-500" for="bot-name">Bot Name</label>
          <input
            id="bot-name"
            type="text"
            bind:value={botName}
            class="w-full mt-1 px-3 py-2 rounded-lg border border-gray-200 text-sm outline-none focus:border-blue-400"
          />
        </div>
        <div>
          <label class="text-xs text-gray-500" for="welcome-msg"
            >Welcome Message</label
          >
          <textarea
            id="welcome-msg"
            bind:value={welcomeMessage}
            rows="2"
            class="w-full mt-1 px-3 py-2 rounded-lg border border-gray-200 text-sm outline-none focus:border-blue-400 resize-none"
          ></textarea>
        </div>
        <div>
          <label class="text-xs text-gray-500" for="fallback-msg"
            >Fallback Message (shown on low-confidence answers)</label
          >
          <textarea
            id="fallback-msg"
            bind:value={fallbackMessage}
            rows="2"
            class="w-full mt-1 px-3 py-2 rounded-lg border border-gray-200 text-sm outline-none focus:border-blue-400 resize-none"
          ></textarea>
        </div>
        <button
          onclick={saveGeneral}
          class="self-start px-4 py-2 rounded-lg bg-gray-800 text-white text-sm hover:bg-gray-700 transition-colors"
        >
          Save
        </button>
      </div>
    </div>

    <!-- Retrieval tuning -->
    <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
      <h2 class="text-sm font-medium text-gray-600 mb-4">
        Retrieval & Response Tuning
      </h2>
      <div class="flex flex-col gap-5">
        <div>
          <div class="flex justify-between text-xs text-gray-500 mb-1">
            <label for="confidence">Confidence Threshold</label>
            <span>{confidenceThreshold.toFixed(2)}</span>
          </div>
          <input
            id="confidence"
            type="range"
            min="0"
            max="1"
            step="0.05"
            bind:value={confidenceThreshold}
            class="w-full accent-gray-800"
          />
          <p class="text-xs text-gray-400 mt-1">
            Answers below this score trigger the fallback message.
          </p>
        </div>

        <div>
          <div class="flex justify-between text-xs text-gray-500 mb-1">
            <label for="topk">Chunks Retrieved per Query (top-k)</label>
            <span>{topK}</span>
          </div>
          <input
            id="topk"
            type="range"
            min="1"
            max="10"
            step="1"
            bind:value={topK}
            class="w-full accent-gray-800"
          />
        </div>

        <div>
          <div class="flex justify-between text-xs text-gray-500 mb-1">
            <label for="temp">Response Temperature</label>
            <span>{temperature.toFixed(2)}</span>
          </div>
          <input
            id="temp"
            type="range"
            min="0"
            max="1"
            step="0.05"
            bind:value={temperature}
            class="w-full accent-gray-800"
          />
          <p class="text-xs text-gray-400 mt-1">
            Lower keeps answers factual and consistent; higher allows more
            varied phrasing.
          </p>
        </div>

        <label class="flex items-center gap-2 text-sm text-gray-600">
          <input
            type="checkbox"
            bind:checked={enableWebScrapeAutoRefresh}
            class="accent-gray-800"
          />
          Automatically re-scrape linked web pages
        </label>

        {#if enableWebScrapeAutoRefresh}
          <div>
            <label class="text-xs text-gray-500" for="scrape-freq"
              >Refresh Frequency</label
            >
            <select
              id="scrape-freq"
              bind:value={scrapeFrequency}
              class="w-full mt-1 px-3 py-2 rounded-lg border border-gray-200 text-sm outline-none focus:border-blue-400"
            >
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
            </select>
          </div>
        {/if}

        <button
          onclick={saveRetrieval}
          class="self-start px-4 py-2 rounded-lg bg-gray-800 text-white text-sm hover:bg-gray-700 transition-colors"
        >
          Save
        </button>
      </div>
    </div>

    <!-- Notifications -->
    <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
      <h2 class="text-sm font-medium text-gray-600 mb-4">Notifications</h2>
      <div class="flex flex-col gap-3">
        <label class="flex items-center gap-2 text-sm text-gray-600">
          <input
            type="checkbox"
            bind:checked={notifyOnFailedIndex}
            class="accent-gray-800"
          />
          Notify when a document fails to index
        </label>
        <label class="flex items-center gap-2 text-sm text-gray-600">
          <input
            type="checkbox"
            bind:checked={notifyOnLowConfidence}
            class="accent-gray-800"
          />
          Notify when enquiries repeatedly get low-confidence answers
        </label>
        <div>
          <label class="text-xs text-gray-500" for="notify-email"
            >Notification Email</label
          >
          <input
            id="notify-email"
            type="email"
            bind:value={notifyEmail}
            class="w-full mt-1 px-3 py-2 rounded-lg border border-gray-200 text-sm outline-none focus:border-blue-400"
          />
        </div>
        <button
          onclick={saveNotifications}
          class="self-start px-4 py-2 rounded-lg bg-gray-800 text-white text-sm hover:bg-gray-700 transition-colors"
        >
          Save
        </button>
      </div>
    </div>

    <!-- Admin account -->
    <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
      <h2 class="text-sm font-medium text-gray-600 mb-4">Admin Account</h2>
      <div class="flex flex-col gap-3">
        <div>
          <label class="text-xs text-gray-500" for="current-pw"
            >Current Password</label
          >
          <input
            id="current-pw"
            type="password"
            bind:value={currentPassword}
            class="w-full mt-1 px-3 py-2 rounded-lg border border-gray-200 text-sm outline-none focus:border-blue-400"
          />
        </div>
        <div>
          <label class="text-xs text-gray-500" for="new-pw">New Password</label>
          <input
            id="new-pw"
            type="password"
            bind:value={newPassword}
            class="w-full mt-1 px-3 py-2 rounded-lg border border-gray-200 text-sm outline-none focus:border-blue-400"
          />
        </div>
        <div>
          <label class="text-xs text-gray-500" for="confirm-pw"
            >Confirm New Password</label
          >
          <input
            id="confirm-pw"
            type="password"
            bind:value={confirmPassword}
            class="w-full mt-1 px-3 py-2 rounded-lg border border-gray-200 text-sm outline-none focus:border-blue-400"
          />
        </div>
        <button
          onclick={changePassword}
          class="self-start px-4 py-2 rounded-lg bg-gray-800 text-white text-sm hover:bg-gray-700 transition-colors"
        >
          Update Password
        </button>
      </div>
    </div>
  </div>
</div>
