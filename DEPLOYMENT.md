# CrawlConda Production Deployment Guide

## 🚀 Quick Deploy Checklist

- [ ] Railway: API + Discord Bot
- [ ] Vercel: Frontend
- [ ] Environment Variables Set
- [ ] Webhook URL Configured
- [ ] Test All Features

---

## 📋 Prerequisites

1. **GitHub Account** (for code hosting)
2. **Railway Account** (for API + Bot)
3. **Vercel Account** (for Frontend)
4. **Discord Bot Token**
5. **xAI API Key**
6. **Pinata JWT**

---

## 🔧 Step 1: Prepare Code for Deployment

### Update .gitignore
Ensure `.env` is in `.gitignore`:
```bash
echo ".env" >> .gitignore
echo "crawlconda_data/" >> .gitignore
echo "__pycache__/" >> .gitignore
echo "*.pyc" >> .gitignore
```

### Push to GitHub
```bash
git add .
git commit -m "Production ready deployment"
git push origin main
```

---

## 🚂 Step 2: Deploy to Railway (API + Bot)

### 2.1 Create Railway Project

1. Go to https://railway.app
2. Click **New Project**
3. Select **Deploy from GitHub repo**
4. Choose your `FactChecker` repository
5. Railway will detect `Procfile` and create TWO services automatically:
   - `api` (FastAPI backend)
   - `bot` (Discord bot)

### 2.2 Configure API Service

1. Click on the **api** service
2. Go to **Settings** → **Networking**
3. Click **Generate Domain**
4. Copy the domain (e.g., `crawlconda-api.up.railway.app`)

### 2.3 Add Environment Variables to API Service

Click **Variables** tab and add:

```env
XAI_API_KEY=your_xai_key_here
PINATA_JWT=your_pinata_jwt_here
DISCORD_VERIFIED_WEBHOOK=https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN
WEB_URL=https://your-vercel-app.vercel.app
```

### 2.4 Add Persistent Volume to API Service

1. Go to **Volumes** tab
2. Click **Add Volume**
3. Mount path: `/app/crawlconda_data`
4. This preserves ChromaDB data across deploys

### 2.5 Configure Bot Service

Click on the **bot** service, then **Variables** tab:

```env
XAI_API_KEY=your_xai_key_here
DISCORD_TOKEN=your_discord_bot_token_here
DISCORD_CHANNEL_ID=your_channel_id_here
VERIFIED_CHANNEL_ID=your_verified_channel_id_here
PINATA_JWT=your_pinata_jwt_here
```

### 2.6 Deploy

Railway will auto-deploy both services. Check logs:
- API: Should show "Uvicorn running on..."
- Bot: Should show "✅ CrawlConda bot live as..."

---

## ▲ Step 3: Deploy to Vercel (Frontend)

### 3.1 Create Vercel Project

1. Go to https://vercel.com
2. Click **New Project**
3. Import your GitHub repository
4. **Root Directory**: Set to `frontend`
5. Click **Deploy**

### 3.2 Configure Environment Variable (Optional)

If you want to override the API URL:

1. Go to **Settings** → **Environment Variables**
2. Add:
   ```
   Key: API_URL
   Value: https://crawlconda-api.up.railway.app
   ```

### 3.3 Get Vercel URL

After deployment, copy your Vercel URL (e.g., `crawlconda.vercel.app`)

### 3.4 Update Railway API Service

Go back to Railway API service → Variables:
```env
WEB_URL=https://crawlconda.vercel.app
```

Redeploy the API service.

---

## 🔗 Step 4: Configure Discord Webhook

### 4.1 Create Webhook

1. Go to your Discord server
2. Open `#verified` channel settings
3. **Integrations** → **Webhooks** → **New Webhook**
4. Name: `CrawlConda`
5. Copy webhook URL

### 4.2 Add to Railway

Go to Railway API service → Variables:
```env
DISCORD_VERIFIED_WEBHOOK=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
```

---

## 🧪 Step 5: Test Production Deployment

### Test 1: API Health
```bash
curl https://crawlconda-api.up.railway.app/verdicts
```
Should return JSON with verdicts.

### Test 2: Web UI
1. Open `https://crawlconda.vercel.app`
2. Submit a claim
3. Should see verdict with sources
4. Check Discord #verified - should see webhook post

### Test 3: Discord Bot
```
!verify test production deployment
```
Should post verdict embed in Discord.

### Test 4: Real-Time Sync
1. Open web UI in two browser tabs
2. Submit claim in one tab
3. Should appear in other tab instantly (SSE)

### Test 5: Vote Sync
1. Vote on web UI
2. Check Discord embed - count should update
3. React in Discord
4. Check web UI - count should update

---

## 🔒 Step 6: Security Checklist

- [ ] `.env` file is in `.gitignore`
- [ ] No API keys in code
- [ ] Railway environment variables set
- [ ] Discord webhook URL is secret
- [ ] Vercel deployment is public (frontend only)
- [ ] Railway services are private (API + Bot)

---

## 📊 Step 7: Monitor Deployment

### Railway Logs

**API Service:**
```
[API] Calling webhook for claim: ...
[WEBHOOK] Response status: 204
```

**Bot Service:**
```
✅ CrawlConda bot live as CrawlConda#1234
[REQUEST] 'test claim' from user#1234 in #general
[SEARCHER] Expanding query with LLM
[DONE] IPFS: QmXxx...
```

### Vercel Logs

Check **Deployments** tab for:
- Build logs
- Function logs (if using serverless)
- Analytics

---

## 🐛 Troubleshooting

### API Returns 500
- Check Railway API logs
- Verify all environment variables are set
- Check ChromaDB volume is mounted

### Bot Not Responding
- Check Railway bot logs
- Verify `DISCORD_TOKEN` is correct
- Check bot has permissions in Discord server
- Ensure `Message Content Intent` is enabled

### Frontend Shows "API Error"
- Check API URL in browser console
- Verify Railway API domain is correct
- Check CORS is enabled (already in code)

### Webhook Not Posting
- Verify `DISCORD_VERIFIED_WEBHOOK` is set
- Check webhook URL is valid
- Check Railway API logs for "[WEBHOOK] Failed"

### Vote Counts Not Syncing
- Check SSE connection (green dot on "The Record")
- Verify both API and Bot are running
- Check browser console for errors

---

## 🔄 Step 8: Update Deployment

### Update Code
```bash
git add .
git commit -m "Update feature X"
git push origin main
```

Railway and Vercel will auto-deploy.

### Update Environment Variables

Railway:
1. Go to service → Variables
2. Update value
3. Service will auto-restart

Vercel:
1. Settings → Environment Variables
2. Update value
3. Redeploy from Deployments tab

---

## 📈 Step 9: Scale (Optional)

### Railway Scaling

1. Go to service → Settings
2. **Resources**:
   - API: 2GB RAM, 2 vCPU (recommended)
   - Bot: 1GB RAM, 1 vCPU (sufficient)

### Vercel Scaling

Vercel auto-scales. No configuration needed.

### Database Scaling

ChromaDB volume on Railway:
- Default: 1GB
- Increase if needed: Settings → Volumes → Resize

---

## 💰 Cost Estimate

### Railway (API + Bot)
- **Hobby Plan**: $5/month (500 hours)
- **Pro Plan**: $20/month (unlimited)
- Recommended: Pro Plan for production

### Vercel (Frontend)
- **Hobby Plan**: Free (100GB bandwidth)
- **Pro Plan**: $20/month (1TB bandwidth)
- Recommended: Hobby Plan (sufficient)

### xAI API
- ~$0.0004 per verification (4 LLM calls)
- 1000 verifications = ~$0.40
- Recommended: Monitor usage

### Pinata (IPFS)
- **Free Plan**: 1GB storage, 100GB bandwidth
- **Paid Plans**: Start at $20/month
- Recommended: Free Plan initially

**Total Monthly Cost**: ~$5-25 depending on usage

---

## 🎯 Production URLs

After deployment, update these in your documentation:

- **Web UI**: `https://crawlconda.vercel.app`
- **API**: `https://crawlconda-api.up.railway.app`
- **API Docs**: `https://crawlconda-api.up.railway.app/docs`
- **Discord**: Your Discord server invite link

---

## ✅ Post-Deployment Checklist

- [ ] All services deployed and running
- [ ] Environment variables configured
- [ ] Discord webhook working
- [ ] Web → Discord sync working
- [ ] Discord → Web sync working
- [ ] Vote sync working (both directions)
- [ ] Trending page loading
- [ ] Activity bar updating
- [ ] Share links working
- [ ] IPFS links accessible
- [ ] Rate limiting working (test 6 requests)
- [ ] Cache working (test duplicate claim)

---

## 🆘 Support

If you encounter issues:

1. Check Railway logs (API + Bot)
2. Check Vercel deployment logs
3. Check browser console (F12)
4. Check Discord bot permissions
5. Verify all environment variables

---

## 🎉 You're Live!

Your production deployment is complete. Share your web URL and Discord invite link with users!

**Next Steps:**
- Monitor usage and costs
- Collect user feedback
- Add analytics (optional)
- Set up monitoring/alerts (optional)
- Scale as needed

---

**Built with:** FastAPI, Discord.py, LangGraph, ChromaDB, IPFS, SSE, Vercel, Railway
