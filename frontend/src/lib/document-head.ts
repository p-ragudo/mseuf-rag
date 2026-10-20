const DEFAULT_TITLE = "RAG Dashboard";
const DEFAULT_FAVICON = "/favicon.svg?v=2";

export function setDocumentHead(
  organizationName: string | null,
  mascotUrl: string | null,
): void {
  document.title = organizationName
    ? `${organizationName} rag dashboard`
    : DEFAULT_TITLE;

  const favicon = document.querySelector<HTMLLinkElement>("#app-favicon");
  if (!favicon) {
    throw new Error("The application favicon link is missing.");
  }

  favicon.href = mascotUrl ?? DEFAULT_FAVICON;
  favicon.type = mascotUrl ? "image/png" : "image/svg+xml";
}
