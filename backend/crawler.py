import asyncio
import json
import os
from urllib.parse import urlparse
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
from crawl4ai.content_scraping_strategy import LXMLWebScrapingStrategy
from crawl4ai.deep_crawling.filters import URLPatternFilter, FilterChain, DomainFilter, ContentTypeFilter

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
        "fit_html": result.fit_html,
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

async def event_crawler(specific_url, specific_url_filter_chain, specific_max_depth):

    config = CrawlerRunConfig(
        deep_crawl_strategy=BFSDeepCrawlStrategy(
            max_depth= specific_max_depth, 
            filter_chain = specific_url_filter_chain
        ),
        scraping_strategy=LXMLWebScrapingStrategy(),
        verbose=True,
        excluded_tags=["header", "footer", "nav", "aside"]
    )

    async with AsyncWebCrawler() as crawler:
        results = await crawler.arun(specific_url, config=config)
        print(f"Crawled {len(results)} pages in total")
    
    return results


async def vmp_crawler_args():

    vmp_url = "https://www.vmp.ethz.ch/en/events/alle_events"
    vmp_include_pattern_filter = URLPatternFilter(patterns = ["*events*"])
    vmp_max_depth = 1

    urls_to_exclude = [
        "https://www.vmp.ethz.ch/en/events/alle_events",
        "https://www.vmp.ethz.ch/en/events",
        "https://www.vmp.ethz.ch/en/events/meine_events",
        "https://www.vmp.ethz.ch/en/events/helper-recruitment",
    ]
    vmp_exclude_pattern_filter = URLPatternFilter(patterns = urls_to_exclude, reverse = True )
    
    vmp_filter_chain = FilterChain([vmp_include_pattern_filter, vmp_exclude_pattern_filter])
    return vmp_url, vmp_filter_chain, vmp_max_depth

async def vis_crawler_args():

    vis_url = "https://vis.ethz.ch/de/events/"
    vis_include_pattern_filter = URLPatternFilter(patterns = ["*events*"])

    vis_max_depth = 1

    urls_to_exclude = [
        "https://vis.ethz.ch/de/events/",
        "https://vis.ethz.ch/de/accounts/keycloak/login?next=/de/events/",
    ]
    vis_exclude_pattern_filter = URLPatternFilter(patterns = urls_to_exclude, reverse = True )
    
    vis_filter_chain = FilterChain([vis_include_pattern_filter, vis_exclude_pattern_filter])
    return vis_url, vis_filter_chain, vis_max_depth



async def main():
    crawler_configs = [
        {"args_func": vmp_crawler_args, "output_filename": "VMP_data.json"},
        {"args_func": vis_crawler_args, "output_filename": "VIS_data.json"}
        # Add more crawler configurations here:
        # {"args_func": another_crawler_args, "output_filename": "ANOTHER_data.json"},
    ]

    for config in crawler_configs:
        start_url, crawl_filters, max_depth = await config["args_func"]()
        results = await event_crawler(start_url, crawl_filters, max_depth)

        print(f"Crawled {len(results)} pages in total for {config['output_filename']}")

        filepath = os.path.join('data/raw', config['output_filename'])

        if os.path.exists(filepath):
            os.remove(filepath)

        for result in results:
            process_result(result, config['output_filename'])



if __name__ == "__main__":
    asyncio.run(main())
