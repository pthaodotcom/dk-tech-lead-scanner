const port = Number(process.argv[2] || 9222);
const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
let reloaded = 0;
for (const target of targets.filter(item => item.type === 'page' && item.url.startsWith('https://www.facebook.com/'))) {
  await new Promise((resolve, reject) => {
    const ws = new WebSocket(target.webSocketDebuggerUrl);
    const timer = setTimeout(() => reject(new Error('Reload timeout')), 10000);
    ws.addEventListener('open', () => ws.send(JSON.stringify({id:1,method:'Page.reload',params:{ignoreCache:false}})));
    ws.addEventListener('message', ({data}) => {
      const message = JSON.parse(data);
      if (message.id !== 1) return;
      clearTimeout(timer);
      ws.close();
      message.error ? reject(new Error(JSON.stringify(message.error))) : resolve();
    });
    ws.addEventListener('error', () => reject(new Error('CDP connection error')), {once:true});
  });
  reloaded += 1;
}
console.log(JSON.stringify({status:'ready',reloaded}));

