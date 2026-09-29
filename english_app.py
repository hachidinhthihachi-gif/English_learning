#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ứng dụng luyện lặp từ vựng tiếng Anh và dịch câu Việt -> Anh.
Chỉ dùng thư viện chuẩn Python; có thể chạy trên Render bằng biến môi trường PORT.
"""

import argparse
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen

UA = {"User-Agent": "EnglishVocabularyPractice/1.0"}
VI_CHARS = re.compile(
    r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệỉĩị"
    r"òóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]",
    re.I,
)
SKIP_CATEGORIES = {"STYLE", "REDUNDANCY", "PLAIN_ENGLISH", "WIKIPEDIA", "TYPOGRAPHY"}
_cache = {}
_entries = {}
last_error = ""

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
    SENTENCES += [
        line.strip()
        for line in Path(__file__).with_name("cau_tap.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
except OSError:
    pass

TEMPLATES = {
    "noun": ["I saw a {w} on my way home yesterday.", "This is my favorite {w}.", "Do you have a {w}?"],
    "verb": ["I want to {w} every day.", "She can {w} very well.", "They {w} together on weekends."],
    "adjective": ["The room is very {w}.", "She feels {w} today.", "It looks {w} to me."],
    "adverb": ["He speaks {w}.", "She did it {w}.", "They walked {w} to school."],
    "other": ['I learned the word "{w}" today.', 'Can you use the word "{w}" in a sentence?'],
}


def _get_json(url, data=None, timeout=12):
    req = Request(url, data=data, headers=UA)
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _short_error(exc):
    match = re.search(r"HTTP Error (\\d+)", str(exc))
    return f"lỗi HTTP {match.group(1)}" if match else "không kết nối được"


def tr(text, src, dst):
    """Dịch văn bản, thử lần lượt các dịch vụ miễn phí/dự phòng."""
    global last_error
    text = (text or "").strip()
    if not text:
        return ""
    key = (text, src, dst)
    if key in _cache:
        return _cache[key]

    q = quote(text, safe="")
    providers = []

    api_key = os.environ.get("GOOGLE_API_KEY")
    if api_key:
        providers.append((
            "Google API",
            lambda: _get_json(
                "https://translation.googleapis.com/language/translate/v2?"
                + urlencode({"key": api_key, "q": text, "source": src, "target": dst, "format": "text"})
            )["data"]["translations"][0]["translatedText"],
        ))

    providers.extend([
        ("Google", lambda: "".join(
            part[0] for part in _get_json(
                f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={src}&tl={dst}&dt=t&q={q}"
            )[0] if part and part[0]
        )),
        ("Google Chrome", lambda: "".join(
            item.get("trans", "") for item in _get_json(
                f"https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl={src}&tl={dst}&q={q}"
            ).get("sentences", [])
        )),
        ("MyMemory", lambda: _get_json(
            "https://api.mymemory.translated.net/get?"
            + urlencode({"q": text, "langpair": f"{src}|{dst}",
                         **({"de": os.environ["MYMEMORY_EMAIL"]} if os.environ.get("MYMEMORY_EMAIL") else {})})
        )["responseData"]["translatedText"]),
    ])

    errors = []
    for name, fn in providers:
        try:
            result = (fn() or "").strip()
            if result and not result.upper().startswith("MYMEMORY WARNING"):
                _cache[key] = result
                return result
            errors.append(f"{name} trả về rỗng")
        except Exception as exc:
            errors.append(f"{name}: {_short_error(exc)}")
    last_error = "Các dịch vụ dịch đều không phản hồi. Bạn thử lại sau nhé."
    return ""


def fetch_entry(word):
    word = (word or "").strip().lower()
    if not word or " " in word:
        return []
    if word in _entries:
        return _entries[word]
    try:
        data = _get_json("https://api.dictionaryapi.dev/api/v2/entries/en/" + quote(word, safe=""))
        if isinstance(data, list):
            _entries[word] = data
            return data
    except Exception:
        pass
    return []


def get_ipa(word):
    if " " in (word or "").strip():
        return ""
    entries = fetch_entry(word)
    if not entries:
        return ""
    entry = entries[0]
    return entry.get("phonetic") or next(
        (item.get("text", "") for item in entry.get("phonetics", []) if item.get("text")), ""
    )


def lookup(q):
    q_clean = (q or "").strip()
    if not q_clean:
        return {"word": "", "ipa": "", "meaning": "", "icon": "📌"}

    if VI_CHARS.search(q_clean):
        word = (tr(q_clean, "vi", "en") or "").strip() or q_clean
        meaning = q_clean
    else:
        word = q_clean
        entries = fetch_entry(word)
        meanings_list = []
        if entries:
            for item in entries[0].get("meanings", []):
                pos = item.get("partOfSpeech", "")
                definitions = item.get("definitions", [])
                if not definitions:
                    continue
                definition = (definitions[0].get("definition") or "").strip()
                if not definition:
                    continue
                translated = (tr(definition, "en", "vi") or "").strip()
                if translated and len(translated) > 2:
                    meanings_list.append(f"({pos}) {translated}" if pos else translated)
        meaning = " | ".join(meanings_list) if meanings_list else (tr(word, "en", "vi") or "").strip()

    if not meaning or len(meaning.strip()) <= 2:
        meaning = (tr(word, "en", "vi") or "").strip() or "Chưa lấy được nghĩa lúc này"
    return {"word": word, "ipa": get_ipa(word), "meaning": meaning, "icon": "📌"}


def exercise(word, k=0):
    word = (word or "").strip()
    if not word:
        return {"error": "Bạn chưa chọn từ để luyện."}

    entries = fetch_entry(word)
    examples, parts = [], []
    for entry in entries:
        for meaning in entry.get("meanings", []):
            pos = meaning.get("partOfSpeech", "")
            if pos:
                parts.append(pos)
            for definition in meaning.get("definitions", []):
                example = (definition.get("example") or "").strip()
                if example and example not in examples:
                    examples.append(example)

    if not examples:
        pos = parts[0] if parts else "other"
        examples = [template.format(w=word) for template in TEMPLATES.get(pos, TEMPLATES["other"])]

    english = examples[k % len(examples)].strip()
    if english:
        english = english[0].upper() + english[1:]
        if english[-1] not in ".!?":
            english += "."
    vietnamese = tr(english, "en", "vi")
    if not vietnamese:
        return {"error": last_error or "Không dịch được câu. Thử lại sau nhé."}
    return {"word": word, "en": english, "vi": vietnamese}


def lt_check(text):
    body = urlencode({"text": text, "language": "en-US"}).encode("utf-8")
    return _get_json("https://api.languagetool.org/v2/check", data=body, timeout=20).get("matches", [])


def grade(vi, ans, ref="", word=""):
    ans = (ans or "").strip()
    if not ans:
        return {"error": "Bạn chưa viết câu trả lời."}
    if VI_CHARS.search(ans):
        return {"error": "Hãy viết câu trả lời bằng tiếng Anh nhé."}

    ref = (ref or "").strip()
    if len(ref) <= 2:
        ref = tr(vi, "vi", "en") or ""

    try:
        matches = [
            match for match in lt_check(ans)
            if match.get("rule", {}).get("category", {}).get("id") not in SKIP_CATEGORIES
        ]
    except Exception:
        return {"error": "Không chấm được ngữ pháp lúc này. Thử lại sau ít phút."}

    matches.sort(key=lambda item: item.get("offset", 0))
    segments, errors, used, cursor = [], [], [], 0
    corrected = ans

    for match in matches:
        offset = match.get("offset", 0)
        length = max(1, match.get("length", 1))
        if offset < cursor or offset > len(ans):
            continue
        if offset > cursor:
            segments.append({"t": ans[cursor:offset], "ok": True})
        original = ans[offset:offset + length]
        segments.append({"t": original, "ok": False})
        fixes = [replacement.get("value", "") for replacement in match.get("replacements", [])[:3]]
        errors.append({
            "text": original,
            "msg": tr(match.get("message", ""), "en", "vi") or match.get("message", ""),
            "fix": fixes,
        })
        used.append((offset, length, fixes))
        cursor = offset + length

    if cursor < len(ans):
        segments.append({"t": ans[cursor:], "ok": True})
    for offset, length, fixes in reversed(used):
        if fixes:
            corrected = corrected[:offset] + fixes[0] + corrected[offset + length:]

    words = set(re.findall(r"[a-z']+", ans.lower()))
    ref_words = set(re.findall(r"[a-z']+", ref.lower()))
    common = len(words & ref_words)
    f1 = (2 * common) / max(len(words) + len(ref_words), 1)
    word_count = len(re.findall(r"[A-Za-z']+", ans))
    grammar_score = max(0.2, 1.0 - (0.5 * len(errors) / max(word_count, 4)))
    meaning_score = max(0.4, f1)
    score = round(10 * (0.6 * grammar_score + 0.4 * meaning_score), 1)

    stem = word.lower()[:-1] if len(word) > 4 else word.lower()
    return {
        "score": score, "segments": segments, "errors": errors,
        "corrected": corrected, "natural": ref or "Chưa lấy được câu gợi ý chuẩn lúc này.",
        "word": word, "used": bool(word) and stem in ans.lower(),
    }


PAGE = r"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lặp Từ Vựng Tiếng Anh</title>
<style>
:root{--bg:#faf9f7;--card:#fff;--ink:#1c1a17;--sub:#6b6560;--accent:#b91c1c;--line:#e8e4de;--good:#dcfce7;--bad:#fee2e2}
@media(prefers-color-scheme:dark){:root{--bg:#17140f;--card:#211d17;--ink:#f3efe8;--sub:#a39c92;--accent:#f0655a;--line:#332c22;--good:#14532d;--bad:#7f1d1d}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:Arial,sans-serif;display:flex;justify-content:center;padding:28px 14px}
.wrap{width:100%;max-width:520px}h1{font-size:1.35rem;margin:0 0 8px}.desc{color:var(--sub);margin:0 0 22px;font-size:.95rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px;margin-bottom:16px}
label{display:block;font-size:.85rem;color:var(--sub);margin-bottom:7px;font-weight:600}
input[type=text],textarea,select,input[type=number]{width:100%;padding:12px;border-radius:9px;border:1px solid var(--line);background:var(--bg);color:var(--ink);font:inherit;margin-bottom:12px}
input[type=text]{font-size:1.15rem}textarea{resize:vertical;margin:0}.row,.playbar{display:flex;gap:10px}.field{flex:1;min-width:0}
button{cursor:pointer;border-radius:9px;padding:12px 15px;font:inherit}.main{background:var(--accent);color:white;border:0;font-weight:700;flex:1}.stop{background:var(--card);color:var(--ink);border:1px solid var(--line)}
.reps{display:flex;gap:8px;align-items:center;margin-bottom:12px}.reps button{width:42px}.reps input{width:75px;text-align:center;margin:0}
#meaningBox{display:none;background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:12px;margin-bottom:14px}
#ipa{color:var(--accent);font-family:monospace}.status{text-align:center;color:var(--sub);margin-top:12px;min-height:1.2em}.count{text-align:center;color:var(--accent);font-size:2rem;font-weight:bold;margin-top:8px}
.vsent{font-size:1.12rem;font-weight:700;line-height:1.5;margin:8px 0 14px}.score{text-align:center;font-size:2.2rem;font-weight:bold}.ans{line-height:2;margin:10px 0}.ok{background:var(--good);border-radius:4px;padding:2px}.bad{background:var(--bad);border-radius:4px;text-decoration:underline wavy}.err,.box{padding:10px;border-radius:8px;margin-top:8px;line-height:1.5;background:var(--bg)}.err{border-left:3px solid #ef4444}.box{border-left:3px solid #22c55e}.box small{display:block;color:var(--sub);font-weight:bold}
</style></head><body><main class="wrap">
<h1>🔁 Lặp Từ Vựng Tiếng Anh</h1>
<p class="desc">Gõ từ hoặc cụm từ, chọn số lần lặp rồi bấm Phát. Bạn cũng có thể luyện dịch câu Việt → Anh.</p>
<section class="card">
<label for="word">Từ / cụm từ</label><input id="word" type="text" placeholder="Ví dụ: unwind" autocomplete="off">
<div id="meaningBox"><div id="ipa"></div><div id="meaning"></div></div>
<div class="row"><div class="field"><label for="voice">Giọng đọc</label><select id="voice"></select></div>
<div class="field"><label for="rate">Tốc độ</label><select id="rate"><option value=".6">Chậm</option><option value=".8">Hơi chậm</option><option value="1" selected>Bình thường</option><option value="1.2">Nhanh</option></select></div></div>
<label>Số lần lặp</label><div class="reps"><button id="dec" type="button">−</button><input id="reps" type="number" value="10" min="1" max="50"><button id="inc" type="button">+</button></div>
<div class="playbar"><button class="main" id="play">▶️ Phát</button><button class="stop" id="stop">⏹ Dừng</button></div>
<div class="count" id="count"></div><div class="status" id="status">Sẵn sàng</div>
</section>
<section class="card"><label>✍️ Bài tập dịch câu: Việt → Anh</label>
<div class="row"><div class="field"><label for="exWord">Từ luyện</label><select id="exWord"><option value="">📚 Câu chung</option></select></div></div>
<div class="vsent" id="vi"></div><textarea id="answer" rows="3" placeholder="Viết câu tiếng Anh của bạn..."></textarea>
<div class="playbar" style="margin-top:10px"><button class="main" id="gradeBtn">Chấm bài</button><button class="stop" id="newBtn">🔀 Câu khác</button></div>
<div id="result" style="display:none;margin-top:16px"></div></section></main>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let voices=[],learned=[],current=null,playing=false,stopRequested=false,repeatTimer=null,lastQ='',timer=null;
try{learned=JSON.parse(localStorage.getItem('learned_en')||'[]')}catch(e){learned=[]}
function loadVoices(){const all=speechSynthesis.getVoices();voices=all.filter(v=>v.lang.toLowerCase().startsWith('en'));if(!voices.length)voices=all;$('voice').innerHTML='';voices.forEach((v,i)=>{const o=document.createElement('option');o.value=i;o.textContent=v.name+' ('+v.lang+')';$('voice').appendChild(o)})}
if('speechSynthesis' in window){loadVoices();speechSynthesis.onvoiceschanged=loadVoices}
function speak(text){return new Promise(resolve=>{if(!('speechSynthesis'in window)){resolve();return}const u=new SpeechSynthesisUtterance(text);u.voice=voices[+$('voice').value]||null;u.lang='en-US';u.rate=+$('rate').value||1;u.onend=resolve;u.onerror=resolve;speechSynthesis.speak(u)})}
$('dec').onclick=()=> $('reps').value=Math.max(1,(+$('reps').value||1)-1);
$('inc').onclick=()=> $('reps').value=Math.min(50,(+$('reps').value||1)+1);
$('play').onclick=async()=>{const text=$('word').value.trim();if(!text)return;$('play').disabled=true;playing=true;stopRequested=false;const total=Math.max(1,Math.min(50,+$('reps').value||10));for(let i=1;i<=total&&!stopRequested;i++){ $('count').textContent=i+' / '+total;$('status').textContent='Đang phát...';await speak(text);if(i<total&&!stopRequested)await new Promise(r=>repeatTimer=setTimeout(r,450))}playing=false;$('play').disabled=false;$('status').textContent=stopRequested?'Đã dừng':'Hoàn thành';};
$('stop').onclick=()=>{stopRequested=true;clearTimeout(repeatTimer);if('speechSynthesis'in window)speechSynthesis.cancel();playing=false;$('play').disabled=false;$('status').textContent='Đã dừng'};
$('word').addEventListener('input',()=>{clearTimeout(timer);const text=$('word').value.trim();if(!text){$('meaningBox').style.display='none';return}timer=setTimeout(()=>lookup(text),500)});
async function api(path,params={}){const u=new URL(path,location.href);Object.entries(params).forEach(([k,v])=>u.searchParams.set(k,v));const res=await fetch(u);return res.json()}
function fillExWords(selected=''){const old=selected||$('exWord').value;$('exWord').innerHTML='<option value="">📚 Câu chung</option>'+learned.map(w=>'<option value="'+esc(w.word)+'">'+esc(w.word)+' — '+esc(w.meaning)+'</option>').join('');$('exWord').value=old}
async function lookup(text){if(text===lastQ)return;lastQ=text;$('meaningBox').style.display='block';$('meaning').textContent='Đang tra...';try{const r=await api('/api/lookup',{q:text});if(text!==$('word').value.trim())return;current=r;$('ipa').textContent=r.ipa||'';$('meaning').textContent=r.error?'⚠️ '+r.error:(r.meaning||'(không rõ nghĩa)');if(!r.error&&r.word&&r.meaning&&!learned.some(x=>x.word.toLowerCase()===r.word.toLowerCase())){learned.push({word:r.word,ipa:r.ipa,meaning:r.meaning});if(learned.length>60)learned.shift();try{localStorage.setItem('learned_en',JSON.stringify(learned))}catch(e){}fillExWords(r.word);$('exWord').value=r.word;newSentence()}}catch(e){$('meaning').textContent='Không tra được nghĩa lúc này.'}}
let sentences=[],curVi='',curRef='',exTarget='',exK=0;
function setVi(vi,ref='',word=''){curVi=vi;curRef=ref;exTarget=word;$('vi').innerHTML='🇻🇳 '+esc(vi)+(word?'<div style="font-size:.85rem;color:var(--sub);margin-top:6px">Hãy dùng từ: <b>'+esc(word)+'</b></div>':'');$('answer').value='';$('result').style.display='none'}
async function newSentence(){const w=$('exWord').value;if(w){$('vi').textContent='Đang tạo câu...';try{const r=await api('/api/exercise',{word:w,k:exK++});if(r.error){$('vi').textContent='⚠️ '+r.error;return}setVi(r.vi,r.en,r.word)}catch(e){$('vi').textContent='Không tạo được câu lúc này.'}return}
if(!sentences.length){try{sentences=await api('/api/sentences')}catch(e){}}
if(!sentences.length)return;let s;do{s=sentences[Math.floor(Math.random()*sentences.length)]}while(s===curVi&&sentences.length>1);setVi(s)}
$('exWord').onchange=()=>{exK=Math.floor(Math.random()*4);newSentence()};$('newBtn').onclick=newSentence;
$('gradeBtn').onclick=async()=>{const answer=$('answer').value.trim();if(!answer||!curVi)return;const btn=$('gradeBtn'),box=$('result');btn.disabled=true;btn.textContent='Đang chấm...';box.style.display='block';box.textContent='Đang chấm bài...';try{const r=await api('/api/grade',{vi:curVi,answer,ref:curRef,word:exTarget});if(r.error){box.innerHTML='<div class="err">⚠️ '+esc(r.error)+'</div>';return}
const label=r.score>=9?'Tuyệt vời! 🎉':r.score>=7?'Tốt lắm 👍':r.score>=5?'Khá ổn, cố thêm nhé':'Cần luyện thêm 💪';
box.innerHTML='<div class="score">'+r.score+' / 10</div><div style="text-align:center;color:var(--sub)">'+label+'</div><div class="ans">'+r.segments.map(s=>'<span class="'+(s.ok?'ok':'bad')+'">'+esc(s.t)+'</span>').join('')+'</div>'+
(r.errors.length?'<label>Lỗi cần sửa ('+r.errors.length+')</label>'+r.errors.map(e=>'<div class="err"><b>“'+esc(e.text)+'”</b> — '+esc(e.msg)+(e.fix.length?'<br>Gợi ý sửa: <b>'+e.fix.map(esc).join(' / ')+'</b>':'')+'</div>'):'<div class="box">Không phát hiện lỗi ngữ pháp. ✅</div>')+
(r.errors.length?'<div class="box"><small>✅ Câu sau khi sửa</small>'+esc(r.corrected)+'</div>':'')+
'<div class="box"><small>💡 Gợi ý cách viết tự nhiên hơn</small>'+esc(r.natural)+'</div>';
}catch(e){box.innerHTML='<div class="err">Không chấm được lúc này, thử lại nhé.</div>'}finally{btn.disabled=false;btn.textContent='Chấm bài'}};
fillExWords('');newSentence();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def send_body(self, body, content_type="application/json; charset=utf-8", status=200):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        params = {key: values[0].strip() for key, values in parse_qs(parsed.query).items() if values}
        def json_response(value):
            self.send_body(json.dumps(value, ensure_ascii=False))

        if parsed.path == "/":
            self.send_body(PAGE, "text/html; charset=utf-8")
        elif parsed.path == "/health":
            json_response({"status": "ok"})
        elif parsed.path == "/api/lookup" and params.get("q"):
            json_response(lookup(params["q"]))
        elif parsed.path == "/api/grade" and params.get("vi"):
            json_response(grade(params["vi"], params.get("answer", ""), params.get("ref", ""), params.get("word", "")))
        elif parsed.path == "/api/exercise" and params.get("word"):
            try:
                k = max(0, int(params.get("k", "0")))
            except ValueError:
                k = 0
            json_response(exercise(params["word"], k))
        elif parsed.path == "/api/sentences":
            json_response(SENTENCES)
        else:
            self.send_error(404, "Not found")

    def log_message(self, fmt, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description="Lặp từ vựng tiếng Anh")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8001")))
    args = parser.parse_args()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"Server đang chạy tại cổng: {args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\\nĐang tắt server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
