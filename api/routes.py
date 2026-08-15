from fastapi import APIRouter

from scraper.bale_scraper import scrape_news
from db.mongodb.crud import save_news,get_news_from_db


router = APIRouter()


@router.post("/go-scrap")
def get_news():

    news = scrape_news()

    saved_count = 0

    for item in news:

        saved = save_news(item)

        if saved:
            saved_count += 1

    return {
        "scraped": len(news),
        "saved": saved_count,
    }


@router.get("/get-news-by-limit")
def get_news_by_limit(limit:int = 10):
    result= get_news_from_db(limit)
    return result


    
