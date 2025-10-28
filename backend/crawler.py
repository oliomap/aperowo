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


# async def vmp_crawler_args():

#     vmp_url = "https://www.vmp.ethz.ch/en/events/alle_events"
#     vmp_include_pattern_filter = URLPatternFilter(patterns = ["*events*"])
#     vmp_max_depth = 1

#     urls_to_exclude = [
#         "https://www.vmp.ethz.ch/en/events/alle_events",
#         "https://www.vmp.ethz.ch/en/events",
#         "https://www.vmp.ethz.ch/en/events/meine_events",
#         "https://www.vmp.ethz.ch/en/events/helper-recruitment",
#     ]
#     vmp_exclude_pattern_filter = URLPatternFilter(patterns = urls_to_exclude, reverse = True )
    
#     vmp_filter_chain = FilterChain([vmp_include_pattern_filter, vmp_exclude_pattern_filter])
#     return vmp_url, vmp_filter_chain, vmp_max_depth

# async def vis_crawler_args():

#     vis_url = "https://vis.ethz.ch/en/events/"
#     vis_include_pattern_filter = URLPatternFilter(patterns = ["*events*"])

#     vis_max_depth = 1

#     urls_to_exclude = [
#         "https://vis.ethz.ch/en/events/",
#         "https://vis.ethz.ch/en/accounts/keycloak/login?next=/en/events/",
#     ]
#     vis_exclude_pattern_filter = URLPatternFilter(patterns = urls_to_exclude, reverse = True )
    
#     vis_filter_chain = FilterChain([vis_include_pattern_filter, vis_exclude_pattern_filter])
#     return vis_url, vis_filter_chain, vis_max_depth




async def run_crawlers_from_file(cfg_path: str = "./backend/urls_to_crawl.json"):
    """Load crawler configs from JSON and run the loop for each job.

    This is intentionally simple: it reads the JSON file, extracts a list of
    jobs (supports either a top-level dict with "jobs" or a plain list), and
    executes the same body that the original `main` used to contain.
    """
    # read file
    with open(cfg_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    jobs = data.get("jobs") if isinstance(data, dict) else data
  
  

    for config in jobs:
        start_url = config.get("url")
        max_depth = config.get("depth", 1)
        # print(max_depth)

        output_filename = config.get("output_filename")
        # print(output_filename)

        

        # Build filter chain

        include_patterns = config.get("include_pattern_filter") or config.get("urls_to_include") or []
        if not isinstance(include_patterns, (list, tuple)):
            include_patterns = [include_patterns]

        exclude_patterns = config.get("urls_to_exclude") or config.get("exclude") or []
        if not isinstance(exclude_patterns, (list, tuple)):
            exclude_patterns = [exclude_patterns] if exclude_patterns else []

        include_filter = URLPatternFilter(patterns=include_patterns)
        exclude_filter = URLPatternFilter(patterns=exclude_patterns, reverse=True)
        crawl_filters = FilterChain([include_filter, exclude_filter])

        # Run crawler
        results = await event_crawler(start_url, crawl_filters, max_depth)
        print(f"Crawled {len(results)} pages in total for {output_filename}")


        # Save results (overwrite)
        filepath = os.path.join("../data/raw/", output_filename)
        if os.path.exists(filepath):
            os.remove(filepath)

        for result in results:
            process_result(result, output_filename)




async def main():
    await run_crawlers_from_file()




if __name__ == "__main__":
    asyncio.run(main())
