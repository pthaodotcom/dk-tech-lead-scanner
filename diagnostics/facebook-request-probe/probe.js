(() => {
  const API_VERSION = '0.2.0';
  if (window.__DKTECH_REQUEST_PROBE__?.version === API_VERSION) return;
  const core = window.__DKTECH_PROBE_CORE__;
  if (!core) throw new Error('DK-Tech probe core chưa được nạp.');

  const nativeFetch = window.fetch.bind(window);
  const records = new Map();
  const names = new Set();
  const unknownGroupQueries = new Set();
  const compatibilityWarnings = new Map();
  const target = Object.freeze({
    groupId: '1163787441488087', postId: '1802484360951722',
    pageId: '61593769810301', defaultMessage: 'ib hoặc liên hệ 0342391808 ạ',
  });
  const HISTORY_KEY = '__dktech_scan_history_v1';
  const COMMENT_KEY = message => `__dktech_comment_test_${target.postId}_${core.hashText(message)}`;
  let targetFeedback = null;
  let observedCommentDocId = null;
  let relayProviders = {};
  let running = false;
  let commenting = false;
  let approval = null;
  let lastScan = null;

  function onTargetPost() {
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
      for (const value of Object.values(source)) {
        if (value?.__typename !== 'Story' || String(value.post_id || '') !== target.postId) continue;
        const id = value.feedback?.__ref || value.feedback?.id;
        if (typeof id === 'string' && id.length > 8) {
          targetFeedback = {id, source: 'relay_store', at: Date.now()};
          break;
        }
      }
    } catch {}
    return targetFeedback;
  }

  function observeResponse(text, info) {
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
    if (info.name === 'useCometUFICreateCommentMutation') observedCommentDocId = info.params.get('doc_id');
    if (/Group/.test(info.name) && names.size < 120) names.add(info.name);
    if (info.kind) remember(info.kind, info, 'name');
    if (info.kind === 'group_posts' && info.actingId === target.pageId) {
      relayProviders = Object.fromEntries(Object.entries(info.variables || {})
        .filter(([key]) => key.startsWith('__relay_internal__pv__')));
    }
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
          if (request && (request.kind || /Group/i.test(request.name))) {
            void promise.then(response => response.clone().text().then(text => observeResponse(text, request))).catch(() => {});
          }
        }).catch(() => {});
        return promise;
      }
      const info = init?.body != null ? inspectRequest(url, init.body, method) : null;
      const promise = nativeFetch(input, init);
      if (info && (info.kind || /Group/i.test(info.name)) && info.actingId === target.pageId) {
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
    if (info && (info.kind || /Group/i.test(info.name)) && info.actingId === target.pageId) {
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
      captured: [...records.values()].map(({kind, name, actingId, at, detectedBy}) => ({kind, name, actingId, at, detectedBy})),
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
    return String(variables.id || variables.groupID || variables.groupId || variables.youthIntegrityHostID || '');
  }

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
              firstSeenAt: history[key]?.firstSeenAt || now, lastSeenAt: now, textHash: core.hashText(item.text)};
            if (posts.length < 2000) posts.push({groupId: group.id, groupName: group.name,
              postId: item.id, text: item.text, textLength: item.textLength, isNew});
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
    return {status: totalStories ? 'PASS' : 'INCONCLUSIVE', kind: 'group_posts', queryName: record.name,
      groupsRequested: groups.length, groupsProcessed: groupResults.length, totalStories, newStories,
      returnedPosts: posts.length, truncatedPosts: Math.max(0, totalStories - posts.length),
      historySize: Object.keys(history).length, groupResults, posts, compatibility: inspect().compatibility};
  }

  function historySummary() {
    const history = loadHistory();
    return {status: 'PASS', historySize: Object.keys(history).length,
      lastSeenAt: Object.values(history).map(item => item.lastSeenAt).sort().at(-1) || null};
  }

  function prepareComment(expectedPageId, message = target.defaultMessage) {
    const text = String(message || '').trim();
    const feedback = findTargetFeedbackFromRelay();
    const mutation = mutationDocId();
    const normalized = value => String(value || '').replace(/\s+/g, ' ').trim();
    const status = {targetUrl: `https://www.facebook.com/groups/${target.groupId}/posts/${target.postId}/`,
      message: text, expectedPageId, activePageId: currentPageId(), targetPostLoaded: onTargetPost(),
      feedbackReady: Boolean(feedback), feedbackSource: feedback?.source || null,
      mutationReady: Boolean(mutation.id), mutationDocSource: mutation.source,
      alreadyAttempted: Boolean(localStorage.getItem(COMMENT_KEY(text))),
      duplicateVisible: Boolean(text && normalized(document.body?.innerText).includes(normalized(text)))};
    const actorError = validateActor(expectedPageId);
    if (actorError) return {...status, status: 'BLOCKED', reason: actorError};
    if (!status.targetPostLoaded) return {...status, status: 'BLOCKED', reason: 'Mở đúng bài đích trong tab Facebook này.'};
    if (!text || text.length > 300) return {...status, status: 'BLOCKED', reason: 'Comment phải có 1-300 ký tự.'};
    if (status.duplicateVisible) return {...status, status: 'BLOCKED', reason: 'Nội dung này đã xuất hiện trên bài; không đăng trùng.'};
    if (status.alreadyAttempted) return {...status, status: 'BLOCKED', reason: 'Nội dung này đã có lần gửi trước; cần kiểm tra bài.'};
    if (!status.feedbackReady) return {...status, status: 'INCONCLUSIVE', reason: 'Chưa lấy được feedback ID của bài.'};
    if (!status.mutationReady) return {...status, status: 'INCONCLUSIVE', reason: 'Không tìm thấy mutation artifact hiện tại.'};
    approval = {token: crypto.randomUUID(), messageHash: core.hashText(text), expiresAt: Date.now() + 2 * 60 * 1000};
    return {...status, status: 'READY', approvalToken: approval.token, expiresInSeconds: 120};
  }

  function mutationDocId() {
    if (observedCommentDocId) return {id: observedCommentDocId, source: 'observed'};
    try {
      const id = window.require('useCometUFICreateCommentMutation.graphql')?.params?.id;
      if (id) return {id: String(id), source: 'relay_artifact'};
    } catch {}
    return {id: null, source: null};
  }

  function findCreatedCommentId(documents) {
    let found = null;
    function walk(value, depth = 0) {
      if (!value || typeof value !== 'object' || depth > 25 || found) return;
      if (value.comment_create) {
        const creation = value.comment_create;
        const node = creation?.comment || creation?.feedback_comment_edge?.node;
        found = node?.legacy_fbid || node?.comment_id || node?.id || null;
      }
      for (const child of Object.values(value)) walk(child, depth + 1);
    }
    documents.forEach(document => walk(document));
    return found;
  }

  async function sendComment(expectedPageId, message, approvalToken) {
    const text = String(message || '').trim();
    const approved = approval && approval.token === approvalToken &&
      approval.messageHash === core.hashText(text) && approval.expiresAt >= Date.now();
    approval = null;
    if (!approved) return {status: 'BLOCKED', reason: 'Cần chạy kiểm tra và xác nhận lại comment trong vòng 2 phút.'};
    const check = prepareComment(expectedPageId, text);
    approval = null;
    if (check.status !== 'READY') return check;
    if (commenting) return {...check, status: 'BUSY'};
    const operation = mutationDocId();
    if (!operation.id) return {...check, status: 'BLOCKED', reason: 'Không tìm thấy mutation artifact hiện tại; không dùng doc_id dự phòng.'};
    const dtsg = (() => { try { return window.require('DTSGInitialData')?.token; } catch { return null; } })();
    if (!dtsg) return {...check, status: 'BLOCKED', reason: 'Không có phiên đăng nhập để gửi comment.'};
    commenting = true;
    const attemptKey = COMMENT_KEY(text);
    localStorage.setItem(attemptKey, JSON.stringify({at: new Date().toISOString(), state: 'attempting'}));
    try {
      const variables = {feedLocation: 'GROUP', feedbackSource: 0, groupID: target.groupId,
        input: {client_mutation_id: String(Date.now()), attachments: [], feedback_id: targetFeedback.id,
          formatting_style: null, message: {ranges: [], text},
          attribution_id_v2: `CometGroupDiscussionRoute.${crypto.randomUUID()}`,
          vod_video_timestamp: null, is_tracking_encrypted: true, tracking: [],
          feedback_source: 'DISCUSSION_FEED',
          idempotence_token: `${target.pageId}_${target.postId}_${core.hashText(text)}`,
          session_id: crypto.randomUUID()},
        inviteShortLinkKey: null, renderLocation: null, scale: 1,
        useDefaultActor: false, focusCommentID: null, ...relayProviders};
      const params = new URLSearchParams({av: target.pageId, __user: target.pageId, __a: '1', fb_dtsg: dtsg,
        fb_api_caller_class: 'RelayModern', fb_api_req_friendly_name: 'useCometUFICreateCommentMutation',
        server_timestamps: 'true', doc_id: operation.id, variables: JSON.stringify(variables)});
      const response = await nativeFetch('https://www.facebook.com/api/graphql/', {
        method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: params.toString(), signal: AbortSignal.timeout(30000)});
      const documents = core.parseDocuments(await response.text());
      const errors = documents.flatMap(document => Array.isArray(document.errors) ? document.errors : []);
      const commentId = findCreatedCommentId(documents);
      // Facebook can return a created comment edge together with non-fatal errors
      // from other streamed response documents. Preserve that distinction so an
      // operator never mistakes a partial response for a clean mutation.
      const status = commentId
        ? (errors.length ? 'PASS_WITH_WARNINGS' : 'PASS')
        : (!response.ok || errors.length) ? 'FAIL' : 'INCONCLUSIVE';
      const report = {status, kind: 'comment', httpStatus: response.status,
        targetPostId: target.postId, targetGroupId: target.groupId, actingId: target.pageId,
        message: text, commentId: commentId || null, mutationDocSource: operation.source,
        graphqlErrorCount: errors.length,
        error: errors[0]?.message?.slice(0, 200) || null, attemptedOnce: true};
      localStorage.setItem(attemptKey, JSON.stringify({at: new Date().toISOString(), state: status, commentId: commentId || null}));
      return report;
    } catch {
      localStorage.setItem(attemptKey, JSON.stringify({at: new Date().toISOString(), state: 'INCONCLUSIVE'}));
      return {status: 'INCONCLUSIVE', kind: 'comment', attemptedOnce: true,
        reason: 'Request có thể đã gửi nhưng không nhận được phản hồi. Không tự thử lại.'};
    } finally { commenting = false; }
  }

  const api = Object.freeze({version: API_VERSION, inspect, run, scanJoinedGroups, scanGroupPosts,
    historySummary, prepareComment, sendComment});
  Object.defineProperty(window, '__DKTECH_REQUEST_PROBE__', {value: api, configurable: false});
  if (!window.__DKTECH_READ_PROBE_V2__) {
    Object.defineProperty(window, '__DKTECH_READ_PROBE_V2__', {value: api, configurable: false});
  }
})();
