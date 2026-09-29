def lookup(q):
    """Tra từ tiếng Anh hoặc dịch nghĩa tiếng Việt sang tiếng Anh.

    Hàm này cần các thành phần được định nghĩa ở nơi khác trong ứng dụng:
    VI_CHARS, tr(), fetch_entry(), get_ipa().
    """
    q_clean = (q or "").strip()

    if not q_clean:
        return {
            "word": "",
            "ipa": "",
            "meaning": "",
            "icon": "📌",
        }

    if VI_CHARS.search(q_clean):
        # Người dùng nhập tiếng Việt: dịch sang tiếng Anh để làm từ mục tiêu.
        word = (tr(q_clean, "vi", "en") or "").strip() or q_clean
        meaning = q_clean
    else:
        word = q_clean
        entry = fetch_entry(word)
        meanings_list = []

        # Dictionary API thường trả về một danh sách các mục từ.
        if isinstance(entry, list) and entry:
            meanings = entry[0].get("meanings", [])
            for item in meanings:
                pos = item.get("partOfSpeech", "")
                definitions = item.get("definitions", [])

                if not definitions:
                    continue

                definition_en = (definitions[0].get("definition") or "").strip()
                if not definition_en:
                    continue

                definition_vi = (tr(definition_en, "en", "vi") or "").strip()
                if definition_vi and len(definition_vi) > 2:
                    meanings_list.append(f"({pos}) {definition_vi}" if pos else definition_vi)

        if meanings_list:
            meaning = " | ".join(meanings_list)
        else:
            # Dự phòng: dịch trực tiếp từ/cụm từ sang tiếng Việt.
            meaning = (tr(word, "en", "vi") or "").strip()

    if not meaning or len(meaning.strip()) <= 2:
        meaning = (tr(word, "en", "vi") or "").strip() or "Chưa lấy được nghĩa lúc này"

    try:
        ipa = get_ipa(word) or ""
    except Exception:
        ipa = ""

    return {
        "word": word,
        "ipa": ipa,
        "meaning": meaning,
        "icon": "📌",
    }
