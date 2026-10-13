self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
// Network only: no stale balances and no private API cache. Offline writes are disabled.
self.addEventListener('fetch',event=>{if(event.request.method==='GET')event.respondWith(fetch(event.request));});
