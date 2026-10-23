const panel = document.querySelector(".chat-panel");
const launcher = document.querySelector(".chat-launcher");
const closeChat = document.querySelector(".close-chat");
const chatFrame = document.querySelector(".chat-frame");
const chatConfigHint = document.querySelector(".chat-config-hint");
const menuButton = document.querySelector(".menu-button");
const mobileMenu = document.querySelector(".mobile-menu");
const hero = document.querySelector(".hero");
const heroImage = document.querySelector(".hero-image");
const heroTitle = document.querySelector(".hero-title");
const heroDescription = document.querySelector(".hero-content > p");
const heroLink = document.querySelector(".community-button");
const heroLinkLabel = heroLink.firstChild;
const heroCaption = document.querySelector(".hero-caption-label");
const slideCount = document.querySelector(".slide-count");
const slideToggle = document.querySelector(".slide-toggle");
const slideDots = [...document.querySelectorAll(".slide-indicator button")];
const programCards = [...document.querySelectorAll(".program-card")];
const programEmpty = document.querySelector(".program-empty");
const programDialog = document.querySelector(".program-dialog");
const programDialogTitle = document.querySelector("#program-dialog-title");
const programDialogDescription = document.querySelector(
  ".program-dialog-description",
);
const searchButton = document.querySelector(".search-button");
const viewAllButton = document.querySelector(".view-all-programs");
const searchDialog = document.querySelector(".search-dialog");
const searchForm = document.querySelector(".program-search");
const searchInput = document.querySelector("#program-search-input");
const searchHint = document.querySelector(".search-hint");
const closeDialogButtons = document.querySelectorAll(".dialog-close");
const askAssistantButton = document.querySelector(".dialog-ask");

const heroSlides = [
  {
    image: "img-8751.webp",
    alt: "Discover more at Enverga University",
    title: "Discover more\nat Enverga University",
    description:
      "Explore opportunities beyond the classroom and shape your future. LIVE IT ALL.",
    action: "EXPLORE YOUR FUTURE",
    caption: "YOUR JOURNEY STARTS HERE",
    href: "https://mseuf.edu.ph/",
  },
  {
    image: "img-8757.webp",
    alt: "Enverga University students enjoying campus life",
    title: "Find your\npeople here.",
    description:
      "Build friendships that make every university moment unforgettable. LIVE IT ALL.",
    action: "JOIN OUR COMMUNITY",
    caption: "FIND YOUR PEOPLE",
    href: "https://mseuf.edu.ph/",
  },
  {
    image: "img-8916.webp",
    alt: "Students sharing an Envergan moment",
    title: "Share every\nEnvergan moment",
    description: "Learn, laugh and grow with a community that cares. LIVE IT ALL.",
    action: "START YOUR JOURNEY",
    caption: "MAKE EVERY MOMENT COUNT",
    href: "https://mseuf.edu.ph/",
  },
  {
    image: "img-8924.webp",
    alt: "Students walking into new campus experiences",
    title: "Walk into new\nexperiences",
    description:
      "Discover new paths, lasting friendships and greater confidence. LIVE IT ALL.",
    action: "FIND YOUR PLACE",
    caption: "THERE'S A PLACE FOR YOU HERE",
    href: "https://mseuf.edu.ph/",
  },
  {
    image: "img-8947.webp",
    alt: "Students growing through university experiences",
    title: "Grow through\nevery experience",
    description:
      "Every opportunity helps you become more of yourself. LIVE IT ALL.",
    action: "BEGIN YOUR APPLICATION",
    caption: "GROW INTO WHAT'S NEXT",
    href: "https://mseuf.edu.ph/",
  },
];

const config = new URLSearchParams(window.location.search);
const frontendUrl = config.get("frontend") ?? chatFrame.dataset.frontendUrl;
const orgId = config.get("org_id") ?? chatFrame.dataset.orgId;

if (frontendUrl && orgId && /^\d+$/.test(orgId)) {
  const frontendOrigin = new URL(frontendUrl, window.location.href);
  frontendOrigin.hash = `/chat/${encodeURIComponent(orgId)}`;
  chatFrame.src = frontendOrigin.toString();
} else {
  chatFrame.hidden = true;
  chatConfigHint.hidden = false;
}

let activeSlide = 1;
let autoplayTimer;
let autoplayPaused = false;
let pointerOverHero = false;
let heroHasFocus = false;
let pointerStartX = null;
let pointerStartY = null;

function renderSlide(index) {
  activeSlide = (index + heroSlides.length) % heroSlides.length;
  const slide = heroSlides[activeSlide];
  heroImage.classList.add("is-changing");

  window.setTimeout(() => {
    heroImage.src = `https://mseuf.edu.ph/web4_assets/homepage/banners/${slide.image}`;
    heroImage.alt = slide.alt;
    heroTitle.textContent = slide.title;
    heroDescription.textContent = slide.description;
    heroLinkLabel.textContent = `\n              ${slide.action} `;
    heroLink.href = slide.href;
    heroCaption.textContent = slide.caption;
    slideCount.textContent =
      `${String(activeSlide + 1).padStart(2, "0")} — ${String(heroSlides.length).padStart(2, "0")}`;

    slideDots.forEach((dot, dotIndex) => {
      const isActive = dotIndex === activeSlide;
      dot.classList.toggle("active", isActive);
      dot.setAttribute("aria-pressed", String(isActive));
    });

    heroImage.classList.remove("is-changing");
  }, 120);
}

function updateAutoplay() {
  window.clearInterval(autoplayTimer);
  const reducedMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)",
  ).matches;
  if (
    autoplayPaused ||
    pointerOverHero ||
    heroHasFocus ||
    reducedMotion ||
    document.hidden
  ) {
    return;
  }

  autoplayTimer = window.setInterval(() => {
    renderSlide(activeSlide + 1);
  }, 6500);
}

document.querySelector(".slide-previous").addEventListener("click", () => {
  renderSlide(activeSlide - 1);
});
document.querySelector(".slide-next").addEventListener("click", () => {
  renderSlide(activeSlide + 1);
});
slideDots.forEach((dot, index) => {
  dot.addEventListener("click", () => renderSlide(index));
});
slideToggle.addEventListener("click", () => {
  autoplayPaused = !autoplayPaused;
  slideToggle.setAttribute(
    "aria-label",
    autoplayPaused ? "Play slides" : "Pause slides",
  );
  slideToggle.innerHTML = `<span aria-hidden="true">${autoplayPaused ? "▶" : "Ⅱ"}</span>`;
  updateAutoplay();
});
hero.addEventListener("pointerenter", () => {
  pointerOverHero = true;
  window.clearInterval(autoplayTimer);
});
hero.addEventListener("pointerleave", () => {
  pointerOverHero = false;
  updateAutoplay();
});
hero.addEventListener("focusin", () => {
  heroHasFocus = true;
  window.clearInterval(autoplayTimer);
});
hero.addEventListener("focusout", (event) => {
  if (event.relatedTarget instanceof Node && hero.contains(event.relatedTarget)) {
    return;
  }
  heroHasFocus = false;
  updateAutoplay();
});
hero.addEventListener("pointerdown", (event) => {
  if (event.target.closest("button, a")) return;
  pointerStartX = event.clientX;
  pointerStartY = event.clientY;
});
hero.addEventListener("pointerup", (event) => {
  if (pointerStartX === null || pointerStartY === null) return;
  const deltaX = event.clientX - pointerStartX;
  const deltaY = event.clientY - pointerStartY;
  pointerStartX = null;
  pointerStartY = null;
  if (Math.abs(deltaX) > 50 && Math.abs(deltaX) > Math.abs(deltaY)) {
    renderSlide(activeSlide + (deltaX < 0 ? 1 : -1));
  }
});
document.addEventListener("visibilitychange", updateAutoplay);
renderSlide(activeSlide);
updateAutoplay();

function closeDialogOnBackdrop(dialog, event) {
  if (event.target === dialog) dialog.close();
}

function openProgramDetails(card) {
  programDialogTitle.textContent = card.dataset.title;
  programDialogDescription.textContent = card.dataset.description;
  programDialog.showModal();
}

programCards.forEach((card) => {
  card.addEventListener("click", () => openProgramDetails(card));
});
programDialog.addEventListener("click", (event) =>
  closeDialogOnBackdrop(programDialog, event),
);

function showProgramSearch() {
  searchInput.value = "";
  searchHint.textContent =
    "Search undergraduate, graduate, or basic education.";
  searchDialog.showModal();
  searchInput.focus();
}

searchButton.addEventListener("click", showProgramSearch);
searchDialog.addEventListener("click", (event) =>
  closeDialogOnBackdrop(searchDialog, event),
);

searchInput.addEventListener("input", () => {
  const query = searchInput.value.trim().toLowerCase();
  searchHint.textContent = query
    ? `Search for “${searchInput.value.trim()}” in our academic programs.`
    : "Search undergraduate, graduate, or basic education.";
});

searchForm.addEventListener("reset", () => {
  window.setTimeout(() => {
    searchHint.textContent =
      "Search undergraduate, graduate, or basic education.";
  });
});

searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = searchInput.value.trim().toLowerCase();
  if (!query) {
    searchHint.textContent = "Enter a keyword to find matching programs.";
    searchInput.focus();
    return;
  }

  let matches = 0;
  programCards.forEach((card) => {
    const searchable =
      `${card.dataset.title} ${card.dataset.search}`.toLowerCase();
    const matched = query
      .split(/\s+/)
      .every((word) => searchable.includes(word));
    card.hidden = !matched;
    if (matched) matches += 1;
  });

  programEmpty.hidden = matches > 0;
  searchHint.textContent = matches
    ? `Found ${matches} matching ${matches === 1 ? "program" : "programs"}.`
    : "No matches yet. Try a broader search like “undergraduate” or “graduate”.";
  document.querySelector(".view-all-label").textContent = "CLEAR FILTERS";
  viewAllButton.setAttribute("aria-label", "Clear program search filters");
  viewAllButton.classList.add("filters-active");
  searchDialog.close();
  document.querySelector("#instruction").scrollIntoView({ behavior: "smooth" });
});

viewAllButton.addEventListener("click", () => {
  const hasFilters = programCards.some((card) => card.hidden);
  if (!hasFilters) {
    showProgramSearch();
    return;
  }
  programCards.forEach((card) => {
    card.hidden = false;
  });
  programEmpty.hidden = true;
  document.querySelector(".view-all-label").textContent = "VIEW ALL PROGRAMS";
  viewAllButton.setAttribute("aria-label", "View all programs");
  viewAllButton.classList.remove("filters-active");
});

closeDialogButtons.forEach((button) => {
  button.addEventListener("click", () => {
    button.closest("dialog").close();
  });
});

askAssistantButton.addEventListener("click", () => {
  programDialog.close();
  if (panel.hidden) {
    launcher.hidden = true;
    panel.hidden = false;
  }
  chatFrame.focus();
});

closeChat.addEventListener("click", () => {
  panel.hidden = true;
  launcher.hidden = false;
  launcher.focus();
});

launcher.addEventListener("click", () => {
  launcher.hidden = true;
  panel.hidden = false;
  closeChat.focus();
});

menuButton.addEventListener("click", () => {
  const isExpanded = menuButton.getAttribute("aria-expanded") === "true";
  menuButton.setAttribute("aria-expanded", String(!isExpanded));
  menuButton.setAttribute("aria-label", isExpanded ? "Open menu" : "Close menu");
  mobileMenu.hidden = isExpanded;
});

mobileMenu.addEventListener("click", (event) => {
  if (!(event.target instanceof HTMLAnchorElement)) return;
  mobileMenu.hidden = true;
  menuButton.setAttribute("aria-expanded", "false");
  menuButton.setAttribute("aria-label", "Open menu");
});
