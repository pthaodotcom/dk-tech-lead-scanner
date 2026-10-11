import path from 'node:path';

const extensionPath = path.resolve(process.argv[2] || 'extension/dk-tech-lead-scanner');
const port = Number(process.argv[3] || 9222);
const version = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
if (!version.webSocketDebuggerUrl) throw new Error('Chrome CDP chưa sẵn sàng');

const ws = new WebSocket(version.webSocketDebuggerUrl);
let nextId = 1;
const pending = new Map();
ws.addEventListener('message', ({data}) => {
  const message = JSON.parse(data);
  const task = pending.get(message.id);
  if (!task) return;
  pending.delete(message.id);
  message.error ? task.reject(new Error(JSON.stringify(message.error))) : task.resolve(message.result);
});
await new Promise((resolve, reject) => {
  ws.addEventListener('open', resolve, {once:true});
  ws.addEventListener('error', () => reject(new Error('Không kết nối được CDP')), {once:true});
});
function call(method, params={}) {
  const id = nextId++;
  return new Promise((resolve,reject) => {
    pending.set(id,{resolve,reject});
    ws.send(JSON.stringify({id,method,params}));
  });
}
const before = await call('Extensions.getExtensions');
for (const extension of before.extensions || []) {
  if (extension.name === 'DK-Tech — kiểm tra request Facebook' || extension.name === 'DK-Tech Lead Scanner') {
    await call('Extensions.uninstall', {id:extension.id});
  }
}
const loaded = await call('Extensions.loadUnpacked', {path:extensionPath});
ws.close();
console.log(JSON.stringify({status:'ready',extensionId:loaded.id}));

