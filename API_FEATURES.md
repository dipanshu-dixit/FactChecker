# CrawlConda API Features

## Overview

The CrawlConda API provides programmatic access to the Ground Truth Engine with API key management, rate limiting, verification badges, and social sharing capabilities.

## 🚀 Quick Start

### 1. Generate an API Key

Visit: `https://fact-checker-teal.vercel.app/api-docs.html`

Or use curl:
```bash
curl -X POST https://factchecker-production-3945.up.railway.app/api-keys/generate \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Your Name",
    "email": "your@email.com",
    "use_case": "Building a fact-checking bot"
  }'
```

Response:
```json
{
  "api_key": "cc_live_a1b2c3d4e5f6...",
  "tier": "free",
  "daily_limit": 100,
  "message": "Save this key securely. It will not be shown again."
}
```

### 2. Verify a Claim

```bash
curl "https://factchecker-production-3945.up.railway.app/verify?claim=Iran%20struck%20Qatar" \
  -H "Authorization: Bearer cc_live_..."
```

### 3. Embed a Badge

```html
<a href="https://fact-checker-teal.vercel.app/#/v/QmXxx">
  <img src="https://factchecker-production-3945.up.railway.app/badge/QmXxx.svg" 
       alt="Verified by CrawlConda" />
</a>
```

## 📊 Rate Limits

| Tier | Limit | Cost |
|------|-------|------|
| No API Key (IP) | 5/hour | Free |
| Free API Key | 100/day | Free |
| Pro API Key | 1,000/day | Contact us |

## 🔑 API Key Management

### Generate Key
```
POST /api-keys/generate
```

**Body:**
```json
{
  "name": "Your Name or Organization",
  "email": "your@email.com",
  "use_case": "Optional description"
}
```

**Response:**
```json
{
  "api_key": "cc_live_...",
  "tier": "free",
  "daily_limit": 100,
  "message": "Save this key securely. It will not be shown again.",
  "usage": "Add header: Authorization: Bearer cc_live_..."
}
```

### Check Usage
```
GET /api-keys/usage
Authorization: Bearer YOUR_API_KEY
```

**Response:**
```json
{
  "tier": "free",
  "requests_today": 42,
  "daily_limit": 100,
  "total_requests": 1337,
  "created_at": "2026-03-26T10:00:00Z"
}
```

## 🎨 Verification Badges

### Get SVG Badge
```
GET /badge/{ipfs_hash}.svg
```

Returns an SVG image with:
- Verdict color (green/yellow/orange/red)
- Verdict emoji and label
- Claim text (truncated to 60 chars)
- "Verified by CrawlConda" footer

**Example:**
```html
<img src="https://factchecker-production-3945.up.railway.app/badge/QmXxx.svg" 
     alt="Verified by CrawlConda" />
```

### Get Embed Codes
```
GET /badge/{ipfs_hash}/embed
```

**Response:**
```json
{
  "ipfs_hash": "QmXxx...",
  "verdict": "CONFIRMED",
  "claim": "Iran struck Qatar gas facilities",
  "badge_url": "https://.../badge/QmXxx.svg",
  "embed": {
    "html": "<a href=\"...\"><img src=\"...\" /></a>",
    "markdown": "[![Verified](...)](...)",
    "url": "https://fact-checker-teal.vercel.app/#/v/QmXxx"
  }
}
```

## 🔗 Shareable Claim Pages

### Get Claim Page with OG Tags
```
GET /claim/{ipfs_hash}
```

Returns an HTML page with:
- Open Graph meta tags for Facebook/LinkedIn
- Twitter Card meta tags
- Auto-redirect to main app
- SEO-friendly content

**Use case:** Share on social media with rich previews

**Example:**
```
https://factchecker-production-3945.up.railway.app/claim/QmXxx
```

When shared on Twitter/Facebook, displays:
- Verdict badge as preview image
- Claim as title
- Summary as description
- Vote counts

## 📡 Core API Endpoints

### Verify Claim
```
GET /verify?claim=YOUR_CLAIM
Authorization: Bearer YOUR_API_KEY (optional)
```

**Response:**
```json
{
  "claim": "Iran struck Qatar gas facilities",
  "verdict": "CONFIRMED",
  "emoji": "✅",
  "summary": "Multiple sources confirm...",
  "sources": [
    {
      "title": "Iran Attacks Qatar LNG Facility",
      "url": "https://...",
      "source": "BBC"
    }
  ],
  "ipfs_hash": "QmXxx...",
  "ipfs_url": "https://gateway.pinata.cloud/ipfs/QmXxx...",
  "timestamp": "2026-03-26T10:30:00Z",
  "human_upvotes": 42,
  "human_downvotes": 3
}
```

### Get Verdict
```
GET /verdict/{ipfs_hash}
```

### List Verdicts
```
GET /verdicts?limit=50
```

### Trending Verdicts
```
GET /trending
```

Returns top 5 most-voted verdicts in last 24 hours.

### Cast Vote
```
POST /confirm/{ipfs_hash}
```

**Body:**
```json
{
  "vote": "up",  // or "down"
  "user_id": "your_unique_id"
}
```

## 🛡️ Authentication

### No API Key
- Rate limit: 5 requests/hour per IP
- Use for testing or low-volume apps

### With API Key
- Rate limit: 100 requests/day (free) or 1,000/day (pro)
- Add header: `Authorization: Bearer cc_live_...`
- Higher priority in queue

## 🎯 Use Cases

### 1. News Website Integration
```javascript
// Verify claims in articles
const response = await fetch(
  `https://factchecker-production-3945.up.railway.app/verify?claim=${claim}`,
  { headers: { 'Authorization': 'Bearer cc_live_...' } }
);
const verdict = await response.json();

// Embed badge
document.getElementById('badge').innerHTML = `
  <a href="${verdict.ipfs_url}">
    <img src="https://factchecker-production-3945.up.railway.app/badge/${verdict.ipfs_hash}.svg" />
  </a>
`;
```

### 2. Social Media Bot
```python
import requests

def verify_claim(claim):
    response = requests.get(
        'https://factchecker-production-3945.up.railway.app/verify',
        params={'claim': claim},
        headers={'Authorization': 'Bearer cc_live_...'}
    )
    return response.json()

# Use in Twitter/Discord bot
verdict = verify_claim("Iran struck Qatar")
print(f"{verdict['emoji']} {verdict['verdict']}: {verdict['summary']}")
```

### 3. Browser Extension
```javascript
// Check selected text
chrome.contextMenus.create({
  title: "Verify with CrawlConda",
  contexts: ["selection"],
  onclick: async (info) => {
    const claim = info.selectionText;
    const verdict = await verifyClaim(claim);
    showNotification(verdict);
  }
});
```

### 4. Embed in Blog Posts
```markdown
This claim has been verified:

[![Verified by CrawlConda](https://factchecker-production-3945.up.railway.app/badge/QmXxx.svg)](https://fact-checker-teal.vercel.app/#/v/QmXxx)
```

## 🔒 Security

- API keys are hashed (SHA256) before storage
- Keys are only shown once during generation
- Rate limiting prevents abuse
- CORS enabled for web apps
- HTTPS only in production

## 📈 Monitoring

### Check Your Usage
```bash
curl https://factchecker-production-3945.up.railway.app/api-keys/usage \
  -H "Authorization: Bearer cc_live_..."
```

### Health Check
```bash
curl https://factchecker-production-3945.up.railway.app/health
```

## 🆘 Error Handling

```javascript
try {
  const res = await fetch(url, { headers });
  
  if (res.status === 429) {
    console.error('Rate limit exceeded');
    // Wait or upgrade to Pro
  } else if (res.status === 401) {
    console.error('Invalid API key');
    // Regenerate key
  } else if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  
  const data = await res.json();
  return data;
} catch (error) {
  console.error('API error:', error);
}
```

## 📚 Full Documentation

Interactive docs with live key generation:
**https://fact-checker-teal.vercel.app/api-docs.html**

## 💬 Support

- **Discord:** [discord.gg/jvzaKkvJM2](https://discord.gg/jvzaKkvJM2)
- **GitHub:** [github.com/dipanshu-dixit/FactChecker](https://github.com/dipanshu-dixit/FactChecker)
- **Web:** [fact-checker-teal.vercel.app](https://fact-checker-teal.vercel.app)

## 🚀 Upgrade to Pro

Want 1,000 requests/day? Contact us on Discord or open a GitHub issue.

## 📝 License

Open source under MIT License. Self-host your own instance if needed.
