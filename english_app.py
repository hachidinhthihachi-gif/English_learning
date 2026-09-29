def grade(vi, ans, ref="", word=""):
    ans = ans.strip()
    if not ans:
        return {"error": "Bạn chưa viết câu trả lời."}
    if VI_CHARS.search(ans):
        return {"error": "Hãy viết câu trả lời bằng tiếng Anh nhé."}
    
    # 1. Đảm bảo câu tham khảo (natural) không bị rỗng hay lỗi ký tự lẻ (như "S")
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
        
    # Dịch lời giải thích lỗi sang tiếng Việt (Bọc try-except tránh sập server Render)
    if errs:
        try:
            with ThreadPoolExecutor(max_workers=3) as ex:
                for e, v in zip(errs, ex.map(lambda item: tr(item["msg"], "en", "vi"), errs)):
                    e["msg"] = v or e["msg"]
        except Exception:
            pass # Nếu lỗi dịch thì giữ nguyên câu tiếng Anh của LanguageTool
            
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