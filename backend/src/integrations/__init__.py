"""External HTTP/SDK clients (WildBerries, S3, etc.).

Integrations contain *only* transport concerns: authentication headers, URL
construction, retries, and raw-payload deserialization. They hold no business
logic and no database access. Modules depend on them; they depend on nothing in
``src.modules``.
"""
