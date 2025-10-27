'''For the AMIV website, we can fetch events from the AMIV API.
This script fetches all events from the AMIV API, filters them for those containing "apero" or "food" in their title or description,
and extracts relevant information such as URL, title, date, start and end times, and location'''

# Import necessary libraries.
import requests
import urllib.parse
import json
import unicodedata
import re

# ---------------------------------------------------------------------------
# Heuristic configuration for extracting refreshment information.
# ---------------------------------------------------------------------------
# The AMIV event payloads do not expose a dedicated field for what is served
# at an event.  We therefore rely on keyword searches inside the text fields
# provided by the API.  Each category contains a short display label that will
# eventually be surfaced in the UI and a set of keywords that are matched on a
# normalised, accent-stripped, lower-case string.
REFRESHMENT_RULES = {
    "drinks": {
        "label": "Drinks",
        "keywords": {
            "beer",
            "bier",
            "wine",
            "wein",
            "cocktail",
            "cocktails",
            "spritz",
            "hugos",
            "hugo",
            "gluhwein",
            "gluehwein",
            "champagne",
            "apero",
            "aperitivo",
            "drink",
            "shots",
            "longdrink",
        },
    },
    "food": {
        "label": "Food",
        "keywords": {
            "pizza",
            "pizzas",
            "burger",
            "burgers",
            "barbecue",
            "bbq",
            "grill",
            "bratwurst",
            "wuerstli",
            "wurst",
            "raclette",
            "fondue",
            "tapas",
            "buffet",
            "buffetts",
            "dinner",
            "meal",
            "meals",
            "supper",
            "lunch",
            "mittagessen",
            "abendessen",
            "food",
            "essen",
            "sushi",
        },
    },
    "snacks": {
        "label": "Snacks",
        "keywords": {
            "snack",
            "snacks",
            "bites",
            "chips",
            "nuts",
            "fingerfood",
            "finger food",
            "sandwich",
            "sandwiches",
            "apero riche",
        },
    },
    "sweet": {
        "label": "Dessert",
        "keywords": {
            "cake",
            "cakes",
            "brownie",
            "brownies",
            "cupcake",
            "cupcakes",
            "dessert",
            "desserts",
            "chocolate",
            "sweets",
            "waffle",
            "waffles",
            "crepe",
            "crepes",
            "ice cream",
            "gelato",
            "donut",
            "donuts",
        },
    },
}

# Define the order in which categories should be displayed when multiple
# matches are found.  The idea is to list the most substantial offering first.
REFRESHMENT_DISPLAY_PRIORITY = ["food", "drinks", "snacks", "sweet"]

# Normalize text by removing diacritical marks (accents).
def normalize_text(text):
    """Normalize text by removing diacritical marks (accents)."""
    return ''.join(
        char for char in unicodedata.normalize('NFD', text)
        if unicodedata.category(char) != 'Mn'
    )

# Filter dictionary for the API query (on the server side).
def build_api_url(base_url, filter_dict):
    """Construct the full API URL with the 'where' query parameter."""
    query_string = urllib.parse.urlencode({"where": json.dumps(filter_dict)})
    return f"{base_url}?{query_string}"

# Filter function to check if an event contains "apero" in any of its text fields (locally).
def event_contains_apero(event):
    """Check if any of the event's text fields contain 'apero'."""
    # Combine several relevant text fields.
    fields = [
        event.get("title_en", ""),
        event.get("description_en", ""),
        event.get("catchphrase_en", ""),
        event.get("title_de", ""),
        event.get("description_de", ""),
        event.get("catchphrase_de", "")
    ]
    # Join the fields into one string, convert to lower case, and normalize.
    combined_text = normalize_text(" ".join(fields).lower())
    # Return True if "apero" is found in the combined text.
    return "apero" in combined_text

# Fetch all events from the API, handling pagination.
def fetch_all_events(base_url, filter_dict=None):
    events = []
    
    # Build the initial URL with filter if provided.
    url = build_api_url(base_url, filter_dict) if filter_dict else base_url
    
    while url:
        #print("Fetching:", url)  # Debug: print the URL of the current page.
        
        # Possibly useful to save the visited URLs to a file.
        # with open("data/visited_urls.json", "w", encoding="utf-8") as outfile:
        #     json.dump(url, outfile, ensure_ascii=False, indent=2)

        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Assuming the API returns a JSON object with a '_items' key for the list of events.
        if isinstance(data, dict) and '_items' in data:
            events.extend(data['_items'])
            # Use the 'next' link if available.
            url = data.get('_links', {}).get('next', {}).get('href')
            # If the API returns a relative URL, join it with the base URL.
            if url and not url.startswith('http'):

                # Remove any trailing slashes from base_url before joining.
                url = requests.compat.urljoin(base_url.rstrip('/'), url)

        # If the API returns a list of events directly.
        # This is less common but some APIs might do this.        
        elif isinstance(data, list):
            events.extend(data)
            # Break out if it's just a list
            url = None
        else:
            url = None
    return events

# Extract specific fields from an event.
def extract_event_fields(event):
    """
    Extract specific fields from an event:
    - URL, extracted from the event's _links section
    - Title (preferring title_en over title_de)
    - Date (from time_start, in YYYY-MM-DD format)
    - Start and end times (only hh:mm)
    - Location
    - Inferred refreshments (based on keyword matches in text fields)
    """
    # Extract the URL assuming it is found in the '_links' section.
    url = event.get("_links", {}).get("self", {}).get("href", "")
    # Prefer the English title, fallback to the German title.
    title = event.get("title_en", event.get("title_de", ""))
    # Get the full start time string in ISO 8601 format.
    time_start = event.get("time_start", "")
    date = time_start[:10] if time_start else ""
    # Extract only hh:mm (characters at positions 11 to 15)
    start_time = time_start[11:16] if time_start and len(time_start) >= 16 else ""
    # Similarly extract end time in hh:mm from the provided time_end field.
    time_end = event.get("time_end", "")
    end_time = time_end[11:16] if time_end and len(time_end) >= 16 else ""
    # Get the location (if available)
    location = event.get("location", "")
    refreshments = infer_refreshments(event)
    
    return {
        "url": url,
        "title": title,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "location": location,
        "refreshments": refreshments.get("summary"),
        "refreshment_details": refreshments,
    }


def infer_refreshments(event, rules=REFRESHMENT_RULES):
    """
    Analyse the textual fields of a raw AMIV event payload and estimate what
    food or drinks will be offered.

    Parameters
    ----------
    event : dict
        Raw event payload as returned by the AMIV API.
    rules : dict, optional
        Mapping from category identifiers to dictionaries that contain a human
        readable ``label`` and a set of ``keywords`` (in lower-case) that signal
        the presence of the respective category.  The default is
        ``REFRESHMENT_RULES`` defined at module level so that tests can inject
        alternative configurations where needed.

    Returns
    -------
    dict
        Always returns a serialisable dictionary with the following keys:
        ``categories`` (``list[str]``) containing the matched category ids in
        display order, ``matches`` (``dict[str, list[str]]``) with the concrete
        keywords that triggered each category, and ``summary`` (``str`` or
        ``None``) providing a ready-to-display sentence fragment for the UI.
        If no clue is found, ``categories`` and ``matches`` are empty and
        ``summary`` is ``None`` so the caller can skip rendering the section.
    """

    # Combine the relevant text fields into a single search string.
    corpus = _build_refreshment_corpus(event)
    if not corpus:
        return {"categories": [], "matches": {}, "summary": None}

    matches = {}
    for category, config in rules.items():
        keywords = config.get("keywords", set())
        # Normalise multi-word keywords so "finger food" is matched properly.
        category_hits = sorted({
            keyword
            for keyword in keywords
            if keyword and _keyword_in_text(keyword, corpus)
        })
        if category_hits:
            matches[category] = category_hits

    if not matches:
        return {"categories": [], "matches": {}, "summary": None}

    categories = [
        cat for cat in REFRESHMENT_DISPLAY_PRIORITY if cat in matches
    ] + [cat for cat in matches if cat not in REFRESHMENT_DISPLAY_PRIORITY]

    summary = _format_refreshment_summary(categories, matches, rules)

    return {
        "categories": categories,
        "matches": matches,
        "summary": summary,
    }


def _build_refreshment_corpus(event):
    """
    Return a single normalised lower-case string with the key text fragments.

    The function concatenates title, catchphrase and description in both
    English and German, strips accents to make keyword matching more robust and
    collapses whitespace so that multi-word keywords remain searchable.
    """
    fields = [
        event.get("title_en", ""),
        event.get("catchphrase_en", ""),
        event.get("description_en", ""),
        event.get("title_de", ""),
        event.get("catchphrase_de", ""),
        event.get("description_de", ""),
    ]
    combined = " ".join(filter(None, fields)).strip()
    if not combined:
        return ""
    normalised = normalize_text(combined.lower())
    # Replace consecutive whitespace characters with a single space which makes
    # matching multi-word phrases (e.g. "finger food") more predictable.
    return re.sub(r"\s+", " ", normalised)


def _keyword_in_text(keyword, text):
    """
    Determine whether ``keyword`` appears in ``text`` after normalisation.
    Both inputs are assumed to be non-empty strings.
    """
    keyword_norm = re.sub(r"\s+", " ", normalize_text(keyword.lower()))
    return keyword_norm in text if keyword_norm else False


def _format_refreshment_summary(categories, matches, rules):
    """
    Build a human readable summary string from the matched categories.
    The summary consists of the category labels (from ``rules``) and up to
    three keywords that triggered each category.
    """
    parts = []
    for category in categories:
        label = rules.get(category, {}).get("label", category.title())
        keywords = matches.get(category, [])
        if not keywords:
            parts.append(label)
            continue
        snippet = ", ".join(keywords[:3])
        parts.append(f"{label} ({snippet})")
    return " · ".join(parts)
