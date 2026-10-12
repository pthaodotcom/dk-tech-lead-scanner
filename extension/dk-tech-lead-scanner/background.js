const API = 'http://127.0.0.1:9350';
const EXTENSION_VERSION = '0.6.7';
const PAGE_ID = '61593769810301';
const DENIED_POST = '1802484360951722';
const ALARM = 'dktech-auto-comment';
const STATE_KEY = 'autoCommentState';
const SCAN_ALARM = 'dktech-periodic-scan';
const SCAN_STATE_KEY = 'backgroundScanState';
const SCAN_CHUNK_SIZE = 5;
let processing = false;
let scanning = false;
let creatingWindow = null;

async function checkBackendVersion() {
  try {
    const info = await local('/api/version');
    console.log(`[VERSION] extension=${EXTENSION_VERSION} backend=${info?.version} service=${info?.service}`);
    if (info?.version && info.version !== EXTENSION_VERSION) {
      console.warn(`[VERSION] Cảnh báo lệch version: extension=${EXTENSION_VERSION}, backend=${info.version}`);
    }
    return info;
  } catch (error) {
    console.warn(`[VERSION] Không kiểm tra được version backend: ${error?.message || error}`);
    return null;
  }
}

async function taskWindow() {
  if (creatingWindow) return creatingWindow;
  creatingWindow = (async () => {
    const {taskWindowId} = await chrome.storage.local.get('taskWindowId');
    if (taskWindowId) {
      try { return await chrome.windows.get(taskWindowId); } catch {}
    }
    const window = await chrome.windows.create({url: 'about:blank', type: 'normal', state: 'minimized', focused: false});
    await chrome.storage.local.set({taskWindowId: window.id});
    return window;
  })();
  try { return await creatingWindow; } finally { creatingWindow = null; }
}

async function createTaskTab() {
  const window = await taskWindow();
  return chrome.tabs.create({windowId: window.id, url: 'about:blank', active: false});
}

const defaultState = () => ({
  enabled: false, continuousOptIn: false, delayMinutes: 10, tabId: null,
  status: 'idle', currentPostId: null, sent: 0, lastResult: null, updatedAt: new Date().toISOString(),
});

async function state() {
  const stored = (await chrome.storage.local.get(STATE_KEY))[STATE_KEY];
  const next = {...defaultState(), ...(stored || {})};
  delete next.batchSize;
  delete next.remaining;
  if (next.status === 'waiting_next_batch') next.status = 'waiting';
  return next;
}

async function updateState(patch) {
  const next = {...await state(), ...patch, updatedAt: new Date().toISOString()};
  await chrome.storage.local.set({[STATE_KEY]: next});
  return next;
}

const defaultScanState = () => ({
  enabled: false, intervalMinutes: 10, maxPagesPerGroup: 3, offset: 0, tabId: null,
  status: 'idle', reason: null, scannedGroups: 0, totalGroups: 0,
  failedGroups: 0, truncatedGroups: 0, lastRunAt: null, updatedAt: new Date().toISOString(),
});

async function scanState() {
  const stored = (await chrome.storage.local.get(SCAN_STATE_KEY))[SCAN_STATE_KEY];
  return {...defaultScanState(), ...(stored || {})};
}

async function updateScanState(patch) {
  const next = {...await scanState(), ...patch, updatedAt: new Date().toISOString()};
  await chrome.storage.local.set({[SCAN_STATE_KEY]: next});
  return next;
}

async function local(path, options = {}) {
  const response = await fetch(`${API}${path}`, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || `Local API ${response.status}`);
  return value;
}

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function callProbe(tabId, method, args = []) {
  await chrome.scripting.executeScript({target: {tabId}, world: 'MAIN', files: ['core.js', 'ui-driver.js', 'probe.js']});
  const [execution] = await chrome.scripting.executeScript({
    target: {tabId}, world: 'MAIN',
    func: async (methodName, methodArgs) => {
      try {
        const probe = window.__DKTECH_REQUEST_PROBE__;
        if (probe && probe.version !== '0.6.7') return {status: 'BLOCKED', reason: 'Hãy tải lại tab Facebook để dùng bản 0.6.7.'};
        if (!probe || typeof probe[methodName] !== 'function') return {status: 'UNAVAILABLE', reason: 'Probe chưa cập nhật.'};
        if (typeof probe[methodName] !== 'function') return {status: 'UNAVAILABLE', reason: 'Không hỗ trợ thao tác.'};
        return await probe[methodName](...methodArgs);
      } catch (error) {
        return {status: 'ERROR', reason: String(error?.message || error).slice(0, 300)};
      }
    }, args: [method, args],
  });
  return execution?.result || {status: 'ERROR', reason: 'Chrome không trả kết quả.'};
}

async function waitForLoad(tabId, expectedUrl) {
  const tab = await chrome.tabs.update(tabId, {url: expectedUrl, active: false});
  if (tab.status === 'complete' && tab.url === expectedUrl) return;
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      reject(new Error('Bài Facebook tải quá 45 giây.'));
    }, 45000);
    function listener(changedId, changeInfo, changedTab) {
      if (changedId !== tabId || changeInfo.status !== 'complete') return;
      clearTimeout(timeout);
      chrome.tabs.onUpdated.removeListener(listener);
      changedTab.url?.startsWith('https://www.facebook.com/')
        ? resolve() : reject(new Error('Facebook chuyển sang trang không hợp lệ.'));
    }
    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function workerTab(current) {
  if (current.tabId) {
    try { return await chrome.tabs.get(current.tabId); } catch {}
  }
  const tab = await createTaskTab();
  await updateState({tabId: tab.id});
  return tab;
}

async function scanFeedTab(groups, current) {
  const tabs = await chrome.tabs.query({url: 'https://www.facebook.com/*'});
  const commentState = await state();
  for (const tab of tabs) {
    if (tab.id === commentState.tabId) continue;
    try {
      const inspected = await callProbe(tab.id, 'inspect');
      if (inspected.activePageId === PAGE_ID &&
          inspected.captured?.some(record => record.kind === 'group_posts')) return tab;
    } catch {}
  }
  let tab = null;
  if (current.tabId) {
    try { tab = await chrome.tabs.get(current.tabId); } catch {}
  }
  if (!tab) tab = await createTaskTab();
  await updateScanState({tabId: tab.id});
  let sawPageActor = false;
  const queryNames = new Set();
  const failures = [];
  for (const group of groups.slice(0, 3)) {
    try {
      try {
        const tabInfo = await chrome.tabs.get(tab.id);
        if (tabInfo?.windowId) {
          await chrome.tabs.update(tab.id, {active: true});
          await chrome.windows.update(tabInfo.windowId, {state: 'normal', focused: false, width: 1200, height: 900});
        }
      } catch {}
      await waitForLoad(tab.id, `https://www.facebook.com/groups/${group.id}/`);
      for (let attempt = 0; attempt < 3; attempt += 1) {
        await sleep(1500);
        const inspected = await callProbe(tab.id, 'inspect');
        sawPageActor ||= inspected.activePageId === PAGE_ID;
        (inspected.observedGroupQueryNames || []).forEach(name => queryNames.add(name));
        if (inspected.activePageId === PAGE_ID &&
            inspected.captured?.some(record => record.kind === 'group_posts')) {
          try {
            const tabInfo = await chrome.tabs.get(tab.id);
            if (tabInfo?.windowId) await chrome.windows.update(tabInfo.windowId, {state: 'minimized', focused: false});
          } catch {}
          return tab;
        }
        await chrome.scripting.executeScript({
          target: {tabId: tab.id}, world: 'MAIN',
          func: async () => {
            const root = document.scrollingElement || document.documentElement;
            const scrollables = [root, ...document.querySelectorAll('main *, [role="main"] *')]
              .filter((element, index, all) => all.indexOf(element) === index &&
                element.scrollHeight - element.clientHeight > 300 &&
                (element === root || /auto|scroll/.test(getComputedStyle(element).overflowY)))
              .slice(0, 6);
            for (const element of scrollables) {
              element.scrollTop = element.scrollHeight;
              element.dispatchEvent(new Event('scroll', {bubbles: true}));
            }
            window.scrollTo(0, root.scrollHeight);
            window.dispatchEvent(new Event('scroll', {bubbles: true}));
            window.dispatchEvent(new WheelEvent('wheel', {deltaY: 1200, bubbles: true}));
          },
        });
      }
    } catch (error) {
      failures.push(String(error?.message || error).slice(0, 100));
    }
  }
  try {
    const tabInfo = await chrome.tabs.get(tab.id);
    if (tabInfo?.windowId) await chrome.windows.update(tabInfo.windowId, {state: 'minimized', focused: false});
  } catch {}
  if (!sawPageActor) {
    throw new Error(`Tab nền không dùng Page DK-Tech nên chưa thể quét bài${failures.length ? `; lỗi tải: ${failures[0]}` : ''}.`);
  }
  const observed = [...queryNames].slice(0, 3).join(', ');
  throw new Error(`Tab nền chưa bắt được request feed sau khi tự thử 3 group${observed ? `; query thấy: ${observed}` : ''}${failures.length ? `; lỗi tải: ${failures[0]}` : ''}.`);
}

async function scheduleScan(delayMinutes) {
  await chrome.alarms.create(SCAN_ALARM, {delayInMinutes: Math.max(0.5, delayMinutes)});
}

async function processScanBatch() {
  if (scanning) return;
  scanning = true;
  try {
    const current = await scanState();
    if (!current.enabled) return;
    await updateScanState({status: 'scanning', reason: null});
    // Leave a wake-up alarm in case Chrome stops this service worker mid-batch.
    await scheduleScan(6);
    const {groups} = await local('/api/scan-groups');
    if (!groups?.length) {
      await updateScanState({status: 'no_groups', totalGroups: 0, reason: 'Chưa có group đã lưu; cần quét danh sách group lần đầu.'});
      await scheduleScan(current.intervalMinutes);
      return;
    }
    const offset = current.offset >= groups.length ? 0 : current.offset;
    const batch = groups.slice(offset, offset + SCAN_CHUNK_SIZE);
    const tab = await scanFeedTab(groups, current);
    const result = await callProbe(tab.id, 'scanGroupPosts', [PAGE_ID, batch,
      {maxGroups: SCAN_CHUNK_SIZE, maxPagesPerGroup: current.maxPagesPerGroup, delayMs: 350}]);
    if (!['PASS', 'PARTIAL'].includes(result.status)) {
      throw new Error(result.reason || `Quét bài: ${result.status}`);
    }
    await local('/api/scan-ingest', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({status: result.status, actingPageId: PAGE_ID,
        groups: batch, posts: result.posts, compatibility: result.compatibility,
        completedGroups: result.completedGroups, truncatedGroups: result.truncatedGroups,
        failedGroups: result.failedGroups}),
    });
    const auto = await state();
    if (auto.enabled && auto.continuousOptIn) void processOne();
    const nextOffset = offset + batch.length;
    const complete = nextOffset >= groups.length;
    const failedGroups = (offset ? current.failedGroups : 0) + (result.failedGroups || 0);
    const truncatedGroups = (offset ? current.truncatedGroups : 0) + (result.truncatedGroups || 0);
    const next = await updateScanState({
      status: complete ? (failedGroups || truncatedGroups ? 'cycle_partial' : 'cycle_complete') : 'waiting_next_batch',
      offset: complete ? 0 : nextOffset,
      scannedGroups: complete ? groups.length : nextOffset,
      totalGroups: groups.length,
      failedGroups, truncatedGroups,
      lastRunAt: new Date().toISOString(), reason: null,
    });
    if (next.enabled) await scheduleScan(complete ? next.intervalMinutes : 0.5);
  } catch (error) {
    const next = await updateScanState({status: 'error', reason: String(error?.message || error).slice(0, 300)});
    if (next.enabled) await scheduleScan(next.intervalMinutes);
  } finally {
    scanning = false;
  }
}

async function startBackgroundScan(message) {
  const intervalMinutes = Math.max(10, Math.min(Number(message.intervalMinutes) || 10, 180));
  const maxPagesPerGroup = Math.max(1, Math.min(Number(message.maxPagesPerGroup) || 3, 20));
  await chrome.alarms.clear(SCAN_ALARM);
  const next = await updateScanState({enabled: true, intervalMinutes, maxPagesPerGroup, offset: 0,
    scannedGroups: 0, failedGroups: 0, truncatedGroups: 0, status: 'starting', reason: null});
  void processScanBatch();
  return next;
}

async function stopBackgroundScan() {
  await chrome.alarms.clear(SCAN_ALARM);
  return updateScanState({enabled: false, status: 'stopped_by_user', reason: null});
}

async function finishQueue(item, report) {
  await local('/api/comments/result', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      queueId: item.id, status: report.status, commentId: report.commentId,
      submitted: Boolean(report.submitted), moderation: report.moderation, attemptedOnce: report.attemptedOnce,
      error: report.error || report.reason,
    }),
  });
}

async function releaseQueue(item, diagnostics = null) {
  return local('/api/comments/release', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({queueId: item.id, diagnostics}),
  });
}

async function processOne() {
  if (processing) return;
  processing = true;
  let continueAfterSkip = false;
  let item = null;
  let sendStarted = false;
  let sendReport = null;
  let debuggerTarget = null;
  let debuggerAttached = false;
  try {
    let current = await state();
    if (!current.enabled || !current.continuousOptIn) return;
    if (current.inFlightQueueId) {
      await updateState({enabled: false, status: 'stopped', lastResult: {status: 'INCONCLUSIVE',
        reason: 'Lượt trước bị ngắt khi gửi. Bài đã được khóa; hãy kiểm tra lịch sử.'}});
      return;
    }
    await chrome.alarms.create(ALARM, {delayInMinutes: 6});
    await updateState({status: 'selecting_and_writing', currentPostId: null, lastResult: null});
    const reserved = await local('/api/comments/auto-next', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}',
    });
    item = reserved.item;
    if (!item) {
      if (reserved.waitReason) {
        const next = await updateState({status: 'waiting_limit', lastResult: {reason: reserved.waitReason}});
        if (next.enabled) await chrome.alarms.create(ALARM, {delayInMinutes: Math.max(0.5, reserved.retrySeconds / 60)});
        return;
      }
      const next = await updateState({status: 'waiting_posts', currentPostId: null});
      if (next.enabled) await chrome.alarms.create(ALARM, {delayInMinutes: next.delayMinutes});
      return;
    }
    console.log(`[COMMENT][JOB_RECEIVED] job_id=${item.id} post_id=${item.post_id}`);
    if (!(await state()).enabled) {
      await releaseQueue(item);
      return;
    }
    if (item.post_id === DENIED_POST) throw new Error('Bài denylist bị chặn tại extension.');
    console.log(`[COMMENT][POST_OPENING] post_id=${item.post_id} url=${item.url}`);
    await updateState({status: 'opening_post', currentPostId: item.post_id});
    current = await state();
    const tab = await workerTab(current);
    await waitForLoad(tab.id, item.url);
    console.log(`[COMMENT][POST_OPENED] post_id=${item.post_id}`);
    await sleep(2500);
    console.log(`[COMMENT][ACTOR_CHECK]`);
    let prepared = null;
    let minimizedDiag = null;
    let normalDiag = null;
    let beforeScrollDiag = null;
    let afterScrollDiag = null;

    // TEST 1: Ensure window is MINIMIZED explicitly (Requirement 4)
    try {
      const tabInfo = await chrome.tabs.get(tab.id);
      if (tabInfo?.windowId) {
        await chrome.windows.update(tabInfo.windowId, {state: 'minimized', focused: false});
        await sleep(1500);
      }
    } catch {}
    const minimizedPrepared = await callProbe(tab.id, 'prepareComment', [PAGE_ID, item.message, {
      groupId: item.group_id, postId: item.post_id, pageId: PAGE_ID,
    }]);
    minimizedDiag = minimizedPrepared?.diagnostics || null;
    beforeScrollDiag = minimizedDiag;
    console.log('[COMPOSER_PROBE][MINIMIZED]', JSON.stringify(minimizedDiag));

    // ACTOR check result log (Requirement 1)
    const actorPassed = minimizedPrepared?.activePageId === PAGE_ID ||
      (minimizedPrepared?.status === 'READY' && !minimizedPrepared?.activePageId);
    if (actorPassed) {
      console.log(`[COMMENT][ACTOR_OK] actor=${minimizedPrepared?.activePageId || PAGE_ID}`);
    } else {
      console.error(`[COMMENT][FAILED] stage=ACTOR_CHECK reason=${minimizedPrepared?.reason || 'Actor không khớp'}`);
      if (minimizedPrepared?.status === 'PAUSED_FACEBOOK') {
        const report = {...(minimizedPrepared || {}), status: 'PAUSED_FACEBOOK', diagnostics: minimizedDiag};
        await releaseQueue(item, report);
        await updateState({enabled: false, status: 'paused_facebook', currentPostId: null, lastResult: report});
        await stopBackgroundScan();
        return;
      }
    }

    console.log(`[COMMENT][COMPOSER_SEARCH] looking for post composer post_id=${item.post_id}`);

    // TEST D (Requirement 3): Find target post container by postId and scrollIntoView
    if (minimizedPrepared?.status !== 'READY') {
      try {
        const scrollResult = await chrome.scripting.executeScript({
          target: {tabId: tab.id}, world: 'MAIN',
          args: [item.post_id],
          func: (postId) => {
            const driver = window.__DKTECH_UI_DRIVER__;
            const container = driver?.findTargetPostContainer ? driver.findTargetPostContainer(postId) : null;
            if (container) {
              const dialog = container.closest('[role="dialog"]') || document.querySelector('[role="dialog"]');
              const scrollables = dialog ? [...dialog.querySelectorAll('*')].filter(el => {
                const s = getComputedStyle(el);
                return (s.overflowY === 'auto' || s.overflowY === 'scroll') && el.scrollHeight > el.clientHeight;
              }) : [];
              for (const el of scrollables) {
                el.scrollTop = el.scrollHeight;
              }
              const existingEditor = (dialog || container).querySelector('[contenteditable="true"]');
              let clickedBtn = false;
              if (!existingEditor) {
                const commentBtn = container.querySelector('[role="button"][aria-label*="Bình luận" i], [role="button"][aria-label*="Comment" i]') ||
                  (dialog || document).querySelector('[role="button"][aria-label*="Bình luận về bài viết" i], [role="button"][aria-label*="Comment on" i]');
                if (commentBtn) {
                  commentBtn.click();
                  clickedBtn = true;
                }
              }
              const commentArea = existingEditor || container.querySelector('[contenteditable="true"]') || container;
              commentArea.scrollIntoView({behavior: 'instant', block: 'end'});
              return {found: true, tag: container.tagName, scrollablesCount: scrollables.length, clickedBtn};
            }
            return {found: false};
          },
        });
        const targetPostFound = Boolean(scrollResult?.[0]?.result?.found);
        console.log(`[COMPOSER_PROBE] targetPostFound=${targetPostFound} targetPostId=${item.post_id} clickedBtn=${scrollResult?.[0]?.result?.clickedBtn}`);
        await sleep(1500);
        const scrolledPrepared = await callProbe(tab.id, 'prepareComment', [PAGE_ID, item.message, {
          groupId: item.group_id, postId: item.post_id, pageId: PAGE_ID,
        }]);
        afterScrollDiag = scrolledPrepared?.diagnostics || null;
        console.log('[COMPOSER_PROBE][AFTER_SCROLL]', JSON.stringify(afterScrollDiag));
      } catch (err) {
        console.warn(`[COMPOSER_PROBE] Scroll error:`, err?.message);
      }
    }

    // TEST 2: Maximize the task window so Facebook mounts the full composer layout.
    let normalPrepared = null;
    try {
      const tabInfo = await chrome.tabs.get(tab.id);
      if (tabInfo?.windowId) {
        await chrome.tabs.update(tab.id, {active: true});
        await chrome.windows.update(tabInfo.windowId, {state: 'maximized', focused: true});
        await sleep(2500);
        normalPrepared = await callProbe(tab.id, 'prepareComment', [PAGE_ID, item.message, {
          groupId: item.group_id, postId: item.post_id, pageId: PAGE_ID,
        }]);
        normalDiag = normalPrepared?.diagnostics || null;
        console.log('[COMPOSER_PROBE][NORMAL_WINDOW]', JSON.stringify(normalDiag));
      }
    } catch (err) {
      console.warn(`[COMPOSER_PROBE] Window normal error:`, err?.message);
    }

    // Build comparison report
    const comparison = {
      MINIMIZED: {
        documentVisibilityState: minimizedDiag?.window?.visibilityState || 'unknown',
        contenteditableCount: minimizedDiag?.counts?.totalContentEditable || 0,
        textboxCount: minimizedDiag?.counts?.totalWithRoleTextbox || 0,
        composerCandidateCount: minimizedDiag?.counts?.composerCandidateCount || 0,
        targetComposer: Boolean(minimizedPrepared?.status === 'READY'),
        rectCount: minimizedDiag?.counts?.activeEditorRectCount || 0,
      },
      NORMAL: {
        documentVisibilityState: normalDiag?.window?.visibilityState || 'unknown',
        contenteditableCount: normalDiag?.counts?.totalContentEditable || 0,
        textboxCount: normalDiag?.counts?.totalWithRoleTextbox || 0,
        composerCandidateCount: normalDiag?.counts?.composerCandidateCount || 0,
        targetComposer: Boolean(normalPrepared?.status === 'READY'),
        rectCount: normalDiag?.counts?.activeEditorRectCount || 0,
      },
      beforeScrollCandidates: beforeScrollDiag?.counts?.totalContentEditable || 0,
      afterScrollCandidates: afterScrollDiag?.counts?.totalContentEditable || 0,
    };

    console.log(`[COMPOSER_PROBE_COMPARISON]
MINIMIZED
document.visibilityState=${comparison.MINIMIZED.documentVisibilityState}
contenteditableCount=${comparison.MINIMIZED.contenteditableCount}
textboxCount=${comparison.MINIMIZED.textboxCount}
composerCandidateCount=${comparison.MINIMIZED.composerCandidateCount}
targetComposer=${comparison.MINIMIZED.targetComposer}
rectCount=${comparison.MINIMIZED.rectCount}

NORMAL
document.visibilityState=${comparison.NORMAL.documentVisibilityState}
contenteditableCount=${comparison.NORMAL.contenteditableCount}
textboxCount=${comparison.NORMAL.textboxCount}
composerCandidateCount=${comparison.NORMAL.composerCandidateCount}
targetComposer=${comparison.NORMAL.targetComposer}
rectCount=${comparison.NORMAL.rectCount}`);

    // Pick best prepared result
    prepared = (normalPrepared?.status === 'READY') ? normalPrepared
      : (minimizedPrepared?.status === 'READY') ? minimizedPrepared
      : normalPrepared || minimizedPrepared;

    // Additional retry loop if needed
    if (prepared?.status !== 'READY') {
      for (let attempt = 0; attempt < 5; attempt += 1) {
        await sleep(2000);
        prepared = await callProbe(tab.id, 'prepareComment', [PAGE_ID, item.message, {
          groupId: item.group_id, postId: item.post_id, pageId: PAGE_ID,
        }]);
        if (prepared.status === 'READY') break;
        if (['BLOCKED', 'ERROR', 'PAUSED_FACEBOOK', 'SKIPPED_COMMENT_DISABLED'].includes(prepared.status)) break;
      }
    }

    if (prepared?.status !== 'READY') {
      console.error(`[COMMENT][FAILED] stage=COMPOSER_SEARCH status=${prepared?.status} reason=${prepared?.reason}`);
      const chosenDiag = normalDiag || minimizedDiag;
      const fullDiag = {
        comparison,
        minimizedDiag,
        normalDiag,
        beforeScrollDiag,
        afterScrollDiag,
        scopeDetails: chosenDiag?.scopeDetails || null,
        candidatesFormatted: (chosenDiag?.candidates || []).map(c => c.formatted),
        candidatesSummary: (chosenDiag?.candidates || []).map(c => c.summary),
      };
      const report = {...(prepared || {}), status: prepared?.status || 'INCONCLUSIVE',
        reason: prepared?.reason || `Không thể chuẩn bị comment cho bài ${item.post_id}`,
        diagnostics: fullDiag};
      if (report.status === 'SKIPPED_COMMENT_DISABLED') {
        await finishQueue(item, report);
        const next = await updateState({status: 'skipped_comment_disabled', currentPostId: null, lastResult: report});
        continueAfterSkip = Boolean(next.enabled);
        return;
      }
      if (report.alreadyAttempted || report.duplicateVisible) await finishQueue(item, report);
      else await releaseQueue(item, fullDiag);
      await updateState({enabled: false, status: prepared?.status === 'PAUSED_FACEBOOK' ? 'paused_facebook' : 'stopped',
        currentPostId: null, lastResult: report});
      if (prepared?.status === 'PAUSED_FACEBOOK') await stopBackgroundScan();
      return;
    }

    console.log(`[COMMENT][COMPOSER_FOUND] composer found for post_id=${item.post_id}`);
    if (!(await state()).enabled) {
      await releaseQueue(item);
      return;
    }
    await updateState({status: 'sending'});
    if (!(await state()).enabled) {
      await releaseQueue(item);
      return;
    }
    const focused = await callProbe(tab.id, 'focusComment', [PAGE_ID, item.message, prepared.approvalToken]);
    if (focused?.status !== 'READY_FOR_BROWSER_INPUT') {
      const report = {...(focused || {}), status: focused?.status || 'ERROR',
        reason: focused?.reason || 'Không focus được composer để Chrome nhập nội dung.'};
      await releaseQueue(item, report);
      await updateState({enabled: false, status: 'stopped', currentPostId: null, lastResult: report});
      return;
    }
    debuggerTarget = {tabId: tab.id};
    await chrome.debugger.attach(debuggerTarget, '1.3');
    debuggerAttached = true;
    await chrome.debugger.sendCommand(debuggerTarget, 'Input.insertText', {text: item.message});
    await sleep(250);
    const confirmed = await callProbe(tab.id, 'confirmCommentText', [item.message, prepared.approvalToken]);
    if (confirmed?.status !== 'READY_TO_SUBMIT') {
      await chrome.debugger.sendCommand(debuggerTarget, 'Input.dispatchKeyEvent', {
        type: 'keyDown', key: 'a', code: 'KeyA', modifiers: 2, windowsVirtualKeyCode: 65,
      });
      await chrome.debugger.sendCommand(debuggerTarget, 'Input.dispatchKeyEvent', {
        type: 'keyUp', key: 'a', code: 'KeyA', modifiers: 2, windowsVirtualKeyCode: 65,
      });
      await chrome.debugger.sendCommand(debuggerTarget, 'Input.dispatchKeyEvent', {
        type: 'keyDown', key: 'Backspace', code: 'Backspace', windowsVirtualKeyCode: 8,
      });
      await chrome.debugger.sendCommand(debuggerTarget, 'Input.dispatchKeyEvent', {
        type: 'keyUp', key: 'Backspace', code: 'Backspace', windowsVirtualKeyCode: 8,
      });
      await chrome.debugger.detach(debuggerTarget);
      debuggerAttached = false;
      const report = {...(confirmed || {}), status: confirmed?.status || 'BLOCKED',
        reason: confirmed?.reason || 'Chrome chưa nhập đúng nội dung; chưa nhấn Enter.'};
      await releaseQueue(item, report);
      await updateState({enabled: false, status: 'stopped', currentPostId: null, lastResult: report});
      return;
    }
    // Persist an attempt only after the browser has inserted and verified the full text.
    await local('/api/comments/attempt', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({queueId: item.id})});
    console.log(`[COMMENT][ATTEMPT_RECORDED] queueId=${item.id} status=ok`);
    await updateState({status: 'sending', inFlightQueueId: item.id});
    sendStarted = true;
    console.log(`[COMMENT][COMPOSER_FILLED] browser input verified for post_id=${item.post_id}`);
    const armed = await callProbe(tab.id, 'armCommentSubmission', [item.message, prepared.approvalToken]);
    if (armed?.status !== 'ARMED') throw new Error(armed?.reason || 'Không thể khóa lượt gửi trước khi nhấn Enter.');
    await chrome.debugger.sendCommand(debuggerTarget, 'Input.dispatchKeyEvent', {
      type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13,
    });
    await chrome.debugger.sendCommand(debuggerTarget, 'Input.dispatchKeyEvent', {
      type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13,
    });
    await chrome.debugger.detach(debuggerTarget);
    debuggerAttached = false;
    console.log(`[COMMENT][SUBMIT_TRIGGERED] transport=chrome_debugger post_id=${item.post_id}`);
    const report = await callProbe(tab.id, 'verifyCommentSubmission', [item.message, prepared.approvalToken]);
    sendReport = report;
    // Requirement 2: Only log SUBMIT_TRIGGERED and VERIFYING if submitted === true
    const isSubmitted = report.submitted === true || Boolean(report.status === 'PASS' && report.commentId);
    if (isSubmitted) {
      console.log(`[COMMENT][SUBMIT_TRIGGERED] report_status=${report.status}`);
      console.log(`[COMMENT][VERIFYING] checking DOM for published comment...`);
    } else {
      console.error(`[COMMENT][FAILED] stage=SUBMIT status=${report.status} reason=${report.reason || report.error}`);
    }
    await finishQueue(item, report);
    await updateState({inFlightQueueId: null});
    const passed = report.commentId && String(report.status).startsWith('PASS');
    if (passed) {
      console.log(`[COMMENT][COMMENT_FOUND] comment_id=${report.commentId} moderation=${report.moderation}`);
      console.log(`[COMMENT][SUCCESS] post_id=${item.post_id} comment_id=${report.commentId}`);
    } else {
      console.warn(`[COMMENT][FAILED] stage=${report.submitted ? 'VERIFYING' : 'SEND'} status=${report.status} reason=${report.reason || report.error}`);
    }
    current = await state();
    if (!passed) {
      await updateState({enabled: false,
        status: report.submitted ? 'paused_moderation' : report.status === 'PAUSED_FACEBOOK' ? 'paused_facebook' : 'stopped',
        sent: current.sent + (report.submitted ? 1 : 0), lastResult: report});
      if (report.status === 'PAUSED_FACEBOOK') await stopBackgroundScan();
      return;
    }
    if (current.runOnce) {
      await chrome.alarms.clear(ALARM);
      await updateState({enabled: false, sent: current.sent + 1,
        status: 'test_complete', currentPostId: null, lastResult: report});
      return;
    }
    const next = await updateState({
      sent: current.sent + 1,
      status: current.enabled ? 'waiting' : 'stopped_by_user',
      currentPostId: null, lastResult: report,
    });
    if (next.enabled) await chrome.alarms.create(ALARM, {delayInMinutes: next.delayMinutes});
    else await updateState({status: 'stopped_by_user'});
  } catch (error) {
    console.error(`[COMMENT][FAILED] stage=DISPATCH error=${String(error?.message || error)}`);
    const report = {status: 'ERROR', reason: String(error?.message || error).slice(0, 300)};
    if (item && !sendReport) {
      try { if (sendStarted) await finishQueue(item, report); else await releaseQueue(item); } catch {}
    }
    await updateState({enabled: false, status: 'stopped', lastResult: sendReport
      ? {...sendReport, persistenceError: report.reason} : report});
  } finally {
    if (debuggerAttached && debuggerTarget) {
      try { await chrome.debugger.detach(debuggerTarget); } catch {}
    }
    processing = false;
    if (continueAfterSkip) void processOne();
  }
}

async function startAutomation(message) {
  await checkBackendVersion();
  const delayMinutes = Math.max(2, Math.min(Number(message.delayMinutes) || 10, 60));
  await chrome.alarms.clear(ALARM);
  const next = await updateState({
    enabled: true, continuousOptIn: true, delayMinutes, status: 'starting',
    currentPostId: null, sent: 0, lastResult: null, inFlightQueueId: null, driverVersion: '0.6.7',
    runOnce: Boolean(message.runOnce),
  });
  void processOne();
  return next;
}

async function stopAutomation() {
  await chrome.alarms.clear(ALARM);
  const current = await updateState({enabled: false, status: 'stopped_by_user'});
  if (current.tabId) {
    try {
      await chrome.scripting.executeScript({target: {tabId: current.tabId}, world: 'MAIN',
        func: () => window.__DKTECH_UI_DRIVER__?.cancel()});
    } catch {}
  }
  return current;
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const task = message?.type === 'auto-start' ? startAutomation(message)
    : message?.type === 'auto-stop' ? stopAutomation()
      : message?.type === 'auto-status' ? state()
        : message?.type === 'scan-start' ? startBackgroundScan(message)
          : message?.type === 'scan-stop' ? stopBackgroundScan()
            : message?.type === 'scan-status' ? scanState() : null;
  if (!task) return false;
  task.then(value => sendResponse({ok: true, state: value}))
    .catch(error => sendResponse({ok: false, error: String(error?.message || error)}));
  return true;
});

chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === ALARM) void processOne();
  if (alarm.name === SCAN_ALARM) void processScanBatch();
});

chrome.runtime.onInstalled.addListener(async () => {
  const stored = (await chrome.storage.local.get(STATE_KEY))[STATE_KEY];
  if (!stored) await chrome.storage.local.set({[STATE_KEY]: defaultState()});
  else if (stored.enabled && (!stored.continuousOptIn || stored.driverVersion !== '0.6.7')) {
    await updateState({enabled: false, status: 'needs_restart'});
    await chrome.alarms.clear(ALARM);
  } else if (stored.enabled) await chrome.alarms.create(ALARM, {delayInMinutes: 0.5});
  const scanStored = (await chrome.storage.local.get(SCAN_STATE_KEY))[SCAN_STATE_KEY];
  if (!scanStored) await chrome.storage.local.set({[SCAN_STATE_KEY]: defaultScanState()});
  else if (scanStored.enabled) await scheduleScan(0.5);
});

chrome.runtime.onStartup.addListener(async () => {
  const current = await state();
  if (current.inFlightQueueId) {
    await updateState({enabled: false, status: 'stopped', lastResult: {
      status: 'INCONCLUSIVE', reason: 'Chrome đóng trong khi gửi. Cần kiểm tra lịch sử trước khi bật lại.'}});
    return;
  }
  if (current.enabled && current.continuousOptIn) {
    await chrome.alarms.create(ALARM, {delayInMinutes: Math.max(2, current.delayMinutes)});
  }
  const savedScan = await scanState();
  if (savedScan.enabled) await scheduleScan(0.5);
});

async function checkPendingTrigger() {
  if (processing) return;
  try {
    const res = await local('/api/comments/trigger-check');
    if (res?.trigger) {
      console.log('[TRIGGER] Received test trigger from backend, starting test job...');
      void startAutomation({runOnce: true, limit: 1});
    }
  } catch {}
}
if (typeof setInterval !== 'undefined') {
  setInterval(checkPendingTrigger, 2000);
}
