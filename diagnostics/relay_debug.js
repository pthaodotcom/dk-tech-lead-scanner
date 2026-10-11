// Paste this into the browser console on the Facebook post page
// to diagnose why feedback ID is not found.
// Make sure you're on the target post page first.

(function() {
  const postId = location.pathname.match(/\/(\d+)\/?$/)?.[1] || 'UNKNOWN';
  console.log('=== DK-Tech Relay Debug ===');
  console.log('Post ID from URL:', postId);

  // Check probe status
  const probe = window.__DKTECH_REQUEST_PROBE__;
  if (probe) {
    console.log('Probe version:', probe.version);
    const prepared = probe.prepareComment('61593769810301', 'test', {
      groupId: location.pathname.match(/\/groups\/(\d+)/)?.[1] || '',
      postId: postId,
      pageId: '61593769810301'
    });
    console.log('prepareComment result:', JSON.stringify(prepared, null, 2));
  } else {
    console.warn('Probe not found!');
  }

  // Examine Relay store
  try {
    const env = window.require('CometRelayEnvironment');
    console.log('CometRelayEnvironment found:', typeof env);
    console.log('env keys:', Object.keys(env).slice(0, 20));
    
    const store = env.getStore();
    console.log('Store found:', typeof store);
    console.log('Store keys:', Object.keys(store).slice(0, 20));
    
    const source = store.getSource();
    console.log('Source found:', typeof source);
    
    const data = source.toJSON();
    const allKeys = Object.keys(data);
    console.log('Total nodes in Relay store:', allKeys.length);
    
    // Find all nodes mentioning our post ID
    const matchingNodes = [];
    const storyNodes = [];
    const feedbackNodes = [];
    
    for (const [key, value] of Object.entries(data)) {
      if (!value || typeof value !== 'object') continue;
      
      // Collect story-type nodes
      const tn = value.__typename || '';
      if (/story|feed/i.test(tn)) {
        storyNodes.push({key, typename: tn, post_id: value.post_id, id: value.id, 
          hasFeedback: Boolean(value.feedback), feedbackRef: value.feedback?.__ref});
      }
      
      // Collect feedback nodes
      if (tn === 'Feedback' || /feedback/i.test(key)) {
        feedbackNodes.push({key, typename: tn, id: value.id});
      }
      
      // Find nodes containing our post ID
      const json = JSON.stringify(value);
      if (json.includes(postId)) {
        matchingNodes.push({key, typename: tn, post_id: value.post_id, id: value.id,
          hasFeedback: Boolean(value.feedback), feedbackRef: value.feedback?.__ref,
          keys: Object.keys(value).slice(0, 15)});
      }
    }
    
    console.log('\n--- Story-type nodes (first 10) ---');
    console.table(storyNodes.slice(0, 10));
    
    console.log('\n--- Feedback nodes (first 10) ---');
    console.table(feedbackNodes.slice(0, 10));
    
    console.log('\n--- Nodes containing post ID', postId, '---');
    console.table(matchingNodes.slice(0, 20));
    
    // Check all unique __typename values
    const typenames = new Map();
    for (const value of Object.values(data)) {
      if (value?.__typename) typenames.set(value.__typename, (typenames.get(value.__typename) || 0) + 1);
    }
    console.log('\n--- All __typename counts ---');
    console.table([...typenames.entries()].sort((a,b) => b[1]-a[1]).slice(0, 30).map(([t,c]) => ({typename: t, count: c})));
    
  } catch (e) {
    console.error('Error reading Relay store:', e);
  }

  // Check mutation artifact
  try {
    const artifact = window.require('useCometUFICreateCommentMutation.graphql');
    console.log('\n--- Mutation artifact ---');
    console.log('Has artifact:', Boolean(artifact));
    console.log('Artifact id:', artifact?.params?.id);
    
    // List all relay provider names required
    const providerNames = new Set();
    const seen = new Set();
    function walk(value, depth = 0) {
      if (!value || typeof value !== 'object' || depth > 12 || seen.has(value)) return;
      seen.add(value);
      for (const [key, child] of Object.entries(value)) {
        if (key === 'name' && typeof child === 'string' && child.startsWith('__relay_internal__pv__')) providerNames.add(child);
        walk(child, depth + 1);
      }
    }
    walk(artifact);
    console.log('Required Relay providers:', [...providerNames]);
    
    // Try to resolve each
    for (const name of providerNames) {
      const moduleName = name.slice('__relay_internal__pv__'.length);
      const providerBase = moduleName.endsWith('relayprovider')
        ? moduleName.slice(0, -'relayprovider'.length) : moduleName;
      let resolved = false;
      for (const candidate of [
        `${providerBase}.relayprovider`, moduleName, providerBase,
        `${providerBase}RelayProvider`,
        moduleName.replace(/_/g, '.'), providerBase.replace(/_/g, '.')
      ]) {
        try {
          const m = window.require(candidate);
          const p = typeof m?.get === 'function' ? m : m?.default;
          if (typeof p?.get === 'function') {
            console.log(`  ✅ ${name} -> require('${candidate}').get() =`, p.get());
            resolved = true;
            break;
          } else if (typeof m === 'boolean' || typeof m === 'number') {
            console.log(`  ✅ ${name} -> require('${candidate}') =`, m);
            resolved = true;
            break;
          }
        } catch {}
      }
      if (!resolved) console.log(`  ❌ ${name} -> NOT FOUND`);
    }
  } catch (e) {
    console.error('Mutation artifact error:', e);
  }

  console.log('\n=== End Debug ===');
})();
