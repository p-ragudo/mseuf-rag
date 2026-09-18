import asyncio
import os
import re
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy

# Absolute path targeting backend/data/knowledge_base
START_URL = "https://mseuf.edu.ph"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "knowledge_base")

def sanitize_filename(url: str) -> str:
    clean_name = re.sub(r'https?://', '', url)
    clean_name = re.sub(r'[^\w\-]', '_', clean_name)
    return clean_name[:100] + ".md"

async def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    config = CrawlerRunConfig(
        deep_crawl_strategy=BFSDeepCrawlStrategy(
            max_depth=2, 
            include_external=False
        ),
        cache_mode=CacheMode.BYPASS,
        excluded_tags=["nav", "footer", "header", "script", "style"]
    )

    print(f"Starting crawl on: {START_URL}...")
    
    async with AsyncWebCrawler() as crawler:
        results = await crawler.arun(url=START_URL, config=config)
        
        saved_count = 0
        for result in results:
            if result.success and result.markdown:
                filename = sanitize_filename(result.url)
                filepath = os.path.join(OUTPUT_DIR, filename)
                
                content = f"---\nsource_url: {result.url}\n---\n\n" + result.markdown
                
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)
                    
                print(f"Saved: {filepath}")
                saved_count += 1
                
        print(f"\nDone! Saved {saved_count} pages into '{OUTPUT_DIR}/'.")

if __name__ == "__main__":
    asyncio.run(main())