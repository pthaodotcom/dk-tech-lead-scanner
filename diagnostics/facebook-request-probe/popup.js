const result = document.getElementById('result');
const actor = document.getElementById('actor');
const comment = document.getElementById('comment');
const confirmBox = document.getElementById('confirm');
const sendButton = document.getElementById('send');
actor.value = localStorage.getItem('expectedPageId') || '61593769810301';
comment.value = localStorage.getItem('testComment') || '';
let approvalToken = null;

async function facebookTabs() {
  return chrome.tabs.query({url: 'https://www.facebook.com/*'});
}

async function activeFacebookTab() {
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  if (!tab?.url?.startsWith('https://www.facebook.com/')) throw new Error('Hãy mở tab www.facebook.com.');
  return tab;
}

async function callProbe(tabId, method, args = []) {
  await chrome.scripting.executeScript({target: {tabId}, world: 'MAIN', files: ['core.js', 'probe.js']});
  const [execution] = await chrome.scripting.executeScript({
    target: {tabId}, world: 'MAIN',
    func: async (methodName, methodArgs) => {
      try {
        const probe = window.__DKTECH_REQUEST_PROBE__;
        if (!probe || probe.version !== '0.2.0') return {status: 'UNAVAILABLE', reason: 'Tiện ích trong tab chưa được cập nhật.'};
        const method = probe[methodName];
        if (typeof method !== 'function') return {status: 'UNAVAILABLE', reason: 'Thao tác không được hỗ trợ.'};
        return await method(...methodArgs);
      } catch (error) {
        return {status: 'ERROR', reason: String(error?.message || error).slice(0, 300)};
      }
    },
    args: [method, args],
  });
  return execution?.result || {status: 'ERROR', reason: 'Chrome không trả kết quả từ tab Facebook.'};
}

async function inspectDom(tabId, expectedPageId) {
  const [execution] = await chrome.scripting.executeScript({
    target: {tabId}, world: 'MAIN',
    func: pageId => {
      const groupId = '1163787441488087';
      const postId = '1802484360951722';
      const existing = 'ib hoặc liên hệ 0342391808 ạ';
      let activePageId = '';
      try { activePageId = String(window.require('CurrentUserInitialData')?.USER_ID || ''); } catch {}
      const normalized = value => String(value || '').replace(/\s+/g, ' ').trim().toLocaleLowerCase('vi');
      const text = normalized(document.body?.innerText);
      const links = [...document.querySelectorAll(`a[href*="comment_id="]`)]
        .map(anchor => anchor.href).filter(href => href.includes(postId));
      return {
        status: 'DOM_REPORT', extensionVersion: '0.2.0', expectedPageId: pageId,
        activePageId,
        targetPostLoaded: new RegExp(`^/groups/${groupId}/(?:posts|permalink)/${postId}/?$`).test(location.pathname),
        commentTextVisible: text.includes(normalized(existing)),
        commentIds: [...new Set(links.map(href => new URL(href).searchParams.get('comment_id')).filter(Boolean))].slice(0, 20),
        probe: window.__DKTECH_REQUEST_PROBE__?.inspect?.() || null,
      };
    },
    args: [expectedPageId],
  });
  return execution?.result || {status: 'ERROR', reason: 'Không đọc được DOM.'};
}

function safeForReport(value, action) {
  if (action === 'scan') {
    const joined = value.joinedGroups || {};
    const posts = value.groupPosts || {};
    return {
      status: value.status, action,
      expectedPageId: value.expectedPageId,
      joinedGroups: {
        status: joined.status, queryName: joined.queryName,
        totalUniqueGroups: joined.totalUniqueGroups, completed: joined.completed, pages: joined.pages,
      },
      groupPosts: {
        status: posts.status, queryName: posts.queryName,
        groupsRequested: posts.groupsRequested, groupsProcessed: posts.groupsProcessed,
        totalStories: posts.totalStories, newStories: posts.newStories,
        returnedPosts: posts.returnedPosts, truncatedPosts: posts.truncatedPosts,
        historySize: posts.historySize,
        groupResults: (posts.groupResults || []).map(group => ({
          groupId: group.groupId, completed: group.completed,
          storyCount: group.storyCount, pageCount: (group.pages || []).length,
          failed: (group.pages || []).some(page => page.status === 'FAIL' || page.httpStatus >= 400 || page.graphQLErrors),
        })),
        compatibility: posts.compatibility,
      },
    };
  }
  const copy = JSON.parse(JSON.stringify(value));
  delete copy.approvalToken;
  if (copy.probe?.lastScan) delete copy.probe.lastScan;
  return copy;
}

async function saveReport(report, action, expectedPageId) {
  const payload = {...safeForReport(report, action), reportedAt: new Date().toISOString(), action, expectedPageId};
  try {
    const response = await fetch('http://127.0.0.1:9340/report', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
    });
    return response.ok;
  } catch { return false; }
}

async function scanAll(expectedPageId) {
  const tabs = await facebookTabs();
  const states = [];
  for (const tab of tabs) states.push({tab, state: await callProbe(tab.id, 'inspect')});
  const joinedTab = states.find(item => item.state.captured?.some(record => record.kind === 'joined_groups'));
  const feedTab = states.find(item => item.state.captured?.some(record => record.kind === 'group_posts'));
  if (!joinedTab || !feedTab) {
    return {status: 'UNAVAILABLE', expectedPageId,
      reason: 'Cần một tab Nhóm của bạn đã phát sinh query danh sách và một tab group đã phát sinh query feed.',
      availableTabs: states.map(item => ({url: item.tab.url, captured: item.state.captured || []}))};
  }
  result.textContent = 'Đang lấy toàn bộ danh sách group…';
  const joinedGroups = await callProbe(joinedTab.tab.id, 'scanJoinedGroups', [expectedPageId, {maxPages: 20, delayMs: 250}]);
  if (joinedGroups.status !== 'PASS') return {status: joinedGroups.status, expectedPageId, joinedGroups};
  result.textContent = `Đã lấy ${joinedGroups.totalUniqueGroups} group. Đang quét bài…`;
  const maxGroups = Number(document.getElementById('maxGroups').value) || 91;
  const maxPagesPerGroup = Number(document.getElementById('maxPages').value) || 3;
  const groupPosts = await callProbe(feedTab.tab.id, 'scanGroupPosts', [expectedPageId, joinedGroups.groups,
    {maxGroups, maxPagesPerGroup, delayMs: 350}]);
  return {status: groupPosts.status, expectedPageId, joinedGroups, groupPosts};
}

async function execute(action) {
  const buttons = [...document.querySelectorAll('button')];
  buttons.forEach(button => { if (button !== sendButton || action !== 'send') button.disabled = true; });
  sendButton.disabled = true;
  try {
    const expectedPageId = actor.value.trim();
    localStorage.setItem('expectedPageId', expectedPageId);
    let report;
    if (action === 'scan') {
      report = await scanAll(expectedPageId);
    } else {
      const tab = await activeFacebookTab();
      if (action === 'inspect') {
        await callProbe(tab.id, 'inspect');
        report = await inspectDom(tab.id, expectedPageId);
      } else if (action === 'run') {
        report = await callProbe(tab.id, 'run', [expectedPageId]);
      } else if (action === 'prepare') {
        const message = comment.value.trim();
        localStorage.setItem('testComment', message);
        report = await callProbe(tab.id, 'prepareComment', [expectedPageId, message]);
        approvalToken = report.status === 'READY' ? report.approvalToken : null;
        sendButton.disabled = !(approvalToken && confirmBox.checked);
      } else if (action === 'send') {
        if (!approvalToken || !confirmBox.checked) throw new Error('Cần kiểm tra và xác nhận comment trước khi gửi.');
        report = await callProbe(tab.id, 'sendComment', [expectedPageId, comment.value.trim(), approvalToken]);
        approvalToken = null;
      }
    }
    const display = safeForReport(report, action);
    result.textContent = JSON.stringify(display, null, 2);
    const saved = await saveReport(report, action, expectedPageId);
    result.textContent += saved ? '\n\nĐã lưu báo cáo cục bộ.' : '\n\nChưa lưu tự động; kết quả vẫn hiển thị ở trên.';
  } catch (error) {
    result.textContent = String(error?.message || error);
  } finally {
    buttons.forEach(button => { if (button !== sendButton) button.disabled = false; });
    if (action !== 'prepare' || !approvalToken || !confirmBox.checked) sendButton.disabled = true;
  }
}

confirmBox.addEventListener('change', () => { sendButton.disabled = !(approvalToken && confirmBox.checked); });
comment.addEventListener('input', () => { approvalToken = null; sendButton.disabled = true; });
document.getElementById('inspect').addEventListener('click', () => execute('inspect'));
document.getElementById('run').addEventListener('click', () => execute('run'));
document.getElementById('scan').addEventListener('click', () => execute('scan'));
document.getElementById('prepare').addEventListener('click', () => execute('prepare'));
sendButton.addEventListener('click', () => execute('send'));
