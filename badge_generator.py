"""Badge generation for verified claims."""
from urllib.parse import quote

def generate_badge_svg(verdict: str, claim: str) -> str:
    """Generate professional SVG badge for verified claims.
    
    Args:
        verdict: CONFIRMED, PARTIALLY CONFIRMED, UNCONFIRMED, or FALSE
        claim: The claim text
    
    Returns:
        Clean, professional SVG badge
    """
    # Professional color scheme
    colors = {
        "CONFIRMED": {"bg": "#22c55e", "text": "#ffffff"},
        "PARTIALLY CONFIRMED": {"bg": "#eab308", "text": "#000000"},
        "UNCONFIRMED": {"bg": "#f97316", "text": "#ffffff"},
        "FALSE": {"bg": "#ef4444", "text": "#ffffff"},
    }
    
    # Clean labels without emojis
    labels = {
        "CONFIRMED": "VERIFIED",
        "PARTIALLY CONFIRMED": "PARTIAL",
        "UNCONFIRMED": "UNCONFIRMED",
        "FALSE": "FALSE",
    }
    
    color_scheme = colors.get(verdict, {"bg": "#888888", "text": "#ffffff"})
    label = labels.get(verdict, "VERIFIED")
    
    # Truncate claim intelligently
    max_chars = 50
    if len(claim) > max_chars:
        claim_short = claim[:max_chars].rsplit(' ', 1)[0] + "..."
    else:
        claim_short = claim
    
    # Escape XML
    claim_escaped = (claim_short
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;"))
    
    # Calculate dynamic width based on text
    label_width = len(label) * 8 + 20
    claim_width = len(claim_short) * 6.5 + 20
    total_width = max(label_width + claim_width, 300)
    
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{int(total_width)}" height="28" role="img" aria-label="CrawlConda: {label}">
  <title>CrawlConda: {label}</title>
  
  <!-- Left section (label) -->
  <rect width="{label_width}" height="28" fill="#2a2a2a"/>
  <text x="{label_width/2}" y="18" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif" 
        font-size="12" font-weight="600" fill="#e8e8e8" text-anchor="middle">CRAWLCONDA</text>
  
  <!-- Right section (verdict) -->
  <rect x="{label_width}" width="{claim_width}" height="28" fill="{color_scheme['bg']}"/>
  <text x="{label_width + claim_width/2}" y="18" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif" 
        font-size="12" font-weight="700" fill="{color_scheme['text']}" text-anchor="middle">{label}</text>
</svg>'''
    
    return svg


def generate_badge_html(ipfs_hash: str, verdict: str, claim: str, web_url: str) -> str:
    """Generate HTML embed code for badge.
    
    Args:
        ipfs_hash: IPFS hash of the verdict
        verdict: Verdict type
        claim: Claim text
        web_url: Base URL of the web app
    
    Returns:
        HTML embed code
    """
    badge_url = f"{web_url}/badge/{ipfs_hash}.svg"
    verdict_url = f"{web_url}/#/v/{ipfs_hash}"
    
    html = f'''<!-- CrawlConda Verified Badge -->
<a href="{verdict_url}" target="_blank" rel="noopener noreferrer">
  <img src="{badge_url}" alt="Verified by CrawlConda: {verdict}" />
</a>'''
    
    return html


def generate_badge_markdown(ipfs_hash: str, verdict: str, web_url: str) -> str:
    """Generate Markdown embed code for badge."""
    badge_url = f"{web_url}/badge/{ipfs_hash}.svg"
    verdict_url = f"{web_url}/#/v/{ipfs_hash}"
    
    return f"[![Verified by CrawlConda]({badge_url})]({verdict_url})"
