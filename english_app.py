def lookup(q):
    q_clean = q.strip()
    if not q_clean:
        return {"word": "", "ipa": "", "meaning": "", "icon": "📌"}
        
    if VI_CHARS.search(q_clean):
        word = tr(q_clean, "vi", "en") or q_clean
        meaning = q_clean
    else:
        word = q_clean
        d = fetch_entry(word)
        meanings_list = []
        
        if d and isinstance(d, list) and len(d) > 0 and "meanings" in d[0]:
            for m in d[0]["meanings"]:
                pos = m.get("partOfSpeech", "")
                defs = m.get("definitions", [])
                if defs:
                    def_en = defs[0].get("definition", "")
                    if def_en:
                        def_vi = tr(def_en, "en", "vi")
                        if def_vi and len(def_vi) > 2:
                            meanings_list.append(f"({pos}) {def_vi}")
                            
        if meanings_list:
            meaning = " | ".join(meanings_list)
        else:
            # Fallback dịch trực tiếp từ sang tiếng Việt nếu không lấy được định nghĩa
            meaning = tr(word, "en", "vi")

    # Nếu vẫn rỗng hoặc chỉ có vài ký tự lỗi, ép dịch lại trực tiếp
    if not meaning or len(meaning.strip()) <= 2:
        meaning = tr(word, "en", "vi") or "Chưa lấy được nghĩa lúc này"

    r = {"word": word, "ipa": get_ipa(word), "meaning": meaning, "icon": "📌"}
    return r