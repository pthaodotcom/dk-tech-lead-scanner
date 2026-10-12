const postsNode = document.getElementById('posts');
const toastNode = document.getElementById('toast');
let bucket = 'all';
let rulesLoaded = false;
let groupsData = [];

function escapeHtml(value='') {
  return String(value).replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
}

function layaTypeLabel(type) {
  return ({service_request:'Đang tìm nhà cung cấp',recruitment:'Tuyển dụng',self_promotion:'Tự quảng cáo dịch vụ',other:'Bài khác'})[type] || '';
}

function layaStatusText(post) {
  if (post.laya_status !== 'done') return ({pending:'Đang chờ Laya',processing:'Laya đang phân loại',failed:'Laya lỗi'})[post.laya_status] || 'Chưa phân loại';
  const type = layaTypeLabel(post.laya_post_type);
  if (post.laya_bucket === 'blocked') return type ? `Chặn an toàn · ${type}` : 'Bị chặn do nội dung không an toàn';
  if (post.laya_safety_review) return `${post.laya_bucket === 'qualified' ? 'Đủ điều kiện · ' : ''}${type || 'Chưa rõ loại bài'} · cần xem lại mục đích`;
  if (type) {
    if (post.laya_bucket === 'qualified') return `Đủ điều kiện · ${type}`;
    const minimum = post.laya_post_type === 'service_request' ? Number(post.laya_post_type_minimum_confidence ?? .6) : .6;
    if (post.laya_post_type_confidence != null && Number(post.laya_post_type_confidence) < minimum) return `Nghiêng về: ${type} · cần xem lại`;
    if (post.laya_post_type === 'recruitment' || post.laya_post_type === 'self_promotion' || post.laya_post_type === 'other') return `${type} · không phải lead`;
    return `${type} · chưa đủ chắc để tự động comment`;
  }
  if (post.laya_label === 'seeking_provider') return 'Có dấu hiệu tìm nhà cung cấp · chưa đủ chắc';
  if (post.laya_label === 'not_seeking_provider') return 'Không tìm nhà cung cấp · chưa tách được loại bài';
  if (post.laya_bucket === 'blocked') return 'Bị chặn do nội dung không an toàn';
  return 'Chưa phân loại được';
}

function toast(message) {
  toastNode.textContent = message;
  toastNode.classList.add('show');
  setTimeout(() => toastNode.classList.remove('show'), 2600);
}

function renderHistory(items) {
  const rows = items;
  const node = document.getElementById('sentComments');
  if (!rows.length) { node.innerHTML = '<p class="muted">Chưa có comment tự động nào.</p>'; return; }
  node.innerHTML = rows.map(item => {
    const sent = item.status.startsWith('sent');
    const statusLabel = {sent: 'Đã gửi · đã thấy hiển thị', sent_rejected: 'Đã gửi · bị từ chối duyệt', sent_pending: 'Đã gửi · chờ duyệt', sent_unverified: 'Đã gửi · chưa xác minh hiển thị', processing: 'Đang xử lý', attempted: 'Đã thử · chưa rõ kết quả', blocked: 'Bị chặn trước gửi'}[item.status] || 'Cần kiểm tra';
    const link = item.url ? (item.comment_id ? `${item.url}?comment_id=${encodeURIComponent(item.comment_id)}` : item.url) : '';
    return `<article class="sent-item">
      <div class="sent-head"><strong>${escapeHtml(item.group_name || item.group_id)}</strong>
        <span class="pill ${sent ? 'candidate' : item.status === 'processing' ? 'uncertain' : 'blocked'}">${statusLabel}</span></div>
      <p>${escapeHtml(item.message)}</p>
      <div class="meta"><span>${escapeHtml(item.generator || 'Không rõ model')}</span><span>${new Date(item.attempted_at || item.created_at).toLocaleString('vi-VN')}</span>${item.comment_id ? `<span>ID ${escapeHtml(item.comment_id)}</span>` : ''}</div>
      ${link ? `<a href="${escapeHtml(link)}" target="_blank" rel="noreferrer">${item.comment_id ? 'Mở comment trên Facebook' : 'Mở bài Facebook'}</a>` : ''}
      ${item.error ? `<p class="history-error">${escapeHtml(item.error)}</p>` : ''}
    </article>`;
  }).join('');
}

function renderGroups(list = groupsData) {
  const tbody = document.getElementById('groupTableBody');
  if (!tbody) return;
  const term = (document.getElementById('groupSearchInput')?.value || '').trim().toLowerCase();
  const filtered = term ? list.filter(g => (g.name || '').toLowerCase().includes(term) || g.id.includes(term)) : list;

  updateGroupBadges();

  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="muted" style="text-align:center;padding:20px">Không tìm thấy nhóm phù hợp từ khóa "${escapeHtml(term)}".</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map((g, idx) => {
    const isScan = Boolean(g.scan_enabled);
    const isComment = Boolean(g.comment_enabled);
    const fbUrl = `https://www.facebook.com/groups/${g.id}/`;
    return `<tr class="${(!isScan && !isComment) ? 'group-disabled' : ''}">
      <td style="text-align:center;color:#657585">${idx + 1}</td>
      <td>
        <strong>${escapeHtml(g.name || 'Nhóm không tên')}</strong>
        <div class="group-id">ID: ${escapeHtml(g.id)}</div>
      </td>
      <td style="text-align:center">
        <input type="checkbox" class="scan-check" data-id="${g.id}" ${isScan ? 'checked' : ''} title="Bật quét bài (24h)">
      </td>
      <td style="text-align:center">
        <input type="checkbox" class="comment-check" data-id="${g.id}" ${isComment ? 'checked' : ''} title="Bật gửi comment">
      </td>
      <td style="text-align:center">${g.post_count || 0}</td>
      <td style="text-align:center">
        <a href="${escapeHtml(fbUrl)}" target="_blank" rel="noreferrer">Mở ↗</a>
      </td>
    </tr>`;
  }).join('');

  tbody.querySelectorAll('.scan-check').forEach(input => {
    input.addEventListener('change', e => {
      const gid = e.target.dataset.id;
      const grp = groupsData.find(g => g.id === gid);
      if (grp) grp.scan_enabled = e.target.checked ? 1 : 0;
      updateGroupBadges();
      e.target.closest('tr').classList.toggle('group-disabled', !grp.scan_enabled && !grp.comment_enabled);
    });
  });

  tbody.querySelectorAll('.comment-check').forEach(input => {
    input.addEventListener('change', e => {
      const gid = e.target.dataset.id;
      const grp = groupsData.find(g => g.id === gid);
      if (grp) grp.comment_enabled = e.target.checked ? 1 : 0;
      updateGroupBadges();
      e.target.closest('tr').classList.toggle('group-disabled', !grp.scan_enabled && !grp.comment_enabled);
    });
  });
}

function updateGroupBadges() {
  const scanCount = groupsData.filter(g => g.scan_enabled).length;
  const commentCount = groupsData.filter(g => g.comment_enabled).length;
  const total = groupsData.length;
  const scanEl = document.getElementById('scanEnabledCount');
  const commentEl = document.getElementById('commentEnabledCount');
  const total1El = document.getElementById('totalGroupsCount1');
  const total2El = document.getElementById('totalGroupsCount2');
  const groupStatsNode = document.getElementById('groupStatsDisplay');
  if (scanEl) scanEl.textContent = scanCount;
  if (commentEl) commentEl.textContent = commentCount;
  if (total1El) total1El.textContent = total;
  if (total2El) total2El.textContent = total;
  if (groupStatsNode) groupStatsNode.textContent = `${scanCount} / ${commentCount}`;
}

async function loadGroups() {
  try {
    const res = await fetch('/api/groups', {cache: 'no-store'});
    const data = await res.json();
    if (res.ok && Array.isArray(data.groups)) {
      groupsData = data.groups;
      renderGroups();
    }
  } catch (err) {
    console.error('Không tải được danh sách nhóm:', err);
  }
}

function render(data) {
  document.getElementById('candidateCount').textContent = data.counts.candidate || 0;
  document.getElementById('uncertainCount').textContent = data.counts.uncertain || 0;
  document.getElementById('blockedCount').textContent = data.counts.blocked || 0;
  document.getElementById('queueCount').textContent = data.queue.filter(item => ['approved','processing'].includes(item.status)).length;
  document.getElementById('sentCount').textContent = data.queue.filter(item => item.status.startsWith('sent')).length;
  if (data.groupStats) {
    const statNode = document.getElementById('groupStatsDisplay');
    if (statNode) statNode.textContent = `${data.groupStats.scanEnabled || 0} / ${data.groupStats.commentEnabled || 0}`;
  }
  renderHistory(data.queue);
  if (!rulesLoaded && data.filterRules) {
    document.getElementById('includeKeywords').value = data.filterRules.includeKeywords.join('\n');
    document.getElementById('excludeKeywords').value = data.filterRules.excludeKeywords.join('\n');
    document.getElementById('minimumMatches').value = data.filterRules.minimumMatches;
    document.getElementById('includeUnmatched').checked = data.filterRules.includeUnmatched;
    rulesLoaded = true;
  }
  document.getElementById('lastScan').textContent = data.latestScan
    ? `Lần quét gần nhất: ${new Date(data.latestScan.started_at).toLocaleString('vi-VN')} · ${data.latestScan.posts_count} bài · ${data.latestScan.new_posts} bài mới`
    : 'Chưa có lần quét nào. Hãy mở extension trong Chrome để quét.';
  const layaStatus = document.getElementById('layaStatus');
  if (layaStatus) {
    const stats = data.layaStats || {};
    const pending = (stats.pending || 0) + (stats.processing || 0);
    const failed = stats.failed || 0;
    const classifier = data.layaClassifier || {};
    const modelState = classifier.error ? 'lỗi khi tải model' : classifier.loaded ? 'đã tải model' : classifier.available ? 'model sẽ tải khi có bài' : 'chưa sẵn sàng';
    layaStatus.textContent = `Laya multilingual${classifier.postTypeTraining?.loaded ? ' · đã train loại bài' : ''} · ${modelState} · ${pending} bài đang chờ/đang xét · ${failed} lỗi`;
    if (classifier.error) layaStatus.title = classifier.error;
  }
  if (!data.posts.length) {
    postsNode.innerHTML = '<article class="post"><p>Chưa có bài trong bộ lọc này (trong vòng 24 giờ).</p></article>';
    return;
  }
  postsNode.innerHTML = data.posts.map(post => `
    <article class="post ${post.bucket === 'blocked' ? 'blocked-card' : ''}" data-id="${post.id}">
      <div>
        <h3>${escapeHtml(post.group_name || `Group ${post.group_id}`)}</h3>
        <p class="post-text">${escapeHtml(post.text || '(Bài không có nội dung chữ)')}</p>
        <div class="meta">
          <span class="pill ${post.bucket}">${post.bucket === 'candidate' ? 'Khớp từ khóa' : post.bucket === 'blocked' ? 'Đã chặn' : 'Chưa khớp từ khóa'}</span>
          <span class="pill">Điểm từ khóa ${post.score}</span>
          <span class="pill ${post.laya_bucket === 'qualified' ? 'candidate' : post.laya_bucket === 'blocked' ? 'blocked' : 'uncertain'}">Laya: ${escapeHtml(layaStatusText(post))}</span>
          ${post.laya_status === 'done' && post.laya_post_type_confidence != null ? `<span class="pill">Tin cậy loại bài ${(Number(post.laya_post_type_confidence) * 100).toFixed(0)}%</span>` : ''}
          ${post.laya_status === 'done' && post.laya_service_confidence != null ? `<span class="pill">Tin cậy dịch vụ ${(Number(post.laya_service_confidence) * 100).toFixed(0)}%</span>` : ''}
          ${post.laya_status === 'done' && post.laya_safety_confidence != null ? `<span class="pill">Tin cậy an toàn ${(Number(post.laya_safety_confidence) * 100).toFixed(0)}%</span>` : ''}
          <span class="pill">ID ${post.id}</span>
          ${post.published_at ? `<span class="pill">Đăng lúc: ${new Date(post.published_at).toLocaleString('vi-VN')}</span>` : ''}
          ${post.queue_status ? `<span class="pill">Comment: ${escapeHtml(post.queue_status)}</span>` : ''}
        </div>
        <p class="reason">${post.reasons.map(escapeHtml).join(' · ')}</p>
        ${post.laya_decision_reasons?.length ? `<p class="reason">Laya: ${post.laya_decision_reasons.map(escapeHtml).join(' · ')}</p>` : ''}
      </div>
      <div class="actions">
        <a href="${escapeHtml(post.url)}" target="_blank" rel="noreferrer">Mở bài</a>
      </div>
    </article>`).join('');
}

async function load() {
  const response = await fetch(`/api/dashboard?bucket=${encodeURIComponent(bucket)}`, {cache:'no-store'});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Không đọc được dữ liệu');
  render(data);
}

document.querySelectorAll('[data-bucket]').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('[data-bucket]').forEach(item => item.classList.remove('active'));
  button.classList.add('active');
  bucket = button.dataset.bucket;
  load().catch(error => toast(error.message));
}));
document.getElementById('refresh').addEventListener('click', () => {
  load().catch(error => toast(error.message));
  loadGroups().catch(() => {});
});
document.getElementById('clearPending').addEventListener('click', async () => {
  if (!confirm('Xóa toàn bộ bài đã quét và lượt quét cũ? Lịch sử comment, danh sách group, rule và bài denylist vẫn được giữ. Hãy dừng gửi ngầm trước.')) return;
  const response = await fetch('/api/comments/clear-pending', {
    method:'POST', headers:{'Content-Type':'application/json'}, body:'{}',
  });
  const value = await response.json();
  if (!response.ok) { toast(value.error || 'Không xóa được hàng chờ'); return; }
  toast(`Đã xóa ${value.deletedPosts} bài và ${value.deletedScans} lượt quét; lịch sử comment được giữ.`);
  await load();
  await loadGroups();
});
document.getElementById('saveRules').addEventListener('click', async () => {
  const split = value => value.split(/[\n,]+/).map(item => item.trim()).filter(Boolean);
  const response = await fetch('/api/rules', {
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      includeKeywords: split(document.getElementById('includeKeywords').value),
      excludeKeywords: split(document.getElementById('excludeKeywords').value),
      minimumMatches: Number(document.getElementById('minimumMatches').value) || 1,
      includeUnmatched: document.getElementById('includeUnmatched').checked,
    }),
  });
  const value = await response.json();
  if (!response.ok) { toast(value.error || 'Không lưu được rule'); return; }
  toast(`Đã lưu rule và đánh giá lại ${value.reevaluatedPosts} bài.`);
  await load();
});
document.getElementById('stopTool').addEventListener('click', async () => {
  if (!confirm('Dừng DK-Tech Lead Scanner trên máy này?')) return;
  await fetch('/api/shutdown', {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  document.body.innerHTML = '<main><section class="notice"><strong>Tool đã dừng.</strong><p>Chạy lại start-tool.cmd khi cần sử dụng.</p></section></main>';
});

// Group Toolbar Events
document.getElementById('groupSearchInput')?.addEventListener('input', () => renderGroups());

document.getElementById('btnPresetTech')?.addEventListener('click', () => {
  const techRegex = /(code|web|app|tool|bot|lập trình|phần mềm|cntt|it|seo|thiết kế|developer|frontend|backend|fullstack|software|automation)/i;
  let matched = 0;
  groupsData.forEach(g => {
    const isTech = techRegex.test(g.name || '');
    g.scan_enabled = isTech ? 1 : 0;
    g.comment_enabled = isTech ? 1 : 0;
    if (isTech) matched++;
  });
  renderGroups();
  toast(`Đã chọn ${matched}/${groupsData.length} nhóm Công nghệ / Web / App / Tool. Nhớ bấm "Lưu cấu hình nhóm"!`);
});

document.getElementById('btnEnableAllScan')?.addEventListener('click', () => {
  groupsData.forEach(g => { g.scan_enabled = 1; });
  renderGroups();
});

document.getElementById('btnDisableAllScan')?.addEventListener('click', () => {
  groupsData.forEach(g => { g.scan_enabled = 0; });
  renderGroups();
});

document.getElementById('btnEnableAllComment')?.addEventListener('click', () => {
  groupsData.forEach(g => { g.comment_enabled = 1; });
  renderGroups();
});

document.getElementById('btnDisableAllComment')?.addEventListener('click', () => {
  groupsData.forEach(g => { g.comment_enabled = 0; });
  renderGroups();
});

document.getElementById('btnSaveGroupConfig')?.addEventListener('click', async () => {
  const payload = {
    groups: groupsData.map(g => ({
      id: g.id,
      scan_enabled: g.scan_enabled ? 1 : 0,
      comment_enabled: g.comment_enabled ? 1 : 0,
    })),
  };
  const response = await fetch('/api/groups/config', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
  const res = await response.json();
  if (!response.ok) { toast(res.error || 'Lỗi khi lưu cấu hình nhóm'); return; }
  toast('Đã lưu cấu hình nhóm thành công!');
  await load();
  await loadGroups();
});

load().catch(error => toast(error.message));
loadGroups().catch(error => console.error(error));
