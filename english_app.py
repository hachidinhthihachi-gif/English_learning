"""
Lặp Từ Vựng Tiếng Anh (có emoji dễ nhớ + luyện nhớ từ) + Bài tập dịch câu Việt -> Anh (có chấm ngữ pháp). Không dùng AI, không tốn token.

Cài thư viện: KHÔNG cần (chỉ dùng thư viện có sẵn của Python).
Nếu dịch bị lỗi 429 khi chạy trên Render: đặt biến môi trường MYMEMORY_EMAIL=<email của bạn> (nâng hạn mức miễn phí)
hoặc GOOGLE_API_KEY=<khoá Google Cloud Translation>. Trang cũng tự thử dịch ngay trên trình duyệt của người dùng.
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
import time
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
_blocked_until = 0   # khi mọi dịch vụ dịch đều lỗi: tạm nghỉ 60s để trang không bị treo


def _open(url, data=None):
    req = urllib.request.Request(url, data=data, headers=UA)
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode("utf-8"))


def _fj(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=6) as r:
        return json.loads(r.read().decode("utf-8"))


def _short(e):
    m = re.search(r"HTTP Error (\d+)", str(e))
    return "lỗi " + m.group(1) if m else "không kết nối được"


def tr(text, src, dst):
    """Dịch với nhiều dịch vụ dự phòng: Google API (nếu có key) -> Google -> Google2 -> Lingva -> MyMemory."""
    global last_error, _blocked_until
    key = (text, src, dst)
    if key in _cache:
        return _cache[key]
    if time.time() < _blocked_until:
        return ""
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
    last_error = "Các dịch vụ dịch đều lỗi (" + ", ".join(errs) + "). Thử lại sau ít phút."
    print("  !", last_error)
    _blocked_until = time.time() + 60
    return ""


_entries = {}
# (câu Việt có {vi} = nghĩa của từ, câu Anh có {en} = từ, {a} = a/an)
TEMPLATES = {
    "noun": [("Tôi vừa nhìn thấy {vi} trên đường về nhà.", "I just saw {a} {en} on my way home."),
             ("Đây là {vi} yêu thích của tôi.", "This is my favorite {en}."),
             ("Bạn có {vi} không?", "Do you have {a} {en}?")],
    "verb": [("Tôi muốn {vi} mỗi ngày.", "I want to {en} every day."),
             ("Cô ấy có thể {vi} rất giỏi.", "She can {en} very well."),
             ("Chúng tôi thường {vi} vào cuối tuần.", "We often {en} on weekends.")],
    "adjective": [("Căn phòng này rất {vi}.", "This room is very {en}."),
                  ("Hôm nay cô ấy cảm thấy {vi}.", "She feels {en} today."),
                  ("Mọi thứ trông thật {vi}.", "Everything looks {en}.")],
    "adverb": [("Anh ấy nói {vi}.", "He speaks {en}."), ("Cô ấy làm việc đó {vi}.", "She did it {en}.")],
    "other": [('Hôm nay tôi vừa học từ "{vi}".', 'Today I learned the word "{en}".'),
              ('Bạn có thể đặt một câu với từ "{vi}" không?', 'Can you make a sentence with the word "{en}"?')],
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


def exercise(word, meaning="", k=0):
    """Câu luyện dịch BẮT BUỘC chứa nghĩa tiếng Việt của từ vừa tra (để bạn biết phải dùng từ nào)."""
    w = word.strip()
    meaning = meaning.strip() or tr(w, "en", "vi")
    if not meaning:
        return {"error": last_error or "Không dịch được"}
    vi_word = re.split(r"[,;/(]", meaning)[0].strip()      # nghĩa chính, ví dụ "táo"
    d = {} if " " in w else fetch_entry(w)
    pos = next((m.get("partOfSpeech") for m in d.get("meanings", []) if m.get("partOfSpeech")), "other")
    stem = w.lower()[:-1] if len(w) > 4 else w.lower()
    exs = []
    for m in d.get("meanings", []):
        for df in m.get("definitions", []):
            e = (df.get("example") or "").strip()
            if e and stem in e.lower() and e not in exs:
                exs.append(e)
    art = "an" if w[:1].lower() in "aeiou" else "a"
    items = [("dict", e) for e in exs] + [("tpl", t) for t in TEMPLATES.get(pos, TEMPLATES["other"])]
    for i in range(len(items)):
        kind, it = items[(k + i) % len(items)]
        if kind == "dict":            # câu ví dụ thật: chỉ nhận nếu bản dịch Việt có chứa nghĩa của từ
            en = it[0].upper() + it[1:] + ("" if it[-1] in ".!?" else ".")
            vi = tr(en, "en", "vi")
            if vi and vi_word.lower() in vi.lower():
                return {"word": w, "en": en, "vi": vi, "vi_word": vi_word}
        else:                          # câu mẫu: luôn chứa nghĩa của từ, không cần gọi dịch
            return {"word": w, "en": it[1].format(a=art, en=w), "vi": it[0].format(vi=vi_word), "vi_word": vi_word}


EMO = """apple 🍎 banana 🍌 orange 🍊 grape 🍇 lemon 🍋 water 💧 milk 🥛 coffee ☕ tea 🍵 rice 🍚 bread 🍞 egg 🥚 fish 🐟 chicken 🐔
meat 🥩 pizza 🍕 cake 🍰 food 🍽️ eat 🍽️ drink 🥤 cook 🍳 dog 🐶 cat 🐱 bird 🐦 horse 🐴 cow 🐮 pig 🐷 rabbit 🐰 monkey 🐒
elephant 🐘 tiger 🐯 lion 🦁 bear 🐻 snake 🐍 tree 🌳 flower 🌸 sun ☀️ moon 🌙 star ⭐ rain 🌧️ snow ❄️ wind 💨 cloud ☁️ fire 🔥
mountain ⛰️ sea 🌊 ocean 🌊 beach 🏖️ river 🏞️ house 🏠 home 🏠 school 🏫 hospital 🏥 hotel 🏨 bank 🏦 shop 🏪 store 🏬 car 🚗
bus 🚌 train 🚆 plane ✈️ airplane ✈️ boat ⛵ ship 🚢 bicycle 🚲 bike 🚲 road 🛣️ phone 📱 computer 💻 book 📖 pen 🖊️ pencil ✏️
paper 📄 letter ✉️ key 🔑 door 🚪 window 🪟 clock 🕒 time ⏰ money 💰 gift 🎁 music 🎵 song 🎤 movie 🎬 game 🎮 ball ⚽
football ⚽ shoe 👟 shirt 👕 hat 🎩 glasses 👓 bag 👜 umbrella ☂️ love ❤️ heart ❤️ happy 😊 sad 😢 angry 😡 tired 😴 sleep 😴
cry 😭 laugh 😂 smile 😊 fear 😨 scared 😨 surprise 😲 sick 🤒 hot 🥵 cold 🥶 big 🐘 small 🐜 fast ⚡ slow 🐢 run 🏃 walk 🚶
swim 🏊 jump 🤸 dance 💃 sing 🎤 read 📖 write ✍️ speak 🗣️ talk 🗣️ listen 👂 look 👀 see 👀 hear 👂 think 🤔 idea 💡 learn 🎓
study 📚 teach 🧑‍🏫 work 💼 job 💼 doctor 🧑‍⚕️ teacher 🧑‍🏫 police 👮 family 👪 baby 👶 friend 🤝 mother 👩 father 👨 man 👨
woman 👩 child 🧒 boy 👦 girl 👧 help 🆘 buy 🛒 sell 🏷️ open 🔓 close 🔒 up ⬆️ down ⬇️ yes ✅ no ❌ good 👍 bad 👎
beautiful 🌺 ugly 🤢 new 🆕 old 👴 young 🧑 rich 🤑 poor 🪙 strong 💪 weak 🥀 clean 🧼 dirty 🧽 quiet 🤫 loud 📢 light 💡
dark 🌑 red 🔴 blue 🔵 green 🟢 yellow 🟡 black ⚫ white ⚪ world 🌍 country 🗺️ city 🏙️ village 🏘️ weather 🌤️ travel 🧳
holiday 🎉 party 🎊 birthday 🎂 wedding 💒 shopping 🛍️ hungry 🍽️ thirsty 🥤 bored 🥱 busy 🏃 late ⏳ early 🌅 morning 🌅
night 🌃 today 📅 tomorrow 📆 yesterday ⏪ week 🗓️ year 📅 health 🩺 exercise 🏋️ garden 🌻 park 🏞️ market 🛒 restaurant 🍴""".split()
EMOJI = dict(zip(EMO[::2], EMO[1::2]))


def _build_uni():
    """Tra emoji theo tên chuẩn Unicode (RED APPLE -> apple...). Không cần thư viện ngoài."""
    import unicodedata
    skip = {"with", "and", "the", "for", "symbol", "sign", "face", "mark"}
    best = {}
    for cp in range(0x1F300, 0x1FB00):
        try:
            toks = unicodedata.name(chr(cp)).lower().split()
        except ValueError:
            continue
        for t in toks:
            if len(t) >= 3 and t not in skip and (t not in best or len(toks) < best[t][0]):
                best[t] = (len(toks), chr(cp))
    return {k: v[1] for k, v in best.items()}


_UNI = _build_uni()


def emoji_for(word):
    """Ký tự minh họa dễ nhớ cho từ: bảng có sẵn -> tên emoji Unicode -> 📌."""
    w = word.strip().lower()
    forms = [w] + [w[:-len(x)] for x in ("ing", "ed", "es", "s") if w.endswith(x) and len(w) - len(x) >= 3]
    if w.endswith("ies"):
        forms.append(w[:-3] + "y")
    forms += [f[:-1] for f in forms if len(f) > 3 and f[-1] == f[-2]]      # running -> runn -> run
    forms += re.findall(r"[a-z]+", w)
    for table in (EMOJI, _UNI):
        for f in forms:
            if f in table:
                return table[f]
    return "📌"


def lookup(q):
    if VI_CHARS.search(q):
        word, meaning = tr(q, "vi", "en"), q
    else:
        word, meaning = q, tr(q, "en", "vi")
    r = {"word": word, "ipa": get_ipa(word), "meaning": meaning, "icon": emoji_for(word)}
    if not meaning or not word:
        r["error"] = last_error or "Không dịch được"
    return r


def lt_check(text):
    """Gọi LanguageTool, trả về danh sách lỗi."""
    body = urlencode({"text": text, "language": "en-US"}).encode()
    return _open("https://api.languagetool.org/v2/check", data=body)["matches"]


STOP = set("the a an is are was were be been am i you he she it we they to of in on at for and or but with my your his "
           "her our their this that these those do does did have has had will would can could should not no so very".split())


def _content(t):
    return [w for w in re.findall(r"[a-z']+", t.lower()) if len(w) > 2 and w not in STOP]


def _same(a, b):
    return a == b or (len(a) >= 4 and len(b) >= 4 and a[:4] == b[:4])   # study ~ studying


def grade(vi, ans, ref="", word=""):
    ans = ans.strip()
    if not ans:
        return {"error": "Bạn chưa viết câu trả lời."}
    if VI_CHARS.search(ans):
        return {"error": "Hãy viết câu trả lời bằng tiếng Anh nhé."}
    ref = ref or tr(vi, "vi", "en")
    try:
        raw = lt_check(ans)
    except Exception as e:
        return {"error": f"Không chấm được ngữ pháp lúc này ({e}). Thử lại sau ít phút."}
    ms = []
    for m in raw:
        tok = ans[m["offset"]:m["offset"] + m["length"]]
        if m["rule"]["category"]["id"] in SKIP_CATEGORIES:
            continue
        if m["rule"]["id"].startswith("MORFOLOGIK") and tok[:1].isupper() and m["offset"] > 0:
            continue                    # tên riêng (Minh, Hanoi...) không tính là lỗi chính tả
        ms.append(m)
    ms.sort(key=lambda m: m["offset"])
    segs, errs, cur, used, gpen = [], [], 0, [], 0.0
    for m in ms:
        o, l = m["offset"], max(1, m["length"])
        if o < cur:
            continue
        if o > cur:
            segs.append({"t": ans[cur:o], "ok": True})
        segs.append({"t": ans[o:o + l], "ok": False})
        fx = [r["value"] for r in m["replacements"][:3]]
        used.append((o, l, fx))
        errs.append({"text": ans[o:o + l], "msg": m["message"], "fix": fx})
        cat = m["rule"]["category"]["id"]
        gpen += 1.0 if cat == "TYPOS" else 0.5 if cat in ("CASING", "PUNCTUATION") else 1.5
        cur = o + l
    if cur < len(ans):
        segs.append({"t": ans[cur:], "ok": True})
    with ThreadPoolExecutor(6) as ex:  # dịch lời giải thích lỗi sang tiếng Việt
        for e, v in zip(errs, ex.map(lambda e: tr(e["msg"], "en", "vi"), errs)):
            e["msg"] = v or e["msg"]
    fixed = ans
    for o, l, fx in reversed(used):
        if fx:
            fixed = fixed[:o] + fx[0] + fixed[o + l:]
    stem = word.lower()[:-1] if len(word) > 4 else word.lower()
    used_word = bool(word) and stem in ans.lower()
    n = len(re.findall(r"[A-Za-z']+", ans))
    refn = len(re.findall(r"[A-Za-z']+", ref))
    rc, uc = _content(ref), _content(ans)
    cov = sum(any(_same(r, u) for u in uc) for r in rc) / len(rc) if rc else 1.0
    pen = []   # (lý do, số điểm bị trừ) — chỉ trừ điểm khi có lý do rõ ràng
    if gpen:
        pen.append(("Ngữ pháp / chính tả", round(min(7, gpen), 1)))
    if cov < 0.6:
        pen.append(("Chưa sát nghĩa câu gốc", round((0.6 - cov) / 0.6 * 2.5, 1)))
    if refn >= 4 and n < 0.5 * refn:
        pen.append(("Câu quá ngắn, chưa đủ ý", round(min(6, (0.5 * refn - n) * 1.5), 1)))
    if word and not used_word:
        pen.append(("Chưa dùng từ luyện", 1.0))
    score = max(0.0, round((10 - sum(v for _, v in pen)) * 2) / 2)
    return {"score": score, "segments": segs, "errors": errs, "corrected": fixed, "natural": ref,
            "word": word, "used": used_word, "breakdown": [{"label": a, "value": b} for a, b in pen if b > 0]}


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
            j(exercise(p["word"], p.get("meaning", ""), int(p["k"]) if p.get("k", "").isdigit() else 0))
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
    <div id="icon" style="font-size:2.8rem;line-height:1"></div>
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

<div class="card" id="pracCard" style="display:none">
  <label style="margin-bottom:10px">🧠 Luyện nhớ từ (ngoài bài dịch)</label>
  <div id="pracTabs" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px"></div>
  <div style="text-align:center;font-size:3rem;line-height:1.2" id="pIcon"></div>
  <div style="text-align:center;font-weight:700;margin:8px 0;line-height:1.5" id="pHint"></div>
  <div style="text-align:center;font-size:1.5rem;letter-spacing:.2em;font-weight:800;color:var(--accent);margin-bottom:14px;word-break:break-word" id="pPuzzle"></div>
  <div id="pInputWrap">
    <input type="text" id="pIn" placeholder="Gõ từ tiếng Anh..." autocomplete="off" autocapitalize="off" style="font-size:1.1rem">
    <button class="main" id="pCheck" type="button" style="width:100%">Kiểm tra</button>
  </div>
  <div id="pFlip" style="display:none">
    <div style="text-align:center;margin-bottom:10px"><button type="button" class="stop" id="pSay">🔊 Nghe</button></div>
    <button class="main" id="pFlipBtn" type="button" style="width:100%">Lật thẻ xem nghĩa</button>
    <div id="pFlipBack" style="display:none;text-align:center">
      <div id="pBackText" style="margin:6px 0 12px;line-height:1.6"></div>
      <div style="display:flex;gap:10px"><button class="main" id="pKnow" type="button">✅ Đã nhớ</button>
        <button class="stop" id="pNo" type="button" style="flex:1">❌ Chưa nhớ</button></div>
    </div>
  </div>
  <div id="pFb" style="margin-top:12px;text-align:center;font-weight:700;min-height:1.4em"></div>
  <button class="stop" id="pNext" type="button" style="width:100%;margin-top:8px">Bài khác ▶️</button>
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
  refreshQuizIntro(); pRefresh();
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
const VI_RE = /[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]/i;
// Dịch ngay trên trình duyệt (IP của bạn, không dùng chung với máy chủ) khi máy chủ bị chặn
async function clientTr(text, src, dst){
  const q = encodeURIComponent(text);
  try{ const d = await (await fetch('https://translate.googleapis.com/translate_a/single?client=gtx&sl='+src+'&tl='+dst+'&dt=t&q='+q)).json();
       const o = d[0].map(p => p[0]).join('').trim(); if(o) return o; }catch(e){}
  try{ const d = await (await fetch('https://api.mymemory.translated.net/get?q='+q+'&langpair='+src+'|'+dst)).json();
       const o = (d.responseData.translatedText||'').trim(); if(o && !/^MYMEMORY WARNING/i.test(o)) return o; }catch(e){}
  return '';
}
async function lookup(text){
  if(text===lastQ) return;
  lastQ = text;
  $('meaningBox').style.display='block'; $('ipa').textContent=''; $('meaning').textContent='Đang tra...';
  let r;
  try{ r = await (await fetch('/api/lookup?q='+encodeURIComponent(text))).json(); }
  catch(e){ r = {error:'server', word:text, ipa:'', meaning:'', icon:'📌'}; }
  if(text !== wordEl.value.trim()) return;
  if(r.error || !r.meaning){
    const isVi = VI_RE.test(text);
    const t = await clientTr(text, isVi?'vi':'en', isVi?'en':'vi');
    if(t){ r.word = isVi ? t : text; r.meaning = isVi ? text : t; r.error = ''; }
  }
  if(text !== wordEl.value.trim()) return;
  current = r;
  $('ipa').textContent = r.ipa || ''; $('icon').textContent = r.icon || '📌';
  $('meaning').textContent = r.error ? '⚠️ Lỗi dịch: '+r.error : (r.meaning || '(không rõ nghĩa)');
  if(r.error) return;
  addLearned(r.word, r.ipa, r.meaning, r.icon); fillExWords(r.word); exK=0; newSentence();
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
      const lw = learned.find(x => x.word===w);
      const r = await (await fetch('/api/exercise?word='+encodeURIComponent(w)+'&meaning='+encodeURIComponent(lw?lw.meaning:'')+'&k='+(exK++))).json();
      if(r.error){ $('vi').textContent='⚠️ Lỗi dịch: '+r.error; return; }
      setVi(r.vi, r.en, r.word, r.vi_word);
    }catch(e){ $('vi').textContent='⚠️ Không tạo được câu lúc này.'; }
    return;
  }
  if(!sentences.length){ try{ sentences = await (await fetch('/api/sentences')).json(); }catch(e){} }
  if(!sentences.length) return;
  let s; do{ s = sentences[Math.floor(Math.random()*sentences.length)]; }while(s===curVi && sentences.length>1);
  setVi(s);
}
function hlVi(s, w){
  let h = esc(s); if(!w) return h;
  const e = esc(w).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return h.replace(new RegExp(e,'gi'), m => '<mark style="background:#fde68a;color:#1c1a17;border-radius:4px;padding:0 3px">'+m+'</mark>');
}
function setVi(s, ref, word, viWord){
  curVi=s; curRef=ref||''; exTarget=word||'';
  if(ref && word){ const lw=learned.find(x=>x.word===word); if(lw){ lw.sample=ref; try{ localStorage.setItem('learned_en', JSON.stringify(learned)); }catch(e){} } }
  $('vi').innerHTML = '🇻🇳 '+hlVi(s, viWord)+(word ? '<div style="font-size:.85rem;color:var(--sub);font-weight:600;margin-top:6px">Hãy dùng từ: <span style="color:var(--accent)">'+esc(word)+'</span> ('+esc(viWord||'')+')</div>' : '');
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
        '<div style="text-align:center;color:var(--sub);margin-bottom:6px">'+label+'</div>'+
        (r.breakdown && r.breakdown.length ? '<div style="text-align:center;font-size:.8rem;color:var(--sub);margin-bottom:10px">'+r.breakdown.map(b => esc(b.label)+' −'+b.value).join(' · ')+'</div>' : '')+
        '<div class="ans">'+r.segments.map(s => '<span class="'+(s.ok?'ok':'bad')+'">'+esc(s.t)+'</span>').join('')+'</div>'+
        (r.errors.length ? '<label style="margin-top:14px">Lỗi cần sửa ('+r.errors.length+')</label>'+r.errors.map(e =>
          '<div class="err"><b>“'+esc(e.text)+'”</b> — '+esc(e.msg)+(e.fix.length?'<br>Gợi ý sửa: <b>'+e.fix.map(esc).join(' / ')+'</b>':'')+'</div>').join('')
          : '<div class="box"><small>Ngữ pháp</small>Không phát hiện lỗi ngữ pháp. ✅</div>')+
        (r.errors.length ? '<div class="box"><small>✅ Câu sau khi sửa lỗi</small>'+esc(r.corrected)+'</div>' : '')+
        (r.word ? '<div class="box"><small>🎯 Từ luyện: '+esc(r.word)+'</small>'+(r.used?'✅ Bạn đã dùng từ này trong câu.':'⚠️ Câu của bạn chưa dùng từ này.')+'</div>' : '')+
        '<div class="box"><small>💡 Gợi ý cách viết tự nhiên hơn</small>'+esc(r.natural)+
          ' <button class="link" id="sayNat" type="button">🔊</button></div>'+
        '<div style="font-size:.78rem;color:var(--sub);margin-top:10px;line-height:1.5">Xanh = đúng, đỏ = lỗi. Điểm ước lượng: 10 điểm, trừ theo số lỗi ngữ pháp, độ sát nghĩa với câu gốc và độ dài câu (xem dòng “−” bên trên); câu gợi ý là câu mẫu từ từ điển hoặc bản dịch máy nên chỉ để tham khảo.</div>';
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

// ---- Luyện nhớ từ: ghép chữ / điền chữ thiếu / điền vào câu / thẻ ghi nhớ ----
var PM=[['scramble','🔤 Ghép chữ'],['missing','✏️ Chữ thiếu'],['cloze','📝 Điền câu'],['flash','🃏 Thẻ nhớ']];
var pMode='scramble', pCur='scramble', pWord=null, pLast=null, pAns=[], pStat={ok:0,no:0};
function pShuf(a){ a=a.slice(); for(let i=a.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[a[i],a[j]]=[a[j],a[i]];} return a; }
function scramble(w){ const L=[...w.replace(/\s+/g,'')]; let s=L; for(let t=0;t<10;t++){ s=pShuf(L); if(s.join('')!==L.join('')) break; } return s.join(' ').toUpperCase(); }
function maskWord(w){
  const ch=[...w], idx=[]; ch.forEach((c,i)=>{ if(/[a-z]/i.test(c) && i>0 && i<ch.length-1) idx.push(i); });
  const hide = idx.length ? new Set(pShuf(idx).slice(0, Math.max(1, Math.ceil(idx.length/2)))) : new Set([ch.length-1]);
  return ch.map((c,i) => c===' ' ? '   ' : hide.has(i) ? '_' : c).join(' ');
}
function clozeOf(w){
  if(!w.sample) return null;
  const stem = w.word.length>4 ? w.word.slice(0,-1) : w.word;
  const re = new RegExp('\\b'+stem.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'[a-z]*','i');
  const m = w.sample.match(re); if(!m) return null;
  return {text: w.sample.replace(re,'_____'), answers:[m[0], w.word]};
}
function pTabs(){
  $('pracTabs').innerHTML = PM.map(m => '<button type="button" class="stop" data-m="'+m[0]+'" style="padding:8px 12px;font-size:.85rem;'+
    (m[0]===pMode?'background:var(--accent);color:var(--accent-ink);border-color:var(--accent)':'')+'">'+m[1]+'</button>').join('');
  document.querySelectorAll('#pracTabs button').forEach(b => b.onclick = () => { pMode=b.dataset.m; pTabs(); pNew(); });
}
function pRefresh(){
  const c=$('pracCard'); if(!c) return;
  c.style.display = learned.length ? 'block' : 'none';
  if(learned.length && !pWord){ pTabs(); pNew(); }
}
function pNew(){
  if(!learned.length) return;
  let w; do{ w = learned[Math.floor(Math.random()*learned.length)]; }while(w===pLast && learned.length>1);
  pLast=pWord=w; pCur=pMode;
  if(pCur==='cloze' && !clozeOf(w)) pCur='scramble';       // từ này chưa có câu mẫu
  $('pFb').textContent=''; $('pIn').value=''; $('pFlipBack').style.display='none'; $('pFlipBtn').style.display='block';
  $('pIcon').textContent = w.icon || '📌';
  const flash = pCur==='flash';
  $('pInputWrap').style.display = flash ? 'none' : 'block'; $('pFlip').style.display = flash ? 'block' : 'none';
  $('pNext').style.display = flash ? 'none' : 'block'; $('pPuzzle').textContent='';
  if(pCur==='scramble'){ $('pHint').textContent='Sắp xếp lại các chữ cái. Nghĩa: '+w.meaning; $('pPuzzle').textContent=scramble(w.word); pAns=[w.word]; }
  if(pCur==='missing'){ $('pHint').textContent='Điền các chữ còn thiếu. Nghĩa: '+w.meaning+(w.ipa?'  '+w.ipa:''); $('pPuzzle').textContent=maskWord(w.word); pAns=[w.word]; }
  if(pCur==='cloze'){ const c=clozeOf(w); $('pHint').textContent='Điền từ còn thiếu (nghĩa: '+w.meaning+')'; $('pPuzzle').style.letterSpacing='normal';
    $('pPuzzle').textContent=c.text; pAns=c.answers; }
  else $('pPuzzle').style.letterSpacing='.2em';
  if(flash){ $('pHint').textContent=w.word; $('pBackText').innerHTML=esc(w.meaning)+(w.ipa?'<br><span style="color:var(--accent);font-family:monospace">'+esc(w.ipa)+'</span>':'');
    $('pFb').textContent='Đã nhớ '+pStat.ok+' · Chưa nhớ '+pStat.no; $('pFb').style.color='var(--sub)'; }
  else if(pCur!=='flash') $('pIn').focus();
}
function pCheck(){
  if(!pWord) return; const v=$('pIn').value.trim().toLowerCase(); if(!v) return;
  const ok = pAns.some(a => a.toLowerCase()===v);
  $('pFb').textContent = ok ? '✅ Chính xác!' : '❌ Đáp án: '+pAns[0]; $('pFb').style.color = ok ? '#16a34a' : '#dc2626';
  say(pWord.word); if(ok) setTimeout(pNew, 1100);
}
$('pCheck').onclick = pCheck; $('pIn').addEventListener('keydown', e => { if(e.key==='Enter') pCheck(); });
$('pNext').onclick = pNew; $('pSay').onclick = () => pWord && say(pWord.word);
$('pFlipBtn').onclick = () => { $('pFlipBack').style.display='block'; $('pFlipBtn').style.display='none'; };
$('pKnow').onclick = () => { pStat.ok++; pNew(); }; $('pNo').onclick = () => { pStat.no++; pNew(); };
pRefresh();
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
