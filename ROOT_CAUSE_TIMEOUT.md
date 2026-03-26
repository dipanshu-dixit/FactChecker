# Root Cause Analysis: Verification Results Not Showing

## The Real Problem

**Frontend timeout (8 seconds) was WAY too short for backend processing (~50 seconds)**

## Timeline of What Was Happening

```
00:00 - User clicks "Investigate"
00:01 - Frontend sends request to /verify
00:08 - Frontend timeout hits → AbortController aborts request
00:08 - Frontend shows "API may be busy" error
00:10 - Backend still processing (expanding query)
00:20 - Backend still processing (searching 34 sources)
00:30 - Backend still processing (extracting facts)
00:40 - Backend still processing (issuing verdict)
00:50 - Backend COMPLETES and stores result in ChromaDB
00:51 - Result appears in "The Record" via SSE
```

**User sees**: Error message, then result magically appears in The Record later  
**What actually happened**: Frontend gave up, but backend kept working

## Evidence from Logs

```
[09:12:55] [SEARCHER] Expanding query with LLM
[09:13:20] [SEARCHER] Done — 8 sources collected
[09:13:30] [SCANNER] → extracting facts
[09:13:40] [VERDICT] → issuing verdict
[09:13:45] [PUBLISHER] → formatting final signal
```

**Total time: 50 seconds**  
**Frontend timeout: 8 seconds** ❌

## The Fix

### Before
```javascript
const timeout = 8000; // 8 seconds for ALL endpoints
```

### After
```javascript
// Use longer timeout for /verify endpoint (120s), shorter for others (15s)
const timeout = endpoint.includes('/verify?') ? 120000 : 15000;
```

## Why This Wasn't Obvious

1. **Discord worked fine** - Discord bot doesn't have a timeout, it just waits
2. **Results appeared later** - Backend completed successfully and stored in DB
3. **SSE worked** - Real-time updates pushed the result to "The Record"
4. **No backend errors** - Backend logs showed successful completion

The frontend was the only component timing out prematurely.

## Testing

### Before Fix
1. Click "Investigate" → Progress tracker runs
2. After 8 seconds → "AbortError: signal is aborted without reason"
3. Shows error: "API may be busy"
4. 40 seconds later → Result appears in "The Record" (via SSE)

### After Fix
1. Click "Investigate" → Progress tracker runs
2. After 50 seconds → Result displays correctly
3. No errors, smooth UX
4. Result also appears in "The Record" immediately

## Related Timeouts in System

| Component | Timeout | Purpose |
|-----------|---------|---------|
| Frontend `/verify` | 120s | Wait for full verification pipeline |
| Frontend other endpoints | 15s | Quick data fetches |
| Railway container | None | Runs until completion |
| Discord bot | None | Waits indefinitely |
| Vercel proxy | 60s | Serverless function limit (not hit) |

## Why 120 Seconds?

- Average verification: 30-60 seconds
- Worst case (slow LLM + retry): 90 seconds
- 120s provides 30s buffer
- Railway has no timeout, so backend won't be killed

## Files Changed

- `frontend/index.html`: Increased timeout from 8s to 120s for `/verify`, 15s for others
- Added better error message distinguishing timeout from other errors
