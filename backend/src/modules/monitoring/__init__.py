"""Monitoring module — WildBerries data harvesting, storage, and analytics.

Responsibilities:
    * Harvest common statistics (sales funnel), remaining stocks, and promotion
      (advertising) metrics from the WB API via Celery workers.
    * Flatten and persist the raw nested payloads into clean relational records
      (PostgreSQL ``monitoring`` schema).
    * Serve normalized analytics through summary (listing) and detailed views.

Persistence lives behind repositories; business/normalization logic never
touches the database session directly.
"""
