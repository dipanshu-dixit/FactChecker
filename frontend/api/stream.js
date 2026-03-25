export const config = {
  runtime: 'edge',
};

export default async function handler(req) {
  const RAILWAY_API = 'https://factchecker-production-3945.up.railway.app';
  
  const { readable, writable } = new TransformStream();
  const writer = writable.getWriter();
  const encoder = new TextEncoder();

  // Start SSE connection to Railway
  fetch(`${RAILWAY_API}/stream`, {
    method: 'GET',
    headers: {
      'Accept': 'text/event-stream',
      'Cache-Control': 'no-cache',
    },
  }).then(async (response) => {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        const chunk = decoder.decode(value, { stream: true });
        await writer.write(encoder.encode(chunk));
      }
    } catch (error) {
      console.error('SSE error:', error);
    } finally {
      writer.close();
    }
  }).catch((error) => {
    console.error('SSE connection error:', error);
    writer.close();
  });

  return new Response(readable, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      'Connection': 'keep-alive',
      'Access-Control-Allow-Origin': '*',
      'X-Accel-Buffering': 'no',
    },
  });
}
