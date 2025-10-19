// Data sources to load event information from.
// Each source is a JSON file (array or single object) pulled via fetch.
const sources = [
  {
    id: "amiv-apero",
    label: "AMIV Aperos",
    path: "/data/apero_results_amiv.json",
  },
  {
    id: "vmp-apero",
    label: "VMP Aperos",
    path: "/data/apero_results_vmp.json",
  }
];

// Fallback for events that do not specify an ease-of-entry score.
const DEFAULT_EASE_OF_ENTRY = 0.69;

// Human-readable month names for UI labels.
const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

// Weekday labels, Monday-first, to match the calendar grid ordering.
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// Main containers and optional mobile modal elements.
const calendarContainer = document.getElementById("calendar");
const eventPanel = document.getElementById("event-panel");
const mobileModal = document.getElementById("mobile-event-modal");
const mobileModalTitle = mobileModal?.querySelector("#mobile-event-title");
const mobileModalContent = mobileModal?.querySelector(".mobile-modal__content");
const mobileModalClose = mobileModal?.querySelector(".mobile-modal__close");

// If modal markup exists, mark the body so CSS can safely hide the fixed panel on ultra-small screens.
if (mobileModal) {
  document.body.classList.add("has-mobile-modal");
}

const state = {
  // Flat list of all events loaded from the configured sources
  events: [],
  // Map keyed by ISO date (YYYY-MM-DD) to an array of events occurring on that day
  eventsByDay: new Map(),
  // Currently visible calendar month/year
  month: new Date().getMonth(),
  year: new Date().getFullYear(),
  // Currently selected day (ISO string) whose details are shown in the panel
  activeDay: null,
};

// Turn a Date into a "YYYY-MM-DD" string in UTC.
const toISODate = (date) => date.toISOString().slice(0, 10);

// Format an ISO date string into a friendly full date for headings.
const formatDisplayDate = (isoString) =>
  new Date(`${isoString}T00:00:00`).toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });

// Compact human-readable time range shown on event cards.
const formatEventTime = (event) => {
  if (event.startTime && event.endTime) {
    return `${event.startTime} — ${event.endTime}`;
  }
  return event.startTime || event.endTime || null;
};

// Convert a 0..1 ease score into a qualitative label.
const describeEaseOfEntry = (value) => {
  if (value <= 0.33) {
    return "Challenging";
  }
  if (value <= 0.66) {
    return "Moderate";
  }
  return "Easy";
};

// Normalize entries from arbitrary sources into a consistent internal event shape.
// - Ensures an id, title, date, optional times, and other metadata are present.
// - Provides sensible defaults when fields are missing.
const normaliseEntry = (entry, sourceId) => {
  if (!entry?.date) {
    throw new Error(`Missing date in ${sourceId} entry: ${JSON.stringify(entry)}`);
  }

  return {
    id: `${sourceId}-${entry.id ?? `${entry.title ?? "event"}-${entry.date}`}`,
    title: entry.title ?? "Untitled event",
    date: entry.date,
    startTime: entry.start_time ?? entry.startTime ?? null,
    endTime: entry.end_time ?? entry.endTime ?? null,
    location: entry.location ?? null,
    url: entry.url ?? null,
    source: sourceId,
    raw: entry,
    refreshments: entry.refreshments ?? entry.refreshment ?? null,
    refreshmentDetails: entry.refreshment_details ?? entry.refreshmentDetails ?? null,
    easeOfEntry: typeof entry.easeOfEntry === "number" ? entry.easeOfEntry : DEFAULT_EASE_OF_ENTRY,
  };
};

// Fetch and parse JSON from a configured source, with error surfacing.
const fetchJson = async (source) => {
  const response = await fetch(source.path);
  if (!response.ok) {
    throw new Error(`Failed to load ${source.path}: ${response.status} ${response.statusText}`);
  }

  return response.json();
};

// Load events from all sources, normalize them, and merge into a single list.
// Invalid entries (e.g., without a date) are skipped with a console warning.
const loadEventSources = async () => {
  const items = [];

  for (const source of sources) {
    const payload = await fetchJson(source);
    const list = Array.isArray(payload) ? payload : [payload];

    let skipped = 0;
    list.forEach((entry, idx) => {
      if (!entry || !entry.date) {
        skipped += 1;
        return;
      }
      const event = normaliseEntry(entry, source.id);
      items.push(event);
    });

    if (skipped > 0) {
      // Surface a clear hint in devtools without interrupting the UI
      console.warn(`Skipped ${skipped} invalid entries from ${source.id} (missing date).`);
    }
  }

  return items;
};

// Build a lookup from ISO date to a sorted list of events for that date.
// Sorting prefers events with start times, then alphabetical by title.
const createEventLookup = (events) => {
  const map = new Map();

  events.forEach((event) => {
    if (!event.date) {
      return;
    }

    const iso = event.date.length === 10 ? event.date : event.date.slice(0, 10);

    if (!map.has(iso)) {
      map.set(iso, []);
    }

    map.get(iso).push(event);
  });

  for (const list of map.values()) {
    list.sort((a, b) => {
      if (a.startTime && b.startTime) {
        return a.startTime.localeCompare(b.startTime);
      }
      if (a.startTime) {
        return -1;
      }
      if (b.startTime) {
        return 1;
      }
      return a.title.localeCompare(b.title);
    });
  }

  return map;
};

// Helper to produce a 6x7 calendar matrix for a given month/year.
// Note: not used by the current renderer, which builds the grid inline.
const buildCalendarMatrix = (year, month) => {
  const firstDay = new Date(Date.UTC(year, month, 1));
  const startOffset = (firstDay.getUTCDay() + 6) % 7;
  const daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();

  const weeks = [];
  let dayCounter = 1 - startOffset;

  for (let week = 0; week < 6; week += 1) {
    const days = [];

    for (let weekday = 0; weekday < 7; weekday += 1) {
      const date = new Date(Date.UTC(year, month, dayCounter));
      const inMonth = date.getUTCMonth() === month;
      days.push({ date, inMonth });
      dayCounter += 1;
    }

    weeks.push(days);
  }

  return weeks;
};

// Show a simple centered notice in the calendar area (loading/error).
const showStatus = (type, message) => {
  const className = type === "error" ? "error-notice" : "loading-notice";
  calendarContainer.innerHTML = `<div class="${className}">${message}</div>`;
};

// Move the visible calendar by a number of months and update the active day.
const changeMonth = (delta) => {
  const ref = new Date(Date.UTC(state.year, state.month + delta, 1));
  state.year = ref.getUTCFullYear();
  state.month = ref.getUTCMonth();

  const monthPrefix = `${state.year}-${String(state.month + 1).padStart(2, "0")}`;
  const monthDays = Array.from(state.eventsByDay.keys())
    .filter((d) => d.startsWith(monthPrefix))
    .sort();

  state.activeDay = monthDays[0] ?? null;
  renderCalendar();
  renderEventPanel();
};

// Render the month grid and day cells, including navigation and highlights.
const renderCalendar = () => {
  const { year, month, eventsByDay, activeDay, events } = state;

  calendarContainer.innerHTML = "";

  const calendar = document.createElement("div");
  calendar.className = "calendar";

  const heading = document.createElement("div");
  heading.className = "calendar__heading";

  const controls = document.createElement("div");
  controls.className = "calendar__controls";

  const prevBtn = document.createElement("button");
  prevBtn.type = "button";
  prevBtn.className = "calendar__nav-btn";
  prevBtn.setAttribute("aria-label", "Previous month");
  prevBtn.textContent = "‹";
  prevBtn.addEventListener("click", () => changeMonth(-1));

  const title = document.createElement("h2");
  title.className = "calendar__title";
  title.textContent = `${MONTH_NAMES[month]} ${year}`;

  const nextBtn = document.createElement("button");
  nextBtn.type = "button";
  nextBtn.className = "calendar__nav-btn";
  nextBtn.setAttribute("aria-label", "Next month");
  nextBtn.textContent = "›";
  nextBtn.addEventListener("click", () => changeMonth(1));

  controls.append(prevBtn, title, nextBtn);

  const meta = document.createElement("p");
  meta.textContent = `${events.length} event${events.length === 1 ? "" : "s"} loaded`;

  heading.append(controls, meta);

  const grid = document.createElement("div");
  grid.className = "calendar__grid";

  WEEKDAYS.forEach((weekday) => {
    const label = document.createElement("div");
    label.className = "calendar__weekday";
    label.textContent = weekday;
    grid.appendChild(label);
  });

  // Render days for the first and last weeks, filling with adjacent-month days,
  // but avoid extra rows that contain only adjacent-month days.
  const firstOfMonth = new Date(Date.UTC(year, month, 1));
  const lastOfMonth = new Date(Date.UTC(year, month + 1, 0));
  const startOffset = (firstOfMonth.getUTCDay() + 6) % 7; // Mon=0..Sun=6
  const endOffset = 6 - ((lastOfMonth.getUTCDay() + 6) % 7);

  const startDate = new Date(Date.UTC(year, month, 1 - startOffset));
  const endDate = new Date(Date.UTC(year, month, lastOfMonth.getUTCDate() + endOffset));

  for (let cur = new Date(startDate); cur <= endDate; cur.setUTCDate(cur.getUTCDate() + 1)) {
    const iso = toISODate(cur);
    const inMonth = cur.getUTCMonth() === month;
    const dayEvents = eventsByDay.get(iso) ?? [];

    const button = document.createElement("button");
    button.type = "button";
    button.className = "calendar__day";
    button.dataset.day = iso;

    if (!inMonth) {
      button.classList.add("calendar__day--muted");
    }

    if (dayEvents.length > 0) {
      button.classList.add("calendar__day--highlight");
    }

    // Mark today for a gentle visual emphasis
    const todayIso = toISODate(new Date());
    if (iso === todayIso) {
      button.classList.add("calendar__day--today");
      button.setAttribute("aria-current", "date");
    }

    if (activeDay === iso) {
      button.classList.add("calendar__day--active");
    }

    // Date row: show weekday inline on ultra-small screens
    const datebar = document.createElement("div");
    datebar.className = "calendar__datebar";

    const weekdayInline = document.createElement("span");
    weekdayInline.className = "calendar__weekday-inline";
    const weekdayIndex = (cur.getUTCDay() + 6) % 7; // Mon=0..Sun=6
    weekdayInline.textContent = WEEKDAYS[weekdayIndex];

    const dateLabel = document.createElement("span");
    dateLabel.className = "calendar__date";
    dateLabel.textContent = cur.getUTCDate();

    datebar.append(weekdayInline, dateLabel);

    const eventsContainer = document.createElement("div");
    eventsContainer.className = "calendar__events";

    dayEvents.slice(0, 3).forEach((event) => {
      const chip = document.createElement("span");
      chip.className = "calendar__event-chip";
      chip.textContent = event.title;
      eventsContainer.appendChild(chip);
    });

    if (dayEvents.length > 3) {
      const more = document.createElement("span");
      more.className = "calendar__more";
      more.textContent = `+${dayEvents.length - 3}`;
      eventsContainer.appendChild(more);
    }

    button.append(datebar, eventsContainer);

    // Avoid closing over the mutable `cur` Date; capture needed values now
    const inMonthCaptured = inMonth;
    const dayMonth = cur.getUTCMonth();
    const dayYear = cur.getUTCFullYear();

    const gotoIfAdjacent = () => {
      if (!inMonthCaptured) {
        const currentAbs = state.year * 12 + state.month;
        const targetAbs = dayYear * 12 + dayMonth;
        const delta = targetAbs - currentAbs;
        changeMonth(delta);
      }
      setActiveDay(iso);
    };

    button.addEventListener("click", gotoIfAdjacent);
    button.addEventListener("keypress", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        gotoIfAdjacent();
      }
    });

    grid.appendChild(button);
  }

  calendar.append(heading, grid);
  calendarContainer.appendChild(calendar);
};

// Render the right-hand event panel (or placeholder) for the active day.
const renderEventPanel = () => {
  const { activeDay, eventsByDay } = state;

  if (!activeDay) {
    eventPanel.innerHTML = `
      <div class="event-panel__placeholder">
        <h2>Select a highlighted day</h2>
        <p>Day details appear here so you can plan your visit.</p>
      </div>
    `;
    eventPanel.classList.add("event-panel--empty");
    return;
  }

  const dayEvents = eventsByDay.get(activeDay) ?? [];

  if (dayEvents.length === 0) {
    eventPanel.innerHTML = `
      <div class="event-panel__placeholder">
        <h2>${formatDisplayDate(activeDay)}</h2>
        <p>No aperos scheduled for this day yet.</p>
      </div>
    `;
    eventPanel.classList.add("event-panel--empty");
    return;
  }

  eventPanel.classList.remove("event-panel--empty");
  eventPanel.innerHTML = "";

  const header = document.createElement("div");
  header.className = "event-panel__header";

  const title = document.createElement("h2");
  title.textContent = formatDisplayDate(activeDay);

  const counter = document.createElement("span");
  counter.textContent = `${dayEvents.length} event${dayEvents.length === 1 ? "" : "s"}`;

  header.append(title, counter);

  const list = document.createElement("ul");
  list.className = "event-panel__list";

  dayEvents.forEach((event) => {
    const item = document.createElement("li");

    const card = document.createElement("article");
    card.className = "event-card";

    const source = document.createElement("span");
    source.className = "event-card__source";
    source.textContent = event.source.replace(/[-_]/g, " ").toUpperCase();

    const eventTitle = document.createElement("span");
    eventTitle.className = "event-card__title";
    eventTitle.textContent = event.title;

    const metaLines = [];
    const time = formatEventTime(event);
    if (time) {
      metaLines.push(time);
    }
    if (event.location) {
      metaLines.push(event.location);
    }

    const url =
      event.url && event.url.startsWith("http")
        ? event.url
        : event.url
        ? `https://amiv.ethz.ch/${event.url.replace(/^\/+/, "")}`
        : null;

    card.append(source, eventTitle);

    if (metaLines.length > 0) {
      const meta = document.createElement("span");
      meta.className = "event-card__meta";
      meta.textContent = metaLines.join(" · ");
      card.appendChild(meta);
    }

    if (metaLines.length === 0) {
      const spacer = document.createElement("span");
      spacer.className = "event-card__meta";
      spacer.textContent = "Details coming soon";
      card.appendChild(spacer);
    }

    const insights = document.createElement("div");
    insights.className = "event-card__insights";

    if (event.refreshments) {
      const refreshmentRow = document.createElement("div");
      refreshmentRow.className = "event-card__insight";

      const refreshmentLabel = document.createElement("span");
      refreshmentLabel.className = "event-card__insight-label";
      refreshmentLabel.textContent = "Offerings";

      const refreshmentValue = document.createElement("span");
      refreshmentValue.className = "event-card__insight-value";
      refreshmentValue.textContent = event.refreshments;

      refreshmentRow.append(refreshmentLabel, refreshmentValue);
      insights.appendChild(refreshmentRow);
    }

    const easeRow = document.createElement("div");
    easeRow.className = "event-card__insight event-card__insight--meter";

    const easeLabel = document.createElement("span");
    easeLabel.className = "event-card__insight-label";
    easeLabel.textContent = "Ease of entry";

    const easeValue = document.createElement("span");
    easeValue.className = "event-card__insight-value";
    const easeScoreRaw = Number.isFinite(event.easeOfEntry) ? event.easeOfEntry : DEFAULT_EASE_OF_ENTRY;
    const easeScore = Math.min(Math.max(easeScoreRaw, 0), 1);
    easeValue.textContent = describeEaseOfEntry(easeScore);

    const meter = document.createElement("div");
    meter.className = "ease-meter";
    meter.setAttribute("role", "img");
    meter.setAttribute("aria-label", `Ease of entry indicator: ${Math.round(easeScore * 100)} percent towards easy.`);

    const marker = document.createElement("span");
    marker.className = "ease-meter__marker";
    const markerPosition = easeScore * 100;
    marker.style.left = `${markerPosition}%`;

    meter.appendChild(marker);
    easeRow.append(easeLabel, meter, easeValue);
    insights.appendChild(easeRow);

    card.appendChild(insights);

    if (url) {
      const link = document.createElement("a");
      link.className = "event-card__link";
      link.href = url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = "View event";
      card.appendChild(link);
    }

    item.appendChild(card);
    list.appendChild(item);
  });

  eventPanel.append(header, list);
};

// Set the selected day, re-render views, and open modal on tiny screens.
const setActiveDay = (isoString) => {
  state.activeDay = isoString;
  renderCalendar();
  renderEventPanel();

  // On ultra-small screens, show details in a modal bottom sheet.
  if (isUltraSmallScreen()) {
    openMobileEventModal(isoString);
  }
};

// App bootstrap: load events, choose a sensible default day, and render.
const initialise = async () => {
  try {
    showStatus("loading", "Loading events…");
    const events = await loadEventSources();

    state.events = events;
    state.eventsByDay = createEventLookup(events);

    const todayIso = toISODate(new Date());
    const eventDays = Array.from(state.eventsByDay.keys()).sort();
    const preferredDay = eventDays.includes(todayIso)
      ? todayIso
      : eventDays.find((iso) => iso.startsWith(`${state.year}-`)) ?? eventDays[0] ?? null;

    state.activeDay = preferredDay ?? null;

    renderCalendar();
    renderEventPanel();
  } catch (error) {
    console.error(error);
    showStatus("error", "Couldn't load events just now. Please verify the JSON files in data/.");
    eventPanel.innerHTML = `
      <div class="event-panel__placeholder">
        <h2>No events available</h2>
        <p>Check that <code>data/apero_results_amiv.json</code> exists and is valid JSON.</p>
      </div>
    `;
    eventPanel.classList.add("event-panel--empty");
  }
};

// Utilities and handlers for ultra-small screen modal
// Detects if the current viewport is extremely small; used to switch to a modal UI.
const isUltraSmallScreen = () => window.matchMedia("(max-width: 420px)").matches;

// Show the mobile modal with the same content as the fixed panel.
const openMobileEventModal = (isoString) => {
  if (!mobileModal || !mobileModalContent) return;
  // Set title
  if (mobileModalTitle) mobileModalTitle.textContent = formatDisplayDate(isoString);
  // Reuse the same content rendered in the fixed panel
  mobileModalContent.innerHTML = eventPanel.innerHTML;
  mobileModal.removeAttribute("hidden");
  document.body.classList.add("modal-open");
};

// Hide the mobile modal and restore body scroll.
const closeMobileEventModal = () => {
  if (!mobileModal) return;
  mobileModal.setAttribute("hidden", "");
  document.body.classList.remove("modal-open");
};

mobileModalClose?.addEventListener("click", closeMobileEventModal);
mobileModal?.addEventListener("click", (e) => {
  if (e.target && e.target.getAttribute("data-close") === "true") {
    closeMobileEventModal();
  }
});

window.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeMobileEventModal();
  }
});

// Close modal if resizing to larger screen
window.matchMedia("(max-width: 420px)").addEventListener("change", (ev) => {
  if (!ev.matches) {
    closeMobileEventModal();
  }
});

// Gate app behind disclaimer acceptance (no persistence)
let appStarted = false;

// Present a disclaimer modal on first load; start the app after acceptance.
// If the modal is missing in the DOM, the app starts immediately.
const startWithDisclaimerGate = () => {
  const modal = document.getElementById("disclaimer-modal");
  const acceptBtn = document.getElementById("disclaimer-accept");

  // If modal elements are missing, fallback to starting the app.
  if (!modal || !acceptBtn) {
    if (!appStarted) {
      appStarted = true;
      initialise();
    }
    return;
  }

  const showModalAndAwaitAcceptance = () => {
    // Always show modal on entry
    modal.removeAttribute("hidden");
    acceptBtn.addEventListener(
      "click",
      () => {
        modal.setAttribute("hidden", "");
        if (!appStarted) {
          appStarted = true;
          initialise();
        }
      },
      { once: true }
    );
  };

  showModalAndAwaitAcceptance();

  // If the page is restored from the BFCache, re-show disclaimer
  window.addEventListener("pageshow", (e) => {
    if (e.persisted) {
      showModalAndAwaitAcceptance();
    }
  });
};

// Module script is loaded after DOM; safe to run directly
startWithDisclaimerGate();
