// Paste into the DevTools Console on a Facebook group tab after loading more posts.
// This reads metadata only; it does not replay requests or send comments.
(() => {
  const probe = window.__DKTECH_REQUEST_PROBE__;
  const report = {
    diagnostic: 'dktech-feed',
    recordedAt: new Date().toISOString(),
    groupId: location.pathname.match(/^\/groups\/(\d+)/)?.[1] || null,
    ...(probe?.inspect() || {
      status: 'PROBE_NOT_LOADED',
      note: 'Reload the extension and this Facebook tab, then load more posts.',
    }),
  };
  const output = JSON.stringify(report, null, 2);
  console.log(output);
  if (typeof copy === 'function') copy(output);
  return report;
})();
