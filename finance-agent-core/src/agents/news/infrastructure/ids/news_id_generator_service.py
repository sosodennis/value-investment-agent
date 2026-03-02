import hashlib


def generate_news_id(url: str, title: str = "") -> str:
    """
    Generate a stable ID for a news item from URL + title.
    This avoids collisions when URL is missing but title is present.
    """
    normalized_url = (url or "").strip().lower()
    normalized_title = (title or "").strip().lower()
    key = f"url:{normalized_url}|title:{normalized_title}"
    return hashlib.md5(key.encode()).hexdigest()
