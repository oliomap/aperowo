import asyncio
import json
import os
from urllib.parse import urlparse
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
from crawl4ai.content_scraping_strategy import LXMLWebScrapingStrategy
from crawl4ai.deep_crawling.filters import URLPatternFilter, FilterChain

def process_result(result, filename):
    '''
    Process the crawled result and append it to a document within data/{filename}.
    This json has the following structure:
    [
        {
            "url": "seed-url/<page-id>",
            "session_id": "<session-id>",
            "success": true,
            "metadata": {},
            "html": "<html-content>",
            "extracted_content": "<extracted-content>",
            "markdown": "## Extracted Markdown Content ..."
        },
        ...
    ]
    '''
    new_data = {
        "url": result.url,
        "session_id": result.session_id,
        "success": result.success,
        "metadata": result.metadata,
        "html": result.html,
        "extracted_content": result.extracted_content,
        "markdown": result.markdown
    }

    filepath = os.path.join('data/raw', filename)
    
    # Create data directory if it doesn't exist
    os.makedirs('data/raw', exist_ok=True)

    # Read existing data
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            try:
                all_data = json.load(f)
            except json.JSONDecodeError:
                all_data = []
    else:
        all_data = []

    # Append new data
    all_data.append(new_data)

    # Write all data back to the file
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=4)

async def event_crawler():
    # Configure a 2-level deep crawl
    url_filter = URLPatternFilter(patterns = ["*events*"])
    config = CrawlerRunConfig(
        deep_crawl_strategy=BFSDeepCrawlStrategy(
            max_depth=1, 
            filter_chain = FilterChain([url_filter])
        ),
        scraping_strategy=LXMLWebScrapingStrategy(),
        verbose=True
    )

    async with AsyncWebCrawler() as crawler:
        results = await crawler.arun("https://www.vmp.ethz.ch/en/events/alle_events", config=config)

        print(f"Crawled {len(results)} pages in total")
    
    return results

async def main():
    
    results = await event_crawler()

    print(f"Crawled {len(results)} pages in total")

    # Define the output filename
    output_filename = "crawled_data_test.json"
    filepath = os.path.join('data/raw', output_filename)

    # Clear the file before starting
    if os.path.exists(filepath):
        os.remove(filepath)

    # Access individual results
    for result in results:  # Show all results
        #print(f"URL: {result.url}")
        #print(f"Depth: {result.metadata.get('depth', 0)}")   
        process_result(result, output_filename)

if __name__ == "__main__":
    asyncio.run(main())
