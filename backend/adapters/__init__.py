"""Conectores de fuentes. Cada módulo expone: TYPE, fetch_latest(source, client), search(source, client, q)."""
from . import json_index, rss_feed, search_url, wp_api

ADAPTERS = {
    wp_api.TYPE: wp_api,
    rss_feed.TYPE: rss_feed,
    json_index.TYPE: json_index,
    search_url.TYPE: search_url,
}

SOURCE_TYPES = list(ADAPTERS)
