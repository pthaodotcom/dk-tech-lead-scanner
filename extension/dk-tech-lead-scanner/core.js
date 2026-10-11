(() => {
  if (globalThis.__DKTECH_PROBE_CORE__) return;

  function parseDocuments(text) {
    const clean = String(text || '').replace(/^\s*for\s*\(;;\);?/, '').trim();
    if (!clean) return [];
    try { return [JSON.parse(clean)]; }
    catch {
      const documents = [];
      for (const line of clean.split('\n')) {
        try { documents.push(JSON.parse(line)); } catch {}
      }
      return documents;
    }
  }

  function longest(values) {
    return values.filter(value => typeof value === 'string' && value.trim())
      .sort((a, b) => b.trim().length - a.trim().length)[0]?.trim() || '';
  }

  function extractStoryText(story) {
    const content = story?.comet_sections?.content?.story || story || {};
    const explicit = [
      content?.message?.text,
      content?.comet_sections?.message?.story?.message?.text,
      content?.comet_sections?.message_container?.story?.message?.text,
      content?.message?.story?.message?.text,
      story?.message?.text,
      story?.comet_sections?.content?.story?.message?.text,
      story?.comet_sections?.content?.story?.comet_sections?.message?.story?.message?.text,
      story?.comet_sections?.content?.story?.comet_sections?.message_container?.story?.message?.text,
    ];
    const rich = [
      content?.rich_message,
      content?.comet_sections?.message?.rich_message,
      story?.comet_sections?.content?.story?.comet_sections?.message?.rich_message,
    ].filter(Array.isArray).map(parts => parts.map(part => part?.text || '').join('\n'));
    const direct = longest([...explicit, ...rich]);
    if (direct) return direct;

    const candidates = [];
    const seen = new Set();
    function walk(value, path = '', depth = 0) {
      if (!value || typeof value !== 'object' || depth > 12 || seen.has(value)) return;
      seen.add(value);
      if (typeof value.text === 'string' && /message|rich_message/i.test(path)) {
        candidates.push(value.text);
      }
      for (const [key, child] of Object.entries(value)) walk(child, `${path}.${key}`, depth + 1);
    }
    walk(story, 'story');
    return longest(candidates);
  }

  function normalizeStoryTime(value) {
    if (typeof value === 'string' && !/^\d+(?:\.\d+)?$/.test(value.trim())) {
      const parsed = Date.parse(value);
      return Number.isNaN(parsed) ? null : parsed;
    }
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric <= 0) return null;
    return numeric < 100000000000 ? numeric * 1000 : numeric;
  }

  function extractStoryPublishedAt(story) {
    const content = story?.comet_sections?.content?.story || story || {};
    const direct = [
      content.creation_time, content.created_time, content.publish_time, content.published_time,
      story?.creation_time, story?.created_time, story?.publish_time, story?.published_time,
    ].map(normalizeStoryTime).find(value => value !== null);
    if (direct !== undefined) return new Date(direct).toISOString();

    const candidates = [];
    const seen = new Set();
    function walk(value, key = '', depth = 0) {
      if (depth > 12 || value === null || value === undefined || seen.has(value)) return;
      if (/^(creation_time|created_time|publish_time|published_time|story_creation_time)$/i.test(key)) {
        const timestamp = normalizeStoryTime(value);
        if (timestamp !== null) candidates.push(timestamp);
      }
      if (typeof value !== 'object') return;
      seen.add(value);
      for (const [childKey, child] of Object.entries(value)) walk(child, childKey, depth + 1);
    }
    walk(story);
    return candidates.length ? new Date(Math.min(...candidates)).toISOString() : null;
  }

  function queryKind(name) {
    if (!/Query$/.test(name || '') || /Mutation/i.test(name || '')) return null;
    if (/EndOfFeedQuery|RootSuccessQuery|RootQuery/i.test(name || '')) return null;
    if (/JoinedGroups|MemberGroups|GroupsYouJoined|TabGroupList|GroupsCometJoinsRoot|AllJoinedGroupsSection/i.test(name)) {
      return 'joined_groups';
    }
    if (/Root|Header|About|Member|Admin/i.test(name || '')) return null;
    if (/GroupsComet.*(?:Feed|Discussion|MainFeed).*Query|CometGroup.*(?:Feed|Discussion).*Query/i.test(name)) return 'group_posts';
    return null;
  }

  function summarizeResponse(text, kind, name = '') {
    const documents = parseDocuments(text);
    const items = new Map();
    const pageInfo = [];
    let graphQLErrors = 0;

    function walk(value, path = '', depth = 0) {
      if (!value || typeof value !== 'object' || depth > 45) return;
      if (Array.isArray(value)) {
        value.forEach((item, index) => walk(item, `${path}[${index}]`, depth + 1));
        return;
      }
      if (Array.isArray(value.errors)) graphQLErrors += value.errors.length;
      const membership = /joined_groups|joinedGroups|member_groups|tab_groups_list|all_joined|groups_you_joined|joined|member/i.test(path);
      const feed = /group_feed|groupFeed|discussion_feed|discussionFeed/i.test(path) || (kind === 'group_posts' && /Feed|Discussion/i.test(name));
      if ((typeof value.has_next_page === 'boolean' || value.end_cursor) &&
          (kind === 'joined_groups' ? membership : feed)) {
        pageInfo.push({
          hasNextPage: typeof value.has_next_page === 'boolean' ? value.has_next_page : null,
          endCursor: typeof value.end_cursor === 'string' ? value.end_cursor : null,
          path,
        });
      }
      if (kind === 'joined_groups' && membership && value.__typename === 'Group' && value.id) {
        const id = String(value.id);
        const previous = items.get(id);
        const candidate = {id, name: String(value.name || '').slice(0, 160), type: 'Group'};
        if (!previous || candidate.name.length > previous.name.length) items.set(id, candidate);
      }
      if (kind === 'group_posts' && feed && value.__typename === 'Story' && (value.id || value.post_id)) {
        const id = String(value.post_id || value.id);
        const message = extractStoryText(value);
        const previous = items.get(id) || {id, text: '', textLength: 0, hasText: false, type: 'Story', occurrences: 0,
          publishedAt: null};
        previous.occurrences += 1;
        previous.publishedAt ||= extractStoryPublishedAt(value);
        if (message.length > previous.textLength) {
          previous.text = message;
          previous.textLength = message.length;
          previous.hasText = true;
        }
        items.set(id, previous);
      }
      for (const [key, child] of Object.entries(value)) walk(child, `${path}.${key}`, depth + 1);
    }

    documents.forEach((document, index) => {
      const label = typeof document?.label === 'string' ? document.label : '';
      const root = label.includes('group_feed') || label.includes('discussion_feed') || (kind === 'group_posts' && /Feed|Discussion/i.test(name))
        ? `doc${index}.group_feed` : `doc${index}`;
      walk(document, root, 0);
    });
    const cursorPage = [...pageInfo].reverse().find(item => typeof item.hasNextPage === 'boolean') ||
      [...pageInfo].reverse().find(item => item.endCursor) || null;
    return {
      parsedDocuments: documents.length,
      graphQLErrors,
      itemCount: items.size,
      items: [...items.values()],
      hasNextPage: cursorPage?.hasNextPage ?? null,
      endCursor: cursorPage?.endCursor || null,
      pageInfoCount: pageInfo.length,
    };
  }

  function classifyResponse(text, name = '') {
    const named = queryKind(name);
    if (!named && !/Group/i.test(name)) return {kind: null, source: 'none'};
    const posts = summarizeResponse(text, 'group_posts', name);
    const groups = summarizeResponse(text, 'joined_groups', name);
    const structuralKind = posts.itemCount ? 'group_posts' : groups.itemCount ? 'joined_groups' : null;
    if (named) return {kind: named, source: 'name', structuralKind};
    if (posts.itemCount) return {kind: 'group_posts', source: 'structure'};
    if (groups.itemCount) return {kind: 'joined_groups', source: 'structure'};
    return {kind: null, source: 'none'};
  }

  function replaceExact(value, from, to) {
    if (value === from) return to;
    if (Array.isArray(value)) return value.map(item => replaceExact(item, from, to));
    if (!value || typeof value !== 'object') return value;
    return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, replaceExact(child, from, to)]));
  }

  function hashText(value) {
    let hash = 2166136261;
    for (const char of String(value || '')) {
      hash ^= char.codePointAt(0);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
  }

  function validateCommentTarget(value, expectedPageId, deniedPostIds = []) {
    const groupId = String(value?.groupId || '');
    const postId = String(value?.postId || '');
    const pageId = String(value?.pageId || '');
    if (!/^\d+$/.test(groupId) || !/^\d+$/.test(postId)) {
      return {ok: false, reason: 'Group ID hoặc post ID không hợp lệ.'};
    }
    if (pageId !== String(expectedPageId || '')) {
      return {ok: false, reason: 'Sai Page được phép sử dụng.'};
    }
    if (deniedPostIds.map(String).includes(postId)) {
      return {ok: false, reason: 'Bài này nằm trong denylist.'};
    }
    return {ok: true, groupId, postId, pageId};
  }

  function relayProviderVariables(variables) {
    if (!variables || typeof variables !== 'object' || Array.isArray(variables)) return {};
    return Object.fromEntries(Object.entries(variables)
      .filter(([key]) => key.startsWith('__relay_internal__pv__')));
  }

  function mergeRelayProviders(current, variables) {
    return {...(current || {}), ...relayProviderVariables(variables)};
  }

  function summarizeGroupScan(groupResults, totalStories) {
    const failed = group => (group.pages || []).some(page =>
      page.status === 'FAIL' || Number(page.httpStatus || 0) >= 400 || Number(page.graphQLErrors || 0) > 0);
    const failedGroups = groupResults.filter(failed).length;
    const truncatedGroups = groupResults.filter(group => !group.completed && !failed(group)).length;
    const completedGroups = groupResults.filter(group => group.completed).length;
    const status = totalStories
      ? (failedGroups || truncatedGroups ? 'PARTIAL' : 'PASS')
      : (failedGroups ? 'FAIL' : 'INCONCLUSIVE');
    return {status, completedGroups, truncatedGroups, failedGroups};
  }

  Object.defineProperty(globalThis, '__DKTECH_PROBE_CORE__', {
    value: Object.freeze({parseDocuments, extractStoryText, extractStoryPublishedAt, queryKind, summarizeResponse,
      classifyResponse, replaceExact, hashText, validateCommentTarget, summarizeGroupScan,
      relayProviderVariables, mergeRelayProviders}),
    configurable: false,
  });
})();
