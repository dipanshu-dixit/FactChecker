# Environment Variables Reference

## 🔑 Required Variables

### Railway API Service
```env
XAI_API_KEY=xai-xxx                                    # xAI Grok API key
PINATA_JWT=eyJxxx                                      # Pinata IPFS JWT token
DISCORD_VERIFIED_WEBHOOK=https://discord.com/api/...   # Discord webhook URL
WEB_URL=https://crawlconda.vercel.app                  # Your Vercel frontend URL
```

### Railway Bot Service
```env
XAI_API_KEY=xai-xxx                                    # xAI Grok API key (same as API)
DISCORD_TOKEN=MTxxx                                    # Discord bot token
DISCORD_CHANNEL_ID=1234567890                          # Main Discord channel ID
VERIFIED_CHANNEL_ID=1234567890                         # #verified channel ID
PINATA_JWT=eyJxxx                                      # Pinata JWT (same as API)
```

### Vercel Frontend (Optional)
```env
API_URL=https://crawlconda-api.up.railway.app          # Override API URL (optional)
```

---

## 📝 How to Get Each Variable

### XAI_API_KEY
1. Go to https://console.x.ai
2. Create API key
3. Copy the key (starts with `xai-`)

### DISCORD_TOKEN
1. Go to https://discord.com/developers/applications
2. Select your application
3. Bot → Reset Token → Copy

### DISCORD_CHANNEL_ID & VERIFIED_CHANNEL_ID
1. Enable Developer Mode in Discord (Settings → Advanced)
2. Right-click channel → Copy Channel ID

### PINATA_JWT
1. Go to https://app.pinata.cloud
2. API Keys → New Key → Admin
3. Copy the JWT token

### DISCORD_VERIFIED_WEBHOOK
1. Discord channel settings
2. Integrations → Webhooks → New Webhook
3. Copy webhook URL

### WEB_URL
Your Vercel deployment URL (e.g., `https://crawlconda.vercel.app`)

---

## ⚠️ Security Notes

- Never commit `.env` to Git
- Keep API keys secret
- Rotate keys if exposed
- Use Railway's secret variables (not visible in logs)
- Don't share webhook URLs publicly

---

## 🔄 Local Development

Create `.env` in project root:
```env
XAI_API_KEY=xai-xxx
DISCORD_TOKEN=MTxxx
DISCORD_CHANNEL_ID=1234567890
VERIFIED_CHANNEL_ID=1234567890
PINATA_JWT=eyJxxx
DISCORD_VERIFIED_WEBHOOK=https://discord.com/api/webhooks/xxx/yyy
WEB_URL=http://localhost:3000
```

---

## ✅ Validation

Test if variables are loaded:

**API:**
```bash
curl https://your-api.up.railway.app/verdicts
```

**Bot:**
Check Railway logs for:
```
✅ CrawlConda bot live as YourBot#1234
```

**Webhook:**
Submit a claim on web, check Discord #verified channel.
