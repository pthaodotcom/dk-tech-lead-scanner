(() => {
  const API_VERSION = '0.6.7';
  // Chrome can inject a newly reloaded extension into a Facebook document that
  // already holds an older probe. That legacy property was non-configurable,
  // so redefining it throws and stops all request observation. Keep the live
  // probe until the Facebook document itself is reloaded.
  if (window.__DKTECH_REQUEST_PROBE__) return;
  const core = window.__DKTECH_PROBE_CORE__;
  if (!core) throw new Error('DK-Tech probe core chưa được nạp.');

  const nativeFetch = window.fetch.bind(window);
  const records = new Map();
  const names = new Set();
  const unknownGroupQueries = new Set();
  const compatibilityWarnings = new Map();
  const target = {groupId: '', postId: '', pageId: '61593769810301', defaultMessage: ''};
  const DENIED_POSTS = new Set(['1802484360951722']);
  const HISTORY_KEY = '__dktech_scan_history_v1';
  let targetFeedback = null;
  let relayProviders = {};
  let running = false;
  let approval = null;
  let lastScan = null;

  function onTargetPost() {
    if (!target.groupId || !target.postId) return false;
    return new RegExp(`^/groups/${target.groupId}/(?:posts|permalink)/${target.postId}/?$`).test(location.pathname);
  }

  function requestParams(body) {
    try {
      if (typeof body === 'string' || body instanceof URLSearchParams) return new URLSearchParams(body);
      if (body instanceof FormData) {
        const params = new URLSearchParams();
        for (const [key, value] of body) {
          if (typeof value !== 'string') return null;
          params.append(key, value);
        }
        return params;
      }
    } catch {}
    return null;
  }

  function currentPageId() {
    try { return String(window.require('CurrentUserInitialData')?.USER_ID || ''); }
    catch { return ''; }
  }

  function requestInfo(url, body, method) {
    try {
      const endpoint = new URL(url, location.href);
      if (endpoint.origin !== 'https://www.facebook.com' || endpoint.pathname !== '/api/graphql/' || method !== 'POST') return null;
      const params = requestParams(body);
      if (!params?.get('doc_id')) return null;
      const name = params.get('fb_api_req_friendly_name') || '';
      const actingId = params.get('av') || '';
      let variables = {};
      try { variables = JSON.parse(params.get('variables') || '{}'); } catch {}
      return {params, name, actingId, variables, kind: core.queryKind(name)};
    } catch { return null; }
  }

  function remember(kind, info, source = 'name') {
    if (!kind || info.actingId !== target.pageId || info.variables?.input) return;
    const key = `${kind}:${info.actingId}`;
    const old = records.get(key);
    const cursor = info.variables?.cursor;
    const record = {kind, name: info.name, actingId: info.actingId,
      body: info.params.toString(), at: new Date().toISOString(), detectedBy: source};
    if (!old || !cursor || (kind === 'joined_groups' && /AllJoinedGroupsSection/i.test(info.name))) records.set(key, record);
  }

  function findTargetFeedbackInValue(value, depth = 0) {
    if (!value || typeof value !== 'object' || depth > 45 || targetFeedback) return;
    if (Array.isArray(value)) {
      value.forEach(item => findTargetFeedbackInValue(item, depth + 1));
      return;
    }
    const isTargetStory = value.__typename === 'Story' &&
      (String(value.post_id || '') === target.postId || String(value.id || '') === target.postId);
    if (isTargetStory) {
      const feedback = value.feedback || value.comet_sections?.feedback?.story?.feedback;
      const id = feedback?.id || feedback?.__ref;
      if (typeof id === 'string' && id.length > 8) targetFeedback = {id, source: 'response', at: Date.now()};
    }
    for (const child of Object.values(value)) findTargetFeedbackInValue(child, depth + 1);
  }

  function findTargetFeedbackFromRelay() {
    if (targetFeedback) return targetFeedback;
    try {
      const source = window.require('CometRelayEnvironment').getStore().getSource().toJSON();
      // Strategy 1: Find Story/CometFeedStory node matching our post_id or id.
      const storyTypes = new Set(['Story', 'CometFeedStory', 'GroupFeedStory', 'FeedStory']);
      for (const value of Object.values(source)) {
        if (!value || typeof value !== 'object') continue;
        if (!storyTypes.has(value.__typename)) continue;
        const pid = String(value.post_id || '');
        const vid = String(value.id || '');
        if (pid !== target.postId && vid !== target.postId) continue;
        // Try multiple paths where Facebook stores the feedback reference.
        const refs = [
          value.feedback?.__ref, value.feedback?.id,
          value.comet_sections?.feedback?.story?.feedback?.__ref,
          value.comet_sections?.feedback?.story?.feedback?.id,
          value.story_ufi_container?.story?.feedback?.__ref,
        ].filter(ref => typeof ref === 'string' && ref.length > 8);
        if (refs.length) {
          targetFeedback = {id: refs[0], source: 'relay_store', at: Date.now()};
          return targetFeedback;
        }
      }
      // Strategy 2: Brute-force scan for any node with a __ref pointing to a Feedback
      // whose parent story references our target post.
      for (const [key, value] of Object.entries(source)) {
        if (!value || typeof value !== 'object') continue;
        // Look for nodes that reference our post_id in any field.
        const json = JSON.stringify(value);
        if (!json.includes(target.postId)) continue;
        // Check if this node or a related node has a feedback ref.
        const feedbackRef = value.feedback?.__ref || value.feedback?.id;
        if (typeof feedbackRef === 'string' && feedbackRef.length > 8) {
          const feedbackNode = source[feedbackRef];
          if (feedbackNode?.__typename === 'Feedback' || feedbackNode?.id === feedbackRef) {
            targetFeedback = {id: feedbackRef, source: 'relay_store_deep', at: Date.now()};
            return targetFeedback;
          }
        }
      }
    } catch {}
    return targetFeedback;
  }

  function observeResponse(text, info) {
    window.__DKTECH_UI_DRIVER__?.observe(info, text);
    if (!info || info.actingId !== target.pageId || !/Query$/.test(info.name)) return;
    names.add(info.name);
    const detected = core.classifyResponse(text, info.name);
    if (detected.kind) {
      remember(detected.kind, info, detected.source);
      if (!info.kind && detected.source === 'structure') {
        unknownGroupQueries.add(info.name);
        compatibilityWarnings.set(`name:${info.name}`, {code: 'QUERY_NAME_CHANGED', queryName: info.name, detectedKind: detected.kind});
      }
      if (info.kind && detected.structuralKind && info.kind !== detected.structuralKind) {
        compatibilityWarnings.set(`shape:${info.name}`, {code: 'QUERY_SHAPE_CHANGED', queryName: info.name,
          expectedKind: info.kind, detectedKind: detected.structuralKind});
      }
    }
    if (onTargetPost()) core.parseDocuments(text).forEach(document => findTargetFeedbackInValue(document));
  }

  function inspectRequest(url, body, method) {
    const info = requestInfo(url, body, method);
    if (!info) return null;
    if (info.actingId === target.pageId) {
      relayProviders = core.mergeRelayProviders(relayProviders, info.variables);
    }
    if (info.name && names.size < 120) names.add(info.name);
    if (info.kind) remember(info.kind, info, 'name');
    return info;
  }

  window.fetch = function(input, init) {
    try {
      const url = input instanceof Request ? input.url : String(input);
      const method = String(init?.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
      if (init?.body == null && input instanceof Request && method === 'POST' && new URL(url).pathname === '/api/graphql/') {
        const promise = nativeFetch(input, init);
        void input.clone().text().then(body => {
          const request = inspectRequest(url, body, method);
          if (request && (request.kind || /Group|Discussion|CreateCommentMutation/i.test(request.name))) {
            void promise.then(response => response.clone().text().then(text => observeResponse(text, request))).catch(() => {});
          }
        }).catch(() => {});
        return promise;
      }
      const info = init?.body != null ? inspectRequest(url, init.body, method) : null;
      const promise = nativeFetch(input, init);
      if (info && (info.kind || /Group|Discussion|CreateCommentMutation/i.test(info.name)) && info.actingId === target.pageId) {
        void promise.then(response => response.clone().text().then(text => observeResponse(text, info))).catch(() => {});
      }
      return promise;
    } catch { return nativeFetch(input, init); }
  };

  const xhrMeta = new WeakMap();
  const nativeOpen = XMLHttpRequest.prototype.open;
  const nativeSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(method, url, ...rest) {
    xhrMeta.set(this, {method: String(method).toUpperCase(), url: String(url)});
    return nativeOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function(body) {
    const meta = xhrMeta.get(this);
    const info = meta ? inspectRequest(meta.url, body, meta.method) : null;
    if (info && (info.kind || /Group|Discussion|CreateCommentMutation/i.test(info.name)) && info.actingId === target.pageId) {
      this.addEventListener('load', () => {
        try {
          const text = (!this.responseType || this.responseType === 'text') ? this.responseText : JSON.stringify(this.response);
          observeResponse(text, info);
        } catch {}
      }, {once: true});
    }
    return nativeSend.call(this, body);
  };

  function publicSummary(summary) {
    return {parsedDocuments: summary.parsedDocuments, graphQLErrors: summary.graphQLErrors,
      itemCount: summary.itemCount,
      sample: summary.items.slice(0, 5).map(item => item.type === 'Story'
        ? {id: item.id, hasText: item.hasText, textLength: item.textLength, occurrences: item.occurrences, type: item.type}
        : item),
      hasNextPage: summary.hasNextPage};
  }

  function inspect() {
    return {status: records.size ? 'CAPTURED_NOT_TESTED' : 'WAITING_FOR_REQUEST', version: API_VERSION,
      activePageId: currentPageId(),
      viewport: {width: window.innerWidth, height: window.innerHeight, visibility: document.visibilityState},
      captured: [...records.values()].map(({kind, name, actingId, at, detectedBy, body}) => {
        const params = new URLSearchParams(body);
        let variableKeys = [];
        try { variableKeys = Object.keys(JSON.parse(params.get('variables') || '{}')).sort(); } catch {}
        return {kind, name, actingId, at, detectedBy, docId: params.get('doc_id'), variableKeys};
      }),
      observedGroupQueryNames: [...names],
      compatibility: {unknownGroupQueryNames: [...unknownGroupQueries], warnings: [...compatibilityWarnings.values()]},
      lastScan, note: 'Request mới chỉ được ghi nhận; PASS cần replay hoặc scan thành công.'};
  }

  function validateActor(expectedPageId) {
    if (expectedPageId !== target.pageId || !/^\d+$/.test(expectedPageId)) return 'ID Page không khớp cấu hình DK-Tech.';
    if (currentPageId() !== expectedPageId) return 'Tab hiện không dùng đúng Page DK-Tech.';
    return null;
  }

  async function fetchRecord(record, variables) {
    const params = new URLSearchParams(record.body);
    params.set('variables', JSON.stringify(variables));
    const started = performance.now();
    const response = await nativeFetch('https://www.facebook.com/api/graphql/', {
      method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: params.toString(), signal: AbortSignal.timeout(30000)});
    return {response, text: await response.text(), elapsedMs: Math.round(performance.now() - started)};
  }

  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

  async function run(expectedPageId) {
    const actorError = validateActor(expectedPageId);
    if (actorError) return {status: 'BLOCKED', reason: actorError};
    if (running) return {status: 'BUSY'};
    running = true;
    const tests = [];
    try {
      for (const kind of ['joined_groups', 'group_posts']) {
        const record = records.get(`${kind}:${expectedPageId}`);
        if (!record) { tests.push({kind, status: 'UNAVAILABLE', reason: 'Chưa ghi nhận query của đúng Page trong tab này.'}); continue; }
        if (Date.now() - Date.parse(record.at) > 30 * 60 * 1000) {
          tests.push({kind, status: 'UNAVAILABLE', reason: 'Request đã cũ. Reload rồi tải thêm dữ liệu.'}); continue;
        }
        try {
          const params = new URLSearchParams(record.body);
          const variables = JSON.parse(params.get('variables') || '{}');
          const result = await fetchRecord(record, variables);
          const summary = core.summarizeResponse(result.text, kind, record.name);
          if (!summary.itemCount && result.response.ok && !summary.graphQLErrors) {
            compatibilityWarnings.set(`empty:${record.name}`, {code: 'RESPONSE_SHAPE_UNRECOGNIZED', queryName: record.name, kind});
          }
          tests.push({kind, queryName: record.name, actingId: record.actingId,
            httpStatus: result.response.status, elapsedMs: result.elapsedMs, ...publicSummary(summary),
            status: !result.response.ok || summary.graphQLErrors ? 'FAIL' : summary.itemCount ? 'PASS' : 'INCONCLUSIVE'});
        } catch { tests.push({kind, status: 'FAIL', reason: 'Lỗi mạng hoặc hết thời gian chờ.'}); }
      }
      return {status: 'REPORT', expectedPageId, tests, compatibility: inspect().compatibility, commentTest: 'NOT_RUN'};
    } finally { running = false; }
  }

  async function scanJoinedGroups(expectedPageId, options = {}) {
    const actorError = validateActor(expectedPageId);
    if (actorError) return {status: 'BLOCKED', reason: actorError};
    const record = records.get(`joined_groups:${expectedPageId}`);
    if (!record) return {status: 'UNAVAILABLE', reason: 'Cần bắt query danh sách nhóm trong tab Nhóm của bạn.'};
    const maxPages = Math.max(1, Math.min(Number(options.maxPages) || 10, 20));
    const delayMs = Math.max(100, Math.min(Number(options.delayMs) || 250, 3000));
    const params = new URLSearchParams(record.body);
    const baseVariables = JSON.parse(params.get('variables') || '{}');
    const groups = new Map();
    const pages = [];
    let cursor = null;
    let completed = false;
    for (let page = 1; page <= maxPages; page += 1) {
      const variables = structuredClone(baseVariables);
      variables.cursor = cursor;
      try {
        const result = await fetchRecord(record, variables);
        const summary = core.summarizeResponse(result.text, 'joined_groups', record.name);
        const before = groups.size;
        summary.items.forEach(item => groups.set(item.id, item));
        pages.push({page, httpStatus: result.response.status, graphQLErrors: summary.graphQLErrors,
          itemCount: summary.itemCount, newItemCount: groups.size - before,
          hasNextPage: summary.hasNextPage, elapsedMs: result.elapsedMs});
        if (!result.response.ok || summary.graphQLErrors) break;
        if (!summary.hasNextPage || !summary.endCursor) { completed = true; break; }
        cursor = summary.endCursor;
        await sleep(delayMs);
      } catch { pages.push({page, status: 'FAIL', reason: 'Lỗi mạng hoặc hết thời gian chờ.'}); break; }
    }
    lastScan = {kind: 'joined_groups', at: new Date().toISOString(), total: groups.size, completed};
    return {status: groups.size ? 'PASS' : 'INCONCLUSIVE', kind: 'joined_groups', queryName: record.name,
      totalUniqueGroups: groups.size, completed, pages, groups: [...groups.values()]};
  }

  function loadHistory() {
    try {
      const parsed = JSON.parse(localStorage.getItem(HISTORY_KEY) || '{}');
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch { return {}; }
  }

  function saveHistory(history) {
    const entries = Object.entries(history)
      .sort((a, b) => String(b[1]?.lastSeenAt || '').localeCompare(String(a[1]?.lastSeenAt || '')))
      .slice(0, 20000);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(Object.fromEntries(entries)));
  }

  function groupSourceId(variables) {
    if (!variables || typeof variables !== 'object') return '';
    const direct = variables.groupID || variables.id || variables.groupId || variables.group_id ||
      variables.targetID || variables.targetId || variables.communityID || variables.communityId ||
      variables.youthIntegrityHostID;
    if (direct && /^\d{5,25}$/.test(String(direct))) return String(direct);

    function search(obj, depth = 0) {
      if (!obj || typeof obj !== 'object' || depth > 5) return '';
      for (const [key, val] of Object.entries(obj)) {
        if (/group.*id|target.*id|community.*id/i.test(key) && /^\d{5,25}$/.test(String(val))) {
          if (String(val) !== target.pageId) return String(val);
        }
        if (typeof val === 'object') {
          const nested = search(val, depth + 1);
          if (nested) return nested;
        }
      }
      return '';
    }
    return search(variables);
  }

  function publishedWithinLast24Hours(publishedAt) {
    const timestamp = Date.parse(String(publishedAt || ''));
    return Number.isFinite(timestamp) && timestamp >= Date.now() - 24 * 60 * 60 * 1000;
  }
  const publishedWithinLastThreeDays = publishedWithinLast24Hours;

  async function scanGroupPosts(expectedPageId, requestedGroups, options = {}) {
    const actorError = validateActor(expectedPageId);
    if (actorError) return {status: 'BLOCKED', reason: actorError};
    const record = records.get(`group_posts:${expectedPageId}`);
    if (!record) return {status: 'UNAVAILABLE', reason: 'Cần bắt query feed trong một tab group.'};
    const params = new URLSearchParams(record.body);
    const baseVariables = JSON.parse(params.get('variables') || '{}');
    const sourceId = groupSourceId(baseVariables);
    if (!sourceId) return {status: 'INCONCLUSIVE', reason: 'Không tìm thấy biến group ID trong query feed.'};
    const maxGroups = Math.max(1, Math.min(Number(options.maxGroups) || 100, 200));
    const maxPagesPerGroup = Math.max(1, Math.min(Number(options.maxPagesPerGroup) || 3, 20));
    const delayMs = Math.max(150, Math.min(Number(options.delayMs) || 350, 5000));
    const groups = (Array.isArray(requestedGroups) ? requestedGroups : [])
      .map(value => typeof value === 'object' ? {id: String(value.id || ''), name: String(value.name || '')} : {id: String(value), name: ''})
      .filter(value => /^\d+$/.test(value.id)).slice(0, maxGroups);
    if (!groups.length) return {status: 'BLOCKED', reason: 'Danh sách group trống hoặc không hợp lệ.'};

    const history = loadHistory();
    const posts = [];
    const groupResults = [];
    let totalStories = 0;
    let newStories = 0;
    for (const [groupIndex, group] of groups.entries()) {
      let cursor = null;
      let groupCompleted = false;
      const seenThisGroup = new Set();
      const pages = [];
      for (let page = 1; page <= maxPagesPerGroup; page += 1) {
        let variables = core.replaceExact(baseVariables, sourceId, group.id);
        variables = structuredClone(variables);
        variables.cursor = cursor;
        if (typeof variables.count === 'number') variables.count = Math.max(1, Math.min(variables.count, 20));
        try {
          const result = await fetchRecord(record, variables);
          const summary = core.summarizeResponse(result.text, 'group_posts', record.name);
          let added = 0;
          for (const item of summary.items) {
            const key = `${group.id}:${item.id}`;
            if (seenThisGroup.has(key)) continue;
            seenThisGroup.add(key);
            added += 1;
            totalStories += 1;
            const now = new Date().toISOString();
            const isNew = !history[key];
            if (isNew) newStories += 1;
            history[key] = {groupId: group.id, postId: item.id,
              firstSeenAt: history[key]?.firstSeenAt || now, lastSeenAt: now, publishedAt: item.publishedAt || null,
              textHash: core.hashText(item.text)};
            if (publishedWithinLast24Hours(item.publishedAt) && posts.length < 2000) {
              posts.push({groupId: group.id, groupName: group.name,
                postId: item.id, text: item.text, textLength: item.textLength,
                publishedAt: item.publishedAt, isNew});
            }
          }
          pages.push({page, httpStatus: result.response.status, graphQLErrors: summary.graphQLErrors,
            itemCount: summary.itemCount, newInGroup: added, hasNextPage: summary.hasNextPage,
            elapsedMs: result.elapsedMs});
          if (!result.response.ok || summary.graphQLErrors) break;
          if (!summary.hasNextPage || !summary.endCursor) { groupCompleted = true; break; }
          cursor = summary.endCursor;
          await sleep(delayMs);
        } catch { pages.push({page, status: 'FAIL', reason: 'Lỗi mạng hoặc hết thời gian chờ.'}); break; }
      }
      groupResults.push({groupId: group.id, groupName: group.name, completed: groupCompleted,
        storyCount: seenThisGroup.size, pages});
      saveHistory(history);
      lastScan = {kind: 'group_posts', at: new Date().toISOString(), groupIndex: groupIndex + 1,
        groupTotal: groups.length, totalStories, newStories};
      await sleep(delayMs);
    }
    posts.sort((a, b) => {
      const timeA = Date.parse(a.publishedAt || '') || 0;
      const timeB = Date.parse(b.publishedAt || '') || 0;
      return timeB - timeA;
    });
    const {status, completedGroups, truncatedGroups, failedGroups} = core.summarizeGroupScan(groupResults, totalStories);
    return {status, kind: 'group_posts', queryName: record.name,
      groupsRequested: groups.length, groupsProcessed: groupResults.length, totalStories, newStories,
      returnedPosts: posts.length, truncatedPosts: Math.max(0, totalStories - posts.length),
      completedGroups, truncatedGroups, failedGroups,
      historySize: Object.keys(history).length, groupResults, posts, compatibility: inspect().compatibility};
  }

  function historySummary() {
    const history = loadHistory();
    return {status: 'PASS', historySize: Object.keys(history).length,
      lastSeenAt: Object.values(history).map(item => item.lastSeenAt).sort().at(-1) || null};
  }

  function configureTarget(value = {}) {
    const checked = core.validateCommentTarget(
      {...value, pageId: String(value.pageId || target.pageId)},
      '61593769810301', [...DENIED_POSTS]);
    if (!checked.ok) return {status: 'BLOCKED', reason: checked.reason};
    const {groupId, postId, pageId} = checked;
    if (target.groupId !== groupId || target.postId !== postId) {
      target.groupId = groupId;
      target.postId = postId;
      targetFeedback = null;
      approval = null;
    }
    return {status: 'READY', groupId, postId, pageId};
  }

  function prepareComment(expectedPageId, message, targetInput) {
    return window.__DKTECH_UI_DRIVER__.prepareComment(expectedPageId, message, targetInput);
  }

  async function sendComment(expectedPageId, message, approvalToken) {
    return window.__DKTECH_UI_DRIVER__.sendComment(expectedPageId, message, approvalToken);
  }

  function focusComment(expectedPageId, message, approvalToken) {
    return window.__DKTECH_UI_DRIVER__.focusComment(expectedPageId, message, approvalToken);
  }

  function confirmCommentText(message, approvalToken) {
    return window.__DKTECH_UI_DRIVER__.confirmCommentText(message, approvalToken);
  }

  function armCommentSubmission(message, approvalToken) {
    return window.__DKTECH_UI_DRIVER__.armCommentSubmission(message, approvalToken);
  }

  async function verifyCommentSubmission(message, approvalToken) {
    return window.__DKTECH_UI_DRIVER__.verifyCommentSubmission(message, approvalToken);
  }

  const api = Object.freeze({version: API_VERSION, inspect, run, scanJoinedGroups, scanGroupPosts,
    historySummary, configureTarget, prepareComment, sendComment, focusComment, confirmCommentText,
    armCommentSubmission, verifyCommentSubmission});
  Object.defineProperty(window, '__DKTECH_REQUEST_PROBE__', {value: api, configurable: true});
  if (!window.__DKTECH_READ_PROBE_V2__) {
    Object.defineProperty(window, '__DKTECH_READ_PROBE_V2__', {value: api, configurable: false});
  }
})();
