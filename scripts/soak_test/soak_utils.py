from urllib.parse import urlparse


def url_with_prefix(url: str, prefix: str) -> str:
    parsed_url = urlparse(url)
    return parsed_url._replace(netloc=f"{prefix}.{parsed_url.netloc}").geturl()
