// Vercel serverless function to proxy POST requests to Railway API
export default async function handler(req, res) {
  const RAILWAY_API = 'https://factchecker-production-3945.up.railway.app';
  
  // Extract path from query
  const { path } = req.query;
  
  if (!path) {
    return res.status(400).json({ error: 'Missing path parameter' });
  }
  
  // Build target URL
  const targetUrl = `${RAILWAY_API}${path.startsWith('/') ? path : '/' + path}`;
  
  try {
    // Forward the request to Railway
    const response = await fetch(targetUrl, {
      method: req.method,
      headers: {
        'Content-Type': 'application/json',
        ...(req.headers.authorization && { 'Authorization': req.headers.authorization })
      },
      ...(req.method !== 'GET' && req.method !== 'HEAD' && { body: JSON.stringify(req.body) })
    });
    
    // Get response data
    const data = await response.json();
    
    // Set CORS headers
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    
    // Return response
    return res.status(response.status).json(data);
  } catch (error) {
    console.error('Proxy error:', error);
    return res.status(500).json({ error: 'Proxy request failed', detail: error.message });
  }
}
