"""
MustafaBuilds - TrHaber İngilizce Çeviri Eklentisi
Türkçe haberleri Gemini ile İngilizce'ye çevirir.
Sadece yeni eklenen haberleri işler (baslik_en alanı olmayanlar).
"""

import json
import os
import sys
import time
import logging
import google.generativeai as genai
from cryptography.fernet import Fernet

HABERLER_PATH = "C:/mustafabuilds/TrHaberPlatformu/data/haberler.json"
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "scraper_config.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "translate.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)


def decrypt_api_key(encrypted_key):
    try:
        key = Fernet.generate_key()
        f = Fernet(key)
        return f.decrypt(encrypted_key.encode()).decode()
    except:
        return encrypted_key


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def translate_to_english(api_key, tr_title, tr_summary, tr_content):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemma-4-31b-it')

    prompt = f"""You are a professional news translator. Translate the following Turkish news to English.

RULES:
- Translate naturally and professionally
- Keep all factual information intact
- Return ONLY valid JSON, no other text
- Preserve HTML tags in the content field

Turkish Title: {tr_title}
Turkish Summary: {tr_summary}
Turkish Content: {tr_content}

{{"baslik_en": "English title", "ozet_en": "English summary", "icerik_en": "<p>English content with HTML tags preserved</p>"}}"""

    for attempt in range(3):
        try:
            response = model.generate_content(prompt)
            text = response.text

            result = extract_json(text)
            if result and result.get("baslik_en") and result.get("icerik_en"):
                return result

            logging.warning(f"Translate parse failed (attempt {attempt + 1}/3)")
            if attempt < 2:
                time.sleep(10 * (attempt + 1))
        except Exception as e:
            logging.error(f"Translate error (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(10 * (attempt + 1))
    return None


def extract_json(raw_text):
    if not raw_text or not isinstance(raw_text, str):
        return None

    text = raw_text.strip()

    if "```json" in text:
        parts = text.split("```json")
        if len(parts) > 1:
            text = parts[1].split("```")[0].strip()
    elif "```" in text:
        parts = text.split("```")
        if len(parts) > 1:
            text = parts[1].split("```")[0].strip()

    for i, ch in enumerate(text):
        if ch == '{':
            depth = 0
            end = -1
            for j in range(i, len(text)):
                if text[j] == '{':
                    depth += 1
                elif text[j] == '}':
                    depth -= 1
                    if depth == 0:
                        end = j
                        break
            if end == -1:
                continue
            candidate = text[i:end + 1]
            try:
                result = json.loads(candidate)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                try:
                    fixed = candidate.replace(",\s*([}\]])", r"\1")
                    result = json.loads(fixed)
                    if isinstance(result, dict):
                        return result
                except:
                    pass
    return None


def process_news():
    config = load_config()
    api_key = config["gemini_api_key"]

    logging.info("=" * 60)
    logging.info("TrHaber İngilizce Çeviri başlatılıyor...")

    if not os.path.exists(HABERLER_PATH):
        logging.error(f"Haberler JSON bulunamadı: {HABERLER_PATH}")
        return

    with open(HABERLER_PATH, "r", encoding="utf-8") as f:
        haberler = json.load(f)

    logging.info(f"Toplam {len(haberler)} haber bulundu.")

    translated_count = 0
    for i, haber in enumerate(haberler):
        if haber.get("baslik_en"):
            continue

        baslik = haber.get("baslik", "")
        ozet = haber.get("ozet", "")
        icerik = haber.get("icerik", "")

        if not baslik or not icerik:
            continue

        logging.info(f"[{i + 1}/{len(haberler)}] Çevriliyor: {baslik[:50]}...")

        result = translate_to_english(api_key, baslik, ozet, icerik)

        if result:
            haber["baslik_en"] = result.get("baslik_en", baslik)
            haber["ozet_en"] = result.get("ozet_en", ozet)
            haber["icerik_en"] = result.get("icerik_en", icerik)
            translated_count += 1
            logging.info(f"  -> {haber['baslik_en'][:50]}...")

            with open(HABERLER_PATH, "w", encoding="utf-8") as f:
                json.dump(haberler, f, ensure_ascii=False, indent=4)

            time.sleep(15)
        else:
            logging.warning(f"Çeviri başarısız: {baslik[:50]}")

    logging.info(f"Toplam {translated_count} haber İngilizce'ye çevrildi.")


def main():
    logging.info("Translate scraper başlatıldı. Sürekli izleme modu...")
    while True:
        try:
            process_news()
            logging.info("2 dakika bekleniyor, yeni haberler kontrol edilecek...")
            time.sleep(120)
        except KeyboardInterrupt:
            logging.info("Kullanıcı tarafından durduruldu.")
            break
        except Exception as e:
            logging.error(f"Beklenmeyen hata: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
