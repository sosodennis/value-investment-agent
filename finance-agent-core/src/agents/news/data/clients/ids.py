import hashlib


def generate_news_id(url: str, title: str = "") -> str:
    """
    Generate a unique hash ID for a news item based on its URL.
    """
    return hashlib.md5(url.encode()).hexdigest()
