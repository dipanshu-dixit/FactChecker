// Vercel serverless function - NO timeout limit
export const config = {
  maxDuration: 300, // 5 minutes
};

export default async function handler(req, res) {
  const RAILWAY_API = 'https://factchecker-production-3945.up.railway.app';
  
  const path = req.query.path || '';
  const url = `${RAILWAY_API}${path}`;
  
  try {
    const response = await fetch(url, {
      method: req.method,
      headers: {
        'Content-Type': 'application/json',
        ...(req.headers.authorization && { 'Authorization': req.headers.authorization }),
      },
      body: req.method !== 'GET' && req.method !== 'HEAD' ? JSON.stringify(req.body) : undefined,
    });
    
    const contentType = response.headers.get('content-type') || 'application/json';
    
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
    res.setHeader('Content-Type', contentType);
    
    if (contentType.includes('application/json')) {
      const data = await response.json();
      res.status(response.status).json(data);
    } else {
      const data = await response.text();
      res.status(response.status).send(data);
    }
  } catch (error) {
    console.error('Proxy error:', error);
    res.status(500).json({ error: 'Proxy error', message: error.message });
  }
}
