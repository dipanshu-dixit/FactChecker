# Bug Fix: Progress Tracker Crash & Discord Webhook Errors

## Issues Fixed

### 1. Frontend Progress Tracker Crash (AbortError)
**Problem**: After completing all 6 progress steps, the verification would crash with:
```
AbortError: signal is aborted without reason
```

**Root Cause**: The code was calling `res.json()` inside a `setTimeout`, but the Response object can only be consumed once. The second call to `.json()` failed because the response body was already read.

**Fix**: 
```javascript
// BEFORE (broken):
setTimeout(() => {
  const data = res.json();  // Returns a Promise
  data.then(d => {
    result.innerHTML = renderVerdictCard(d, true);
  });
}, 500);

// AFTER (fixed):
const data = await res.json();  // Consume response immediately
progress.forEach(p => p.done = true);
updateProgress();

setTimeout(() => {
  result.innerHTML = renderVerdictCard(data, true);  // Use already-parsed data
}, 500);
```

### 2. Discord Webhook 400 Bad Request
**Problem**: Every verification triggered a Discord webhook that returned `400 Bad Request`, causing errors in Railway logs.

**Root Causes**:
1. **Empty URLs**: `ipfs_url` or `web_url` fields were sometimes empty, causing Discord to reject the embed
2. **Field length violations**: Source list could exceed Discord's 1024-character limit per field
3. **Invalid timestamps**: Timestamp format wasn't properly validated before sending

**Fixes**:
```python
# 1. Validate URLs before sending
ipfs_url = payload.get("ipfs_url", "").strip()
web_url = payload.get("web_url", "").strip()
if not ipfs_url or not web_url:
    print(f"[WEBHOOK] Skipped - missing URLs")
    return

# 2. Truncate sources to Discord's limit
source_lines = "\n".join(
    f"{i+1}. [{s['title'][:60]}]({s['url']})"
    for i, s in enumerate(sources[:3])
    if s.get('title') and s.get('url')
)[:1020]  # Discord limit is 1024 chars

# 3. Validate timestamp format
try:
    dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
    embed["timestamp"] = dt.isoformat().replace("+00:00", "Z")
except (ValueError, AttributeError):
    pass  # Skip invalid timestamp
```

### 3. Missing Vote Counts in API Response
**Problem**: The `/verify` endpoint wasn't returning vote counts, causing frontend to show `0/0` votes initially.

**Fix**: Added vote count lookup before returning payload:
```python
votes = votes_col.get(where={"ipfs_hash": ipfs_hash})
payload["human_upvotes"] = sum(1 for v in votes["metadatas"] if v["vote"] == "up")
payload["human_downvotes"] = sum(1 for v in votes["metadatas"] if v["vote"] == "down")
```

## Testing

### Before Fix:
1. Submit claim → Progress tracker reaches step 6 → **CRASH** with AbortError
2. Result appears briefly then disappears
3. Railway logs show `[WEBHOOK] UNCONFIRMED → 400`

### After Fix:
1. Submit claim → Progress tracker completes smoothly → Result displays correctly
2. Result stays visible and interactive
3. Railway logs show `[WEBHOOK] UNCONFIRMED → 204` (success)

## Files Modified

- **frontend/index.html**: Fixed async/await in `runVerify()` function
- **api.py**: 
  - Enhanced `post_to_discord_webhook()` with validation and truncation
  - Added vote counts to `/verify` endpoint response

## Deployment

Changes deployed to:
- **Frontend**: Vercel (auto-deploy from main branch)
- **Backend**: Railway (auto-deploy from main branch)

Both services should redeploy within 2-3 minutes of the git push.

## Related Issues

This fix resolves the following user-reported issues:
- Progress tracker crashing on step 6
- Results appearing then disappearing
- Discord webhook 400 errors in logs
- Vote counts showing 0/0 on new verdicts
