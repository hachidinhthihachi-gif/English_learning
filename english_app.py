"""
Lặp Từ Vựng Tiếng Anh + Bài tập dịch câu Việt -> Anh (có chấm ngữ pháp). Không dùng AI, không tốn token.

Cài thư viện: KHÔNG cần (chỉ dùng thư viện có sẵn của Python).
Chạy:        python english_app.py
Mở:          http://localhost:8001

- Ngữ pháp: chấm bằng LanguageTool (dịch vụ miễn phí, giới hạn ~20 lượt/phút)
- Nghĩa/dịch: Google Translate miễn phí (dự phòng MyMemory)
- IPA: dictionaryapi.dev (miễn phí)
- Bài tập dịch câu bám theo TỪ BẠN VỪA TRA (câu ví dụ lấy từ từ điển, dịch sang tiếng Việt)
- Muốn thêm câu tập chung của riêng bạn: tạo file cau_tap.txt cùng thư mục, mỗi dòng 1 câu tiếng Việt.
"""
import argparse
import json
import os
import re
import socket
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse

UA = {"User-Agent": "Mozilla/5.0"}
VI_CHARS = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)
SKIP_CATEGORIES = {"STYLE", "REDUNDANCY", "PLAIN_ENGLISH", "WIKIPEDIA", "TYPOGRAPHY"}
SENTENCES = [
    "Hôm nay trời đẹp nên tôi đi dạo trong công viên.",
    "Tôi đã học tiếng Anh được hai năm rồi.",
    "Bạn có thể chỉ cho tôi đường đến nhà ga không?",
    "Nếu ngày mai trời mưa, chúng tôi sẽ ở nhà.",
    "Cô ấy đang nấu bữa tối khi tôi về đến nhà.",
    "Tôi muốn đặt một bàn cho bốn người vào tối nay.",
    "Anh ấy làm việc chăm chỉ nhưng vẫn chưa được tăng lương.",
    "Chúng tôi đã đến muộn vì đường rất đông xe.",
    "Bạn nghĩ gì về bộ phim mới này?",
    "Tôi thích uống cà phê vào buổi sáng hơn là trà.",
    "Cuối tuần trước tôi đã gặp lại một người bạn cũ.",
    "Làm ơn nói chậm hơn một chút, tôi chưa hiểu.",
]
try:
    SENTENCES += [l.strip() for l in Path(__file__).with_name("cau_tap.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
except Exception:
    pass

_cache = {}
last_error = ""


def _open(url, data=None):
    req = urllib.request.Request(url, data=data, headers=UA)
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode("utf-8"))


def tr(text, src, dst):
    """Dịch: Google (gtx) trước, lỗi thì MyMemory. Có nhớ kết quả."""
    global last_error
    key = (text, src, dst)
    if key in _cache:
        return _cache[key]
    q, out = quote(text), ""
    try:
        d = _open(f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={src}&tl={dst}&dt=t&q={q}")
        out = "".join(p[0] for p in d[0] if p[0]).strip()
    except Exception as e:
        last_error = f"Google: {e}"
        print("  ! Lỗi dịch (Google):", e)
    if not out:
        try:
            d = _open(f"https://api.mymemory.translated.net/get?q={q}&langpair={src}|{dst}")
            out = (d.get("responseData", {}).get("translatedText") or "").strip()
        except Exception as e:
            last_error = f"MyMemory: {e}"
            print("  ! Lỗi dịch (MyMemory):", e)
    if out:
        _cache[key] = out
    return out


_entries = {}
TEMPLATES = {
    "noun": ["I saw a {w} on my way home yesterday.", "This is my favorite {w}.", "Do you have a {w}?"],
    "verb": ["I want to {w} every day.", "She can {w} very well.", "They {w} together on weekends."],
    "adjective": ["The room is very {w}.", "She feels {w} today.", "It looks {w} to me."],
    "adverb": ["He speaks {w}.", "She did it {w}.", "They walked {w} to school."],
    "other": ['I learned the word "{w}" today.', 'Can you use the word "{w}" in a sentence?'],
}


def fetch_entry(word):
    """Tra từ điển miễn phí (dictionaryapi.dev): IPA, loại từ, câu ví dụ. Có nhớ kết quả."""
    w = word.strip().lower()
    if w in _entries:
        return _entries[w]
    try:
        d = _open("https://api.dictionaryapi.dev/api/v2/entries/en/" + quote(w))[0]
    except Exception:
        return {}
    _entries[w] = d
    return d


def get_ipa(word):
    if " " in word.strip():
        return ""
    d = fetch_entry(word)
    return d.get("phonetic") or next((p["text"] for p in d.get("phonetics", []) if p.get("text")), "")


def exercise(word, k=0):
    """Tạo câu luyện dịch chứa từ vừa tra: lấy câu ví dụ thật, dịch sang tiếng Việt."""
    w = word.strip()
    stem = w.lower()[:-1] if len(w) > 4 else w.lower()
    d = {} if " " in w else fetch_entry(w)
    exs, pos = [], []
    for m in d.get("meanings", []):
        pos.append(m.get("partOfSpeech", ""))
        for df in m.get("definitions", []):
            e = (df.get("example") or "").strip()
            if e and stem in e.lower() and e not in exs:
                exs.append(e)
    if not exs:  # từ điển không có ví dụ -> dùng câu mẫu theo loại từ
        exs = [t.format(w=w) for t in TEMPLATES.get(pos[0] if pos else "other", TEMPLATES["other"])]
    en = exs[k % len(exs)]
    en = en[0].upper() + en[1:] + ("" if en[-1] in ".!?" else ".")
    vi = tr(en, "en", "vi")
    if not vi:
        return {"error": last_error or "Không dịch được"}
    return {"word": w, "en": en, "vi": vi}


def lookup(q):
    if VI_CHARS.search(q):
        word, meaning = tr(q, "vi", "en"), q
    else:
        word, meaning = q, tr(q, "en", "vi")
    r = {"word": word, "ipa": get_ipa(word), "meaning": meaning, "icon": "📌"}
    if not meaning or not word:
        r["error"] = last_error or "Không dịch được"
    return r


def lt_check(text):
    """Gọi LanguageTool, trả về danh sách lỗi."""
    body = urlencode({"text": text, "language": "en-US"}).encode()
    return _open("https://api.languagetool.org/v2/check", data=body)["matches"]


def grade(vi, ans, ref="", word=""):
    ans = ans.strip()
    if not ans:
        return {"error": "Bạn chưa viết câu trả lời."}
    if VI_CHARS.search(ans):
        return {"error": "Hãy viết câu trả lời bằng tiếng Anh nhé."}
    ref = ref or tr(vi, "vi", "en")
    try:
        ms = [m for m in lt_check(ans) if m["rule"]["category"]["id"] not in SKIP_CATEGORIES]
    except Exception as e:
        return {"error": f"Không chấm được ngữ pháp lúc này ({e}). Thử lại sau ít phút."}
    ms.sort(key=lambda m: m["offset"])
    segs, errs, cur, fixed = [], [], 0, ans
    used = []
    for m in ms:
        o, l = m["offset"], max(1, m["length"])
        if o < cur:
            continue
        if o > cur:
            segs.append({"t": ans[cur:o], "ok": True})
        segs.append({"t": ans[o:o + l], "ok": False})
        used.append((o, l, [r["value"] for r in m["replacements"][:3]]))
        errs.append({"text": ans[o:o + l], "msg": m["message"], "fix": [r["value"] for r in m["replacements"][:3]]})
        cur = o + l
    if cur < len(ans):
        segs.append({"t": ans[cur:], "ok": True})
    with ThreadPoolExecutor(6) as ex:  # dịch lời giải thích lỗi sang tiếng Việt
        for e, v in zip(errs, ex.map(lambda e: tr(e["msg"], "en", "vi"), errs)):
            e["msg"] = v or e["msg"]
    for o, l, fx in reversed(used):
        if fx:
            fixed = fixed[:o] + fx[0] + fixed[o + l:]
    words = set(re.findall(r"[a-z']+", ans.lower()))
    rwords = set(re.findall(r"[a-z']+", ref.lower()))
    common = len(words & rwords)
    p, r_ = common / max(len(words), 1), common / max(len(rwords), 1)
    f1 = 2 * p * r_ / (p + r_) if p + r_ else 0
    n = len(re.findall(r"[A-Za-z']+", ans))
    grammar = max(0.0, 1 - 1.2 * len(errs) / max(n, 5))
    score = round(10 * grammar * (0.35 + 0.65 * min(1, f1 * 2)), 1)
    stem = word.lower()[:-1] if len(word) > 4 else word.lower()
    return {"score": score, "segments": segs, "errors": errs, "corrected": fixed, "natural": ref,
            "word": word, "used": bool(word) and stem in ans.lower()}


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, ctype):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        p = {k: v[0].strip() for k, v in parse_qs(u.query).items()}
        j = lambda o: self._send(json.dumps(o, ensure_ascii=False), "application/json")
        if u.path == "/":
            self._send(PAGE, "text/html")
        elif u.path == "/api/lookup" and p.get("q"):
            j(lookup(p["q"]))
        elif u.path == "/api/grade" and p.get("vi"):
            j(grade(p["vi"], p.get("answer", ""), p.get("ref", ""), p.get("word", "")))
        elif u.path == "/api/exercise" and p.get("word"):
            j(exercise(p["word"], int(p["k"]) if p.get("k", "").isdigit() else 0))
        elif u.path == "/api/sentences":
            j(SENTENCES)
        else:
            self.send_error(404)

    def log_message(self, *a):
        pass


PAGE = r"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Lặp Từ Vựng Tiếng Anh</title>
<style>
:root{--bg:#faf9f7;--card:#fff;--ink:#1c1a17;--sub:#6b6560;--accent:#b91c1c;--accent-ink:#fff;--line:#e8e4de;--gbg:#dcfce7;--gink:#14532d;--rbg:#fee2e2;--rink:#7f1d1d}
@media (prefers-color-scheme:dark){:root{--bg:#17140f;--card:#211d17;--ink:#f3efe8;--sub:#a39c92;--accent:#f0655a;--accent-ink:#1a1310;--line:#332c22;--gbg:#14532d;--gink:#dcfce7;--rbg:#7f1d1d;--rink:#fee2e2}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;display:flex;justify-content:center;padding:32px 16px}
.wrap{width:100%;max-width:480px}
h1{font-size:1.3rem;margin:0 0 6px}
p.desc{color:var(--sub);margin:0 0 28px;font-size:.95rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:24px;margin-bottom:16px}
label{display:block;font-size:.85rem;color:var(--sub);margin-bottom:6px;font-weight:600}
input[type=text],textarea{width:100%;padding:14px 16px;font-size:1.3rem;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink);margin-bottom:12px;font-family:inherit}
textarea{font-size:1.05rem;padding:12px 14px;resize:vertical;margin-bottom:0}
input:focus,textarea:focus{outline:2px solid var(--accent);outline-offset:1px}
#meaningBox{display:none;margin:0 0 18px;padding:12px 14px;border-radius:10px;background:var(--bg);border:1px solid var(--line)}
#ipa{font-family:monospace;color:var(--accent);font-size:1rem}
.row{display:flex;gap:16px;margin-bottom:18px}.field{flex:1}
select,input[type=number]{width:100%;padding:10px 12px;font-size:1rem;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)}
.reps{display:flex;align-items:center;gap:10px}
.reps button{width:38px;height:38px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--ink);font-size:1.1rem;cursor:pointer}
.reps input{text-align:center;width:60px}
.playbar{display:flex;gap:10px;margin-top:22px}
button.main{flex:1;padding:14px;font-size:1.05rem;font-weight:700;border:none;border-radius:10px;background:var(--accent);color:var(--accent-ink);cursor:pointer}
button.main:disabled{opacity:.5}
button.stop{padding:14px 18px;font-size:1rem;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}
.status{margin-top:16px;text-align:center;color:var(--sub);font-size:.9rem;min-height:1.2em}
.count{font-size:2rem;font-weight:800;text-align:center;margin-top:6px;color:var(--accent)}
.hint{font-size:.8rem;color:var(--sub);margin:20px 0;line-height:1.5}
.quiz-opt{padding:12px 14px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink);font-size:1rem;text-align:left;cursor:pointer}
.quiz-opt.correct{background:#dcfce7;border-color:#22c55e;color:#14532d}
.quiz-opt.wrong{background:#fee2e2;border-color:#ef4444;color:#7f1d1d}
.vsent{font-size:1.2rem;font-weight:700;margin:4px 0 14px;line-height:1.5}
.score{font-size:2.4rem;font-weight:800;text-align:center}
.ans{font-size:1.15rem;line-height:1.9;margin:10px 0}
.ok{background:var(--gbg);color:var(--gink);border-radius:4px;padding:1px 3px}
.bad{background:var(--rbg);color:var(--rink);border-radius:4px;padding:1px 3px;text-decoration:underline wavy}
.err{padding:10px 12px;border-radius:10px;background:var(--bg);border-left:3px solid #ef4444;margin-bottom:8px;font-size:.92rem;line-height:1.5}
.box{padding:10px 12px;border-radius:10px;background:var(--bg);border-left:3px solid #22c55e;margin-top:8px;font-size:.95rem;line-height:1.5}
.box small{display:block;color:var(--sub);font-weight:600;margin-bottom:2px}
.link{background:none;border:none;color:var(--accent);cursor:pointer;font-size:.9rem;padding:8px 0}
</style></head>
<body><div class="wrap">
<h1>🔁 Lặp Từ Vựng Tiếng Anh</h1>
<p class="desc">Gõ từ hoặc câu tiếng Anh, chọn số lần lặp, bấm Phát. Tra từ nào thì có bài tập dịch câu chứa từ đó, chấm điểm ngữ pháp.</p>

<div class="card">
  <label for="word">Từ / cụm từ</label>
  <input type="text" id="word" placeholder="ví dụ: apple" autocomplete="off">
  <div id="meaningBox"><div style="display:flex;align-items:center;gap:10px">
    <div id="icon" style="font-size:2rem;line-height:1"></div>
    <div style="flex:1"><div id="ipa"></div><div id="meaning" style="margin-top:4px"></div></div></div></div>
  <div class="row">
    <div class="field"><label for="voice">Giọng đọc</label><select id="voice"></select></div>
    <div class="field"><label for="rate">Tốc độ</label>
      <select id="rate"><option value="0.6">Chậm</option><option value="0.8">Hơi chậm</option>
      <option value="1" selected>Bình thường</option><option value="1.2">Nhanh</option></select></div>
  </div>
  <label>Số lần lặp</label>
  <div class="reps"><button id="dec" type="button">−</button>
    <input type="number" id="reps" value="10" min="1" max="50"><button id="inc" type="button">+</button></div>
  <div class="playbar"><button class="main" id="play">▶️ Phát</button><button class="stop" id="stop">⏹ Dừng</button></div>
  <div class="count" id="count"></div><div class="status" id="status">Sẵn sàng</div>
</div>
<p class="hint">Mẹo: Chrome/Edge thường có nhiều giọng tiếng Anh nhất. Nếu không nghe thấy, thử chọn giọng khác.</p>

<div class="card">
  <label>✍️ Bài tập dịch câu: Việt → Anh</label>
  <div style="display:flex;gap:8px;align-items:center;margin-bottom:10px">
    <span style="font-size:.85rem;color:var(--sub);font-weight:600">Từ luyện:</span>
    <select id="exWord" style="flex:1"></select>
  </div>
  <div class="vsent" id="vi"></div>
  <textarea id="answer" rows="3" placeholder="Viết câu tiếng Anh của bạn..."></textarea>
  <div style="display:flex;gap:10px;margin-top:10px">
    <button class="main" id="gradeBtn" type="button">Chấm bài</button>
    <button class="stop" id="newBtn" type="button">🔀 Câu khác</button>
  </div>
  <button class="link" id="customToggle" type="button">+ Tự nhập câu tiếng Việt để luyện</button>
  <div id="customBox" style="display:none">
    <textarea id="customVi" rows="2" placeholder="Nhập câu tiếng Việt..."></textarea>
    <button class="stop" id="useCustom" type="button" style="margin-top:8px;width:100%">Dùng câu này</button>
  </div>
  <div id="result" style="display:none;margin-top:18px"></div>
</div>

<div class="card" id="quizCard" style="display:none">
  <label style="margin-bottom:14px">🎯 Kiểm tra từ đã học</label>
  <div id="quizIntro" style="font-size:.9rem;color:var(--sub);margin-bottom:14px"></div>
  <button class="main" id="quizStart" type="button" style="width:100%">Bắt đầu kiểm tra</button>
  <div id="quizBody" style="display:none">
    <div style="text-align:center;margin:6px 0 4px;font-size:1.8rem;font-weight:800" id="qMain"></div>
    <div style="text-align:center;color:var(--sub);font-size:.85rem;margin-bottom:16px" id="qSub"></div>
    <div id="qOpts" style="display:flex;flex-direction:column;gap:10px"></div>
    <div id="qSpell" style="display:none"><input type="text" id="spellIn" placeholder="Viết lại từ tiếng Anh..." autocomplete="off">
      <button class="main" id="spellBtn" type="button" style="width:100%">Kiểm tra</button></div>
    <div id="qFb" style="margin-top:14px;text-align:center;font-weight:700;min-height:1.4em"></div>
    <button class="main" id="qNext" type="button" style="width:100%;margin-top:14px;display:none">Từ tiếp theo ▶️</button>
  </div>
</div>
</div>

<script>
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const wordEl=$('word'), voiceEl=$('voice'), rateEl=$('rate'), repsEl=$('reps'), playBtn=$('play'), statusEl=$('status'), countEl=$('count');
let voices=[], playing=false, stopRequested=false, current=null;

// ---- Giọng đọc + lặp ----
function loadVoices(){
  const all = speechSynthesis.getVoices();
  voices = all.filter(v => v.lang.toLowerCase().startsWith('en'));
  if(!voices.length) voices = all;
  voiceEl.innerHTML = '';
  voices.forEach((v,i) => { const o=document.createElement('option'); o.value=i; o.textContent=v.name+' ('+v.lang+')'; voiceEl.appendChild(o); });
}
loadVoices();
if('onvoiceschanged' in speechSynthesis) speechSynthesis.onvoiceschanged = loadVoices;
$('dec').onclick = () => repsEl.value = Math.max(1,(+repsEl.value||1)-1);
$('inc').onclick = () => repsEl.value = Math.min(50,(+repsEl.value||1)+1);
function speakOnce(text, voice, rate){
  return new Promise(res => {
    const u = new SpeechSynthesisUtterance(text);
    if(voice) u.voice = voice;
    u.lang='en-US'; u.rate=rate; u.onend=res; u.onerror=res;
    speechSynthesis.speak(u);
  });
}
const say = t => { speechSynthesis.cancel(); speakOnce(t, voices[+voiceEl.value]||null, +rateEl.value||1); };
async function playLoop(){
  let text = wordEl.value.trim();
  if(!text){ statusEl.textContent='Vui lòng nhập từ hoặc câu tiếng Anh.'; return; }
  if(/[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]/i.test(text) && current) text = current.word;
  const total = Math.min(50, Math.max(1, +repsEl.value||1));
  playing=true; stopRequested=false; playBtn.disabled=true; statusEl.textContent='Đang phát...';
  for(let i=1;i<=total;i++){
    if(stopRequested) break;
    countEl.textContent = i+' / '+total;
    await speakOnce(text, voices[+voiceEl.value]||null, +rateEl.value||1);
    await new Promise(r => setTimeout(r,350));
  }
  playing=false; playBtn.disabled=false;
  statusEl.textContent = stopRequested ? 'Đã dừng.' : 'Hoàn tất!';
}
playBtn.onclick = () => { if(playing) return; speechSynthesis.cancel(); playLoop(); };
$('stop').onclick = () => { stopRequested=true; speechSynthesis.cancel(); playing=false; playBtn.disabled=false; statusEl.textContent='Đã dừng.'; };
wordEl.addEventListener('keydown', e => { if(e.key==='Enter') playBtn.click(); });

// ---- Từ đã học (lưu trong trình duyệt) ----
let learned = [];
try{ learned = JSON.parse(localStorage.getItem('learned_en')||'[]'); }catch(e){}
function addLearned(word, ipa, meaning, icon){
  if(!word || !meaning || learned.some(w => w.word.toLowerCase()===word.toLowerCase())) return;
  learned.push({word, ipa, meaning, icon:icon||'📌'});
  if(learned.length>60) learned.shift();
  try{ localStorage.setItem('learned_en', JSON.stringify(learned)); }catch(e){}
  refreshQuizIntro();
}
function refreshQuizIntro(){
  if(!learned.length) return;
  $('quizCard').style.display='block';
  $('quizIntro').textContent = 'Đã học '+learned.length+' từ. Bấm bắt đầu để tự kiểm tra.';
}
refreshQuizIntro();

// ---- Tra IPA + nghĩa khi gõ ----
let timer=null, lastQ='';
wordEl.addEventListener('input', () => {
  clearTimeout(timer);
  const text = wordEl.value.trim();
  if(!text){ $('meaningBox').style.display='none'; return; }
  timer = setTimeout(() => lookup(text), 600);
});
async function lookup(text){
  if(text===lastQ) return;
  lastQ = text;
  $('meaningBox').style.display='block'; $('ipa').textContent=''; $('meaning').textContent='Đang tra...';
  try{
    const r = await (await fetch('/api/lookup?q='+encodeURIComponent(text))).json();
    if(text !== wordEl.value.trim()) return;
    current = r;
    $('ipa').textContent = r.ipa || '';
    $('meaning').textContent = r.error ? '⚠️ Lỗi dịch: '+r.error : (r.meaning || '(không rõ nghĩa)');
    $('icon').textContent = r.icon;
    if(!r.error){ addLearned(r.word, r.ipa, r.meaning, r.icon); fillExWords(r.word); exK=0; newSentence(); }
  }catch(e){ $('meaning').textContent='Không tra được nghĩa lúc này.'; }
}

// ---- Bài tập dịch câu Việt -> Anh ----
let sentences=[], curVi='', curRef='', exTarget='', exK=0;
function fillExWords(sel){
  const cur = sel !== undefined ? sel : $('exWord').value;
  $('exWord').innerHTML = '<option value="">📚 Câu chung (không theo từ)</option>'+
    learned.map(w => '<option value="'+esc(w.word)+'">'+esc(w.word)+' — '+esc(w.meaning)+'</option>').join('');
  $('exWord').value = cur;
}
async function newSentence(){
  const w = $('exWord').value;
  if(w){
    $('vi').textContent='Đang tạo câu...'; $('result').style.display='none';
    try{
      const r = await (await fetch('/api/exercise?word='+encodeURIComponent(w)+'&k='+(exK++))).json();
      if(r.error){ $('vi').textContent='⚠️ Lỗi dịch: '+r.error; return; }
      setVi(r.vi, r.en, r.word);
    }catch(e){ $('vi').textContent='⚠️ Không tạo được câu lúc này.'; }
    return;
  }
  if(!sentences.length){ try{ sentences = await (await fetch('/api/sentences')).json(); }catch(e){} }
  if(!sentences.length) return;
  let s; do{ s = sentences[Math.floor(Math.random()*sentences.length)]; }while(s===curVi && sentences.length>1);
  setVi(s);
}
function setVi(s, ref, word){
  curVi=s; curRef=ref||''; exTarget=word||'';
  $('vi').innerHTML = '🇻🇳 '+esc(s)+(word ? '<div style="font-size:.85rem;color:var(--sub);font-weight:600;margin-top:6px">Hãy dùng từ: <span style="color:var(--accent)">'+esc(word)+'</span></div>' : '');
  $('answer').value=''; $('result').style.display='none';
}
$('exWord').onchange = () => { exK = Math.floor(Math.random()*5); newSentence(); };
$('newBtn').onclick = newSentence;
$('customToggle').onclick = () => { const b=$('customBox'); b.style.display = b.style.display==='none'?'block':'none'; };
$('useCustom').onclick = () => { const s=$('customVi').value.trim(); if(s){ setVi(s); $('customBox').style.display='none'; } };
$('gradeBtn').onclick = async () => {
  const ans = $('answer').value.trim(); if(!ans || !curVi) return;
  const btn=$('gradeBtn'); btn.disabled=true; btn.textContent='Đang chấm...';
  const box=$('result'); box.style.display='block'; box.innerHTML='<div style="color:var(--sub)">Đang chấm bài...</div>';
  try{
    const r = await (await fetch('/api/grade?vi='+encodeURIComponent(curVi)+'&answer='+encodeURIComponent(ans)+'&ref='+encodeURIComponent(curRef)+'&word='+encodeURIComponent(exTarget))).json();
    if(r.error){ box.innerHTML='<div class="err">⚠️ '+esc(r.error)+'</div>'; }
    else{
      const label = r.score>=9?'Tuyệt vời! 🎉':r.score>=7?'Tốt lắm 👍':r.score>=5?'Khá ổn, cố thêm nhé':'Cần luyện thêm 💪';
      const col = r.score>=7?'#16a34a':r.score>=5?'#d97706':'#dc2626';
      box.innerHTML =
        '<div class="score" style="color:'+col+'">'+r.score+' / 10</div>'+
        '<div style="text-align:center;color:var(--sub);margin-bottom:10px">'+label+'</div>'+
        '<div class="ans">'+r.segments.map(s => '<span class="'+(s.ok?'ok':'bad')+'">'+esc(s.t)+'</span>').join('')+'</div>'+
        (r.errors.length ? '<label style="margin-top:14px">Lỗi cần sửa ('+r.errors.length+')</label>'+r.errors.map(e =>
          '<div class="err"><b>“'+esc(e.text)+'”</b> — '+esc(e.msg)+(e.fix.length?'<br>Gợi ý sửa: <b>'+e.fix.map(esc).join(' / ')+'</b>':'')+'</div>').join('')
          : '<div class="box"><small>Ngữ pháp</small>Không phát hiện lỗi ngữ pháp. ✅</div>')+
        (r.errors.length ? '<div class="box"><small>✅ Câu sau khi sửa lỗi</small>'+esc(r.corrected)+'</div>' : '')+
        (r.word ? '<div class="box"><small>🎯 Từ luyện: '+esc(r.word)+'</small>'+(r.used?'✅ Bạn đã dùng từ này trong câu.':'⚠️ Câu của bạn chưa dùng từ này.')+'</div>' : '')+
        '<div class="box"><small>💡 Gợi ý cách viết tự nhiên hơn</small>'+esc(r.natural)+
          ' <button class="link" id="sayNat" type="button">🔊</button></div>'+
        '<div style="font-size:.78rem;color:var(--sub);margin-top:10px;line-height:1.5">Xanh = đúng, đỏ = lỗi. Điểm là ước lượng tự động (ngữ pháp + độ sát nghĩa với bản dịch tham khảo); câu gợi ý là câu mẫu từ từ điển hoặc bản dịch máy nên chỉ để tham khảo.</div>';
      $('sayNat').onclick = () => say(r.natural);
    }
  }catch(e){ box.innerHTML='<div class="err">⚠️ Không chấm được lúc này, thử lại nhé.</div>'; }
  btn.disabled=false; btn.textContent='Chấm bài';
};
fillExWords(''); newSentence();

// ---- Kiểm tra từ đã học ----
const shuffle = a => { a=a.slice(); for(let i=a.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[a[i],a[j]]=[a[j],a[i]];} return a; };
const pick = a => a[Math.floor(Math.random()*a.length)];
const modes=['en2vi','vi2en','listen','spell']; let mi=-1, curWord=null;
function render(opts, correct){
  $('qSpell').style.display='none'; $('qOpts').style.display='flex'; $('qOpts').innerHTML='';
  opts.forEach(o => {
    const b=document.createElement('button'); b.className='quiz-opt'; b.type='button'; b.textContent=o;
    b.onclick = () => {
      document.querySelectorAll('#qOpts button').forEach(x => { x.disabled=true; if(x.textContent===correct) x.classList.add('correct'); });
      if(o===correct){ $('qFb').textContent='✅ Chính xác!'; $('qFb').style.color='#16a34a'; setTimeout(nextQ,900); }
      else { b.classList.add('wrong'); $('qFb').textContent='❌ Đáp án: '+correct; $('qFb').style.color='#dc2626'; $('qNext').style.display='block'; }
    };
    $('qOpts').appendChild(b);
  });
}
function nextQ(){
  $('quizBody').style.display='block'; $('quizStart').style.display='none';
  if(learned.length<2){ $('qFb').textContent='Cần học ít nhất 2 từ để kiểm tra.'; return; }
  $('qFb').textContent=''; $('qNext').style.display='none';
  mi=(mi+1)%modes.length; const m=modes[mi];
  const w=pick(learned), o=shuffle(learned.filter(x=>x!==w)).slice(0,4); curWord=w;
  if(m==='en2vi'){ $('qMain').textContent=w.icon+'  '+w.word; $('qSub').textContent='Anh → Việt'; render(shuffle([w.meaning,...o.map(x=>x.meaning)]), w.meaning); }
  if(m==='vi2en'){ $('qMain').textContent=w.icon+'  '+w.meaning; $('qSub').textContent='Việt → Anh'; render(shuffle([w.word,...o.map(x=>x.word)]), w.word); }
  if(m==='listen'){
    $('qMain').innerHTML='🔊 <button type="button" id="again" class="stop" style="font-size:.95rem">Nghe lại</button>'; $('qSub').textContent='Nghe & chọn đúng từ';
    $('again').onclick=()=>say(w.word); setTimeout(()=>say(w.word),200); render(shuffle([w.word,...o.map(x=>x.word)]), w.word);
  }
  if(m==='spell'){
    $('qMain').innerHTML='🔊 <button type="button" id="again" class="stop" style="font-size:.95rem">Nghe lại</button>'; $('qSub').textContent='Nghe & viết lại (tiếng Anh)';
    $('again').onclick=()=>say(w.word); setTimeout(()=>say(w.word),200);
    $('qOpts').style.display='none'; $('qSpell').style.display='block'; $('spellIn').value=''; $('spellIn').focus();
  }
}
$('spellBtn').onclick = () => {
  if(!curWord) return;
  const ok = $('spellIn').value.trim().toLowerCase()===curWord.word.toLowerCase();
  $('qFb').textContent = ok ? '✅ Chính xác!' : '❌ Đáp án: '+curWord.word; $('qFb').style.color = ok?'#16a34a':'#dc2626';
  if(ok) setTimeout(nextQ,900); else $('qNext').style.display='block';
};
$('spellIn').addEventListener('keydown', e => { if(e.key==='Enter') $('spellBtn').click(); });
$('quizStart').onclick = nextQ; $('qNext').onclick = nextQ;
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8001)))
    ap.add_argument("--lan", action="store_true", help="cho điện thoại cùng Wi-Fi truy cập")
    a = ap.parse_args()
    host = "0.0.0.0" if (a.lan or "PORT" in os.environ) else "127.0.0.1"
    print(f"Mở trình duyệt: http://localhost:{a.port}")
    if a.lan:
        print(f"Điện thoại (cùng Wi-Fi): http://{socket.gethostbyname(socket.gethostname())}:{a.port}")
    print("Nhấn Ctrl+C để tắt.")
    ThreadingHTTPServer((host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
