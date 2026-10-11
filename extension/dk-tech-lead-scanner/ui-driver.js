(() => {
  if (window.__DKTECH_UI_DRIVER__) return;
  const PAGE_ID = '61593769810301';
  const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const visible = node => Boolean(node?.isConnected && node.getClientRects().length &&
    getComputedStyle(node).visibility !== 'hidden' && getComputedStyle(node).display !== 'none');
  let target = null;
  let approval = null;
  let active = null;
  let browserInput = null;
  let cancelled = false;

  function actor() {
    try { return String(window.require('CurrentUserInitialData')?.USER_ID || ''); } catch { return ''; }
  }
  function pageProblem() {
    const text = normalize(document.body?.innerText);
    if (/\/(checkpoint|login|recover)(\/|\.|\?|$)/i.test(location.pathname) ||
        document.querySelector('input[type="password"]')) return 'Phiên đăng nhập cần xác nhận lại.';
    const alerts = [...document.querySelectorAll('[role="alert"], [role="dialog"]')]
      .filter(visible).map(node => normalize(node.innerText));
    if (alerts.some(value => /temporarily blocked|tạm thời bị chặn|bị chặn tạm thời|confirm your identity|xác nhận danh tính|session expired|phiên.*hết hạn/i.test(value)) ||
        (text.length < 1200 && /temporarily blocked|sorry, something went wrong/i.test(text))) {
      return 'Facebook yêu cầu dừng hoặc kiểm tra phiên đăng nhập.';
    }
    return null;
  }
  function commentDisabled() {
    const pattern = /bình luận đã bị tắt cho bài viết này|comments? (?:have been |are )?turned off for this post/i;
    return [...document.querySelectorAll('div,span,p')].some(node => {
      const text = normalize(node.innerText);
      return visible(node) && text.length <= 160 && pattern.test(text);
    });
  }
  function root() {
    const dialogs = [...document.querySelectorAll('[role="dialog"]')].filter(visible);
    return dialogs.find(node => /bài viết của|post by|\bpost\b/i.test(node.getAttribute('aria-label') ||
      node.querySelector('h1,h2,[role="heading"]')?.innerText || '')) ||
      (dialogs.length === 1 ? dialogs[0] : document.querySelector('[role="main"]'));
  }
  function composer() {
    const scope = root();
    if (!scope) return null;
    const editors = [...scope.querySelectorAll('[contenteditable="true"][role="textbox"]')]
      .filter(visible).filter(node => !node.closest('[role="article"]') ||
        !/comment|bình luận của/i.test(node.closest('[role="article"]').getAttribute('aria-label') || ''))
      .filter(node => {
        const placeholder = node.getAttribute('aria-label') || node.getAttribute('aria-placeholder') || node.getAttribute('data-placeholder') || '';
        return /bình luận|trả lời dưới tên|comment|answer as/i.test(placeholder);
      });
    // Ambiguous reply composers must never receive a top-level comment.
    return editors.length === 1 ? editors[0] : null;
  }
  function sendButton(editor) {
    for (let node = editor.parentElement, depth = 0; node && depth < 6; node = node.parentElement, depth++) {
      const buttons = [...node.querySelectorAll('button,[role="button"]')].filter(visible)
        .filter(button => /^(?:bình luận|gửi|gửi bình luận|đăng bình luận|comment|send|post comment)$/i
          .test(normalize(button.getAttribute('aria-label') || button.getAttribute('title') || button.innerText)))
        .filter(button => !button.disabled && button.getAttribute('aria-disabled') !== 'true');
      if (buttons.length === 1) return buttons[0];
      if (buttons.length > 1) return null;
      if (node === root()) break;
    }
    return null;
  }
  function commentEvidence(text) {
    const scope = root();
    if (!scope) return null;
    const nodes = [...scope.querySelectorAll('[role="article"], [aria-label*="Bình luận của"], [aria-label*="Comment by"]')];
    const expected = normalize(text);
    for (const node of nodes) {
      if (!visible(node) || node.querySelector('[contenteditable="true"]')) continue;
      const content = normalize(node.innerText);
      if (!content.includes(expected)) continue;
      const authors = [...node.querySelectorAll('a[href]')];
      const author = authors.find(link => {
        const url = new URL(link.href, location.href);
        return url.searchParams.get('id') === PAGE_ID || url.pathname === `/${PAGE_ID}` ||
          url.pathname === `/${PAGE_ID}/` || /^\/dktechsupport\/?$/i.test(url.pathname);
      });
      if (!author) continue;
      const link = authors.find(a => new URL(a.href, location.href).searchParams.has('comment_id'));
      const moderation = /bị từ chối|declined|rejected/i.test(content) ? 'rejected'
        : /đang chờ|chờ phê duyệt|pending approval|pending review/i.test(content) ? 'pending'
          : /đang viết|đang đăng|posting|sending/i.test(content) ? 'sending' : 'visible';
      return {commentId: link ? new URL(link.href, location.href).searchParams.get('comment_id') : null,
        moderation, visible: true, authorId: PAGE_ID};
    }
    return null;
  }
  function findTargetPostContainer(postId) {
    if (!postId) return null;
    const links = [...document.querySelectorAll(`a[href*="${postId}"]`)];
    for (const link of links) {
      const container = link.closest('[role="article"]') ||
        link.closest('[data-pagelet*="FeedUnit"]') ||
        link.closest('[data-pagelet*="GroupPermalink"]') ||
        link.closest('[role="feed"] > div');
      if (container) return container;
    }
    const postAttrEl = document.querySelector(`[data-post-id="${postId}"], [id*="${postId}"]`);
    if (postAttrEl) {
      return postAttrEl.closest('[role="article"]') || postAttrEl;
    }
    const dialogs = [...document.querySelectorAll('[role="dialog"]')];
    for (const dialog of dialogs) {
      if (dialog.querySelector(`a[href*="${postId}"]`)) return dialog;
    }
    return null;
  }
  function probeComposer() {
    const scope = root();
    const targetPostNode = target?.postId ? findTargetPostContainer(target.postId) : null;
    const allContentEditable = [...document.querySelectorAll('[contenteditable="true"]')];
    const allWithRoleTextbox = allContentEditable.filter(node => node.getAttribute('role') === 'textbox');
    const pool = allContentEditable.length ? allContentEditable : [...new Set([
      ...document.querySelectorAll('[contenteditable="true"]'),
      ...document.querySelectorAll('[role="textbox"]'),
      ...document.querySelectorAll('[aria-label*="bình luận" i], [aria-label*="comment" i]'),
    ])];
    const candidates = pool.slice(0, 15).map((node, idx) => {
      const rects = node.getClientRects();
      const bRect = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      const isConn = node.isConnected;
      const role = node.getAttribute('role') || 'none';
      const ariaLabel = node.getAttribute('aria-label') || '';
      const ariaPlaceholder = node.getAttribute('aria-placeholder') || '';
      const dataPlaceholder = node.getAttribute('data-placeholder') || '';
      const placeholder = ariaLabel || ariaPlaceholder || dataPlaceholder;
      const textPreview = normalize(node.innerText || node.textContent).slice(0, 60);
      const hasOffsetParent = node.offsetParent !== null;

      const isVis = visible(node);
      const isTextbox = role === 'textbox';
      const targetContainer = targetPostNode || scope;
      const inScope = Boolean(targetContainer && targetContainer.contains(node));
      const isArticle = Boolean(node.closest('[role="article"]'));
      const isArticleComment = isArticle && /comment|bình luận của/i.test(node.closest('[role="article"]').getAttribute('aria-label') || '');
      const matchesPlaceholder = /bình luận|trả lời dưới tên|comment|answer as/i.test(placeholder);

      // Requirement 5 predicates: CONNECTED, VISIBLE, ROLE, PLACEHOLDER, TARGET_POST_SCOPE, NOT_REPLY
      let result = 'ACCEPT';
      if (!isConn) result = 'REJECT_CONNECTED';
      else if (!isVis) result = 'REJECT_VISIBLE';
      else if (!isTextbox) result = 'REJECT_ROLE';
      else if (!matchesPlaceholder) result = 'REJECT_PLACEHOLDER';
      else if (!inScope) result = 'REJECT_TARGET_POST_SCOPE';
      else if (isArticleComment) result = 'REJECT_NOT_REPLY';

      const formatted = [
        `candidate #${idx}`,
        `connected=${isConn}`,
        `rects=${rects.length}`,
        `role=${role}`,
        `placeholder=${JSON.stringify(placeholder.slice(0, 40))}`,
        `targetPostScope=${inScope}`,
        `reply=${isArticleComment}`,
        `RESULT=${result}`,
      ].join('\n');

      const summary = `candidate #${idx} | connected=${isConn} | rects=${rects.length} | role=${role} | placeholder=${JSON.stringify(placeholder.slice(0, 40))} | targetPostScope=${inScope} | reply=${isArticleComment} | RESULT=${result}`;

      return {
        idx,
        summary,
        formatted,
        result,
        tagName: node.tagName,
        role,
        ariaLabel,
        ariaPlaceholder,
        dataPlaceholder,
        placeholder,
        textPreview,
        isConnected: isConn,
        clientRectsLength: rects.length,
        boundingClientRect: {
          width: Math.round(bRect.width),
          height: Math.round(bRect.height),
          top: Math.round(bRect.top),
          left: Math.round(bRect.left),
        },
        hasOffsetParent,
        display: style.display,
        visibility: style.visibility,
        opacity: style.opacity,
        inScope,
        isVis,
        isArticleComment,
      };
    });

    const activeEditor = composer();
    const scopeDetails = {
      textSnippet: normalize(scope?.innerText || '').slice(-400),
      commentElements: [...(scope || document).querySelectorAll(
        '[aria-label*="bình luận" i], [aria-label*="comment" i], [placeholder*="bình luận" i], [data-placeholder*="bình luận" i], [role="textbox"], [data-lexical-editor]'
      )].slice(0, 8).map((el, i) => ({
        i,
        tag: el.tagName,
        role: el.getAttribute('role'),
        ariaLabel: el.getAttribute('aria-label'),
        contenteditable: el.getAttribute('contenteditable'),
        text: normalize(el.innerText || el.textContent).slice(0, 40),
        rects: el.getClientRects().length,
        vis: visible(el),
      })),
      scrollables: scope ? [...scope.querySelectorAll('*')].filter(el => {
        const s = getComputedStyle(el);
        return (s.overflowY === 'auto' || s.overflowY === 'scroll') && el.scrollHeight > el.clientHeight;
      }).map(el => ({tag: el.tagName, scrollTop: el.scrollTop, scrollHeight: el.scrollHeight, clientHeight: el.clientHeight})) : [],
    };
    return {
      window: {
        innerWidth: window.innerWidth,
        innerHeight: window.innerHeight,
        visibilityState: document.visibilityState,
      },
      targetPost: {
        targetPostFound: Boolean(targetPostNode),
        targetPostId: target?.postId || null,
        tag: targetPostNode?.tagName || null,
        role: targetPostNode?.getAttribute('role') || null,
      },
      scope: {
        found: Boolean(scope),
        tag: scope?.tagName || null,
        role: scope?.getAttribute('role') || null,
        ariaLabel: scope?.getAttribute('aria-label') || null,
        heading: scope?.querySelector('h1,h2,[role="heading"]')?.innerText?.slice(0, 80) || null,
      },
      counts: {
        totalContentEditable: allContentEditable.length,
        totalWithRoleTextbox: allWithRoleTextbox.length,
        composerCandidateCount: candidates.length,
        validComposerFound: Boolean(activeEditor),
        activeEditorRectCount: activeEditor ? activeEditor.getClientRects().length : 0,
      },
      candidates,
      scopeDetails,
    };
  }
  function preflight(expectedPageId, message, input = target) {
    if (input) target = {groupId: String(input.groupId), postId: String(input.postId), pageId: String(input.pageId)};
    if (!target || !/^\d+$/.test(target.groupId) || !/^\d+$/.test(target.postId) ||
        target.postId === '1802484360951722' || target.pageId !== PAGE_ID || expectedPageId !== PAGE_ID) {
      return {status: 'BLOCKED', reason: 'Bài hoặc Page không hợp lệ.'};
    }
    const problem = pageProblem();
    if (problem) return {status: 'PAUSED_FACEBOOK', reason: problem};
    if (actor() !== PAGE_ID) return {status: 'PAUSED_FACEBOOK', reason: 'Tab chưa dùng đúng Page DK-Tech.'};
    if (!new RegExp(`^/groups/${target.groupId}/(?:posts|permalink)/${target.postId}/?$`).test(location.pathname)) {
      return {status: 'BLOCKED', reason: 'Tab chưa mở đúng bài đích.'};
    }
    const text = normalize(message);
    if (!text || text.length > 300) return {status: 'BLOCKED', reason: 'Nội dung phải có 1–300 ký tự.'};
    if (commentDisabled()) return {status: 'SKIPPED_COMMENT_DISABLED', commentDisabled: true,
      reason: 'Facebook đã tắt bình luận cho bài viết này.', activePageId: actor()};
    if (localStorage.getItem(`__dktech_ui_attempt_${target.postId}`)) {
      return {status: 'BLOCKED', alreadyAttempted: true, reason: 'Bài đã có lần gửi; không gửi lại.'};
    }
    if (commentEvidence(text)) return {status: 'BLOCKED', duplicateVisible: true, reason: 'Đã thấy comment của Page trên bài.'};
    const editor = composer();
    const diagnostics = probeComposer();
    if (!editor) return {status: 'INCONCLUSIVE', reason: 'Chưa xác định được một ô bình luận của bài gốc.', activePageId: actor(), diagnostics};
    if (normalize(editor.innerText)) return {status: 'BLOCKED', reason: 'Ô bình luận đang có bản nháp; giữ nguyên.', activePageId: actor(), diagnostics};
    approval = {token: crypto.randomUUID(), text, postId: target.postId, expiresAt: Date.now() + 120000};
    cancelled = false;
    return {status: 'READY', approvalToken: approval.token, transport: 'facebook_ui', activePageId: actor(), diagnostics};
  }
  function observe(info, responseText) {
    if (!active || !active.clicked || info?.name !== 'useCometUFICreateCommentMutation' ||
        info.actingId !== PAGE_ID || normalize(info.variables?.input?.message?.text) !== active.text) return;
    // The UI chooses feedback/actor; inspect its response, never construct a mutation.
    if (String(info.variables?.groupID || '') !== target.groupId) return;
    const documents = window.__DKTECH_PROBE_CORE__.parseDocuments(responseText);
    function walk(value, depth = 0) {
      if (!value || typeof value !== 'object' || depth > 35) return;
      const creation = value.comment_create;
      const node = creation?.comment || creation?.feedback_comment_edge?.node;
      if (node) {
        const id = node.legacy_fbid || node.comment_id || node.id;
        const text = node.body?.text || node.message?.text;
        const author = node.author?.id;
        if (id && (!text || normalize(text) === active.text) && (!author || String(author) === PAGE_ID)) {
          active.commentId = String(id); active.accepted = true;
        }
      }
      for (const child of Object.values(value)) walk(child, depth + 1);
    }
    documents.forEach(item => walk(item));
  }
  async function send(expectedPageId, message, token) {
    if (active) return {status: 'BUSY', reason: 'Đang xử lý một comment.'};
    const text = normalize(message);
    if (!approval || approval.token !== token || approval.text !== text || approval.postId !== target?.postId ||
        approval.expiresAt < Date.now()) return {status: 'BLOCKED', reason: 'Cần kiểm tra lại bài và nội dung trước gửi.'};
    const check = preflight(expectedPageId, text);
    approval = null;
    if (check.status !== 'READY') return check;
    const editor = composer();
    active = {text, clicked: false, commentId: null, accepted: false};
    const key = `__dktech_ui_attempt_${target.postId}`;
    try {
      editor.focus();
      if (!document.execCommand('insertText', false, text) || normalize(editor.innerText) !== text) {
        return {status: 'BLOCKED', reason: 'Composer không nhận đúng nội dung; chưa bấm gửi.'};
      }
      await wait(400);
      if (cancelled) return {status: 'BLOCKED', reason: 'Đã dừng trước khi gửi.'};
      const problem = pageProblem();
      if (problem || actor() !== PAGE_ID) return {status: 'PAUSED_FACEBOOK', reason: problem || 'Page đã thay đổi.'};
      const button = sendButton(editor);
      if (!button) return {status: 'BLOCKED', reason: 'Chưa xác định được nút gửi trong composer.'};
      localStorage.setItem(key, JSON.stringify({at: new Date().toISOString(), status: 'INCONCLUSIVE'}));
      active.clicked = true;
      button.click();
      let stable = 0;
      for (let i = 0; i < 40; i++) {
        await wait(500);
        const problem = pageProblem();
        if (problem) return {status: 'PAUSED_FACEBOOK', attemptedOnce: true, reason: problem};
        const evidence = commentEvidence(text);
        if (evidence?.commentId) active.commentId = evidence.commentId;
        if (evidence?.moderation === 'rejected' || evidence?.moderation === 'pending') {
          return {status: evidence.moderation === 'rejected' ? 'SUBMITTED_REJECTED' : 'SUBMITTED_PENDING',
            submitted: true, attemptedOnce: true, commentId: active.commentId, moderation: evidence.moderation,
            reason: evidence.moderation === 'rejected' ? 'Đã gửi; bình luận bị từ chối xét duyệt.' : 'Đã gửi; đang chờ duyệt.'};
        }
        if (active.accepted && active.commentId) return {status: 'PASS_NETWORK_CONFIRMED', submitted: true,
          attemptedOnce: true, commentId: active.commentId, moderation: 'accepted_unrendered', visible: false};
        stable = evidence?.moderation === 'visible' && active.commentId ? stable + 1 : 0;
        if (stable >= 4) return {status: 'PASS', submitted: true, attemptedOnce: true,
          commentId: active.commentId, moderation: 'visible', visible: true};
      }
      return {status: active.accepted ? 'SUBMITTED_UNVERIFIED' : 'INCONCLUSIVE', submitted: active.accepted,
        attemptedOnce: true, commentId: active.commentId, moderation: 'unknown',
        reason: 'Chưa xác minh được bình luận hiển thị đúng Page. Không tự gửi lại.'};
    } catch (error) {
      return {status: active?.clicked ? 'INCONCLUSIVE' : 'ERROR', attemptedOnce: Boolean(active?.clicked),
        reason: String(error?.message || error).slice(0, 250)};
    } finally { active = null; }
  }

  function focusComment(expectedPageId, message, token) {
    if (active || browserInput) return {status: 'BUSY', reason: 'Đang xử lý một comment.'};
    const text = normalize(message);
    if (!approval || approval.token !== token || approval.text !== text || approval.postId !== target?.postId ||
        approval.expiresAt < Date.now()) return {status: 'BLOCKED', reason: 'Cần kiểm tra lại bài và nội dung trước gửi.'};
    const check = preflight(expectedPageId, text);
    approval = null;
    if (check.status !== 'READY') return check;
    const editor = composer();
    editor.scrollIntoView({behavior: 'instant', block: 'center'});
    editor.click();
    editor.focus();
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(editor);
    range.collapse(false);
    selection.removeAllRanges();
    selection.addRange(range);
    browserInput = {token, text, postId: target.postId};
    cancelled = false;
    return {status: 'READY_FOR_BROWSER_INPUT', activePageId: actor()};
  }

  function confirmCommentText(message, token) {
    const text = normalize(message);
    if (!browserInput || browserInput.token !== token || browserInput.text !== text ||
        browserInput.postId !== target?.postId) return {status: 'BLOCKED', reason: 'Phiên nhập comment không còn hợp lệ.'};
    const editor = composer();
    const observed = normalize(editor?.innerText);
    if (!editor || observed !== text) return {status: 'BLOCKED', reason: 'Chrome chưa nhập đúng nội dung vào composer; chưa bấm gửi.',
      expectedLength: text.length, observedLength: observed.length};
    return {status: 'READY_TO_SUBMIT'};
  }

  function armCommentSubmission(message, token) {
    const confirmed = confirmCommentText(message, token);
    if (confirmed.status !== 'READY_TO_SUBMIT') return confirmed;
    const key = `__dktech_ui_attempt_${target.postId}`;
    localStorage.setItem(key, JSON.stringify({at: new Date().toISOString(), status: 'INCONCLUSIVE'}));
    active = {text: browserInput.text, clicked: true, commentId: null, accepted: false};
    return {status: 'ARMED'};
  }

  async function verifyCommentSubmission(message, token) {
    const text = normalize(message);
    if (!browserInput || browserInput.token !== token || browserInput.text !== text || !active?.clicked) {
      return {status: 'BLOCKED', reason: 'Lượt gửi qua trình duyệt chưa được xác nhận.'};
    }
    try {
      let stable = 0;
      for (let i = 0; i < 40; i += 1) {
        await wait(500);
        if (cancelled) return {status: 'INCONCLUSIVE', submitted: true, attemptedOnce: true,
          reason: 'Đã dừng sau khi nhấn gửi; cần kiểm tra lịch sử.'};
        const problem = pageProblem();
        if (problem) return {status: 'PAUSED_FACEBOOK', submitted: true, attemptedOnce: true, reason: problem};
        const evidence = commentEvidence(text);
        if (evidence?.commentId) active.commentId = evidence.commentId;
        if (evidence?.moderation === 'rejected' || evidence?.moderation === 'pending') {
          return {status: evidence.moderation === 'rejected' ? 'SUBMITTED_REJECTED' : 'SUBMITTED_PENDING',
            submitted: true, attemptedOnce: true, commentId: active.commentId, moderation: evidence.moderation,
            reason: evidence.moderation === 'rejected' ? 'Đã gửi; bình luận bị từ chối xét duyệt.' : 'Đã gửi; đang chờ duyệt.'};
        }
        if (active.accepted && active.commentId) return {status: 'PASS_NETWORK_CONFIRMED', submitted: true,
          attemptedOnce: true, commentId: active.commentId, moderation: 'accepted_unrendered', visible: false};
        stable = evidence?.moderation === 'visible' && active.commentId ? stable + 1 : 0;
        if (stable >= 4) return {status: 'PASS', submitted: true, attemptedOnce: true,
          commentId: active.commentId, moderation: 'visible', visible: true};
      }
      return {status: active.accepted ? 'SUBMITTED_UNVERIFIED' : 'INCONCLUSIVE', submitted: true,
        attemptedOnce: true, commentId: active.commentId, moderation: 'unknown',
        reason: 'Đã nhấn gửi nhưng chưa xác minh được bình luận hiển thị đúng Page. Không tự gửi lại.'};
    } finally {
      active = null;
      browserInput = null;
    }
  }

  window.__DKTECH_UI_DRIVER__ = Object.freeze({prepareComment: preflight, sendComment: send,
    focusComment, confirmCommentText, armCommentSubmission, verifyCommentSubmission,
    pageProblem, observe, cancel: () => { cancelled = true; }, commentEvidence, findTargetPostContainer});
})();
