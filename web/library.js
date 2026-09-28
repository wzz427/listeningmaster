/* 资料库侧边栏、上传面板、空库的播放器（SPEC-009，对外模式专用）。
 * app.js 只在服务报 copy=hosted 时叫这一层（startPage → hostedStart）；本地模式没有账号和上传，这层整个不动。
 * 给 app.js 的两个入口：hostedStart()（开页选课——回 false 表示不进播放器：跳去别的课、或一节课都没有）、
 * hostedLessonMissing()（要播的课不在了，换个去处）。
 * 学习记录的键跟 app.js 一致：listening:<课名>（进行中）、listening:<课名>:done（整集听完，app.js 在最后一段
 * 播完时写下）——进度点：空心没开始 / 半满进行中 / 实心听完。
 *
 * 2026-09-28 owner 验收后的五条（SPEC-009 v6）：登录只问邮箱密码（记住邮箱，第二次只输密码）；
 * 空库不挡路——播放器照常进场，卡片里给一句邀请，没有遮罩没有「必须先上传」；
 * 上传面板重设计——选音频的拖放区是主角、「上传」垫底通栏；讲稿是可选的文件（TXT/PDF/MD，
 * 传完还能在材料上补），不是粘贴；「来源」改叫「系列」。 */

'use strict';

const el = (id) => document.getElementById(id);
const fmtClock = (seconds) => {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
};
const fmtMB = (bytes) => `${(bytes / 1048576).toFixed(1)}MB`;
const safeGet = (key) => { try { return localStorage.getItem(key); } catch { return null; } };
const LIB_WIDE = 'listening:sidebar';   // 侧边栏开还是收：记住选择；第一次进站自动展开一次

let lib = { materials: [], lessons: [] };   // 最近一次 /api/library 的数据（课按新到旧排）
let libFetchedAt = 0;                       // 拿到这份数据的时刻（备课已用时在本地接着数，不用每秒去问）
let preppingIds = new Set();                // 上一眼里备课中的材料：用来发现「变课的那一刻」
let freshLessons = new Set();               // 刚从材料变来的课：画一次高亮
let freshMaterial = null;                   // 刚传上来的材料：画一次高亮
let pollTimer = null;
let tickTimer = null;
let pickedAudio = null;                     // 上传面板里选好的音频
let pickedScript = null;                    // 上传面板里选好的讲稿文件（可选）
let scriptFor = null;                       // 资料库里点了「＋讲稿」的是哪条材料

/* ---------- 开页：选哪一课 ---------- */

async function hostedStart() {
  wireLibrary();
  const data = await fetchLibrary();
  if (!data) return true;   // 接口暂时拿不到（掉线）：先进播放器，侧边栏等着有网再说
  lib = data;
  libFetchedAt = Date.now();
  const want = new URLSearchParams(location.search).get('lesson');
  if (want && lib.lessons.some((x) => x.lesson === want)) {
    maybeOpenSidebar();
    renderLibrary();
    return true;            // 指了课、课也在：照常进播放器
  }
  if (lib.lessons.length) {  // 没指课、或指的课不在了：跳到最新备好的一课
    location.replace(`/web/?lesson=${encodeURIComponent(lib.lessons[0].lesson)}`);
    return false;
  }
  showEmptyPlayer();         // 一节课都没有：播放器照常进场，空着摆着（不挡路、不逼着上传）
  renderLibrary();
  return false;
}

async function hostedLessonMissing() {
  const data = await fetchLibrary();
  if (data) {
    lib = data;
    libFetchedAt = Date.now();
    if (lib.lessons.length) {
      location.replace(`/web/?lesson=${encodeURIComponent(lib.lessons[0].lesson)}`);
      return;
    }
  }
  showEmptyPlayer();
  renderLibrary();
}

async function fetchLibrary() {
  try {
    const r = await fetch('/api/library', { cache: 'no-store' });
    if (r.status === 401) { location.replace('/login'); return null; }   // 会话没了
    if (!r.ok) return null;
    const data = await r.json();
    data.lessons = (data.lessons || []).sort((a, b) => (a.lesson < b.lesson ? 1 : a.lesson > b.lesson ? -1 : 0));
    return data;
  } catch {
    return null;
  }
}

/* 空库的播放器：没有遮罩、不挡路。卡片里一句邀请＋一步行动；左边资料库里可能还有材料在备。 */
function showEmptyPlayer() {
  const withMaterials = lib.materials.length > 0;
  el('emptyTitle').textContent = withMaterials ? '还没有备好的课' : '资料库还是空的';
  el('emptyText').textContent = withMaterials
    ? '已上传的材料在左边的资料库里，点「备课」，几分钟后就变成一节课。'
    : '从左边的资料库传一集 BBC 音频（mp3 和讲稿文件），点一下「备课」，几分钟就能听。';
  const btn = el('emptyAct');
  btn.textContent = withMaterials ? '打开资料库' : '上传一集';
  btn.dataset.mode = withMaterials ? 'lib' : 'upload';
  el('emptyHint').hidden = false;
  document.body.classList.add('no-lesson');
}

/* ---------- 侧边栏开合 ---------- */

/* 侧边栏的开合偏好：第一次进站自动展开一次，之后按上次的选择（只在有课可播时）。 */
function maybeOpenSidebar() {
  let remembered = null;
  try { remembered = localStorage.getItem(LIB_WIDE); } catch { /* 当第一次来 */ }
  if (remembered !== '0') setLibraryOpen(true);
}

function setLibraryOpen(open) {
  el('libPanel').hidden = !open;
  el('libMask').hidden = !open;
  el('libBtn').classList.toggle('on', open);
  try { localStorage.setItem(LIB_WIDE, open ? '1' : '0'); } catch { /* 记不住就每次自动展开 */ }
  if (open) poll();   // 打开时拿最新一眼：备课可能已经好了
}

/* ---------- 画两区 ---------- */

function renderLibrary() {
  const pageLesson = new URLSearchParams(location.search).get('lesson');

  // 先看上一眼备课中的材料有没有变课（要给高亮和顶部通知）
  const nowPrepping = new Set(lib.materials.filter((m) => m.state === 'prepping').map((m) => m.id));
  preppingIds.forEach((id) => {
    if (!nowPrepping.has(id) && lib.lessons.some((x) => x.lesson === id)) {
      freshLessons.add(id);
      const row = lib.lessons.find((x) => x.lesson === id);
      noticeSay(`备好了：${row.title}`, { label: '去听', go: () => goLesson(row.lesson) });
    }
  });
  preppingIds = nowPrepping;

  // 课区：按系列分组（窄听单元）；每行＝进度点＋标题＋（正在听的小声浪）＋时长
  const lessonBox = el('libLessonList');
  lessonBox.innerHTML = '';
  const groups = new Map();
  lib.lessons.forEach((x) => {
    const key = x.source || '其他材料';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(x);
  });
  groups.forEach((items, source) => {
    const head = document.createElement('p');
    head.className = 'lib-group';
    head.textContent = source;
    lessonBox.appendChild(head);
    items.forEach((x) => lessonBox.appendChild(lessonRow(x, pageLesson)));
  });
  el('libLessons').hidden = !lib.lessons.length;

  // 材料区：serve.py 已按状态排好（备课中最上、失败次之、未备课在后）
  const matBox = el('libMaterialList');
  matBox.innerHTML = '';
  lib.materials.forEach((m) => matBox.appendChild(materialRow(m)));
  el('libMaterials').hidden = !lib.materials.length;
  el('libEmpty').hidden = Boolean(lib.lessons.length || lib.materials.length);

  freshLessons.clear();
  freshMaterial = null;
  schedulePolling();
}

function lessonRow(x, pageLesson) {
  const row = document.createElement('div');
  const done = safeGet(`listening:${x.lesson}:done`) === '1';
  const started = !done && !!safeGet(`listening:${x.lesson}`);
  row.className = 'lib-row lesson' + (x.lesson === pageLesson ? ' current' : '')
    + (freshLessons.has(x.lesson) ? ' fresh' : '');
  row.innerHTML =
    `<span class="dot ${done ? 'full' : started ? 'half' : ''}"></span>` +
    '<span class="lib-title"></span>' +
    (x.lesson === pageLesson ? '<span class="now-bars" title="正在听这一集"><i></i><i></i><i></i></span>' : '') +
    `<span class="lib-meta">${fmtClock(x.duration)}</span>`;
  row.querySelector('.lib-title').textContent = x.title;
  row.title = x.title;
  row.onclick = () => { setLibraryOpen(false); goLesson(x.lesson); };
  return row;
}

function materialRow(m) {
  const row = document.createElement('div');
  const main = document.createElement('div');
  main.className = 'lib-main';
  const name = document.createElement('b');
  name.textContent = m.title;
  const sub = document.createElement('span');
  sub.className = 'lib-sub';
  main.append(name, sub);
  if (m.state === 'prepping') {
    row.className = 'lib-row mat prepping';
    sub.innerHTML = `备课中 · <span class="lib-elapsed" data-base="${m.prepping_for || 0}" data-at="${libFetchedAt}">0:00</span>`;
    row.insertAdjacentHTML('afterbegin', '<span class="spin" aria-label="备课中"></span>');
    row.appendChild(main);
    tickElapsed();
  } else if (m.state === 'failed') {
    row.className = 'lib-row mat failed';
    sub.textContent = m.error || '备课没成功';
    row.insertAdjacentHTML('afterbegin', '<span class="mat-warn" aria-hidden="true">!</span>');
    row.appendChild(main);
    row.appendChild(miniBtn('＋讲稿', () => { scriptFor = m.id; el('rowScriptInput').click(); }));   // 失败常因讲稿：补完就地重试
    row.appendChild(miniBtn('重试', () => prep(m.id)));
    row.appendChild(xBtn(m));
  } else {
    row.className = 'lib-row mat new';
    row.insertAdjacentHTML('afterbegin', '<span class="mat-icon" aria-hidden="true">▷</span>');
    row.appendChild(main);
    if (!m.has_script) {   // 讲稿可选；没传的给个就地补传的口，不说「必须」
      row.appendChild(miniBtn('＋讲稿', () => { scriptFor = m.id; el('rowScriptInput').click(); }));
    }
    row.appendChild(miniBtn('备课', () => prep(m.id)));
    row.appendChild(xBtn(m));
  }
  if (m.id === freshMaterial) row.classList.add('fresh');
  return row;
}

function miniBtn(label, onclick) {
  const b = document.createElement('button');
  b.className = 'mini-btn';
  b.textContent = label;
  b.onclick = onclick;
  return b;
}

function xBtn(m) {
  const b = document.createElement('button');
  b.className = 'x-btn';
  b.setAttribute('aria-label', '删除');
  b.textContent = '×';
  b.title = '删除这份材料';
  b.onclick = () => {
    if (!confirm(`删除「${m.title}」？音频和讲稿都会删掉。`)) return;
    fetch('/api/material/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ id: m.id }) })
      .then((r) => (r.ok ? poll() : r.json().then((j) => noticeSay(j.error || '没删掉，再试一次'))))
      .catch(() => noticeSay('网络没通，稍后再试'));
  };
  return b;
}

function goLesson(id) {
  const pageLesson = new URLSearchParams(location.search).get('lesson');
  if (id === pageLesson && !document.body.classList.contains('no-lesson')) return;   // 正在听这集：收起就行，别重载丢位置
  location.href = `/web/?lesson=${encodeURIComponent(id)}`;
}

/* ---------- 备课、轮询 ---------- */

function prep(id) {
  fetch('/api/prep', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id }) })
    .then(async (r) => {
      if (r.ok) { poll(); return; }   // 立刻刷新一眼：状态马上变「备课中」
      const j = await r.json().catch(() => ({}));
      noticeSay(j.error || '没成功，再试一次');
    })
    .catch(() => noticeSay('网络没通，稍后再试'));
}

function schedulePolling() {
  const busy = lib.materials.some((m) => m.state === 'prepping');
  if (busy && !pollTimer) {
    pollTimer = setInterval(poll, 2500);        // 备课中每两三秒问一眼（SPEC-009 R8）
    tickTimer = setInterval(tickElapsed, 1000);
  } else if (!busy && pollTimer) {
    clearInterval(pollTimer);
    clearInterval(tickTimer);
    pollTimer = null;
    tickTimer = null;
  }
}

async function poll() {
  const data = await fetchLibrary();
  if (!data) return;
  lib = data;
  libFetchedAt = Date.now();
  renderLibrary();
}

/* 备课已用时：服务报的秒数（prepping_for）＋距上次拿数据过了多久，本地一秒一秒数 */
function tickElapsed() {
  document.querySelectorAll('.lib-elapsed').forEach((t) => {
    const base = Number(t.dataset.base || 0);
    const at = Number(t.dataset.at || 0);
    t.textContent = fmtClock(base + (Date.now() - at) / 1000);
  });
}

/* ---------- 上传面板 ---------- */

function openUpload() {
  pickedAudio = null;
  pickedScript = null;
  el('audioInput').value = '';
  el('scriptInput').value = '';
  paintDropZone();
  el('scriptName').textContent = 'TXT · PDF · MD';
  el('scriptName').classList.remove('picked');
  el('upTitle').value = '';
  el('upSource').value = '';
  el('uploadErr').hidden = true;
  el('uploadPhase').hidden = true;
  el('uploadBar').hidden = true;
  el('uploadFill').style.width = '0';
  el('uploadSend').disabled = false;
  el('uploadPanel').hidden = false;
}

/* 选的音频行不行；没问题回 ''，有问题回一句人话 */
function audioCheck(file) {
  if (!file) return '先选一个音频文件';
  if (!/\.mp3$/i.test(file.name)) return '只收 mp3（BBC 下载的就是 mp3）';
  if (file.size > 60 * 1024 * 1024) return '文件太大了，最大 60MB';
  return '';
}

function scriptCheck(file) {
  if (!/\.(txt|pdf|md)$/i.test(file.name)) return '讲稿只收 TXT、PDF、MD 文件';
  if (file.size > 2 * 1024 * 1024) return '讲稿文件太大了，最大 2MB';
  return '';
}

/* 拖放区画成两种样子：还没选（大字邀请）／选好了（一张「票」：文件名·大小·重选） */
function paintDropZone(badText) {
  const zone = el('dropZone');
  if (badText) {
    zone.classList.remove('picked');
    el('dzTitle').textContent = badText;
    el('dzTitle').className = 'dz-title bad';
    el('dzSub').textContent = '点一下重新选 · mp3 · 最大 60MB';
    return;
  }
  if (pickedAudio) {
    zone.classList.add('picked');
    el('dzTitle').textContent = `${pickedAudio.name} · ${fmtMB(pickedAudio.size)}`;
    el('dzTitle').className = 'dz-title';
    el('dzSub').innerHTML = '选好了。点一下可以<span class="again">重新选</span>';
  } else {
    zone.classList.remove('picked');
    el('dzTitle').textContent = '把音频文件拖到这里';
    el('dzTitle').className = 'dz-title';
    el('dzSub').textContent = '或点击选择 · mp3 · 最大 60MB';
  }
}

function setAudio(file) {
  pickedAudio = file || null;
  const bad = pickedAudio ? audioCheck(pickedAudio) : '';
  paintDropZone(bad || null);
}

function sendUpload() {
  const bad = audioCheck(pickedAudio);
  if (bad) { uploadErrSay(bad); return; }
  const q = new URLSearchParams({
    filename: pickedAudio.name,
    title: el('upTitle').value.trim(),
    source: el('upSource').value.trim(),
  });
  el('uploadErr').hidden = true;
  el('uploadSend').disabled = true;
  postFile(`/api/upload?${q}`, pickedAudio, '正在传音频…', (r0) => {
    let mid = null;
    try { mid = JSON.parse(r0).material.id; } catch { /* 下面按失败说 */ }
    if (!mid) {
      uploadErrSay('没传上去，再试一次');
      el('uploadSend').disabled = false;
      return;
    }
    const done = () => {
      el('uploadPanel').hidden = true;
      freshMaterial = mid;
      setLibraryOpen(true);   // 落到材料区：打开侧边栏让他看见
      poll();
    };
    if (pickedScript) {
      const sq = new URLSearchParams({ id: mid, filename: pickedScript.name });
      postFile(`/api/material/script?${sq}`, pickedScript, '正在传讲稿…', () => done(), () => {
        // 音频已经传好了：别让他白传一遍——落库，指引到材料行上补讲稿
        el('uploadPanel').hidden = true;
        freshMaterial = mid;
        setLibraryOpen(true);
        poll();
        noticeSay('音频已传好；讲稿没传上，在资料库里这条材料上点「＋讲稿」补一个');
      });
    } else {
      done();
    }
  }, () => {
    el('uploadSend').disabled = false;
  });
}

/* 原始字节 POST（进度条要用 xhr）；onText(phase) 换进度条上那行字。
 * 回调 raw：响应文本；失败给 null。onFail 只在「音频那一步」用来恢复按钮。 */
function postFile(url, file, phase, onDone, onFail) {
  const xhr = new XMLHttpRequest();
  el('uploadBar').hidden = false;
  el('uploadPhase').hidden = false;
  el('uploadPhase').textContent = phase;
  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable) el('uploadFill').style.width = `${Math.round((e.loaded / e.total) * 100)}%`;
  };
  xhr.onload = () => {
    el('uploadPhase').hidden = true;
    if (xhr.status >= 200 && xhr.status < 300) onDone(xhr.responseText);
    else {
      let j = {};
      try { j = JSON.parse(xhr.responseText); } catch { /* 按没话处理 */ }
      uploadErrSay(j.error || '没传上去，再试一次');
      onFail && onFail();
    }
  };
  xhr.onerror = () => {
    el('uploadPhase').hidden = true;
    uploadErrSay('网络没通，稍后再试');
    onFail && onFail();
  };
  xhr.open('POST', url);
  xhr.send(file);
}

/* 资料库里「＋讲稿」：选完就地补传，传完刷新那一行 */
function uploadRowScript(file) {
  const mid = scriptFor;
  scriptFor = null;
  const bad = scriptCheck(file);
  if (bad) { noticeSay(bad); return; }
  const q = new URLSearchParams({ id: mid, filename: file.name });
  fetch(`/api/material/script?${q}`, { method: 'POST', body: file })
    .then(async (r) => {
      if (r.ok) { poll(); return; }
      const j = await r.json().catch(() => ({}));
      noticeSay(j.error || '讲稿没传上，再试一次');
    })
    .catch(() => noticeSay('网络没通，稍后再试'));
}

function uploadErrSay(text) {
  el('uploadErr').textContent = text;
  el('uploadErr').hidden = false;
}

/* ---------- 顶部通知（复用 .notices 的样式：浮在顶上正中，不推开东西） ---------- */

function noticeSay(text, action) {
  const n = document.createElement('div');
  n.className = 'notice';
  n.innerHTML = '<span></span>' + (action ? '<button class="notice-btn"></button>' : '');
  n.querySelector('span').textContent = text;
  if (action) {
    const b = n.querySelector('button');
    b.textContent = action.label;
    b.onclick = () => { n.remove(); action.go(); };
  }
  el('notices').appendChild(n);
  setTimeout(() => n.remove(), 10000);
  return n;
}

/* ---------- 接线 ---------- */

function wireLibrary() {
  el('libBtn').hidden = false;
  el('libBtn').onclick = () => setLibraryOpen(el('libPanel').hidden);
  el('libClose').onclick = () => setLibraryOpen(false);
  el('libMask').onclick = () => setLibraryOpen(false);
  el('uploadBtn').onclick = openUpload;
  el('emptyAct').onclick = () => (el('emptyAct').dataset.mode === 'lib' ? setLibraryOpen(true) : openUpload());
  el('uploadClose').onclick = () => { el('uploadPanel').hidden = true; };

  const zone = el('dropZone');
  zone.onclick = () => el('audioInput').click();
  el('audioInput').onchange = () => setAudio(el('audioInput').files[0] || null);
  ['dragover', 'dragenter'].forEach((name) => zone.addEventListener(name, (e) => {
    e.preventDefault();
    zone.classList.add('drag');
  }));
  ['dragleave', 'drop'].forEach((name) => zone.addEventListener(name, (e) => {
    e.preventDefault();
    zone.classList.remove('drag');
    if (name === 'drop') setAudio(e.dataTransfer.files[0] || null);
  }));

  el('scriptBtn').onclick = () => el('scriptInput').click();
  el('scriptInput').onchange = () => {
    pickedScript = el('scriptInput').files[0] || null;
    const bad = pickedScript ? scriptCheck(pickedScript) : '';
    if (bad) {
      el('scriptName').textContent = bad;
      el('scriptName').classList.remove('picked');
      pickedScript = null;
    } else if (pickedScript) {
      el('scriptName').textContent = `${pickedScript.name} · ${fmtMB(pickedScript.size)}`;
      el('scriptName').classList.add('picked');
    } else {
      el('scriptName').textContent = 'TXT · PDF · MD';
      el('scriptName').classList.remove('picked');
    }
  };
  el('rowScriptInput').onchange = () => {
    const f = el('rowScriptInput').files[0];
    el('rowScriptInput').value = '';
    if (f) uploadRowScript(f);
  };
  el('uploadSend').onclick = sendUpload;
  el('logoutBtn').onclick = async () => {
    try { await fetch('/api/logout', { method: 'POST' }); } catch { /* 照样走，让登录页兜着 */ }
    location.replace('/login');
  };
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (!el('uploadPanel').hidden) { el('uploadPanel').hidden = true; return; }   // 先关最上层的浮层
    if (!el('libPanel').hidden) setLibraryOpen(false);
  });
}
