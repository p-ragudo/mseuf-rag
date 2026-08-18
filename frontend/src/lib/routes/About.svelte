<script lang="ts">
  import Header from "../components/Header.svelte";
</script>

<main class="">
  <Header disableInfo={true} pageIsToPop={true} />
  <div class="p-5">
    <section>
      <h2 class="text-3xl font-heading font-semibold mb-3.5">About</h2>
      <p class="text-[#393939] font-heading">
        This chatbot is designed to assist applicants of Manuel S. Enverga
        University Foundation with admission-related inquiries. It provides
        quick and convenient access to information about application procedures,
        requirements, entrance exams, and enrollment.
      </p>
    </section>
    <hr class="my-4 border-[#E0E0E0]" />
    <section>
      <h1 class="text-3xl font-heading font-semibold mb-3.5">
        How to Use the Chatbot
      </h1>
      <p class="text-[#393939] font-heading">Using the chatbot is simple:</p>
      <ul class="text-[#393939] font-heading list-disc ml-10">
        <li>Type your question in the chat box</li>
        <li>
          Use clear and simple keywords (e.g., “requirements”, “how to apply”)
        </li>
        <li>Select from suggested questions if available</li>
      </ul>
      <p class="text-[#393939] font-heading">
        The chatbot will respond instantly with relevant information.
      </p>
    </section>
    <hr class="my-4 border-[#E0E0E0]" />
    <section>
      <h2 class="text-3xl font-heading font-semibold mb-3.5">Disclaimer</h2>
      <p class="text-[#393939] font-heading">
        This chatbot provides general information for guidance purposes only.
        While we strive to keep all information accurate and up to date, some
        details may change. For official confirmation or specific concerns,
        please contact the Admissions Office
      </p>
    </section>
  </div>
</main>
