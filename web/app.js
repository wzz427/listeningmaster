/* 按句子播放的听力播放器。规格见 specs/SPEC-001-player.md。
 *
 * 几条要记住的理由：
 * - 默认一直往下播；「每句播完停一下」是开关，默认关（owner 2026-09-21 拍板，决策 D16）。
 * - 进度条上每一段是一句话，颜色区分说话人：点上一句、下一句时看得见自己跳到了哪（R15）。
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
const WORD_PAD = 0.06;    // 播单词原声时前后各留一点
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
let stopKind = null;      // 'sentence' 停在句末 · 'word' 播完一个词
let fadedFor = null;      // 已经为哪个停点安排过渐弱
let atSentenceEnd = false;
let resumeAfterWord = null;
let ctx = null;
let gain = null;
const speakerClass = {};  // 说话人 → 'a' / 'b'

/* ---------- 启动 ---------- */

async function boot() {
  lesson = await (await fetch(BASE + 'lesson.json')).json();
  body = lesson.sentences.filter((s) => s.speaker !== OUTSIDE);
  body.forEach((s) => {
    if (!(s.speaker in speakerClass)) speakerClass[s.speaker] = Object.keys(speakerClass).length ? 'b' : 'a';
  });
  audio.addEventListener('loadedmetadata', () => {
    buildTimeline();
    $('timeTotal').textContent = clock(audio.duration);
    if (audio.currentTime === 0) audio.currentTime = cur().start;  // 显示第 1 句，播放也从第 1 句开始
  });
  audio.src = BASE + lesson.audio;
  audio.preservesPitch = true;
  $('title').textContent = lesson.title || '听力练习';
  $('source').textContent = lesson.source || '';
  records = readJSON(recordKey(), {});
  $('autoPause').checked = localStorage.getItem(settingKey('autoPause')) === 'on';
  $('autoSlow').checked = localStorage.getItem(settingKey('autoSlow')) !== 'off';
  buildLegend();
  buildCheckList();
  idx = Math.max(0, lesson.sentences.indexOf(body[0]));
  setRate(1);
  render();
  requestAnimationFrame(tick);
}

const recordKey = () => `listening:${LESSON}`;
const settingKey = (name) => `listening:${LESSON}:${name}`;
const cur = () => lesson.sentences[idx];
const cls = (s) => (s.speaker === OUTSIDE ? 'o' : speakerClass[s.speaker] || 'o');

function readJSON(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) || fallback; } catch { return fallback; }
}

function record(patch, sentence = cur()) {
  const old = records[sentence.id] || { replays: 0, slowed: false, sawText: false, sawZh: false, words: [] };
  records[sentence.id] = Object.assign({}, old, patch(old));
  localStorage.setItem(recordKey(), JSON.stringify(records));
  markStuck();
}

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
  stopAt = stop;
  stopKind = kind;
  fadedFor = null;
  if (gain) gain.gain.setValueAtTime(0, ctx.currentTime);
  audio.currentTime = seconds;
  audio.playbackRate = kind === 'word' ? 1 : rate;
  audio.play();
  rampGain(1, FADE_IN);
}

function resume() {
  ensureGraph();
  if (gain) gain.gain.setValueAtTime(0, ctx.currentTime);
  audio.play();
  rampGain(1, FADE_IN);
}

function sentenceStopWanted() {
  return $('autoPause').checked || !$('text').hidden;
}

/* 每一帧：该停就停，跟上当前是第几句，画进度 */
function tick() {
  const t = audio.currentTime;

  if (!audio.paused) {
    const target = stopAt !== null ? stopAt : ($('autoPause').checked ? cur().end : null);
    if (target !== null) {
      const remain = (target - t) / audio.playbackRate;
      if (fadedFor !== target && remain <= FADE + 0.025) {
        rampGain(0, remain);
        fadedFor = target;
      }
      if (remain <= 0.004) reachStop();
    }
  }

  if (!audio.paused && stopKind !== 'word') {
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
  const kind = stopKind || 'sentence';
  audio.pause();
  stopAt = null;
  stopKind = null;
  fadedFor = null;
  if (kind === 'word') {
    audio.playbackRate = rate;
    if (resumeAfterWord) {
      audio.currentTime = resumeAfterWord.time;
      atSentenceEnd = resumeAfterWord.atEnd;
      resumeAfterWord = null;
    }
  } else {
    atSentenceEnd = true;
  }
  render();
}

/* ---------- 跳句 ---------- */

function gotoSentence(i, { flash = true } = {}) {
  idx = Math.max(0, Math.min(lesson.sentences.length - 1, i));
  hideText();
  start(cur().start);
  render();
  if (flash) flashSegment(idx);
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
  start(cur().start, sentenceStopWanted() ? { stop: cur().end, kind: 'sentence' } : {});
  render();
  flashSegment(idx);
}

function togglePlay() {
  if (!audio.paused) {
    audio.pause();
  } else if (atSentenceEnd) {
    gotoSentence(idx + 1);   // 停在句末，按播放就是进下一句
  } else {
    resume();
  }
  render();
}

function setRate(value) {
  rate = value;
  if (stopKind !== 'word') audio.playbackRate = rate;
  document.querySelectorAll('.speed-btn').forEach((b) => {
    b.classList.toggle('on', Number(b.dataset.rate) === rate);
  });
}

/* ---------- 画面 ---------- */

function render() {
  const s = cur();
  const nth = body.indexOf(s) + 1;
  const playing = !audio.paused;
  document.body.classList.toggle('playing', playing);
  $('speaker').textContent = s.speaker;
  $('avatar').textContent = s.speaker === OUTSIDE ? '♪' : s.speaker.slice(0, 1);
  $('avatar').className = `avatar ${cls(s)}`;
  $('counter').textContent = nth > 0 ? `第 ${nth} 句 / 共 ${body.length} 句` : '片头片尾，不算正文';
  // 矢量图标不认 .hidden 属性，要直接改 hidden 这个标记
  $('iconPlay').toggleAttribute('hidden', playing);
  $('iconPause').toggleAttribute('hidden', !playing);
  $('playLabel').textContent = playing ? '暂停' : (atSentenceEnd ? '下一句' : '播放');

  const tag = $('stateTag');
  if (atSentenceEnd) { tag.textContent = '停在这句末尾'; tag.classList.add('stop'); }
  else if (sentenceStopWanted()) { tag.textContent = '这句播完会停'; tag.classList.add('stop'); }
  else { tag.textContent = '连续播放'; tag.classList.remove('stop'); }

  document.querySelectorAll('.seg').forEach((el) => {
    el.classList.toggle('current', Number(el.dataset.i) === idx);
  });
  document.querySelectorAll('#checkList li').forEach((li) => {
    li.classList.toggle('current', Number(li.dataset.i) === idx);
  });
}

function drawProgress(t) {
  const total = audio.duration || 1;
  $('playhead').style.left = `${(t / total) * 100}%`;
  $('timeNow').textContent = clock(t);
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
  $('againBtn').hidden = false;
  $('againBtn').classList.remove('nudge');
  void $('againBtn').offsetWidth;
  $('againBtn').classList.add('nudge');
  $('zhBtn').hidden = false;
  $('textBtn').innerHTML = '收起文字 <kbd>T</kbd>';
  record(() => ({ sawText: true }));
  // 看了文字说明卡在这句了：这句播完就停，让他读、点词、重听
  if (!audio.paused && stopAt === null) {
    stopAt = s.end;
    stopKind = 'sentence';
  }
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
  if (stopKind === 'sentence' && !$('autoPause').checked) {
    stopAt = null;
    stopKind = null;
  }
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

/* ---------- 进度条：每一段是一句 ---------- */

function buildTimeline() {
  const total = audio.duration || lesson.sentences[lesson.sentences.length - 1].end;
  const box = $('segments');
  box.innerHTML = '';
  lesson.sentences.forEach((s, i) => {
    const seg = document.createElement('div');
    seg.className = `seg ${cls(s)}`;
    seg.dataset.i = i;
    seg.style.left = `${(s.start / total) * 100}%`;
    seg.style.width = `max(2px, calc(${((s.end - s.start) / total) * 100}% - 1.5px))`;
    box.appendChild(seg);
  });
  markStuck();
  render();
}

function markStuck() {
  document.querySelectorAll('.seg').forEach((el) => {
    const r = records[lesson.sentences[Number(el.dataset.i)].id];
    el.classList.toggle('stuck', !!r && r.replays > 0);
  });
}

function sentenceAt(clientX) {
  const rect = $('timeline').getBoundingClientRect();
  const t = ((clientX - rect.left) / rect.width) * (audio.duration || 1);
  let best = 0;
  lesson.sentences.forEach((s, i) => {
    const d = t < s.start ? s.start - t : t > s.end ? t - s.end : 0;
    const bd = t < lesson.sentences[best].start ? lesson.sentences[best].start - t
      : t > lesson.sentences[best].end ? t - lesson.sentences[best].end : 0;
    if (d < bd) best = i;
  });
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
  legend.insertAdjacentHTML('beforeend',
    '<span><i style="background:var(--spk-o)"></i>片头片尾</span>' +
    '<span><i class="stuck-dot"></i>重听过的句子</span>');
}

$('timeline').addEventListener('pointermove', (e) => {
  const i = sentenceAt(e.clientX);
  const s = lesson.sentences[i];
  const nth = body.indexOf(s) + 1;
  const tip = $('tip');
  const rect = $('timeline').getBoundingClientRect();
  tip.innerHTML = `<b>${nth > 0 ? '第 ' + nth + ' 句' : OUTSIDE}</b>${s.speaker === OUTSIDE ? '' : s.speaker} · ${clock(s.start)}`;
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
$('timeline').addEventListener('click', (e) => gotoSentence(sentenceAt(e.clientX)));

/* ---------- 单词 ---------- */

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
  // 优先弹在词的上方，别盖住下面的中文和按钮；上方放不下再放下方
  const above = r.top - box.offsetHeight - 14;
  box.style.top = above > 12 ? `${above}px` : `${Math.min(window.innerHeight - box.offsetHeight - 12, r.bottom + 14)}px`;
  $('wordTts').onclick = () => speak(clean);
  $('wordRaw').onclick = () => {
    resumeAfterWord = { time: audio.paused ? audio.currentTime : cur().start, atEnd: atSentenceEnd };
    start(Math.max(0, w.start - WORD_PAD), { stop: w.end + WORD_PAD, kind: 'word' });
  };
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

/* ---------- 家长检查 ---------- */

function buildCheckList() {
  const list = $('checkList');
  list.innerHTML = '';
  lesson.sentences.forEach((s, i) => {
    const li = document.createElement('li');
    li.dataset.i = i;
    if (s.speaker === OUTSIDE) li.classList.add('outside');
    li.innerHTML = `<span class="t"></span><span class="s"><b class="${cls(s)}"></b></span>`;
    li.querySelector('.t').textContent = clock(s.start) + '.' + String(Math.round((s.start % 1) * 100)).padStart(2, '0');
    li.querySelector('b').textContent = s.speaker;
    li.querySelector('.s').appendChild(document.createTextNode(s.text));
    li.onclick = () => {
      idx = i;
      hideText();
      start(s.start, { stop: s.end, kind: 'sentence' });  // 只播这一句，方便听开头结尾
      render();
      flashSegment(i);
    };
    list.appendChild(li);
  });
}

/* ---------- 按钮和键盘 ---------- */

$('playBtn').onclick = togglePlay;
$('replayBtn').onclick = replayCurrent;
$('prevBtn').onclick = () => gotoSentence(idx - 1);
$('nextBtn').onclick = () => gotoSentence(idx + 1);
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
$('autoPause').onchange = (e) => {
  localStorage.setItem(settingKey('autoPause'), e.target.checked ? 'on' : 'off');
  render();
};
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
  $('checkPanel').hidden = !open;
  $('checkBtn').classList.toggle('on', open);
  document.body.classList.toggle('drawer-open', open);  // 宽屏时播放器往左让开，别被挡住
}
$('checkBtn').onclick = () => setDrawer($('checkPanel').hidden);
$('checkClose').onclick = () => setDrawer(false);
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
    ArrowLeft: () => gotoSentence(idx - 1),
    ArrowRight: () => gotoSentence(idx + 1),
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
