import json
from pathlib import Path
from typing import Union

from backend.amiv_api import fetch_all_events, extract_event_fields
from backend.filter import load_raw_events, filter_events_for_refreshments, write_filtered_events

def extract_amiv():
    """
    Fetches events from the AMIV API, filters for 'apero' or 'food',
    and saves the results to a JSON file.
    """
    api = 'https://api.amiv.ethz.ch/events/'

    # Fetch all events from the AMIV API and filter them for "apero".
    events_with_apero_amiv = fetch_all_events(api, {"$or": [
    {"title_en": {"$regex": "aper", "$options": "i"}},
    {"description_en": {"$regex": "aper", "$options": "i"}},
    {"catchphrase_en": {"$regex": "aper", "$options": "i"}},
    {"title_de": {"$regex": "aper", "$options": "i"}},
    {"description_de": {"$regex": "aper", "$options": "i"}},
    {"catchphrase_de": {"$regex": "aper", "$options": "i"}},
    {"title_en": {"$regex": "food", "$options": "i"}},
    {"description_en": {"$regex": "food", "$options": "i"}},
    {"catchphrase_en": {"$regex": "food", "$options": "i"}},
    {"title_de": {"$regex": "essen", "$options": "i"}},
    {"description_de": {"$regex": "essen", "$options": "i"}},
    {"catchphrase_de": {"$regex": "essen", "$options": "i"}}
    ]})

    print(f"Found {len(events_with_apero_amiv)} events with 'apero' or 'food' in the title or description on the AMIV website.")

    # Extract specific fields from each event.
    filtered_events_amiv = [extract_event_fields(event) for event in events_with_apero_amiv]
    
    # Write the filtered events to a JSON file.
    with open("data/raw/AMIV_data.json", "w", encoding="utf-8") as outfile:
        json.dump(filtered_events_amiv, outfile, ensure_ascii=False, indent=2)

    print(f"Extracted information for {len(filtered_events_amiv)} AMIV events and saved to AMIV_data.json.")

def main(
    source: Union[str, Path] = Path("data/raw/VMP_data.json"),
    destination: Union[str, Path] = Path("data/apero_results_vmp.json"),
) -> None:
    """
    Main function to process event data and extract refreshment events.
    Loads raw event data from the source file, filters for events with refreshments,
    and writes the results to the destination files.

    TODO: 
        - Change the signature to accept multiple sources and destinations for different websites.
        - Implement a loop to process multiple event data files.
    """

    records = load_raw_events(source)
    # The crawler stores fairly verbose HTML and Markdown snippets; prioritise
    # those fields to keep the keyword search focused.
    filtered = filter_events_for_refreshments(
        records,
        text_fields=("markdown", "extracted_content", "html", "metadata.title"),
    )


    seen_titles = set()
    # write_filtered_events(filtered, destination)
    write_filtered_events(filtered, destination, seen_titles=seen_titles)


    print(
        f"Processed {len(records)} records, "
        f"found {len(filtered)} refreshment events. "
        f"Output written to {destination}."
    )

    extract_amiv()

if __name__ == "__main__":
    main()