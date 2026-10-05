<script lang="ts">
  import { fly } from "svelte/transition";
  import { auth, login, register } from "../auth.svelte";

  type Mode = "login" | "register";

  let mode = $state<Mode>("login");

  let email = $state("");
  let password = $state("");
  let confirmPassword = $state("");
  let firstName = $state("");
  let lastName = $state("");

  let isSubmitting = $state(false);
  let errorMessage = $state("");
  let successMessage = $state("");

  let passwordsMatch = $derived(
    mode === "login" || password === confirmPassword,
  );

  function switchMode(next: Mode) {
    mode = next;
    errorMessage = "";
    successMessage = "";
    auth.error = null;
  }

  async function handleSubmit(e: Event) {
    e.preventDefault();
    errorMessage = "";
    successMessage = "";

    if (mode === "register" && !passwordsMatch) {
      errorMessage = "Passwords do not match.";
      return;
    }

    isSubmitting = true;
    try {
      if (mode === "login") {
        const ok = await login({ email, password });
        if (!ok) {
          errorMessage =
            auth.error ?? "Something went wrong. Please try again.";
        }
        // On success auth.token is set, so App.svelte swaps this page out.
      } else {
        const ok = await register({
          email,
          password,
          first_name: firstName,
          last_name: lastName,
        });

        if (ok) {
          // Back to login, keep the email so they only need to type the password
          mode = "login";
          password = "";
          confirmPassword = "";
          firstName = "";
          lastName = "";
          successMessage = "Account created! You can now log in.";
        } else {
          errorMessage =
            auth.error ?? "Something went wrong. Please try again.";
        }
      }
    } catch {
      errorMessage = "Something went wrong. Please try again.";
    } finally {
      isSubmitting = false;
    }
  }
</script>

<main
  class="flex min-h-screen flex-1 flex-col items-center justify-center bg-[#F5F8FB] px-4"
>
  <div
    class="w-full max-w-md rounded-xl border border-outline bg-white p-8 shadow-sm"
  >
    <div class="text-center">
      <h2 class="text-xs font-bold uppercase tracking-wider text-primary">
        Admissions Intelligence Hub
      </h2>
      <h1 class="mt-1 text-2xl font-bold">
        {mode === "login" ? "Welcome back" : "Create your account"}
      </h1>
      <p class="mt-1 text-sm text-gray-500">
        {mode === "login"
          ? "Sign in to manage your institution's chatbot"
          : "Set up your admin account"}
      </p>
    </div>

    <!-- Tabs -->
    <div
      class="mt-6 flex flex-row rounded-md border border-outline bg-[#F5F8FB] p-1"
    >
      <button
        class={`flex-1 rounded-md py-2 text-sm font-semibold transition-colors duration-200 ${
          mode === "login" ? "bg-white text-primary shadow-sm" : "text-gray-500"
        }`}
        onclick={() => switchMode("login")}
      >
        Log in
      </button>
      <button
        class={`flex-1 rounded-md py-2 text-sm font-semibold transition-colors duration-200 ${
          mode === "register"
            ? "bg-white text-primary shadow-sm"
            : "text-gray-500"
        }`}
        onclick={() => switchMode("register")}
      >
        Register
      </button>
    </div>

    <form class="mt-6 flex flex-col gap-4" onsubmit={handleSubmit}>
      {#if mode === "register"}
        <div
          transition:fly={{ y: -8, duration: 150 }}
          class="flex flex-row gap-4"
        >
          <div class="flex-1">
            <label for="firstName" class="mb-1.5 block text-sm font-bold"
              >First name</label
            >
            <input
              id="firstName"
              type="text"
              bind:value={firstName}
              required
              placeholder="Juan"
              class="w-full rounded-md border border-outline px-4 py-2.5 text-sm outline-none focus:border-primary"
            />
          </div>
          <div class="flex-1">
            <label for="lastName" class="mb-1.5 block text-sm font-bold"
              >Last name</label
            >
            <input
              id="lastName"
              type="text"
              bind:value={lastName}
              required
              placeholder="Dela Cruz"
              class="w-full rounded-md border border-outline px-4 py-2.5 text-sm outline-none focus:border-primary"
            />
          </div>
        </div>
      {/if}

      <div>
        <label for="email" class="mb-1.5 block text-sm font-bold">Email</label>
        <input
          id="email"
          type="email"
          bind:value={email}
          required
          placeholder="you@university.edu"
          class="w-full rounded-md border border-outline px-4 py-2.5 text-sm outline-none focus:border-primary"
        />
      </div>

      <div>
        <label for="password" class="mb-1.5 block text-sm font-bold"
          >Password</label
        >
        <input
          id="password"
          type="password"
          bind:value={password}
          required
          placeholder="••••••••"
          class="w-full rounded-md border border-outline px-4 py-2.5 text-sm outline-none focus:border-primary"
        />
      </div>

      {#if mode === "register"}
        <div transition:fly={{ y: -8, duration: 150 }}>
          <label for="confirmPassword" class="mb-1.5 block text-sm font-bold"
            >Confirm password</label
          >
          <input
            id="confirmPassword"
            type="password"
            bind:value={confirmPassword}
            required
            placeholder="••••••••"
            class={`w-full rounded-md border px-4 py-2.5 text-sm outline-none focus:border-primary ${
              !passwordsMatch ? "border-red-500" : "border-outline"
            }`}
          />
        </div>
      {/if}

      {#if mode === "login"}
        <div class="flex justify-end">
          <button
            type="button"
            class="text-sm font-semibold text-primary hover:underline"
          >
            Forgot password?
          </button>
        </div>
      {/if}

      {#if successMessage}
        <div
          transition:fly={{ y: -8, duration: 150 }}
          role="status"
          class="flex flex-row items-center gap-2 rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm font-semibold text-green-700"
        >
          <svg
            class="h-4 w-4 shrink-0"
            viewBox="0 0 20 20"
            fill="currentColor"
            aria-hidden="true"
          >
            <path
              fill-rule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.7-9.3a1 1 0 00-1.4-1.4L9 10.6 7.7 9.3a1 1 0 00-1.4 1.4l2 2a1 1 0 001.4 0l4-4z"
              clip-rule="evenodd"
            />
          </svg>
          {successMessage}
        </div>
      {/if}

      {#if errorMessage}
        <p class="text-sm text-red-600">{errorMessage}</p>
      {/if}

      <button
        type="submit"
        disabled={isSubmitting}
        class="mt-2 flex w-full flex-row items-center justify-center gap-2 rounded-md bg-primary px-4 py-3 text-sm font-semibold text-white transition-opacity duration-200 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {#if isSubmitting}
          Please wait...
        {:else}
          {mode === "login" ? "Log in" : "Create account"}
        {/if}
      </button>
    </form>

    <p class="mt-6 text-center text-sm text-gray-500">
      {#if mode === "login"}
        Don't have an account?
        <button
          class="font-semibold text-primary hover:underline"
          onclick={() => switchMode("register")}
        >
          Register
        </button>
      {:else}
        Already have an account?
        <button
          class="font-semibold text-primary hover:underline"
          onclick={() => switchMode("login")}
        >
          Log in
        </button>
      {/if}
    </p>
  </div>
</main>
