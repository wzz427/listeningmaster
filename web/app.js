/* 按句子播放的听力播放器。规格见 specs/SPEC-001-player.md。
 *
 * 几条要记住的理由：
 * - 两种播法，按哪个键就是哪种（owner 2026-09-22 提出并拍板，决策 D23）：
 *   按播放键是连续播，一直往下播到段末；按上一句、下一句、重听本句、点进度条或全文里的某一句，
 *   只播那一句，播完停在句末；停在句末再按播放，从下一句接着连续播。
 *   孩子按「重听」「上一句」就是想抠这一句，不该一直往下跑。原来设置里的「每句播完停一下」因此删了。
 * - 正文按话题分成两分钟左右一段（D22）。进度条分两层：上面一条是整集，看得见自己在第几段；
 *   下面一条只画当前这段，每一小段是一句话，颜色区分说话人（R15、R20）。
 *   整集画在一条上太密：6 分钟挤在 900 像素里，最短的句子不到 2 像素，点不中。
 * - 一段播完就停，给「这段再听一遍」「听下一段」两个选择；片头播完不停，直接进正文（R21）。
 * - 需要停在句末时，提前几十毫秒把音量渐弱到零再停，不然会带进下一句开头的声音。
 *   有十几处两句贴得太紧，句子边界挪到哪都不够，只能靠这里收得准（见 docs/lessons.md）。
 * - 重听有 1 秒的反应延迟保护：人按键慢半拍，不保护就总跳错句（R3）。
 * - 文字默认不显示，显示时给整句；看了文字就停在这句末尾，方便他读、点词、重听（R5、D17）。
 * - 看过文字后提示原速再听一遍，否则就变成读课文（R6）。中文藏在看过英文之后（R7b）。
 * - 不问孩子懂没懂，只记他的动作（R9）。
 */

const LESSON = new URLSearchParams(location.search).get('lesson') || '260821';
const BASE = `../lessons/${LESSON}/`;
const OUTSIDE = '片头片尾';
const BACK_GRACE = 1.0;   // 本句才播了这么久以内按重听，视为想听上一句
const FADE = 0.04;        // 停之前渐弱这么久（秒）
const FADE_IN = 0.015;    // 每次开始播渐强这么久，免得跳转时「啪」一声
const SLOW = 0.8;

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
let parts = [];           // 按时间顺序：片头、正文第 1 段 … 第 N 段、片尾
let partOf = [];          // 第 i 句属于 parts 的哪一项
let shownPart = -1;       // 下面那条进度条现在画的是哪一项
let sectionCount = 0;

/* ---------- 启动 ---------- */

async function boot() {
  lesson = await (await fetch(BASE + 'lesson.json')).json();
  body = lesson.sentences.filter((s) => s.speaker !== OUTSIDE);
  body.forEach((s) => {
    if (!(s.speaker in speakerClass)) speakerClass[s.speaker] = Object.keys(speakerClass).length ? 'b' : 'a';
  });
  buildParts();
  audio.addEventListener('loadedmetadata', () => {
    buildOverview();  // 整集那条要用音频总长，片尾后面还有一点音乐
    render();
    if (audio.currentTime === 0) audio.currentTime = cur().start;  // 显示第 1 句，播放也从第 1 句开始
  });
  audio.src = BASE + lesson.audio;
  audio.preservesPitch = true;
  $('title').textContent = lesson.title || '听力练习';
  $('source').textContent = lesson.source || '';
  records = readJSON(recordKey(), {});
  $('autoSlow').checked = localStorage.getItem(settingKey('autoSlow')) !== 'off';
  buildLegend();
  buildOverview();
  buildFullText();
  idx = Math.max(0, lesson.sentences.indexOf(body[0]));
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
  const old = records[sentence.id] || { replays: 0, slowed: false, sawText: false, sawZh: false, words: [] };
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
  sectionCount = sections.length;
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
  const t = audio.currentTime;

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
  const before = records[cur().id] ? records[cur().id].replays : 0;
  record((old) => ({ replays: old.replays + 1 }));
  if (before + 1 >= 2 && rate === 1 && $('autoSlow').checked) {
    setRate(SLOW);
    record(() => ({ slowed: true }));
  }
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
  $('counter').textContent = p.kind === 'section'
    ? `第 ${p.n} 段 · 第 ${idx - p.first + 1} 句 / 共 ${p.last - p.first + 1} 句`
    : `${p.title}，不算正文`;
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
  document.querySelectorAll('.part').forEach((el) => {
    el.classList.toggle('current', Number(el.dataset.k) === partOf[idx]);
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
  document.querySelectorAll('.part').forEach((el) => {
    const q = parts[Number(el.dataset.k)];
    const done = Math.max(0, Math.min(1, (t - q.t0) / (q.t1 - q.t0)));
    el.firstChild.style.width = `${done * 100}%`;
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
  $('againBtn').hidden = false;
  $('againBtn').classList.remove('nudge');
  void $('againBtn').offsetWidth;
  $('againBtn').classList.add('nudge');
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
  $('againBtn').hidden = true;
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

/* ---------- 进度：上面整集分几段，下面这段每一小段是一句 ---------- */

function buildOverview() {
  const total = audio.duration || lesson.sentences[lesson.sentences.length - 1].end;
  const box = $('parts');
  box.innerHTML = '';
  parts.forEach((p, k) => {
    const from = k === 0 ? 0 : p.t0;
    const to = k + 1 < parts.length ? parts[k + 1].t0 : total;
    const el = document.createElement('button');
    el.className = `part ${p.kind}`;
    el.dataset.k = k;
    el.style.flexGrow = String(Math.max(1, to - from));
    el.title = p.kind === 'section' ? `第 ${p.n} 段：${p.title}` : p.title;
    el.setAttribute('aria-label', el.title);
    el.innerHTML = '<span class="fill"></span><span class="label"></span>';
    el.querySelector('.label').textContent = p.kind === 'section' ? p.n : p.title;
    el.onclick = () => playFrom(p.first);  // 点一段：从那段开头连续听
    box.appendChild(el);
  });
}

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
  $('partNo').textContent = p.kind === 'section' ? `第 ${p.n} 段` : p.title;
  $('partNo').classList.toggle('outside', p.kind !== 'section');
  $('partTitle').textContent = p.kind === 'section' ? p.title : '不算正文';
  $('partCount').textContent = `共 ${sectionCount} 段`;
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

$('timeline').addEventListener('pointermove', (e) => {
  const i = sentenceAt(e.clientX);
  const s = lesson.sentences[i];
  const p = parts[shownPart];
  const tip = $('tip');
  const rect = $('timeline').getBoundingClientRect();
  tip.innerHTML = `<b>第 ${i - p.first + 1} 句</b>${s.speaker === OUTSIDE ? '' : s.speaker} · ${clock(s.start - p.t0)}`;
  tip.style.left = `${Math.min(rect.width - 70, Math.max(70, e.clientX - rect.left))}px`;
  tip.hidden = false;
  document.querySelectorAll('.seg.hover').forEach((el) => el.classList.remove('hover'));
  const seg = document.querySelector(`.seg[data-i="${i}"]`);
  if (seg) seg.classList.add('hover');
});
$('timeline').addEventListener('pointerleave', () => {
  $('tip').hidden = true;
  document.querySelectorAll('.seg.hover').forEach((el) => el.classList.remove('hover'));
});
$('timeline').addEventListener('click', (e) => playOne(sentenceAt(e.clientX)));

/* ---------- 单词 ---------- */

/* 点词：看这个词在这句里的中文意思，听朗读。
 * 原来还有「这句里的原声」，2026-09-22 拿掉了（决策 D24）：识别给的词时间偏晚、每个词偏得不一样，
 * 在真的 Chrome 里录下放出来的声音交给机器耳朵听，切出来的大多是半个词加下一个词的开头。
 * 想听这个词在句子里怎么读，看着文字按「重听本句」：正在读的词会亮，还能放慢。 */
function openWord(i, tag) {
  const w = cur().words[i];
  const g = lesson.glossary[w.key] || {};
  const clean = w.text.replace(/^[^A-Za-z']+|[^A-Za-z']+$/g, '');
  document.querySelectorAll('.sentence w.picked').forEach((el) => el.classList.remove('picked'));
  tag.classList.add('picked');
  $('wordText').textContent = clean;
  $('wordZh').textContent = g.zh || '（这个词没有释义）';
  $('wordHard').hidden = !g.hard;
  const box = $('wordbox');
  box.hidden = false;
  const r = tag.getBoundingClientRect();
  const width = box.offsetWidth;
  box.style.left = `${Math.min(window.innerWidth - width - 16, Math.max(16, r.left + r.width / 2 - width / 2))}px`;
  // 优先弹在词的上方，别盖住下面的中文和按钮；空间紧就贴近一点，实在放不下再放下方
  const room = r.top - box.offsetHeight;
  box.style.top = room >= 12 ? `${room - Math.min(14, room - 4)}px`
    : `${Math.min(window.innerHeight - box.offsetHeight - 12, r.bottom + 14)}px`;
  $('wordTts').onclick = () => speak(clean);
  record((old) => ({ words: old.words.indexOf(w.key) < 0 ? old.words.concat(w.key) : old.words }));
}

function speak(text) {
  if (!window.speechSynthesis) return;
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'en-GB';
  const voices = speechSynthesis.getVoices();
  const voice = voices.find((v) => v.lang === 'en-GB') || voices.find((v) => v.lang.indexOf('en') === 0);
  if (voice) u.voice = voice;
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
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
$('nextSectionBtn').onclick = () => playFrom(nextSection().first);
$('againSectionBtn').onclick = () => playFrom(part().first);
$('againBtn').onclick = () => {
  setRate(1);
  $('againBtn').classList.remove('nudge');
  start(cur().start, { stop: cur().end, kind: 'sentence' });
  render();
};
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
$('autoSlow').onchange = (e) =>
  localStorage.setItem(settingKey('autoSlow'), e.target.checked ? 'on' : 'off');
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
  if (e.target.tagName === 'INPUT' || e.ctrlKey || e.metaKey || e.altKey) return;
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

boot();
