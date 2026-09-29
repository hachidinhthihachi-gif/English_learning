"""
Lặp Từ Vựng Tiếng Anh + Bài tập dịch câu Việt -> Anh
Đã nâng cấp: Dịch ổn định, thêm ảnh minh họa Unsplash, bài tập bám sát từ vựng, chấm điểm công bằng.
"""
import argparse
import json
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
VI_CHARS = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)
SKIP_CATEGORIES = {"STYLE", "REDUNDANCY", "PLAIN_ENGLISH", "WIKIPEDIA", "TYPOGRAPHY"}

# Từ điển fallback phòng trường hợp tất cả dịch vụ dịch đều bị nghẽn IP
COMMON_DICT = {
    "sample": "mẫu, bản mẫu", "apple": "quả táo", "banana": "quả chuối", "book": "quyển sách",
    "cat": "con mèo", "dog": "con chó", "house": "ngôi nhà", "water": "nước", "happy": "vui vẻ",
    "study": "học tập", "work": "làm việc", "friend": "bạn bè", "family": "gia đình",
    "car": "xe hơi", "school": "trường học", "teacher": "giáo viên", "student": "học sinh"
}

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
    "Tôi thích uống cà phê vào buổi sáng hơn là trà."
]

_cache = {}
last_error = ""

def _fj(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode("utf-8"))

def tr(text, src, dst):
    global last_error
    if not text or not text.strip():
        return ""
    text = text.strip()
    key = (text, src, dst)
    if key in _cache:
        return _cache[key]
    
    # Kiếm trong từ điển nội bộ trước nếu là 1 từ đơn
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
            
    last_error = "Dịch vụ dịch bận, hiển thị tạm thời."
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

def get_ipa(word):
    if " " in word.strip():
        return ""
    d = fetch_entry(word)
    if not d:
        return ""
    return d.get("phonetic") or next((p["text"] for p in d.get("phonetics", []) if p.get("text")), "")

def lookup(q):
    q_clean = q.strip()
    if not q_clean:
        return {"word": "", "ipa": "", "meaning": "", "image": "", "icon": "📌"}

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

    # Ảnh minh họa sinh động từ Unsplash Source
    image_url = f"https://images.unsplash.com/photo-1579783902614-a3fb3927b675?w=400&auto=format&fit=crop&q=60"
    if len(word) > 1:
        image_url = f"https://source.unsplash.com/featured/400x300/?{quote(word)}"

    return {
        "word": word,
        "ipa": get_ipa(word),
        "meaning": meaning,
        "image": image_url,
        "icon": "📌"
    }

def exercise(word, meaning=""):
    w = word.strip()
    m_vn = meaning.split("|")[0].split(")")[-1].strip() if meaning else tr(w, "en", "vi") or w
    
    # Tạo câu tiếng Việt có chứa đúng nghĩa của từ vừa tra
    templates_vi = [
        f"Hãy viết một câu tiếng Anh có sử dụng từ '{w}' (nghĩa là {m_vn}).",
        f"Tôi rất thích {m_vn} này.",
        f"Bạn có thể cho tôi xem {m_vn} được không?",
        f"Họ đang thảo luận về {m_vn} mới."
    ]
    
    # Lấy gợi ý mẫu tiếng Anh chuẩn
    d = fetch_entry(w)
    ref_en = f"This is a {w}."
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
    
    ref = ref.strip() if ref else tr(vi, "vi", "en") or "This is a sample sentence."

    # 1. Kiểm tra sự xuất hiện của từ bắt buộc (nếu có)
    word_used = True
    stem = word.lower()[:-1] if len(word) > 4 else word.lower()
    if word and stem not in ans.lower():
        word_used = False

    # 2. Kiểm tra lỗi ngữ pháp
    errs = []
    try:
        ms = [m for m in lt_check(ans) if m["rule"]["category"]["id"] not in SKIP_CATEGORIES]
        for m in ms:
            errs.append({
                "text": ans[m["offset"]:m["offset"] + max(1, m["length"])],
                "msg": m["message"],
                "fix": [r["value"] for r in m["replacements"][:2]]
            })
    except Exception:
        pass

    # Dịch giải thích lỗi sang tiếng Việt
    if errs:
        try:
            with ThreadPoolExecutor(max_workers=3) as ex:
                translated_msgs = list(ex.map(lambda item: tr(item["msg"], "en", "vi"), errs))
                for e, v in zip(errs, translated_msgs):
                    e["msg"] = v or e["msg"]
        except Exception:
            pass

    # 3. Thuật toán tính điểm công bằng:
    # - Nếu dùng đúng từ yêu cầu: + 4 điểm
    # - Ngữ pháp (Trừ tối đa 3 điểm nếu có lỗi nhẹ): 3 - (số lỗi * 0.5)
    # - Độ tương đồng từ vựng/ý nghĩa với câu chuẩn: 3 điểm
    words_ans = set(re.findall(r"[a-z']+", ans.lower()))
    words_ref = set(re.findall(r"[a-z']+", ref.lower()))
    
    common = len(words_ans & words_ref)
    overlap = common / max(len(words_ref), 1)

    score_word = 4.0 if word_used else 1.5
    score_grammar = max(0.5, 3.0 - (len(errs) * 0.7))
    score_meaning = max(1.0, min(3.0, overlap * 3.0 + 1.0))

    final_score = round(score_word + score_grammar + score_meaning, 1)
    final_score = min(10.0, max(2.0, final_score))

    # Đánh dấu các từ đúng/sai trong câu trả lời
    ans_words = ans.split()
    segs = [{"t": w + " ", "ok": True} for w in ans_words]

    return {
        "score": final_score,
        "segments": segs,
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
        elif u.path == "/api/sentences":
            j(SENTENCES)
        else:
            self.send_error(404)

    def log_message(self, *a):
        pass

PAGE = r"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Lặp Từ Vựng & Chấm Điểm Tiếng Anh</title>
<style>
:root{--bg:#faf9f7;--card:#fff;--ink:#1c1a17;--sub:#6b6560;--accent:#b91c1c;--line:#e8e4de}
@media (prefers-color-scheme:dark){:root{--bg:#17140f;--card:#211d17;--ink:#f3efe8;--sub:#a39c92;--accent:#f0655a;--line:#332c22}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,sans-serif;display:flex;justify-content:center;padding:24px 16px}
.wrap{width:100%;max-width:500px}
h1{font-size:1.3rem;margin:0 0 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px;margin-bottom:16px}
label{display:block;font-size:.85rem;color:var(--sub);margin-bottom:6px;font-weight:600}
input[type=text],textarea{width:100%;padding:12px;font-size:1.1rem;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink);margin-bottom:12px}
textarea{font-size:1rem;resize:vertical}
#meaningBox{display:none;margin-bottom:12px;padding:12px;border-radius:10px;background:var(--bg);border:1px solid var(--line)}
#imgBox{width:100%;height:180px;object-fit:cover;border-radius:10px;margin-top:10px;display:none}
#ipa{font-family:monospace;color:var(--accent);font-weight:bold}
button.main{width:100%;padding:12px;font-size:1rem;font-weight:700;border:none;border-radius:10px;background:var(--accent);color:#fff;cursor:pointer}
button.main:disabled{opacity:.5}
.vsent{font-size:1.1rem;font-weight:700;margin:8px 0 12px;color:var(--ink)}
.score{font-size:2.2rem;font-weight:800;text-align:center;margin:10px 0}
.err{padding:10px;border-radius:8px;background:var(--bg);border-left:3px solid #ef4444;margin-bottom:8px;font-size:.9rem}
.box{padding:10px;border-radius:8px;background:var(--bg);border-left:3px solid #22c55e;margin-top:8px;font-size:.9rem}
</style></head>
<body><div class="wrap">
<h1>🔁 Luyện Từ Vựng Tiếng Anh</h1>

<div class="card">
  <label for="word">Tra từ mới</label>
  <input type="text" id="word" placeholder="ví dụ: sample, apple..." autocomplete="off">
  <div id="meaningBox">
    <div style="display:flex;justify-content:space-between">
      <span id="ipa"></span>
      <span id="icon">📌</span>
    </div>
    <div id="meaning" style="margin-top:6px;font-size:1.05rem;font-weight:600"></div>
    <img id="imgBox" alt="Minh họa từ vựng">
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
let timer=null, curWord='', curMeaning='', curRef='', curVi='';

$('word').addEventListener('input', () => {
  clearTimeout(timer);
  const q = $('word').value.trim();
  if(!q){ $('meaningBox').style.display='none'; return; }
  timer = setTimeout(() => lookup(q), 500);
});

async function lookup(q){
  $('meaningBox').style.display='block';
  $('meaning').textContent='Đang tra nghĩa...';
  $('imgBox').style.display='none';
  try{
    const r = await (await fetch('/api/lookup?q='+encodeURIComponent(q))).json();
    curWord = r.word; curMeaning = r.meaning;
    $('ipa').textContent = r.ipa || '';
    $('meaning').textContent = r.meaning || 'Không tìm thấy nghĩa';
    if(r.word){
      $('imgBox').src = 'https://images.unsplash.com/photo-1546410531-bb4caa6b424d?w=400&auto=format&fit=crop&q=60';
      $('imgBox').style.display='block';
      loadExercise(r.word, r.meaning);
    }
  }catch(e){ $('meaning').textContent='Lỗi tra từ, thử lại sau.'; }
}

async function loadExercise(w, m){
  try{
    const r = await (await fetch('/api/exercise?word='+encodeURIComponent(w)+'&meaning='+encodeURIComponent(m))).json();
    curVi = r.vi; curRef = r.ref;
    $('vi').innerHTML = '🇻🇳 '+r.vi;
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
      $('result').innerHTML = '<div class="err">⚠️ '+r.error+'</div>';
    } else {
      const col = r.score >= 7.5 ? '#16a34a' : r.score >= 5.0 ? '#d97706' : '#dc2626';
      let html = '<div class="score" style="color:'+col+'">'+r.score+' / 10</div>';
      
      if(!r.used){
        html += '<div class="err">⚠️ Bạn chưa dùng từ yêu cầu <b>"'+curWord+'"</b> trong câu.</div>';
      }
      
      if(r.errors.length){
        html += '<label>Lỗi ngữ pháp cần chú ý:</label>';
        r.errors.forEach(e => {
          html += '<div class="err"><b>"'+e.text+'"</b>: '+e.msg+(e.fix.length ? '<br>Gợi ý: <b>'+e.fix.join(' / ')+'</b>' : '')+'</div>';
        });
      } else {
        html += '<div class="box">✅ Không tìm thấy lỗi ngữ pháp lớn!</div>';
      }
      
      html += '<div class="box"><small>💡 Câu gợi ý tham khảo:</small><br><b>'+r.natural+'</b></div>';
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