"""Badge generation for verified claims."""
from urllib.parse import quote

def generate_badge_svg(verdict: str, claim: str) -> str:
    """Generate SVG badge for a verified claim.
    
    Args:
        verdict: CONFIRMED, PARTIALLY CONFIRMED, UNCONFIRMED, or FALSE
        claim: The claim text (truncated to 60 chars)
    
    Returns:
        SVG markup as string
    """
    colors = {
        "CONFIRMED": "#22c55e",
        "PARTIALLY CONFIRMED": "#eab308",
        "UNCONFIRMED": "#f97316",
        "FALSE": "#ef4444",
    }
    
    emojis = {
        "CONFIRMED": "✅",
        "PARTIALLY CONFIRMED": "🟡",
        "UNCONFIRMED": "⚠️",
        "FALSE": "❌",
    }
    
    color = colors.get(verdict, "#888888")
    emoji = emojis.get(verdict, "🔍")
    claim_short = claim[:60] + ("..." if len(claim) > 60 else "")
    
    # Escape XML special chars
    claim_escaped = (claim_short
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;"))
    
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="400" height="80" role="img" aria-label="CrawlConda Verified">
  <title>CrawlConda Verified</title>
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" style="stop-color:#1a1a1a;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#0d0d0d;stop-opacity:1" />
    </linearGradient>
  </defs>
  
  <!-- Background -->
  <rect width="400" height="80" rx="8" fill="url(#bg)"/>
  <rect width="400" height="80" rx="8" fill="none" stroke="{color}" stroke-width="2"/>
  
  <!-- Verdict badge -->
  <rect x="10" y="10" width="120" height="28" rx="14" fill="{color}"/>
  <text x="70" y="29" font-family="Arial, sans-serif" font-size="14" font-weight="bold" 
        fill="white" text-anchor="middle">{emoji} {verdict.split()[0]}</text>
  
  <!-- Claim text -->
  <text x="10" y="52" font-family="Arial, sans-serif" font-size="11" fill="#e8e8e8">
    {claim_escaped}
  </text>
  
  <!-- Footer -->
  <text x="10" y="70" font-family="Arial, sans-serif" font-size="9" fill="#666">
    Verified by CrawlConda · Ground Truth Engine
  </text>
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
