const API = 'http://127.0.0.1:9350';
const PAGE_ID = '61593769810301';
const resultNode = document.getElementById('result');
let autoPoll = null;
let scanPoll = null;

function show(value) { resultNode.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2); }

async function local(path, options={}) {
  const response = await fetch(`${API}${path}`, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || `Local API ${response.status}`);
  return value;
}

async function facebookTabs() { return chrome.tabs.query({url:'https://www.facebook.com/*'}); }
async function callProbe(tabId, method, args=[]) {
  await chrome.scripting.executeScript({target:{tabId},world:'MAIN',files:['core.js','ui-driver.js','probe.js']});
  const [execution] = await chrome.scripting.executeScript({
    target:{tabId},world:'MAIN',
    func:async (methodName,methodArgs) => {
      try {
        const probe=window.__DKTECH_REQUEST_PROBE__;
        if (probe && probe.version !== '0.6.7') return {status: 'BLOCKED', reason: 'Hãy tải lại tab Facebook để dùng bản 0.6.7.'};
        if (!probe || typeof probe[methodName]!=='function') return {status:'UNAVAILABLE',reason:'Probe chưa cập nhật.'};
        if (typeof probe[methodName]!=='function') return {status:'UNAVAILABLE',reason:'Không hỗ trợ thao tác.'};
        return await probe[methodName](...methodArgs);
      } catch(error) { return {status:'ERROR',reason:String(error?.message||error).slice(0,300)}; }
    }, args:[method,args],
  });
  return execution?.result || {status:'ERROR',reason:'Chrome không trả kết quả.'};
}

async function scanAndSync() {
  await local('/health');
  const tabs=await facebookTabs();
  const states=[];
  for (const tab of tabs) states.push({tab,state:await callProbe(tab.id,'inspect')});
  const joined=states.find(item=>item.state.captured?.some(record=>record.kind==='joined_groups'));
  const feed=states.find(item=>item.state.captured?.some(record=>record.kind==='group_posts'));
  if (!joined || !feed) throw new Error('Cần tab “Nhóm của bạn” và một tab group đã tải feed.');
  show('Đang lấy danh sách group…');
  const joinedResult=await callProbe(joined.tab.id,'scanJoinedGroups',[PAGE_ID,{maxPages:20,delayMs:250}]);
  if (joinedResult.status!=='PASS') throw new Error(joinedResult.reason||`Danh sách group: ${joinedResult.status}`);
  
  let groupsToScan = joinedResult.groups;
  try {
    const {groups: allowed} = await local('/api/scan-groups');
    if (Array.isArray(allowed) && allowed.length > 0) {
      const allowedSet = new Set(allowed.map(g => g.id));
      groupsToScan = joinedResult.groups.filter(g => allowedSet.has(g.id));
    }
  } catch {}

  show(`Đã thấy ${joinedResult.totalUniqueGroups} group (lọc ${groupsToScan.length} group theo cấu hình). Đang quét bài trong 24h…`);
  const maxGroups=Number(document.getElementById('maxGroups').value)||91;
  const maxPagesPerGroup=Number(document.getElementById('maxPages').value)||3;
  const postsResult=await callProbe(feed.tab.id,'scanGroupPosts',[PAGE_ID,groupsToScan,
    {maxGroups,maxPagesPerGroup,delayMs:350}]);
  if (!['PASS','PARTIAL','INCONCLUSIVE'].includes(postsResult.status)) throw new Error(postsResult.reason||postsResult.status);
  const saved=await local('/api/scan-ingest',{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      status:postsResult.status,actingPageId:PAGE_ID,groups:joinedResult.groups,posts:postsResult.posts,
      compatibility:postsResult.compatibility,completedGroups:postsResult.completedGroups,
      truncatedGroups:postsResult.truncatedGroups,failedGroups:postsResult.failedGroups,
    }),
  });
  return {status:postsResult.status,joinedGroups:joinedResult.totalUniqueGroups,
    scannedStories:postsResult.totalStories,newInChrome:postsResult.newStories,
    completedGroups:postsResult.completedGroups,truncatedGroups:postsResult.truncatedGroups,
    failedGroups:postsResult.failedGroups,...saved};
}

function autoMessage(message) {
  return new Promise((resolve, reject) => chrome.runtime.sendMessage(message, response => {
    if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
    if (!response?.ok) return reject(new Error(response?.error || 'Không đọc được trạng thái tự động.'));
    resolve(response.state);
  }));
}

async function scanMessage(message) {
  return autoMessage(message);
}

function renderScan(state) {
  const labels = {
    idle: 'Chưa bật', starting: 'Đang bắt đầu', scanning: 'Đang quét bài trong tab nền',
    waiting_next_batch: 'Đang chờ quét nhóm tiếp theo', cycle_complete: 'Đã quét xong một vòng',
    cycle_partial: 'Đã quét xong một vòng, còn group chưa hoàn tất',
    no_groups: 'Chưa có danh sách group', error: 'Quét ngầm gặp lỗi', stopped_by_user: 'Đã dừng',
  };
  document.getElementById('scanStatus').textContent =
    `${labels[state.status] || state.status} · ${state.scannedGroups || 0}/${state.totalGroups || 0} group` +
    (state.failedGroups ? ` · lỗi ${state.failedGroups}` : '') +
    (state.truncatedGroups
      ? ` · ${state.truncatedGroups} group còn trang sau giới hạn ${state.maxPagesPerGroup || 3} trang/group` : '') +
    (state.reason ? ` · ${state.reason}` : '');
  document.getElementById('scanStart').disabled = Boolean(state.enabled && state.status !== 'error');
  document.getElementById('scanStop').disabled = !state.enabled;
}

async function refreshScan() {
  renderScan(await scanMessage({type: 'scan-status'}));
  try {
    const {groups} = await local('/api/scan-groups');
    const el = document.getElementById('popupGroupCount');
    if (el && Array.isArray(groups)) el.textContent = groups.length;
  } catch {}
}

async function startScan() {
  renderScan(await scanMessage({type: 'scan-start',
    intervalMinutes: Number(document.getElementById('scanInterval').value),
    maxPagesPerGroup: Number(document.getElementById('maxPages').value)}));
}

async function stopScan() {
  renderScan(await scanMessage({type: 'scan-stop'}));
}

function renderAuto(state) {
  const labels = {
    paused_facebook: 'Tạm dừng: kiểm tra Facebook', paused_moderation: 'Đã gửi; cần kiểm tra xét duyệt/hiển thị',
    test_complete: 'Đã gửi thử 1 comment, đã dừng',
    idle: 'Chưa chạy', starting: 'Đang khởi động', selecting_and_writing: 'Đang chọn bài và Qwen viết comment',
    waiting_posts: 'Đang chờ bài phù hợp rule',
    opening_post: 'Đang mở bài trong tab nền', sending: 'Đang gửi comment', waiting: 'Đang nghỉ trước comment tiếp theo',
    stopped: 'Đã tự dừng do lỗi/kết quả chưa rõ',
    stopped_by_user: 'Đã dừng theo yêu cầu', needs_restart: 'Cần bật gửi ngầm riêng ở bản mới',
  };
  const detail = state.currentPostId ? ` · bài ${state.currentPostId}` : '';
  const result = state.lastResult?.persistenceError || state.lastResult?.reason ||
    state.lastResult?.error || state.lastResult?.status || '';
  const missing = state.lastResult?.missingRelayProviders?.slice(0, 3).join(', ') || '';
  document.getElementById('autoStatus').textContent =
    `${labels[state.status] || state.status}${detail} · đã gửi ${state.sent}` +
    (result ? ` · ${result}` : '') + (missing ? ` · ${missing}` : '');
  document.getElementById('autoStart').disabled = Boolean(state.enabled && state.continuousOptIn);
  document.getElementById('autoTest').disabled = Boolean(state.enabled);
  document.getElementById('autoStop').disabled = !state.enabled;
  document.getElementById('autoClearPending').disabled = Boolean(state.enabled);
}

async function refreshAuto() {
  renderAuto(await autoMessage({type: 'auto-status'}));
}

async function saveAutoSettings() {
  const value = await local('/api/automation-settings', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      hourlyLimit: Number(document.getElementById('autoHourlyLimit').value),
      dailyLimit: Number(document.getElementById('autoDailyLimit').value),
    }),
  });
  document.getElementById('autoHourlyLimit').value = value.hourlyLimit;
  document.getElementById('autoDailyLimit').value = value.dailyLimit;
  return `Đã lưu giới hạn ${value.hourlyLimit} comment/giờ, ${value.dailyLimit} comment/ngày.`;
}

async function loadAutoSettings() {
  const value = await local('/api/automation-settings');
  document.getElementById('autoHourlyLimit').max = value.maximumHourlyLimit;
  document.getElementById('autoHourlyLimit').value = value.hourlyLimit;
  document.getElementById('autoDailyLimit').value = value.dailyLimit;
}

async function startAuto(runOnce = false) {
  await saveAutoSettings();
  const state = await autoMessage({
    type: 'auto-start', runOnce,
    delayMinutes: Number(document.getElementById('autoDelay').value),
  });
  renderAuto(state);
}

async function stopAuto() {
  renderAuto(await autoMessage({type: 'auto-stop'}));
}

async function clearPendingComments() {
  const current = await autoMessage({type: 'auto-status'});
  if (current.enabled) throw new Error('Hãy dừng gửi ngầm trước khi xóa bài đã quét.');
  if (!confirm('Xóa toàn bộ bài đã quét và lượt quét cũ? Lịch sử comment, danh sách group, rule và bài denylist vẫn được giữ.')) return 'Đã hủy xóa bài đã quét.';
  const value = await local('/api/comments/clear-pending', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
  return `Đã xóa ${value.deletedPosts} bài và ${value.deletedScans} lượt quét; lịch sử comment được giữ.`;
}

async function run(button,task) {
  const buttons=[...document.querySelectorAll('button')];
  buttons.forEach(item=>item.disabled=true);
  try { show(await task()); }
  catch(error) { show({status:'ERROR',reason:String(error?.message||error)}); }
  finally {
    buttons.forEach(item=>item.disabled=false);
    refreshAuto().catch(()=>{});
    refreshScan().catch(()=>{});
  }
}

document.getElementById('scan').addEventListener('click',event=>run(event.target,scanAndSync));
document.getElementById('scanStart').addEventListener('click',event=>run(event.target,startScan));
document.getElementById('scanStop').addEventListener('click',event=>run(event.target,stopScan));
document.getElementById('dashboard').addEventListener('click',()=>chrome.tabs.create({url:`${API}/`}));
document.getElementById('autoStart').addEventListener('click',event=>run(event.target,startAuto));
document.getElementById('autoStop').addEventListener('click',event=>run(event.target,stopAuto));
document.getElementById('autoClearPending').addEventListener('click',event=>run(event.target,clearPendingComments));
document.getElementById('autoSaveLimits').addEventListener('click',event=>run(event.target,saveAutoSettings));
local('/health').then(()=>show('Tool cục bộ đã sẵn sàng.')).catch(()=>show('Hãy chạy start-tool.ps1 trước.'));
loadAutoSettings().catch(error=>show({status:'ERROR',reason:error.message}));
refreshAuto().catch(error=>document.getElementById('autoStatus').textContent=error.message);
refreshScan().catch(error=>document.getElementById('scanStatus').textContent=error.message);
autoPoll=setInterval(()=>refreshAuto().catch(()=>{}),1500);
scanPoll=setInterval(()=>refreshScan().catch(()=>{}),3000);

document.getElementById('backgroundSettings').addEventListener('click', () => chrome.tabs.create({url: 'chrome://settings/system'}));
document.getElementById('autoTest').addEventListener('click', event => run(event.target, () => startAuto(true)));
document.getElementById('openGroupConfig')?.addEventListener('click', (e) => {
  e.preventDefault();
  chrome.tabs.create({url: `${API}/#groupsSection`});
});
