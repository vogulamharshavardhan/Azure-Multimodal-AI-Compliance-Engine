"""Source restrictions and exact-block citation checks for the bundled corpus."""
from pathlib import PurePosixPath
import re

SOURCE_PREFIXES = {
    'ADVERTISING_DISCLOSURES': ('ftc-', '1001a-influencer-guide'),
    'YOUTUBE_AD_SPECIFICATIONS': ('google-ads-',),
}

def source_matches_domain(source, domain):
    return PurePosixPath(str(source)).name.startswith(SOURCE_PREFIXES.get(domain, ()))

def citation_matches_block(source, page, quote, packet):
    normalize = lambda s: re.sub(r'\s+', ' ', str(s)).strip().casefold()
    needle = normalize(quote)
    if len(needle) < 12 or not source:
        return False
    expected_page = str(page) if page is not None else 'Not applicable'
    for block in packet.split('\n\n---\n\n'):
        header, sep, content = block.partition('Policy text:\n')
        if not sep:
            # Legacy test fixtures use Policy text: on the same line.
            header, sep, content = block.partition('Policy text:')
        lines = header.splitlines()
        if sep and f'Source: {source}' in lines and f'PDF page: {expected_page}' in lines and needle in normalize(content):
            return True
    return False


def jurisdiction_supported(domain, jurisdiction):
    """Bundled disclosure sources are US-only. Never infer jurisdiction from language."""
    return domain != "ADVERTISING_DISCLOSURES" or str(jurisdiction).strip().upper() in {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"}
