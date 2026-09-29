def grade(vi, ans, ref="", word=""):
    ans = ans.strip()
    if not ans:
        return {"error": "Bạn chưa viết câu trả lời."}
    if VI_CHARS.search(ans):
        return {"error": "Hãy viết câu trả lời bằng tiếng Anh nhé."}
    
    # 1. Đảm bảo câu tham khảo (natural) không bị rỗng hay lỗi ký tự lẻ (như "S")
    ref = ref.strip() if ref else ""
    if not ref or len(ref) <= 2:
        ref = tr(vi, "vi", "en")
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
        
    with ThreadPoolExecutor(6) as ex:
        for e, v in zip(errs, ex.map(lambda e: tr(e["msg"], "en", "vi"), errs)):
            e["msg"] = v or e["msg"]
            
    for o, l, fx in reversed(used):
        if fx:
            fixed = fixed[:o] + fx[0] + fixed[o + l:]
            
    # 2. Cải tiến thuật toán tính điểm hợp lý hơn:
    words = set(re.findall(r"[a-z']+", ans.lower()))
    rwords = set(re.findall(r"[a-z']+", ref.lower()))
    
    # Tỷ lệ từ trùng lặp
    common = len(words & rwords)
    f1 = (2 * common) / max(len(words) + len(rwords), 1)
    
    n = len(re.findall(r"[A-Za-z']+", ans))
    # Giảm mức phạt lỗi chính tả nhỏ (từ 1.2 xuống 0.5) để tránh tụt điểm quá đà
    grammar_score = max(0.2, 1.0 - (0.5 * len(errs) / max(n, 4)))
    
    # Điểm ý nghĩa/từ vựng (tối thiểu 0.4 nếu cấu trúc câu cơ bản đã đúng)
    meaning_score = max(0.4, f1)
    
    # Tổng điểm quy về thang 10
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