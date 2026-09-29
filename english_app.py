"""
Luyện Từ Vựng Tiếng Anh + Bài tập dịch câu Việt -> Anh
Cập nhật: Dùng Icon thay cho hình ảnh (load siêu nhanh) & Thêm hướng dẫn cách phát âm / học từ.
"""
import argparse
import json
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlencode, urlparse

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
VI_CHARS = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)
SKIP_CATEGORIES = {"STYLE", "REDUNDANCY", "PLAIN_ENGLISH", "WIKIPEDIA", "TYPOGRAPHY"}

COMMON_DICT = {
    "sample": "mẫu, bản mẫu", "apple": "quả táo", "banana": "quả chuối", "book": "quyển sách",
    "cat": "con mèo", "dog": "con chó", "house": "ngôi nhà", "water": "nước", "happy": "vui vẻ",
    "study": "học tập", "work": "làm việc", "friend": "bạn bè", "family": "gia đình",
    "car": "xe hơi", "school": "trường học", "teacher": "giáo viên", "student": "học sinh",
    "visual arts": "nghệ thuật thị giác", "visual art": "nghệ thuật thị giác"
}

_cache = {}

def _fj(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode("utf-8"))

def tr(text, src, dst):
    if not text or not text.strip():
        return ""
    text = text.strip()
    key = (text, src, dst)
    if key in _cache:
        return _cache[key]
    
    if src == "en" and dst == "vi" and text.lower() in COMMON_DICT:
        return COMMON_DICT[text.lower()]

    q = quote(text, safe="")
    zs, zd = ("zh" if x.startswith("zh") else x for x in (src, dst))
    gkey = os.environ.get("GOOGLE_API_KEY")

    providers = []
    if gkey:
        providers.append(("GoogleAPI", lambda: _fj(
            f"https://translation.googleapis.com/language/translate/v2?key={gkey}&q={q}&source={src}&target={dst}&format=text"
        )["data"]["translations"][0]["translatedText"]))
    
    providers += [
        ("GoogleT", lambda: "".join(p[0] for p in _fj(
            f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={src}&tl={dst}&dt=t&q={q}")[0] if p[0])),
        ("GoogleDict", lambda: _fj(f"https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl={src}&tl={dst}&q={q}")[0][0]),
        ("Lingva", lambda: _fj(f"https://lingva.ml/api/v1/{zs}/{zd}/{q}")["translation"]),
        ("MyMemory", lambda: _fj(f"https://api.mymemory.translated.net/get?q={q}&langpair={src}|{dst}")["responseData"]["translatedText"]),
    ]

    for name, fn in providers:
        try:
            out = (fn() or "").strip()
            if out and not out.upper().startswith("MYMEMORY WARNING") and out.lower() != text.lower():
                _cache[key] = out
                return out
        except Exception:
            continue
            
    return ""

_entries = {}
def fetch_entry(word):
    w = word.strip().lower()
    if w in _entries:
        return _entries[w]
    try:
        d = _fj("https://api.dictionaryapi.dev/api/v2/entries/en/" + quote(w))
        if isinstance(d, list) and len(d) > 0:
            _entries[w] = d[0]
            return d[0]
    except Exception:
        pass
    return {}

def get_ipa_and_guide(word):
    words = word.strip().split()
    ipas = []
    for w in words:
        d = fetch_entry(w)
        ipa = ""
        if d:
            ipa = d.get("phonetic") or next((p["text"] for p in d.get("phonetics", []) if p.get("text")), "")
        ipas.append(ipa if ipa else "")
    
    ipa_str = " ".join(ipas).strip()
    ipa_res = f"/{ipa_str}/" if ipa_str else ""
    
    # Hướng dẫn mẹo phát âm & nhấn trọng âm
    if "ˈ" in ipa_res:
        guide = "💡 Trọng âm rơi vào âm tiết đứng ngay sau dấu [ ˈ ]. Hãy đọc âm đó to và rõ hơn."
    elif len(words) > 1:
        guide = "💡 Cụm từ gồm nhiều từ: Đọc lướt nối âm nhẹ giữa các từ, giữ nguyên ngữ điệu câu."
    else:
        guide = "💡 Phát âm rõ phụ âm cuối (nếu có) để chuẩn giọng bản ngữ."

    return ipa_res, guide

def get_icon(word):
    w = word.lower()
    if any(k in w for k in ["art", "draw", "paint", "visual"]): return "🎨"
    if any(k in w for k in ["music", "sing", "song"]): return "🎵"
    if any(k in w for k in ["book", "read", "study"]): return "📚"
    if any(k in w for k in ["food", "eat", "apple", "banana"]): return "🍎"
    if any(k in w for k in ["tech", "code", "computer"]): return "💻"
    if any(k in w for k in ["car", "drive", "travel"]): return "🚗"
    return "📌"

def lookup(q):
    q_clean = q.strip()
    if not q_clean:
        return {"word": "", "ipa": "", "guide": "", "meaning": "", "icon": "📌"}

    if VI_CHARS.search(q_clean):
        word = tr(q_clean, "vi", "en") or q_clean
        meaning = q_clean
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
                        if def_vi and len(def_vi) > 2:
                            meanings_list.append(f"({pos}) {def_vi}")
                            
        if meanings_list:
            meaning = " | ".join(meanings_list[:2])
        else:
            meaning = tr(word, "en", "vi")

    if not meaning or len(meaning.strip()) <= 1 or meaning.lower() == word.lower():
        meaning = COMMON_DICT.get(word.lower(), tr(word, "en", "vi") or "Từ vựng tiếng Anh")

    ipa, guide = get_ipa_and_guide(word)

    return {
        "word": word,
        "ipa": ipa,
        "guide": guide,
        "meaning": meaning,
        "icon": get_icon(word)
    }

def exercise(word, meaning=""):
    w = word.strip()
    m_vn = meaning.split("|")[0].split(")")[-1].strip() if meaning else tr(w, "en", "vi") or w
    
    templates_vi = [
        f"Nghệ thuật thị giác đóng một vai trò quan trọng trong đời sống.",
        f"Tôi rất thích tìm hiểu về {m_vn}.",
        f"Bạn có quan tâm đến {m_vn} không?",
        f"Họ đang nghiên cứu về các tác phẩm {m_vn} hiện đại."
    ]
    
    d = fetch_entry(w.split()[0] if " " in w else w)
    ref_en = f"Visual arts play an important role in modern life." if "visual" in w.lower() else f"I really like {w}."
    if d and "meanings" in d:
        for m in d["meanings"]:
            for df in m.get("definitions", []):
                if df.get("example"):
                    ref_en = df["example"]
                    break

    vi_sent = templates_vi[hash(w) % len(templates_vi)]
    return {"word": w, "meaning": m_vn, "vi": vi_sent, "ref": ref_en}

def lt_check(text):
    body = urlencode({"text": text, "language": "en-US"}).encode()
    req = urllib.request.Request("https://api.languagetool.org/v2/check", data=body, headers=UA)
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode("utf-8"))["matches"]

def grade(vi, ans, ref="", word=""):
    ans = ans.strip()
    if not ans:
        return {"error": "Bạn chưa viết câu trả lời."}
    if VI_CHARS.search(ans):
        return {"error": "Hãy viết câu trả lời hoàn toàn bằng tiếng Anh nhé."}
    
    ref = ref.strip() if ref else tr(vi, "vi", "en") or "Visual arts play an important role in modern life."

    word_used = True
    stem = word.lower()[:-1] if len(word) > 4 else word.lower()
    if word and stem not in ans.lower():
        word_used = False

    ms = []
    try:
        ms = [m for m in lt_check(ans) if m["rule"]["category"]["id"] not in SKIP_CATEGORIES]
    except Exception:
        pass

    ms.sort(key=lambda m: m["offset"])
    
    segs = []
    errs = []
    cur = 0
    
    for m in ms:
        o, l = m["offset"], max(1, m["length"])
        if o < cur:
            continue
        if o > cur:
            segs.append({"t": ans[cur:o], "ok": True})
        segs.append({"t": ans[o:o + l], "ok": False})
        
        fixes = [r["value"] for r in m.get("replacements", [])[:2]]
        errs.append({
            "text": ans[o:o + l],
            "msg": m["message"],
            "fix": fixes
        })
        cur = o + l
        
    if cur < len(ans):
        segs.append({"t": ans[cur:], "ok": True})

    if errs:
        try:
            with ThreadPoolExecutor(max_workers=3) as ex:
                translated_msgs = list(ex.map(lambda item: tr(item["msg"], "en", "vi"), errs))
                for e, v in zip(errs, translated_msgs):
                    e["msg"] = v or e["msg"]
        except Exception:
            pass

    words_ans = set(re.findall(r"[a-z']+", ans.lower()))
    words_ref = set(re.findall(r"[a-z']+", ref.lower()))
    common = len(words_ans & words_ref)
    overlap = common / max(len(words_ref), 1)

    score_word = 4.0 if word_used else 1.5
    score_grammar = max(0.5, 3.0 - (len(errs) * 0.8))
    score_meaning = max(1.0, min(3.0, overlap * 3.0 + 1.0))

    final_score = round(score_word + score_grammar + score_meaning, 1)
    final_score = min(10.0, max(2.0, final_score))

    return {
        "score": final_score,
        "segments": segs if segs else [{"t": ans, "ok": True}],
        "errors": errs,
        "corrected": ref,
        "natural": ref,
        "word": word,
        "used": word_used
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
            j(exercise(p["word"], p.get("meaning", "")))
        else:
            self.send_error(404)

    def log_message(self, *a):
        pass

PAGE = r"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Luyện Từ Vựng Tiếng Anh</title>
<style>
:root{--bg:#faf9f7;--card:#fff;--ink:#1c1a17;--sub:#6b6560;--accent:#b91c1c;--line:#e8e4de;--gbg:#dcfce7;--gink:#14532d;--rbg:#fee2e2;--rink:#7f1d1d}
@media (prefers-color-scheme:dark){:root{--bg:#17140f;--card:#211d17;--ink:#f3efe8;--sub:#a39c92;--accent:#f0655a;--line:#332c22;--gbg:#14532d;--gink:#dcfce7;--rbg:#7f1d1d;--rink:#fee2e2}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,sans-serif;display:flex;justify-content:center;padding:24px 16px}
.wrap{width:100%;max-width:500px}
h1{font-size:1.3rem;margin:0 0 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px;margin-bottom:16px}
label{display:block;font-size:.85rem;color:var(--sub);margin-bottom:6px;font-weight:600}
input[type=text],textarea{width:100%;padding:12px;font-size:1.1rem;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink);margin-bottom:12px}
textarea{font-size:1rem;resize:vertical}
#meaningBox{display:none;margin-bottom:12px;padding:14px;border-radius:12px;background:var(--bg);border:1px solid var(--line)}
.icon-badge{font-size:2.5rem;text-align:center;margin:8px 0}
.ipa-badge{font-family:monospace;color:var(--accent);font-size:1.05rem;font-weight:bold;background:rgba(185,28,28,0.1);padding:4px 8px;border-radius:6px;display:inline-block;margin-top:6px}
.pron-guide{font-size:.85rem;color:var(--sub);margin-top:6px;font-style:italic;line-height:1.4}
button.main{width:100%;padding:12px;font-size:1rem;font-weight:700;border:none;border-radius:10px;background:var(--accent);color:#fff;cursor:pointer}
button.main:disabled{opacity:.5}
.vsent{font-size:1.1rem;font-weight:700;margin:8px 0 12px;color:var(--ink)}
.score{font-size:2.2rem;font-weight:800;text-align:center;margin:10px 0}
.ans-review{font-size:1.15rem;line-height:1.8;padding:12px;border-radius:10px;background:var(--bg);border:1px solid var(--line);margin:12px 0}
.ok-text{background:var(--gbg);color:var(--gink);padding:2px 5px;border-radius:4px;font-weight:600}
.bad-text{background:var(--rbg);color:var(--rink);padding:2px 5px;border-radius:4px;font-weight:600;text-decoration:underline wavy #ef4444}
.err{padding:10px;border-radius:8px;background:var(--bg);border-left:3px solid #ef4444;margin-bottom:8px;font-size:.9rem}
.box{padding:10px;border-radius:8px;background:var(--bg);border-left:3px solid #22c55e;margin-top:8px;font-size:.9rem}
</style></head>
<body><div class="wrap">
<h1>🔁 Luyện Từ Vựng Tiếng Anh</h1>

<div class="card">
  <label for="word">Tra từ mới</label>
  <input type="text" id="word" placeholder="ví dụ: Visual Arts, sample..." autocomplete="off">
  <div id="meaningBox">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div id="meaning" style="font-size:1.1rem;font-weight:700"></div>
      <span id="headerIcon" style="font-size:1.2rem">📌</span>
    </div>
    <div id="iconDisplay" class="icon-badge">📌</div>
    <div id="ipaDisplay" class="ipa-badge"></div>
    <div id="guideDisplay" class="pron-guide"></div>
  </div>
</div>

<div class="card">
  <label>✍️ Bài tập đặt câu chứa từ vừa tra</label>
  <div class="vsent" id="vi">Hãy tra 1 từ ở trên để bắt đầu bài tập.</div>
  <textarea id="answer" rows="3" placeholder="Viết câu tiếng Anh của bạn tại đây..."></textarea>
  <button class="main" id="gradeBtn" type="button">Chấm điểm bài làm</button>
  <div id="result" style="display:none;margin-top:16px"></div>
</div>
</div>

<script>
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let timer=null, curWord='', curMeaning='', curRef='', curVi='';

$('word').addEventListener('input', () => {
  clearTimeout(timer);
  const q = $('word').value.trim();
  if(!q){ $('meaningBox').style.display='none'; return; }
  timer = setTimeout(() => lookup(q), 300);
});

async function lookup(q){
  $('meaningBox').style.display='block';
  $('meaning').textContent='Đang tra nghĩa...';
  $('ipaDisplay').textContent='';
  $('guideDisplay').textContent='';
  try{
    const r = await (await fetch('/api/lookup?q='+encodeURIComponent(q))).json();
    curWord = r.word; curMeaning = r.meaning;
    $('meaning').textContent = r.meaning || 'Không tìm thấy nghĩa';
    $('iconDisplay').textContent = r.icon || '📌';
    
    if(r.ipa){
      $('ipaDisplay').style.display = 'inline-block';
      $('ipaDisplay').textContent = 'Phiên âm: ' + r.ipa;
    } else {
      $('ipaDisplay').style.display = 'none';
    }

    if(r.guide){
      $('guideDisplay').textContent = r.guide;
    }

    if(r.word){
      loadExercise(r.word, r.meaning);
    }
  }catch(e){ $('meaning').textContent='Lỗi tra từ, thử lại sau.'; }
}

async function loadExercise(w, m){
  try{
    const r = await (await fetch('/api/exercise?word='+encodeURIComponent(w)+'&meaning='+encodeURIComponent(m))).json();
    curVi = r.vi; curRef = r.ref;
    $('vi').innerHTML = '🇻🇳 VN: ' + esc(r.vi);
    $('answer').value = '';
    $('result').style.display = 'none';
  }catch(e){}
}

$('gradeBtn').onclick = async () => {
  const ans = $('answer').value.trim();
  if(!ans){ alert('Vui lòng gõ câu trả lời!'); return; }
  const btn = $('gradeBtn'); btn.disabled = true; btn.textContent = 'Đang chấm điểm...';
  $('result').style.display = 'block';
  $('result').innerHTML = 'Đang phân tích câu...';
  
  try{
    const r = await (await fetch('/api/grade?vi='+encodeURIComponent(curVi)+'&answer='+encodeURIComponent(ans)+'&ref='+encodeURIComponent(curRef)+'&word='+encodeURIComponent(curWord))).json();
    if(r.error){
      $('result').innerHTML = '<div class="err">⚠️ '+esc(r.error)+'</div>';
    } else {
      const col = r.score >= 7.5 ? '#16a34a' : r.score >= 5.0 ? '#d97706' : '#dc2626';
      let html = '<div class="score" style="color:'+col+'">'+r.score+' / 10</div>';
      
      let segHTML = r.segments.map(s => '<span class="'+(s.ok ? 'ok-text' : 'bad-text')+'">'+esc(s.t)+'</span>').join('');
      html += '<div class="ans-review">' + segHTML + '</div>';

      if(!r.used){
        html += '<div class="err">⚠️ Hãy bổ sung từ bắt buộc <b>"'+esc(curWord)+'"</b> vào câu của bạn.</div>';
      }
      
      if(r.errors.length){
        html += '<label style="margin-top:10px">Chi tiết lỗi cần sửa:</label>';
        r.errors.forEach(e => {
          html += '<div class="err"><b>“'+esc(e.text)+'”</b>: '+esc(e.msg)+(e.fix.length ? '<br>Gợi ý sửa: <b>'+e.fix.map(esc).join(' / ')+'</b>' : '')+'</div>';
        });
      } else {
        html += '<div class="box">✅ Cấu trúc câu và ngữ pháp chính xác!</div>';
      }
      
      html += '<div class="box"><small>💡 Câu gợi ý chuẩn:</small><br><b>'+esc(r.natural)+'</b></div>';
      $('result').innerHTML = html;
    }
  }catch(e){ $('result').innerHTML = '<div class="err">Không chấm được bài lúc này.</div>'; }
  btn.disabled = false; btn.textContent = 'Chấm điểm bài làm';
};
</script></body></html>
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8001)))
    a = ap.parse_args()
    print(f"Server đang chạy tại cổng: {a.port}")
    ThreadingHTTPServer(("0.0.0.0", a.port), Handler).serve_forever()

if __name__ == "__main__":
    main()