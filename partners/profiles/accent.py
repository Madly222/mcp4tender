from __future__ import annotations


ACCENT = {
    "partner": "Accent",
    "sheets": [
        {
            "name": "PriceList",
            "ingest": True,
            "header_tokens": ["brand", "p/n", "description"],
            "columns": {
                "brand": "brand",
                "mpn": "p/n",
                "description": "description",
                "price_lei": "online, lei",
                "retail_usd": "online, usd",
                "cost": "dealer b, usd",
                "promo": "promo dealer, usd",
                "warranty": "warranty",
                "stock": "stock",
            },
            "cost_field": "cost",
            "cost_currency": "USD",
            "promo_field": "promo",
            "category": "outline",
        },
        {"name": "Used-Refurb", "ingest": False,
         "reason": "used / refurbished — different condition, not comparable to new goods"},
        {"name": "ASC", "ingest": False, "reason": "service sheet, no price rows"},
    ],
}
