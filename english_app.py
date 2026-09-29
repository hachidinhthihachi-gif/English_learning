"""
Lặp Từ Vựng Tiếng Anh + Bài tập dịch câu Việt -> Anh
Dùng thư viện chuẩn Python, đã tối ưu an toàn tuyệt đối cho Render.
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

def _fj(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))

def _short(e):
    m = re.search(r"HTTP Error (\d+)", str(e))
    return "lỗi " + m.group(1) if m else "không kết nối được"

def tr(text, src, dst):
    global last_error
    key = (text, src, dst)
    if key in _cache:
        return _cache[key]
    q = quote(text, safe="")
    zs, zd = ("zh" if x.startswith("zh") else x for x in (src, dst))
    gkey, email = os.environ.get("GOOGLE_API_KEY"), os.environ.get("MYMEMORY_EMAIL")

    def google2():
        d = _fj(f"https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl={src}&tl={dst}&q={q}")
        return "".join(s["trans"] for s in d["sentences"]) if isinstance(d, dict) else d[0][0]

    providers = []
    if gkey:
        providers.append(("GoogleAPI", lambda: _fj(
            f"https://translation.googleapis.com/language/translate/v2?key={gkey}&q={q}&source={src}&target={dst}&format=text"
        )["data"]["translations"][0]["translatedText"]))
    providers += [
        ("Google", lambda: "".join(p[0] for p in _fj(
            f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={src}&tl={dst}&dt=t&q={q}")[0] if p[0])),
        ("Google2", google2),
        ("Lingva", lambda: _fj(f"https://lingva.ml/api/v1/{zs}/{zd}/{q}")["translation"]),
        ("MyMemory", lambda: _fj(f"https://api.mymemory.translated.net/get?q={q}&langpair={src}|{dst}"
                                 + (f"&de={quote(email)}" if email else ""))["responseData"]["translatedText"]),
    ]
    errs = []
    for name, fn in providers:
        try:
            out = (fn() or "").strip()
        except Exception as e:
            errs.append(f"{name} {_short(e)}")
            continue
        if out and not out.upper().startswith("MYMEMORY WARNING"):
            _cache[key] = out
            return out
        errs.append(f"{name} hết hạn mức" if out else f"{name} trả về rỗng")
    last_error = "Các dịch vụ dịch đều lỗi. Thử lại sau ít phút."
    return ""

_entries = {}
TEMPLATES = {
    "noun": ["I saw a {w} on my way home yesterday.", "This is my favorite {w}.", "Do you have a {w}?"],
    "verb": ["I want to {w} every day.", "She can {w} very well.", "They {w} together on weekends."],
    "adjective": ["The room is very {w}.", "She feels {w} today.", "It looks {w} to me."],
    "adverb": ["He speaks {w}.", "She did it {w}.", "They walked {w} to school."],
    "other": ['I learned the word "{w}" today.', 'Can you use the word "{w}" in a sentence?'],
}

def fetch_entry(word):
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
    if not exs:
        exs = [t.format(w=w) for t in TEMPLATES.get(pos[0] if pos else "other", TEMPLATES["other"])]
    en = exs[k % len(exs)]
    en = en[0].upper() + en[1:] + ("" if en[-1] in ".!?" else ".")
    vi = tr(en, "en", "vi")
    if not vi:
        return {"error": last_error or "Không dịch được"}
    return {"word": w, "en": en, "vi": vi}

def lookup(q):
    q_clean = q.strip()
    if VI_CHARS.search(q_clean):
        word, meaning = tr(q_clean, "vi", "en"), q_clean
    else:
        word = q_clean
        d = fetch_entry(word)
        meanings_list = []
        if d and "meanings" in d:
            for m in d["meanings"]:
                pos = m.get("partOfSpeech", "")
                defs = m.get("definitions", [])
                if defs:
                    def_en = defs[0].get("definition", "")
                    if def_en:
                        def_vi = tr(def_en, "en", "vi")
                        if def_vi:
                            meanings_list.append(f"({pos}) {def_vi}")
        if meanings_list:
            meaning = " | ".join(meanings_list)
        else:
            meaning = tr(word, "en", "vi")

    r = {"word": word, "ipa": get_ipa(word), "meaning": meaning, "icon": "📌"}
    if not meaning or not word:
        r["error"] = last_error or "Không dịch được"
    return r

def lt_check(text):
    body = urlencode({"text": text, "language": "en-US"}).encode()
    return _open("https://api.languagetool.org/v2/check", data=body)["matches"]

def grade(vi, ans, ref="", word=""):
    ans = ans.strip()
    if not ans:
        return {"error": "Bạn chưa viết câu trả lời."}
    if VI_CHARS.search(ans):
        return {"error": "Hãy viết câu trả lời bằng tiếng Anh nhé."}
    
    # 1. Đảm bảo câu tham khảo (natural) không bị rỗng hay lỗi ký tự lẻ
    ref = ref.strip() if ref else ""
    if not ref or len(ref) <= 2:
        try:
            ref = tr(vi, "vi", "en")
        except Exception:
            ref = ""
    if not ref or len(ref) <= 2:
        ref = "Chưa lấy được câu gợi ý chuẩn lúc này."

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
        
    # Khối dịch lỗi được định dạng thụt lề chuẩn xác
    if errs:
        try:
            with ThreadPoolExecutor(max_workers=3) as ex:
                translated_msgs = list(ex.map(lambda item: tr(item["msg"], "en", "vi"), errs))
                for e, v in zip(errs, translated_msgs):
                    e["msg"] = v or e["msg"]
        except Exception:
            pass
            
    for o, l, fx in reversed(used):
        if fx:
            fixed = fixed[:o] + fx[0] + fixed[o + l:]
            
    # 2. Cải tiến thuật toán tính điểm hợp lý
    words = set(re.findall(r"[a-z']+", ans.lower()))
    rwords = set(re.findall(r"[a-z']+", ref.lower()))
    
    common = len(words & rwords)
    f1 = (2 * common) / max(len(words) + len(rwords), 1)
    
    n = len(re.findall(r"[A-Za-z']+", ans))
    grammar_score = max(0.2, 1.0 - (0.5 * len(errs) / max(n, 4)))
    meaning_score = max(0.4, f1)
    
    score = round(10 * (0.6 * grammar_score + 0.4 * meaning_score), 1)
    
    stem = word.lower()[:-1] if len(word) > 4 else word.lower()
    return {
        "score": score, 
        "segments": segs, 
        "errors": errs, 
        "corrected": fixed, 
        "natural": ref,
        "word": word, 
        "used": bool(word) and stem in ans.lower()
    }

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
  <div id="result" style="display:none;margin-top:18px"></div>
</div>
</div>

<script>
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const wordEl=$('word'), voiceEl=$('voice'), rateEl=$('rate'), repsEl=$('reps'), playBtn=$('play'), statusEl=$('status'), countEl=$('count');
let voices=[], playing=false, stopRequested=false, current=null;

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

let learned = [];
try{ learned = JSON.parse(localStorage.getItem('learned_en')||'[]'); }catch(e){}
function addLearned(word, ipa, meaning, icon){
  if(!word || !meaning || learned.some(w => w.word.toLowerCase()===word.toLowerCase())) return;
  learned.push({word, ipa, meaning, icon:icon||'📌'});
  if(learned.length>60) learned.shift();
  try{ localStorage.setItem('learned_en', JSON.stringify(learned)); }catch(e){}
}

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
        '<div class="box"><small>💡 Gợi ý cách viết tự nhiên hơn</small>'+esc(r.natural)+'</div>';
    }
  }catch(e){ box.innerHTML='<div class="err">⚠️ Không chấm được lúc này, thử lại nhé.</div>'; }
  btn.disabled=false; btn.textContent='Chấm bài';
};
fillExWords(''); newSentence();
</script></body></html>
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8001)))
    a = ap.parse_args()
    host = "0.0.0.0"
    print(f"Server đang chạy tại cổng: {a.port}")
    ThreadingHTTPServer((host, a.port), Handler).serve_forever()

if __name__ == "__main__":
    main()