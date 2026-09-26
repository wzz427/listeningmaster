/* 按句子播放的听力播放器。规格见 specs/SPEC-001-player.md（播放器）、SPEC-006（单词卡）、SPEC-007（朗读）；
 * 下面括号里的 R 编号没写规格号的都是 SPEC-001 的。
 *
 * 几条要记住的理由：
 * - 两种播法，按哪个键就是哪种（owner 2026-09-22 提出并拍板，决策 D23）：
 *   按播放键是连续播，一直往下播到段末；按上一句、下一句、重听本句、点进度条或全文里的某一句，
 *   只播那一句，播完停在句末；停在句末再按播放，从下一句接着连续播。
 *   孩子按「重听」「上一句」就是想抠这一句，不该一直往下跑。原来设置里的「每句播完停一下」因此删了。
 * - 正文按话题分成两分钟左右一段（D22）。进度条一条：只画当前这段，每一小段是一句话，颜色区分说话人
 *   （R15）。原来上面还有一条整集的分段条，2026-09-26 删了（owner：听当前段用不到后面每段多长，
 *   跳别的段用「全文」和段末的「听下一段」）；位置信息合并成卡片上方一行（说话人 + 段标题 + 第几句）。
 * - 一段播完就停，给「这段再听一遍」「听下一段」两个选择；片头播完不停，直接进正文（R21）。
 * - 需要停在句末时，提前几十毫秒把音量渐弱到零再停，不然会带进下一句开头的声音。
 *   有十几处两句贴得太紧，句子边界挪到哪都不够，只能靠这里收得准（见 docs/lessons.md）。
 * - 重听有 1 秒的反应延迟保护：人按键慢半拍，不保护就总跳错句（R3）。
 * - 速度只归用户：0.6 / 0.8 / 1.0 手动切，任何操作都不自动改（owner 2026-09-26：不要自己跳来跳去）；
 *   看过文字后亮起「重听本句」提醒回听（R6，决策 D7 的提醒；原速再听一遍按钮并进来了）。
 * - 进度条能拖（R23）：拖的时候声音先停；松手后原来在播就按原来的播法接着播，暂停着就停在那儿。
 * - 文字默认不显示，显示时给整句；看了文字就停在这句末尾，方便他读、点词、重听（R5、D17）。
 * - 中文藏在看过英文之后（R7b）。不问孩子懂没懂，只记他的动作（R9）。
 * - 换版本（SPEC-008）：开着的这一页知道自己旧了、页面上的「更新」，见文件末尾「换版本」一节。
 */

const LESSON = new URLSearchParams(location.search).get('lesson') || '260821';
const BASE = `../lessons/${LESSON}/`;
const OUTSIDE = '片头片尾';
const BACK_GRACE = 1.0;   // 本句才播了这么久以内按重听，视为想听上一句
const FADE = 0.04;        // 停之前渐弱这么久（秒）
const FADE_IN = 0.015;    // 每次开始播渐强这么久，免得跳转时「啪」一声

const $ = (id) => document.getElementById(id);
const audio = $('audio');

let lesson = null;
let body = [];            // 正文句子（不含片头片尾）
let idx = 0;              // 当前是 lesson.sentences 的第几句
let rate = 1;
let records = {};
let stopAt = null;        // 这次播放要在哪一秒停（null 表示不停）
let stopKind = null;      // 'sentence'：只播一句，停在句末
let fadedFor = null;      // 已经为哪个停点安排过渐弱
let atSentenceEnd = false;
let atSectionEnd = false; // 停在一段的末尾，卡片上换成「这段再听一遍 / 听下一段」
let ctx = null;
let gain = null;
const speakerClass = {};  // 说话人 → 'a' / 'b'
let parts = [];           // 按时间顺序：片头、正文第 1 段 … 第 N 段、片尾（内部用：分段、跳段、画这一段）
let partOf = [];          // 第 i 句属于 parts 的哪一项
let shownPart = -1;       // 进度条现在画的是哪一项

/* ---------- 启动 ---------- */

async function boot() {
  lesson = await (await fetch(BASE + 'lesson.json')).json();
  loadNotes();
  body = lesson.sentences.filter((s) => s.speaker !== OUTSIDE);
  body.forEach((s) => {
    if (!(s.speaker in speakerClass)) speakerClass[s.speaker] = Object.keys(speakerClass).length ? 'b' : 'a';
  });
  buildParts();
  audio.addEventListener('loadedmetadata', () => {
    render();
    if (audio.currentTime === 0) audio.currentTime = cur().start;  // 显示第 1 句，播放也从第 1 句开始
  });
  audio.src = BASE + lesson.audio;
  audio.preservesPitch = true;
  $('title').textContent = lesson.title || '听力练习';
  $('source').textContent = lesson.source || '';
  records = readJSON(recordKey(), {});
  buildLegend();
  buildFullText();
  idx = Math.max(0, lesson.sentences.indexOf(body[0]));
  backToPlace();
  setRate(1);
  render();
  requestAnimationFrame(tick);
}

const recordKey = () => `listening:${LESSON}`;
const settingKey = (name) => `listening:${LESSON}:${name}`;
const cur = () => lesson.sentences[idx];
const cls = (s) => (s.speaker === OUTSIDE ? 'o' : speakerClass[s.speaker] || 'o');
const part = (i = idx) => parts[partOf[i]];
const isSectionLast = (i = idx) => part(i).kind === 'section' && part(i).last === i;

function readJSON(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) || fallback; } catch { return fallback; }
}

function record(patch, sentence = cur()) {
  const old = records[sentence.id] || { replays: 0, sawText: false, sawZh: false, words: [] };
  records[sentence.id] = Object.assign({}, old, patch(old));
  localStorage.setItem(recordKey(), JSON.stringify(records));
  markStuck();
}

/* ---------- 分段：片头、正文各段、片尾 ---------- */

function buildParts() {
  const n = lesson.sentences.length;
  const at = (id) => lesson.sentences.findIndex((s) => s.id === id);
  let sections = (lesson.sections || []).map((x) => ({ first: at(x.first), title: x.title }))
    .filter((x) => x.first >= 0);
  if (!sections.length) {  // 旧的课程文件没有分段：整集正文算一段
    sections = [{ first: lesson.sentences.indexOf(body[0]), title: lesson.title || '' }];
  }
  const bodyLast = lesson.sentences.indexOf(body[body.length - 1]);
  // 每段到下一段开头之前为止，夹在中间的片头片尾句也归它，保证每一句都有归属
  sections.forEach((x, k) => { x.last = k + 1 < sections.length ? sections[k + 1].first - 1 : bodyLast; });
  parts = [];
  if (sections[0].first > 0) parts.push({ kind: 'intro', first: 0, last: sections[0].first - 1, title: '片头' });
  sections.forEach((x, k) => parts.push({ kind: 'section', n: k + 1, first: x.first, last: x.last, title: x.title }));
  if (bodyLast < n - 1) parts.push({ kind: 'outro', first: bodyLast + 1, last: n - 1, title: '片尾' });
  parts.forEach((p) => {
    p.t0 = lesson.sentences[p.first].start;
    p.t1 = lesson.sentences[p.last].end;
  });
  partOf = lesson.sentences.map((_, i) => parts.findIndex((p) => i >= p.first && i <= p.last));
}

/* 下一段正文；已经是最后一段，就回到第 1 段 */
function nextSection() {
  const k = partOf[idx];
  return parts.find((p, j) => j > k && p.kind === 'section') || parts.find((p) => p.kind === 'section');
}

const isLastSection = () => part().kind === 'section' && nextSection().n <= part().n;

/* ---------- 声音：渐强、渐弱、准点停 ---------- */

function ensureGraph() {
  if (!ctx) {
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    gain = ctx.createGain();
    ctx.createMediaElementSource(audio).connect(gain).connect(ctx.destination);
  }
  if (ctx.state === 'suspended') ctx.resume();
}

function rampGain(to, seconds) {
  if (!gain) return;
  const now = ctx.currentTime;
  gain.gain.cancelScheduledValues(now);
  gain.gain.setValueAtTime(gain.gain.value, now);
  gain.gain.linearRampToValueAtTime(to, now + Math.max(0.005, seconds));
}

function start(seconds, { stop = null, kind = null } = {}) {
  ensureGraph();
  atSentenceEnd = false;
  atSectionEnd = false;
  stopAt = stop;
  stopKind = kind;
  fadedFor = null;
  if (gain) gain.gain.setValueAtTime(0, ctx.currentTime);
  audio.currentTime = seconds;
  audio.playbackRate = rate;
  audio.play();
  rampGain(1, FADE_IN);
}

function resume() {
  ensureGraph();
  if (stopKind === 'sentence') {  // 按播放就是连续播：只播一句的停点作废
    stopAt = null;
    stopKind = null;
    fadedFor = null;
  }
  if (gain) gain.gain.setValueAtTime(0, ctx.currentTime);
  audio.play();
  rampGain(1, FADE_IN);
}

/* 每一帧：该停就停，跟上当前是第几句，画进度 */
function tick() {
  const t = scrub && scrub.moved ? scrub.t : audio.currentTime;  // 正在拖：画拖到的位置

  if (!audio.paused) {
    // 只播一句时 stopAt 就是句末。连续播时也有两种情况停在这句末尾：
    // 他点开了文字（卡在这句了，接着播文字两秒就被冲掉，R17）；这句是一段的最后一句（R21）
    const target = stopAt !== null ? stopAt
      : (!$('text').hidden || isSectionLast()) ? cur().end : null;
    if (target !== null) {
      const remain = (target - t) / audio.playbackRate;
      if (fadedFor !== target && remain <= FADE + 0.025) {
        rampGain(0, remain);
        fadedFor = target;
      }
      if (remain <= 0.004) reachStop();
    }
  }

  if (!audio.paused) {
    const here = lesson.sentences.findIndex((s) => t >= s.start && t < s.end);
    if (here >= 0 && here !== idx) {
      idx = here;
      hideText();
      render();
    }
  }

  drawProgress(t);
  highlightSpeaking(t);
  requestAnimationFrame(tick);
}

function reachStop() {
  const kind = stopKind || 'flow';  // 'flow'：连续播时停下（看着文字，或到了段末）
  audio.pause();
  stopAt = null;
  stopKind = null;
  fadedFor = null;
  atSentenceEnd = true;
  // 一段听完才换成「这段再听一遍 / 听下一段」；一句一句听到段末不换，免得挡住看文字
  atSectionEnd = kind === 'flow' && isSectionLast();
  render();
}

/* ---------- 跳句：两种播法 ---------- */

const clampIndex = (i) => Math.max(0, Math.min(lesson.sentences.length - 1, i));

/* 只播第 i 句，播完停在句末：上一句、下一句、点进度条上的一句、点全文里的一句 */
function playOne(i) {
  idx = clampIndex(i);
  hideText();
  start(cur().start, { stop: cur().end, kind: 'sentence' });
  render();
  flashSegment(idx);
}

/* 从第 i 句开始连续往下播：停在句末按播放、点整集那条上的一段、这段再听一遍、听下一段 */
function playFrom(i) {
  idx = clampIndex(i);
  hideText();
  start(cur().start);
  render();
  flashSegment(idx);
}

function replayCurrent() {
  const played = audio.currentTime - cur().start;
  if (!atSentenceEnd && !audio.paused && played >= 0 && played < BACK_GRACE && idx > 0) {
    idx -= 1;  // 刚换句就按，说明想听的是刚才那句
    hideText();
  }
  record((old) => ({ replays: old.replays + 1 }));
  start(cur().start, { stop: cur().end, kind: 'sentence' });  // 重听只播这一句
  render();
  flashSegment(idx);
}

/* 播放键：在播就暂停；停着就连续往下播 */
function togglePlay() {
  if (!audio.paused) {
    audio.pause();
  } else if (atSectionEnd) {
    playFrom(nextSection().first);  // 一段听完，按播放就是听下一段
  } else if (atSentenceEnd) {
    playFrom(idx + 1);   // 停在句末，按播放就从下一句接着连续播
  } else {
    resume();
  }
  render();
}

function setRate(value) {
  rate = value;
  audio.playbackRate = rate;
  document.querySelectorAll('.speed-btn').forEach((b) => {
    b.classList.toggle('on', Number(b.dataset.rate) === rate);
  });
}

/* ---------- 画面 ---------- */

function render() {
  const s = cur();
  const p = part();
  if (partOf[idx] !== shownPart) buildTimeline();
  const playing = !audio.paused;
  const last = isLastSection();
  document.body.classList.toggle('playing', playing);
  $('speaker').textContent = s.speaker;
  $('avatar').textContent = s.speaker === OUTSIDE ? '♪' : s.speaker.slice(0, 1);
  $('avatar').className = `avatar ${cls(s)}`;
  // 位置一行（owner 2026-09-26 两轮）：左边谁在说；右边在哪一段（段号+标题+第几句），
  // 段名和段号、句数是一组，不跟在人名后面
  $('counter').textContent = p.kind === 'section' ? `第 ${p.n} 段 · ${p.title}` : `${p.title}，不算正文`;
  $('partTitle').textContent = p.kind === 'section' ? `第 ${idx - p.first + 1} 句 / 共 ${p.last - p.first + 1} 句` : '';
  $('partTitle').hidden = p.kind !== 'section';
  const k = partOf[idx];
  $('prevPartBtn').disabled = k <= 0;
  $('nextPartBtn').disabled = k >= parts.length - 1;
  const partName = (q) => (q.kind === 'section' ? `第 ${q.n} 段` : q.title);
  $('prevPartBtn').title = k > 0 ? `上一段：${partName(parts[k - 1])}` : '';
  $('nextPartBtn').title = k + 1 < parts.length ? `下一段：${partName(parts[k + 1])}` : '';
  // 矢量图标不认 .hidden 属性，要直接改 hidden 这个标记
  $('iconPlay').toggleAttribute('hidden', playing);
  $('iconPause').toggleAttribute('hidden', !playing);
  $('playLabel').textContent = playing ? '暂停'
    : atSectionEnd ? (last ? '从头听' : '下一段') : '播放';

  // 状态牌说清楚现在是哪种播法、播完会不会停
  const tag = $('stateTag');
  const [label, stop] = playing
    ? (stopKind === 'sentence' ? ['只播这一句', true]
      : !$('text').hidden ? ['这句播完会停', true]
      : isSectionLast() ? ['这段播完会停', true]
      : ['连续播放', false])
    : (atSectionEnd ? ['这段听完了', true]
      : atSentenceEnd ? ['停在这句末尾', true]
      : ['暂停中', false]);
  tag.textContent = label;
  tag.classList.toggle('stop', stop);

  // 一段听完：卡片上换成两个选择；他点开了文字就先让他看文字
  const ending = atSectionEnd && $('text').hidden;
  $('sectionEnd').hidden = !ending;
  $('cardActions').hidden = ending;
  $('hint').hidden = ending || !$('text').hidden;
  if (ending) {
    $('endTitle').textContent = last ? '这集听完了' : `第 ${p.n} 段听完了`;
    $('endNext').textContent = last ? '想再练哪一段，点下面的段号' : `下一段：${nextSection().title}`;
    $('nextSectionBtn').innerHTML = `${last ? '从第 1 段开始' : '听下一段'} <kbd>空格</kbd>`;
  }

  document.querySelectorAll('.seg').forEach((el) => {
    el.classList.toggle('current', Number(el.dataset.i) === idx);
  });
  document.querySelectorAll('#fullList li.line').forEach((li) => {
    li.classList.toggle('current', Number(li.dataset.i) === idx);
  });
}

function drawProgress(t) {
  const p = parts[shownPart];
  if (!p) return;
  const span = p.t1 - p.t0;
  const into = Math.max(0, Math.min(span, t - p.t0));
  $('playhead').style.left = `${(into / span) * 100}%`;
  $('timeNow').textContent = clock(into);
  document.querySelectorAll('.seg').forEach((el) => {
    el.classList.toggle('past', lesson.sentences[Number(el.dataset.i)].end <= t);
  });
}

function clock(seconds) {
  if (!isFinite(seconds)) return '0:00';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

function showText() {
  const s = cur();
  const el = $('text');
  el.innerHTML = '';
  s.words.forEach((w, i) => {
    if (i > 0) el.appendChild(document.createTextNode(' '));
    const tag = document.createElement('w');
    tag.textContent = w.text;
    const g = lesson.glossary[w.key];
    if (g && g.hard) tag.classList.add('hard');
    tag.onclick = (e) => openWord(i, e.currentTarget);
    el.appendChild(tag);
  });
  el.hidden = false;
  $('hint').hidden = true;
  // 看过文字说明卡在这句了：亮起「重听本句」提醒回听（R6，决策 D7 的提醒；
  // 速度归用户，不自动回原速——原来单独的「原速再听一遍」按钮并进来了，owner 2026-09-26）
  const replay = $('replayBtn');
  replay.classList.remove('nudge');
  void replay.offsetWidth;
  replay.classList.add('nudge');
  $('zhBtn').hidden = false;
  $('textBtn').innerHTML = '收起文字 <kbd>T</kbd>';
  record(() => ({ sawText: true }));
  // 看了文字说明卡在这句了：连续播时这句播完就停（在 tick 里判断），让他读、点词、重听
  render();
}

function hideText() {
  $('text').hidden = true;
  $('zh').hidden = true;
  $('hint').hidden = false;
  $('replayBtn').classList.remove('nudge');
  $('zhBtn').hidden = true;
  $('zhBtn').textContent = '看中文';
  $('textBtn').innerHTML = '看文字 <kbd>T</kbd>';
  $('wordbox').hidden = true;
}

function highlightSpeaking(t) {
  if ($('text').hidden) return;
  const words = cur().words;
  const tags = $('text').querySelectorAll('w');
  tags.forEach((tag, i) => {
    const w = words[i];
    tag.classList.toggle('speaking', !audio.paused && !!w && t >= w.start && t < w.end);
  });
}

/* ---------- 进度：当前这段，每一小段是一句 ---------- */

function buildTimeline() {
  shownPart = partOf[idx];
  const p = parts[shownPart];
  const span = p.t1 - p.t0;
  const box = $('segments');
  box.innerHTML = '';
  for (let i = p.first; i <= p.last; i++) {
    const s = lesson.sentences[i];
    const seg = document.createElement('div');
    seg.className = `seg ${cls(s)}`;
    seg.dataset.i = i;
    seg.style.left = `${((s.start - p.t0) / span) * 100}%`;
    seg.style.width = `max(3px, calc(${((s.end - s.start) / span) * 100}% - 2px))`;
    box.appendChild(seg);
  }
  box.classList.remove('swap');
  void box.offsetWidth;
  box.classList.add('swap');
  $('timeTotal').textContent = clock(span);
  markStuck();
}

function markStuck() {
  const stuck = (i) => {
    const r = records[lesson.sentences[i].id];
    return !!r && r.replays > 0;
  };
  document.querySelectorAll('.seg').forEach((el) => el.classList.toggle('stuck', stuck(Number(el.dataset.i))));
  document.querySelectorAll('#fullList li.line').forEach((li) => li.classList.toggle('stuck', stuck(Number(li.dataset.i))));
}

function sentenceAt(clientX) {
  const p = parts[shownPart];
  const rect = $('timeline').getBoundingClientRect();
  const t = p.t0 + ((clientX - rect.left) / rect.width) * (p.t1 - p.t0);
  let best = p.first;
  let bestGap = Infinity;
  for (let i = p.first; i <= p.last; i++) {
    const s = lesson.sentences[i];
    const gap = t < s.start ? s.start - t : t > s.end ? t - s.end : 0;
    if (gap < bestGap) { best = i; bestGap = gap; }
  }
  return best;
}

function flashSegment(i) {
  const el = document.querySelector(`.seg[data-i="${i}"]`);
  if (!el) return;
  el.classList.remove('flash');
  void el.offsetWidth;
  el.classList.add('flash');
}

function buildLegend() {
  const legend = $('legend');
  legend.innerHTML = '';
  Object.entries(speakerClass).forEach(([name, c]) => {
    legend.insertAdjacentHTML('beforeend',
      `<span><i style="background:var(--spk-${c})"></i>${name}</span>`);
  });
  legend.insertAdjacentHTML('beforeend', '<span><i class="stuck-dot"></i>重听过的句子</span>');
}

/* 指到条上：提示指着的是第几句、从哪儿开始；正在拖时写拖到的时间（和右下角的时间一样） */
function showTip(clientX) {
  const dragging = scrub && scrub.moved;
  const i = dragging ? idx : sentenceAt(clientX);
  const s = lesson.sentences[i];
  const p = parts[shownPart];
  const tip = $('tip');
  const rect = $('timeline').getBoundingClientRect();
  const at = dragging ? scrub.t : s.start;
  tip.innerHTML = `<b>第 ${i - p.first + 1} 句</b>${s.speaker === OUTSIDE ? '' : s.speaker} · ${clock(at - p.t0)}`;
  tip.style.left = `${Math.min(rect.width - 70, Math.max(70, clientX - rect.left))}px`;
  tip.hidden = false;
  document.querySelectorAll('.seg.hover').forEach((el) => el.classList.remove('hover'));
  const seg = document.querySelector(`.seg[data-i="${i}"]`);
  if (seg) seg.classList.add('hover');
}

function hideTip() {
  $('tip').hidden = true;
  document.querySelectorAll('.seg.hover').forEach((el) => el.classList.remove('hover'));
}

$('timeline').addEventListener('pointermove', (e) => {
  if (!(scrub && scrub.moved)) showTip(e.clientX);  // 正在拖：由 moveScrub 算完位置再写
});
$('timeline').addEventListener('pointerleave', hideTip);
$('timeline').addEventListener('click', (e) => { if (!justDragged()) playOne(sentenceAt(e.clientX)); });

/* ---------- 拖进度（R23） ----------
 * 按下后挪过 4 像素才算拖，不然还是「点」（R15）。
 * 拖的时候声音先停：一边拖一边放原来位置的声音，屏幕上的句子和耳朵听到的对不上。
 * 松手：原来在播，就从落点按原来的播法接着播——连续播的接着连续播；只播一句的播到落点那句的句末停
 * （孩子拖回去多半是想把这句里没听清的几个词再听一遍）。原来暂停着，就停在落点不播（owner 2026-09-24）。
 */

const DRAG_FROM = 4;      // 按下后挪过这么多像素才算拖
let scrub = null;         // 正在拖：{ el, id, x0, moved, t, wasPlaying, oneSentence }
let draggedAt = -1e9;     // 上一次松手的时刻：紧跟着的那次 click 不算点

const justDragged = () => performance.now() - draggedAt < 400;

/* 横坐标 → 这一段里的时间 */
function timeOnTimeline(clientX) {
  const p = parts[shownPart];
  const rect = $('timeline').getBoundingClientRect();
  const f = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
  return Math.min(p.t0 + f * (p.t1 - p.t0), p.t1 - 0.01);  // 拖到最右端也还在这一段里
}

/* 落在哪一句：正在说的那句；落在两句之间的空当，算接下来那句 */
function sentenceAtTime(t, from = 0, to = lesson.sentences.length - 1) {
  for (let i = from; i <= to; i++) if (t < lesson.sentences[i].end) return i;
  return to;
}

function beginScrub(e) {
  if (e.button !== 0 || !lesson || updating) return;
  scrub = { el: e.currentTarget, id: e.pointerId, x0: e.clientX, moved: false };
}

function moveScrub(e) {
  if (!scrub || e.pointerId !== scrub.id) return;
  if (!scrub.moved) {
    if (Math.abs(e.clientX - scrub.x0) < DRAG_FROM) return;
    scrub.moved = true;
    scrub.el.setPointerCapture(e.pointerId);
    scrub.wasPlaying = !audio.paused;
    scrub.oneSentence = stopKind === 'sentence';
    atSentenceEnd = false;  // 状态牌别再写「停在这句末尾」
    atSectionEnd = false;
    audio.pause();
    $('wordbox').hidden = true;
    document.body.classList.add('scrubbing');
  }
  scrub.t = timeOnTimeline(e.clientX);
  const p = parts[shownPart];
  const i = sentenceAtTime(scrub.t, p.first, p.last);
  if (i !== idx) {
    idx = i;
    hideText();
    render();
  }
  showTip(e.clientX);
}

function endScrub(e) {
  if (!scrub || e.pointerId !== scrub.id) return;
  const s = scrub;
  scrub = null;
  if (!s.moved) return;  // 没拖动：是一次点，交给 click
  draggedAt = performance.now();
  document.body.classList.remove('scrubbing');
  if (s.wasPlaying) {
    start(s.t, s.oneSentence ? { stop: cur().end, kind: 'sentence' } : {});
  } else {
    atSentenceEnd = false;
    atSectionEnd = false;
    stopAt = null;
    stopKind = null;
    fadedFor = null;
    audio.currentTime = s.t;  // 暂停着：只挪位置，不播
  }
  render();
}

['pointerdown', 'pointermove', 'pointerup', 'pointercancel'].forEach((name) =>
  $('timeline').addEventListener(name, name === 'pointerdown' ? beginScrub : name === 'pointermove' ? moveScrub : endScrub));

/* ---------- 单词 ---------- */

/* 点词：看这个词在这句里的中文意思，听朗读。
 * 原来还有「这句里的原声」，2026-09-22 拿掉了（决策 D24）：识别给的词时间偏晚、每个词偏得不一样，
 * 在真的 Chrome 里录下放出来的声音交给机器耳朵听，切出来的大多是半个词加下一个词的开头。
 * 想听这个词在句子里怎么读，看着文字按「重听本句」：正在读的词会亮，还能放慢。 */
/* 点词的讲解分两步（决策 D30，owner 2026-09-22）：
 * 点词先出一行，像词典的词条：词性、英式音标、这句里的中文意思。备课时每个词都写好了（lesson.json 每句的 notes），
 * 点了马上出来；备课漏了的，点了再让本地服务补查。
 * 点「展开」才去查常见意思（标出这句用的是哪个）、常见搭配、例句（决策 D29）：点展开的更少，不该每个词都写。
 * 查过的服务那边存着，再点马上出来。
 * 词属于词组（cut down on）时，点其中哪个词都讲整个词组、读整个词组，词组里的词一起亮。 */
const notes = {};         // '句子id:词序号' → 那一行（展开过的带着 detail）
let asking = 0;           // 连着点了几个词，只认最后一个的结果
let shown = null;         // 单词卡上现在是哪一句的哪个词：{ s, i, note }

function loadNotes() {
  lesson.sentences.forEach((s) => (s.notes || []).forEach((note) => {
    note.words.forEach((k) => { notes[`${s.id}:${k}`] = note; });
  }));
}

async function api(path, body) {
  const r = await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(Object.assign({ lesson: LESSON }, body)),
  });
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}

function openWord(i, tag) {
  const s = cur();
  const w = s.words[i];
  const clean = w.text.replace(/^[^A-Za-z']+|[^A-Za-z']+$/g, '');
  const ticket = ++asking;
  showNote(s, i, { words: [i], text: clean, loading: true });
  $('wordbox').hidden = false;
  placeWordbox(tag);
  record((old) => ({ words: old.words.indexOf(w.key) < 0 ? old.words.concat(w.key) : old.words }));
  const known = notes[`${s.id}:${i}`];
  if (known) { showNote(s, i, known); return; }
  api('/api/explain', { sentence: s.id, word: i }).then((note) => {
    note.words.forEach((k) => { notes[`${s.id}:${k}`] = note; });
    if (ticket === asking && cur() === s && !$('wordbox').hidden) showNote(s, i, note);
  }).catch(() => {
    if (ticket !== asking) return;
    $('wordZh').textContent = '没查到，点这里再试一次';
    $('wordZh').className = 'word-zh retry';
    $('wordZh').onclick = () => openWord(i, tag);
  });
}

/* 把那一行填进单词卡；loading 表示还在查 */
function showNote(s, i, note) {
  const members = note.words.length > 1 ? note.words : [i];
  const tags = document.querySelectorAll('#text w');
  document.querySelectorAll('.sentence w.picked').forEach((el) => el.classList.remove('picked'));
  members.forEach((k) => tags[k] && tags[k].classList.add('picked'));
  shown = { s, i, note };
  $('wordText').textContent = note.text;
  const pos = note.loading ? '' : note.pos || '';
  $('wordPos').textContent = pos;
  $('wordPos').className = /[一-鿿]/.test(pos) ? 'word-pos cn' : 'word-pos';  // 词组、名字、缩写
  $('wordPos').hidden = !pos;
  $('wordIpa').textContent = note.loading ? '' : note.ipa || '';
  $('wordIpa').hidden = note.loading || !note.ipa;
  $('wordZh').textContent = note.loading ? '正在查' : note.zh;
  $('wordZh').className = note.loading ? 'word-zh loading' : 'word-zh';
  $('wordZh').onclick = null;
  $('wordHard').hidden = !members.some((k) => (lesson.glossary[s.words[k].key] || {}).hard);
  $('wordMore').hidden = true;
  $('wordMoreBtn').hidden = !!note.loading || note.more === false;  // 人名这类不用展开
  $('wordMoreBtn').textContent = '展开';
  $('wordMoreBtn').setAttribute('aria-expanded', 'false');
  if (note.detail) fillMore(note.detail);
  // 单个词先用发音词典里的；词组和词典里没有的，点了再让本地服务现读
  const key = members.length > 1 ? note.text : s.words[i].key;
  $('wordTts').hidden = false;
  $('wordTts').onclick = () => speakKey(key.toLowerCase(), note.text);
  if (!$('wordbox').hidden) placeWordbox(tags[members[0]]);
}

/* 点了「展开」才去查；查过的（这个词组里点哪个词都算）直接显示 */
function loadMore(at) {
  $('moreBody').hidden = true;
  $('moreWait').hidden = false;
  $('moreWait').textContent = '正在查';
  $('moreWait').className = 'more-wait loading';
  $('moreWait').onclick = null;
  api('/api/more', { sentence: at.s.id, word: at.i }).then((detail) => {
    at.note.detail = detail;
    if (shown === at && !$('wordbox').hidden) fillMore(detail);
  }).catch(() => {
    if (shown !== at) return;
    $('moreWait').textContent = '没查到，点这里再试一次';
    $('moreWait').className = 'more-wait retry';
    $('moreWait').onclick = () => loadMore(at);
  });
}

function fillMore(more) {
  const esc = (t) => String(t || '').replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  $('moreSenses').innerHTML = (more.senses || []).map((x, k) => (k + 1 === more.used
    ? `<li class="used">${esc(x)}<em>这句用的</em></li>` : `<li>${esc(x)}</li>`)).join('');
  $('moreColl').innerHTML = (more.collocations || [])
    .map((c) => `<li><b>${esc(c.en)}</b><span>${esc(c.zh)}</span></li>`).join('');
  const ex = more.example || {};
  $('moreEx').innerHTML = ex.en ? `<b>${esc(ex.en)}</b><span>${esc(ex.zh)}</span>` : '';
  $('moreWait').hidden = true;
  $('moreBody').hidden = false;
}

/* 优先弹在词的上方，别盖住下面的中文和按钮；空间紧就贴近一点，实在放不下再放下方。
 * 位置只在点开这个词的时候定一次；之后展开、收起、查回来都不挪（owner 2026-09-26：一跳体验很差）。
 * 放不下屏幕时不再挪位置，而是把卡片最高到多少定死，展开的内容在里面滚动（word-more） */
function placeWordbox(tag) {
  const box = $('wordbox');
  box.dataset.for = Array.prototype.indexOf.call(document.querySelectorAll('#text w'), tag);
  const r = tag.getBoundingClientRect();
  const width = box.offsetWidth;
  box.style.left = `${Math.min(window.innerWidth - width - 16, Math.max(16, r.left + r.width / 2 - width / 2))}px`;
  const h = box.offsetHeight;
  const room = r.top - h;
  if (room >= 12) box.style.top = `${room - Math.min(14, room - 4)}px`;
  else if (r.bottom + 14 + h <= window.innerHeight - 12) box.style.top = `${r.bottom + 14}px`;
  else box.style.top = `${Math.max(12, window.innerHeight - h - 12)}px`;
  const top = parseFloat(box.style.top);
  box.style.maxHeight = `${Math.max(180, window.innerHeight - top - 12)}px`;
}

/* 卡片高度变了（查回来了），也不用挪：owner 2026-09-26 定的，展开就原地变高、遮住词也不动。
 * 放不下屏幕时贴着底、里面滚动，位置仍不动（placeWordbox 里定好的 maxHeight 兜着） */

$('wordMoreBtn').onclick = () => {
  const open = $('wordMore').hidden;
  $('wordMore').hidden = !open;
  $('wordMoreBtn').textContent = open ? '收起' : '展开';
  $('wordMoreBtn').setAttribute('aria-expanded', String(open));
  if (open && shown && !shown.note.detail) loadMore(shown);
};

/* 朗读：单个词放备课时从发音词典拷来的谷歌英音；词组和词典里没有的，本地服务让百炼 Emily 现读、存下来（决策 D27）。
 * 不用浏览器自带的朗读：用哪个声音随浏览器和系统变，owner 的 Chrome 挑中的是谷歌的联网声音，
 * 中国大陆不翻墙读不出来（demand.md 的网络约束）。 */
const voice = new Audio();

async function speakKey(key, text) {
  if (!audio.paused) {  // 句子正在放就先停下，两个声音叠在一起听不清
    audio.pause();
    render();
  }
  let file = lesson.tts.files[key];
  if (!file) {
    $('wordTts').classList.add('busy');
    try {
      file = (await api('/api/speak', { key, text })).file;
      lesson.tts.files[key] = file;
    } catch (e) {
      return;
    } finally {
      $('wordTts').classList.remove('busy');
    }
  }
  voice.src = BASE + file;
  voice.play().catch(() => {});
}

/* ---------- 全文：按段列出每一句，点一句只播这一句 ---------- */

function buildFullText() {
  const list = $('fullList');
  list.innerHTML = '';
  parts.forEach((p) => {
    const head = document.createElement('li');
    head.className = `group ${p.kind}`;
    head.innerHTML = '<span class="g-no"></span><span class="g-title"></span>';
    head.querySelector('.g-no').textContent = p.kind === 'section' ? `第 ${p.n} 段` : p.title;
    head.querySelector('.g-title').textContent = p.kind === 'section' ? p.title : '不算正文';
    list.appendChild(head);
    for (let i = p.first; i <= p.last; i++) {
      const s = lesson.sentences[i];
      const li = document.createElement('li');
      li.className = 'line';
      li.dataset.i = i;
      if (s.speaker === OUTSIDE) li.classList.add('outside');
      li.innerHTML = `<span class="t"></span><span class="s"><b class="${cls(s)}"></b></span>`;
      li.querySelector('.t').textContent = clock(s.start - p.t0);
      li.querySelector('b').textContent = s.speaker === OUTSIDE ? '' : s.speaker;
      li.querySelector('.s').appendChild(document.createTextNode(s.text));
      li.onclick = () => playOne(i);  // 只播这一句，方便听开头结尾
      list.appendChild(li);
    }
  });
  markStuck();
}

/* ---------- 按钮和键盘 ---------- */

$('playBtn').onclick = togglePlay;
$('replayBtn').onclick = replayCurrent;
$('prevBtn').onclick = () => playOne(idx - 1);
$('nextBtn').onclick = () => playOne(idx + 1);
/* 段导航（R24，owner 2026-09-26）：点了从那段开头连续播——播放类的动作（R1），和原来点整集条上的一段一样 */
$('prevPartBtn').onclick = () => {
  const k = partOf[idx];
  if (k > 0) playFrom(parts[k - 1].first);
};
$('nextPartBtn').onclick = () => {
  const k = partOf[idx];
  if (k + 1 < parts.length) playFrom(parts[k + 1].first);
};
$('nextSectionBtn').onclick = () => playFrom(nextSection().first);
$('againSectionBtn').onclick = () => playFrom(part().first);
$('textBtn').onclick = () => {
  if ($('text').hidden) showText(); else { hideText(); render(); }
};
$('zhBtn').onclick = () => {
  const el = $('zh');
  el.textContent = cur().zh || '（这句没有中文）';
  el.hidden = !el.hidden;
  $('zhBtn').textContent = el.hidden ? '看中文' : '收起中文';
  if (!el.hidden) record(() => ({ sawZh: true }));
};
document.querySelectorAll('.speed-btn').forEach((b) => {
  b.onclick = () => setRate(Number(b.dataset.rate));
});

$('settingsBtn').onclick = (e) => {
  e.stopPropagation();
  const panel = $('settings');
  panel.hidden = !panel.hidden;
  $('settingsBtn').setAttribute('aria-expanded', String(!panel.hidden));
};
$('settings').onclick = (e) => e.stopPropagation();
$('exportBtn').onclick = () => {
  const blob = new Blob([JSON.stringify({ lesson: LESSON, records }, null, 2)], { type: 'application/json' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `listening-${LESSON}.json`;
  link.click();
};
function setDrawer(open) {
  $('fullPanel').hidden = !open;
  $('fullBtn').classList.toggle('on', open);
  document.body.classList.toggle('drawer-open', open);  // 宽屏时播放器往左让开，别被挡住
  const here = document.querySelector('#fullList li.current');
  if (open && here) here.scrollIntoView({ block: 'center' });
}
$('fullBtn').onclick = () => setDrawer($('fullPanel').hidden);
$('fullClose').onclick = () => setDrawer(false);
$('wordClose').onclick = () => { $('wordbox').hidden = true; };

document.addEventListener('click', (e) => {
  if (!$('settings').hidden && !e.target.closest('#settings')) {
    $('settings').hidden = true;
    $('settingsBtn').setAttribute('aria-expanded', 'false');
  }
  if (!$('wordbox').hidden && !e.target.closest('#wordbox') && e.target.tagName !== 'W') {
    $('wordbox').hidden = true;
  }
});

audio.addEventListener('play', render);
audio.addEventListener('pause', render);

document.addEventListener('keydown', (e) => {
  if (updating || e.target.tagName === 'INPUT' || e.ctrlKey || e.metaKey || e.altKey) return;
  const actions = {
    ' ': togglePlay,
    ArrowLeft: () => playOne(idx - 1),
    ArrowRight: () => playOne(idx + 1),
    r: replayCurrent,
    R: replayCurrent,
    t: () => $('textBtn').click(),
    T: () => $('textBtn').click(),
    Escape: () => { $('wordbox').hidden = true; $('settings').hidden = true; setDrawer(false); },
  };
  if (actions[e.key]) {
    e.preventDefault();
    actions[e.key]();
  }
});

/* ---------- 换版本（SPEC-008） ----------
 * - 服务换了版本，一直开着的这一页照样能用，只是新做的东西安静地不在，看的人会以为「这个功能没做」。
 *   所以页面记下打开时服务是哪一版，每分钟问一次、切回这个页签马上问一次，换了就在顶上挂一条提示。
 *   不自动刷新：孩子可能正听着（R8，决策 D35）。问不到（服务正在重启）、说不清是哪一版，都不挂。
 * - 「更新」只在 claude 钉了一版、还没换过去时出现（R5，决策 D34）：平时不在，孩子的屏幕上不多一个用不上的按钮。
 *   点了服务停几秒、换完起回来，页面自己刷新，回到刚才那一句。
 * - 服务报的版本只拿来比，不显示（R9）。
 */

const ASK_EVERY = 60000;
const RESUME = `listening:${LESSON}:resume`;
let myVersion;            // 这一页打开时服务是哪一版：undefined 还没问到，null 说不清
let updating = false;
let failedClosed = '';    // 他关掉过的那句「没换成」，同一句不再挂

async function askVersion() {
  try {
    const r = await fetch('/api/version', { cache: 'no-store' });
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

async function checkVersion() {
  if (updating) return;
  const v = await askVersion();
  if (!v || updating) return;                           // 问不到不等于旧了
  const version = v.version || null;
  if (myVersion === undefined) myVersion = version;
  else if (myVersion && version && version !== myVersion) $('stale').hidden = false;  // 挂上就不撤
  const waiting = Boolean(v.update && v.update.waiting);
  $('updateBtn').hidden = !waiting;
  $('updateBtn').title = waiting ? `有新版本：${v.update.what}\n点一下换过去，几秒钟后页面自己回来。` : '';
  const failed = v.failed || '';
  $('updateFailedText').textContent = failed;
  $('updateFailed').hidden = !failed || failed === failedClosed;
}

/* 刷新前记下在哪一句，刷新后回到这一句（只在这个页签里记，关了就没了） */
function reloadHere() {
  try { sessionStorage.setItem(RESUME, String(cur().id)); } catch { /* 记不下就从头开始 */ }
  location.reload();
}

function backToPlace() {
  let id = null;
  try {
    id = sessionStorage.getItem(RESUME);
    sessionStorage.removeItem(RESUME);
  } catch {
    return;
  }
  const i = lesson.sentences.findIndex((s) => String(s.id) === id);
  if (i >= 0) idx = i;
}

async function update() {
  $('updateBtn').disabled = true;
  let r = null;
  try { r = await fetch('/api/update', { method: 'POST' }); } catch { /* 下面一起说 */ }
  if (!r || r.status !== 202) {
    $('updateBtn').disabled = false;
    $('updateFailedText').textContent = '现在换不了。关掉那个黑窗口，重新双击 start-player.bat，再点一次「更新」。';
    $('updateFailed').hidden = false;
    checkVersion();
    return;
  }
  updating = true;
  audio.pause();
  $('wordbox').hidden = true;
  $('updating').hidden = false;
  // 服务先停、再起回来。起回来的标志：中间断过一次，或者报的版本变了（停得太快、一次都没问到断的时候）
  const deadline = Date.now() + 180000;
  let sawDown = false;
  while (Date.now() < deadline) {
    await new Promise((ok) => setTimeout(ok, 1000));
    const v = await askVersion();
    if (!v) { sawDown = true; continue; }
    if (sawDown || v.version !== myVersion) { reloadHere(); return; }
  }
  $('updatingText').textContent = '等了三分钟它还没回来。看一眼那个黑窗口，或者关掉它、重新双击 start-player.bat。';
}

function watchVersion() {
  $('updateBtn').addEventListener('click', update);
  $('staleRefresh').addEventListener('click', reloadHere);
  $('updateFailedClose').addEventListener('click', () => {
    failedClosed = $('updateFailedText').textContent;
    $('updateFailed').hidden = true;
  });
  checkVersion();
  setInterval(checkVersion, ASK_EVERY);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') checkVersion();
  });
}

boot();
watchVersion();
