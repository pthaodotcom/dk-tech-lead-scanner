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

  function queryKind(name) {
    if (!/Query$/.test(name || '') || /Mutation/i.test(name || '')) return null;
    if (/EndOfFeedQuery/i.test(name || '')) return null;
    if (/JoinedGroups|MemberGroups|GroupsYouJoined|TabGroupList|GroupsCometJoinsRoot|AllJoinedGroupsSection/i.test(name)) {
      return 'joined_groups';
    }
    if (/GroupsComet.*Feed.*(?:Pagination)?Query/i.test(name)) return 'group_posts';
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
      const feed = /group_feed|groupFeed/i.test(path) || (kind === 'group_posts' && /Feed/i.test(name));
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
        const previous = items.get(id) || {id, text: '', textLength: 0, hasText: false, type: 'Story', occurrences: 0};
        previous.occurrences += 1;
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
      const root = label.includes('group_feed') || (kind === 'group_posts' && /Feed/i.test(name))
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

  Object.defineProperty(globalThis, '__DKTECH_PROBE_CORE__', {
    value: Object.freeze({parseDocuments, extractStoryText, queryKind, summarizeResponse,
      classifyResponse, replaceExact, hashText}),
    configurable: false,
  });
})();
