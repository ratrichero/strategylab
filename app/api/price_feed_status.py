from fastapi import APIRouter
from app.services.price_feed import get_price_feed, restart_price_feed

router = APIRouter(prefix="/api", tags=["price-feed"])


@router.get("/price-feed/status")
def price_feed_status():
    feed = get_price_feed()
    return feed.get_stats()


@router.post("/price-feed/restart")
def price_feed_restart():
    restart_price_feed()
    return {"ok": True, "message": "Price feed restart requested"}