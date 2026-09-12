/* 按句子播放的听力播放器。规格见 specs/SPEC-001-player.md。
 *
 * 几条要记住的理由：
 * - 重听有 1 秒的反应延迟保护：人按键慢半拍，不保护就总跳错句（R3）。
 * - 文字默认不显示，显示时给整句而不是关键词：只显示关键词的字幕没有效果（R2、R5）。
 * - 看过文字后要回到原速再听一遍，否则就变成读课文（R6）。
 * - 中文翻译藏在看过英文之后（R7b）。
 * - 不问孩子懂没懂，只记他的动作（R9）。
 */

const LESSON = new URLSearchParams(location.search).get('lesson') || '260821';
const BASE = `../lessons/${LESSON}/`;
const PAD = 0.08;          // 播单词时前后各留一点，免得切掉音头
const BACK_GRACE = 1.0;    // 本句才播了这么久以内按重听，视为想听上一句
const RATES = [1, 0.8, 0.7];
const RATE_NAMES = { 1: '原速', 0.8: '慢速 0.8', 0.7: '最慢 0.7' };
const OUTSIDE = '片头片尾';

const $ = (id) => document.getElementById(id);
const audio = $('audio');

let lesson = null;
let idx = 0;                 // 当前第几句
let intensive = true;        // 精听模式
let rateStep = 0;
let records = {};
let wordPlayUntil = null;    // 正在播某个单词时的结束时间
let atSentenceEnd = false;   // 精听模式下停在本句末尾，等着进下一句

/* ---------- 启动 ---------- */

async function boot() {
  lesson = await (await fetch(BASE + 'lesson.json')).json();
  audio.src = BASE + lesson.audio;
  audio.preservesPitch = true;
  audio.mozPreservesPitch = true;
  audio.webkitPreservesPitch = true;
  $('title').textContent = lesson.title || '听力练习';
  $('source').textContent = lesson.source || '';
  records = JSON.parse(localStorage.getItem(recordKey()) || '{}');
  $('autoPause').checked = localStorage.getItem(recordKey() + ':autoPause') !== 'off';
  buildCheckList();
  idx = Math.max(0, lesson.sentences.findIndex((s) => s.speaker !== OUTSIDE));
  render();
  requestAnimationFrame(tick);
}

const recordKey = () => `listening:${LESSON}`;
const cur = () => lesson.sentences[idx];

function record(patch) {
  const id = cur().id;
  const old = records[id] || { replays: 0, slowed: false, sawText: false, sawZh: false, words: [] };
  records[id] = Object.assign({}, old, patch(old));
  localStorage.setItem(recordKey(), JSON.stringify(records));
}

/* ---------- 播放 ---------- */

function playFrom(seconds) {
  wordPlayUntil = null;
  atSentenceEnd = false;
  audio.currentTime = seconds;
  audio.playbackRate = RATES[rateStep];
  audio.play();
}

function gotoSentence(i, play = true) {
  idx = Math.max(0, Math.min(lesson.sentences.length - 1, i));
  hideText();
  render();
  if (play) playFrom(cur().start);
}

function replayCurrent() {
  const played = audio.currentTime - cur().start;
  // 停在句末等着进下一句时，重听一定是指刚听完的这句，不适用反应延迟保护
  if (!atSentenceEnd && played >= 0 && played < BACK_GRACE && idx > 0) {
    gotoSentence(idx - 1);
    return;
  }
  const before = records[cur().id] ? records[cur().id].replays : 0;
  record((old) => ({ replays: old.replays + 1 }));
  // 同一句第二次重听自动放慢（R4）
  if (before + 1 >= 2 && rateStep === 0 && $('autoSlow').checked) {
    rateStep = 1;
    record(() => ({ slowed: true }));
    updateRateButton();
  }
  playFrom(cur().start);
}

function tick() {
  const t = audio.currentTime;

  if (wordPlayUntil !== null && t >= wordPlayUntil) {
    audio.pause();
    wordPlayUntil = null;
    audio.playbackRate = RATES[rateStep];
  }

  if (wordPlayUntil === null) {
    const here = lesson.sentences.findIndex((s) => t >= s.start && t < s.end);
    if (here >= 0 && here !== idx) {
      idx = here;
      hideText();
      render();
    }
    if (intensive && $('autoPause').checked && !audio.paused && t >= cur().end) {
      audio.pause();
      audio.currentTime = cur().end;
      atSentenceEnd = true;
      render();
    }
  }

  $('progressFill').style.width = `${(t / (audio.duration || 1)) * 100}%`;
  highlightWord(t);
  requestAnimationFrame(tick);
}

/* ---------- 画面 ---------- */

function render() {
  const s = cur();
  const body = lesson.sentences.filter((x) => x.speaker !== OUTSIDE);
  const nth = body.indexOf(s) + 1;
  $('speaker').textContent = s.speaker;
  $('counter').textContent = nth > 0 ? `第 ${nth} 句 / 共 ${body.length} 句` : OUTSIDE;
  $('playBtn').textContent = !audio.paused ? '暂停' : (atSentenceEnd ? '继续 · 下一句' : '播放');
  $('modeBtn').textContent = intensive ? '精听' : '整段';
  $('modeBtn').classList.toggle('on', intensive);
}

function showText() {
  const s = cur();
  const el = $('text');
  el.innerHTML = '';
  s.words.forEach((w, i) => {
    const tag = document.createElement('w');
    tag.textContent = (i === 0 ? '' : ' ') + w.text;
    const g = lesson.glossary[w.key];
    if (g && g.hard) tag.classList.add('hard');
    tag.onclick = () => openWord(i);
    el.appendChild(tag);
  });
  el.hidden = false;
  $('hidden-hint').hidden = true;
  $('againBtn').hidden = false;
  $('zhBtn').hidden = false;
  $('textBtn').textContent = '收起文字';
  record(() => ({ sawText: true }));
}

function hideText() {
  $('text').hidden = true;
  $('zh').hidden = true;
  $('hidden-hint').hidden = false;
  $('againBtn').hidden = true;
  $('zhBtn').hidden = true;
  $('zhBtn').textContent = '看中文';
  $('textBtn').textContent = '看文字';
  $('wordbox').hidden = true;
}

function highlightWord(t) {
  if ($('text').hidden) return;
  const words = cur().words;
  const tags = $('text').children;
  for (let i = 0; i < tags.length; i++) {
    const w = words[i];
    const on = !audio.paused && w && t >= w.start && t < w.end;
    tags[i].classList.toggle('playing', on);
  }
}

/* ---------- 单词 ---------- */

function openWord(i) {
  const w = cur().words[i];
  const g = lesson.glossary[w.key] || {};
  const clean = w.text.replace(/^[^A-Za-z']+|[^A-Za-z']+$/g, '');
  $('wordText').textContent = clean;
  $('wordZh').textContent = g.zh || '（这个词没有释义）';
  $('wordHard').hidden = !g.hard;
  $('wordbox').hidden = false;
  $('wordTts').onclick = () => speak(clean);
  $('wordRaw').onclick = () => {
    audio.playbackRate = 1;
    audio.currentTime = Math.max(0, w.start - PAD);
    wordPlayUntil = w.end + PAD;
    audio.play();
  };
  record((old) => ({ words: old.words.indexOf(w.key) < 0 ? old.words.concat(w.key) : old.words }));
}

function speak(text) {
  if (!window.speechSynthesis) return;
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = 'en-GB';
  const voices = speechSynthesis.getVoices();
  const voice = voices.find((v) => v.lang === 'en-GB') || voices.find((v) => v.lang.indexOf('en') === 0);
  if (voice) utterance.voice = voice;
  speechSynthesis.cancel();
  speechSynthesis.speak(utterance);
}

/* ---------- 家长检查 ---------- */

function buildCheckList() {
  const list = $('checkList');
  lesson.sentences.forEach((s, i) => {
    const li = document.createElement('li');
    const time = document.createElement('span');
    time.className = 't';
    time.textContent = s.start.toFixed(2);
    li.appendChild(time);
    li.appendChild(document.createTextNode(`${s.speaker}：${s.text}`));
    if (s.speaker === OUTSIDE) li.classList.add('outside');
    li.onclick = () => gotoSentence(i);
    list.appendChild(li);
  });
}

function updateRateButton() {
  $('rateBtn').textContent = RATE_NAMES[RATES[rateStep]];
  $('rateBtn').classList.toggle('on', rateStep !== 0);
  audio.playbackRate = RATES[rateStep];
}

/* ---------- 按钮和键盘 ---------- */

$('playBtn').onclick = () => {
  if (!audio.paused) {
    audio.pause();
  } else if (atSentenceEnd) {
    // 停在句末，按播放就是进下一句；不这么做会卡在原地反复自动暂停
    gotoSentence(idx + 1);
  } else {
    audio.play();
  }
  render();
};
$('replayBtn').onclick = replayCurrent;
$('prevBtn').onclick = () => gotoSentence(idx - 1);
$('nextBtn').onclick = () => gotoSentence(idx + 1);
$('againBtn').onclick = () => {
  rateStep = 0;
  updateRateButton();
  playFrom(cur().start);
};
$('textBtn').onclick = () => ($('text').hidden ? showText() : hideText());
$('zhBtn').onclick = () => {
  const el = $('zh');
  el.textContent = cur().zh || '（这句没有中文）';
  el.hidden = !el.hidden;
  $('zhBtn').textContent = el.hidden ? '看中文' : '收起中文';
  if (!el.hidden) record(() => ({ sawZh: true }));
};
$('modeBtn').onclick = () => {
  intensive = !intensive;
  render();
};
$('rateBtn').onclick = () => {
  rateStep = (rateStep + 1) % RATES.length;
  updateRateButton();
};
$('autoPause').onchange = (e) =>
  localStorage.setItem(recordKey() + ':autoPause', e.target.checked ? 'on' : 'off');
$('skipIntro').onclick = () =>
  gotoSentence(lesson.sentences.findIndex((s) => s.speaker !== OUTSIDE));
$('checkBtn').onclick = () => {
  const panel = $('checkPanel');
  panel.hidden = !panel.hidden;
  $('checkBtn').classList.toggle('on', !panel.hidden);
};
$('wordClose').onclick = () => ($('wordbox').hidden = true);
$('exportBtn').onclick = () => {
  const blob = new Blob([JSON.stringify({ lesson: LESSON, records }, null, 2)],
    { type: 'application/json' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `listening-${LESSON}.json`;
  link.click();
};
audio.onplay = render;
audio.onpause = render;

document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT') return;
  const actions = {
    ' ': () => $('playBtn').click(),
    r: replayCurrent,
    R: replayCurrent,
    t: () => $('textBtn').click(),
    T: () => $('textBtn').click(),
    s: () => $('rateBtn').click(),
    S: () => $('rateBtn').click(),
    ArrowLeft: () => (e.shiftKey ? gotoSentence(idx - 1) : replayCurrent()),
    ArrowRight: () => gotoSentence(idx + 1),
  };
  if (actions[e.key]) {
    e.preventDefault();
    actions[e.key]();
  }
});

boot();
