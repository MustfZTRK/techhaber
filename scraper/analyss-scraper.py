import json
import mysql.connector
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
import time
import os
import sys
from cryptography.fernet import Fernet
import json
from urllib.parse import urljoin
import feedparser
import xml.etree.ElementTree as ET
import re
import logging
import subprocess
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from lxml import etree, html




sys.path.insert(0, os.path.dirname(__file__))


def application(environ, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    message = 'It works!\n'
    version = 'Python v' + sys.version.split()[0] + '\n'
    response = '\n'.join([message, version])
    return [response.encode()]
    
# Logging setup for both file and terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "scraper.log"),encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

def sleep_until_after_first_quarter():
    try:
        now = time.localtime()
        if now.tm_min < 1:
            wait_seconds = (15 - now.tm_min) * 60 - now.tm_sec
            logging.info("Saat başı yoğunluk: ilk 15 dakikada bekleniyor...")
            time.sleep(max(1, wait_seconds))
    except Exception:
        # Eğer zaman hesabında beklenmedik bir hata olursa, güvenli kısa bekleme
        time.sleep(60)
def resource_path(relative_path):
    """PyInstaller ile paketlenmiş dosya yolunu bulur"""
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)
def load_config():
    with open(resource_path("scraper_config.json"), "r") as f:
        return json.load(f)

def load_site_categories():
    try:
        app_cat_path = "C:/mustafabuilds/TrHaberPlatformu/data/kategoriler.json"
        with open(app_cat_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return [c.get("ad") for c in data if c.get("ad")]
    except Exception as e:
        logging.info(f"Kategori dosyası okunamadı, varsayılana dönülüyor: {e}")
        return ["Gündem", "Ekonomi", "Teknoloji", "Sağlık", "Bilim", "Otomobil", "Yapay Zeka", "Oyun", "Kültür", "Politika", "Güvenlik", "Uzay"]

def normalize_category(cat, site_categories):
    if not cat:
        return "Gündem"
    cat_clean = cat.strip()
    for sc in site_categories:
        if sc.lower() == cat_clean.lower():
            return sc
    synonyms = {
        "culture": "Kültür",
        "science": "Bilim",
        "health": "Sağlık",
        "technology": "Teknoloji",
        "automobile": "Otomobil",
        "auto": "Otomobil",
        "politics": "Politika",
        "security": "Güvenlik",
        "space": "Uzay",
        "gaming": "Oyun",
        "game": "Oyun",
        "ai": "Yapay Zeka",
        "artificial intelligence": "Yapay Zeka",
        "economy": "Ekonomi",
        "business": "Ekonomi",
        "finance": "Ekonomi"
    }
    mapped = synonyms.get(cat_clean.lower())
    if mapped and mapped in site_categories:
        return mapped
    return "Gündem"
def rewrite_with_gemini(api_key, english_title, english_content, categories):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemma-4-31b-it')
    
    prompt = f"""Sen bir haber editörüsün. İngilizce haberi al ve Türk haber sitesi üslubuyla yeniden yaz.

KURALLAR:
- Haberi tamamen Türkçe yaz
- Kategorilerden birini seç: {', '.join(categories)}
- İçerik kısaysa yeni bilgi uydurma
- SADECE JSON dön, başka metin ekleme

İngilizce Başlık: {english_title}
İngilizce İçerik: {english_content}

{{"baslik": "Haber başlığı", "kisa_baslik": "Kısa başlık", "ozet": "Haber özeti", "icerik": "<p>Haber metni...</p>", "kategori": "Seçilen kategori"}}"""
    
    for attempt in range(3):
        try:
            response = model.generate_content(prompt)
            text = response.text
            
            result = extract_json_from_llm(text, expected_keys=["baslik", "icerik"])
            if result:
                return result
            
            if attempt < 2:
                logging.warning(f"rewrite_with_gemini: JSON parse başarısız (deneme {attempt + 1}/3), yeniden deneniyor...")
                time.sleep(10 * (attempt + 1))
                continue
            
            logging.error(f"rewrite_with_gemini: 3 deneme sonunda JSON parse başarısız. Ham çıktı: {text[:500]}")
            return None
            
        except Exception as e:
            msg = str(e)
            if "403" in msg and "unregistered callers" in msg:
                logging.error(f"Gemini 403 hatası (API quota): {e}")
                if attempt == 0:
                    time.sleep(600)
                    continue
            logging.error(f"rewrite_with_gemini hatası (deneme {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(10 * (attempt + 1))
    return None

def fix_encoding(text):
    if not text: return text
    # Fix common UTF-8 to Windows-1252 artifacts
    replacements = {
        "â€¢": "•",
        "â€“": "–",
        "â€”": "—",
        "â€™": "'",
        "â€œ": '"',
        "â€?": '"',
        "Â": "",
        "â€¦": "...",
        "Ä±": "ı",
        "ÄŸ": "ğ",
        "Ã¼": "ü",
        "ÅŸ": "ş",
        "Ã¶": "ö",
        "Ã§": "ç"
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text

def extract_json_from_llm(raw_text, expected_keys=None):
    """
    LLM'den gelen ham metinden JSON'u güvenli bir şekilde çıkarır ve onarır.
    Tüm '{' pozisyonlarını deneyip hangisinin geçerli JSON olduğunu bulur.
    
    Args:
        raw_text: LLM'den gelen ham metin
        expected_keys: Beklenen JSON anahtarları (doğrulama için, opsiyonel)
    
    Returns:
        dict veya None
    """
    if not raw_text or not isinstance(raw_text, str):
        return None

    text = raw_text.strip()

    # 1. Adım: Markdown code block temizleme
    if "```json" in text:
        parts = text.split("```json")
        if len(parts) > 1:
            text = parts[1].split("```")[0].strip()
    elif "```" in text:
        parts = text.split("```")
        if len(parts) > 1:
            text = parts[1].split("```")[0].strip()

    # 2. Adım: Tüm '{' pozisyonlarını bul ve her birini dene
    candidates = []
    for i, ch in enumerate(text):
        if ch == '{':
            candidates.append(i)

    if not candidates:
        logging.warning(f"LLM çıktısında JSON başlangıcı bulunamadı (ilk 200 karakter): {raw_text[:200]}")
        return None

    # Her aday için: '{' den başlayıp eşleşen '}' yi bul ve parse et
    for start_idx in candidates:
        # Bu '{' için eşleşen '}' yi bul (basit parantez sayma)
        depth = 0
        end_idx = -1
        for j in range(start_idx, len(text)):
            if text[j] == '{':
                depth += 1
            elif text[j] == '}':
                depth -= 1
                if depth == 0:
                    end_idx = j
                    break

        if end_idx == -1:
            continue

        candidate = text[start_idx:end_idx + 1]

        # Açıkça geçersiz adayları atla
        if len(candidate) < 5:
            continue
        if '...' in candidate and '"..."' in candidate:
            continue

        # Çoklu onarım stratejisi ile parse et
        parse_attempts = [
            ("ham", candidate),
            ("trailing_comma", _fix_trailing_commas(candidate)),
            ("unescape_newlines", _fix_unescaped_newlines(candidate)),
            ("combined", _fix_combined(_fix_unescaped_newlines(_fix_trailing_commas(candidate)))),
        ]

        for attempt_name, fix_candidate in parse_attempts:
            try:
                result = json.loads(fix_candidate)
                if isinstance(result, dict):
                    # Beklenen anahtarlar varsa kontrol et
                    if expected_keys:
                        missing = [k for k in expected_keys if k not in result]
                        if missing:
                            # Anahtar eksikse ama en azından bazı değerler varsa yine de kabul et
                            if len(result) >= 1:
                                logging.warning(f"JSON parse ({attempt_name})成功 ama eksik anahtarlar: {missing} (ama {len(result)} alan mevcut)")
                                return result
                            continue
                    return result
            except json.JSONDecodeError:
                continue

    # 3. Adım: Son çare - agresif onarım ile tüm adayları tekrar dene
    for start_idx in candidates:
        depth = 0
        end_idx = -1
        for j in range(start_idx, len(text)):
            if text[j] == '{':
                depth += 1
            elif text[j] == '}':
                depth -= 1
                if depth == 0:
                    end_idx = j
                    break
        if end_idx == -1:
            continue
        candidate = text[start_idx:end_idx + 1]
        if len(candidate) < 5:
            continue

        repaired = _aggressive_json_repair(candidate)
        if repaired:
            try:
                result = json.loads(repaired)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

    logging.error(f"JSON parse başarısız - tüm stratejiler tükendi. İlk 300 karakter: {text[:300]}")
    return None


def _fix_trailing_commas(text):
    """JSON'daki trailing comma'ları temizler: {, } ve [, ]"""
    text = re.sub(r',\s*([}\]])', r'\1', text)
    return text


def _fix_unescaped_newlines(text):
    """JSON string değerleri içindeki escape edilmemiş newline karakterlerini düzeltir."""
    result = []
    in_string = False
    escape_next = False
    for char in text:
        if escape_next:
            result.append(char)
            escape_next = False
            continue
        if char == '\\' and in_string:
            result.append(char)
            escape_next = True
            continue
        if char == '"':
            in_string = not in_string
            result.append(char)
            continue
        if in_string and char == '\n':
            result.append('\\n')
            continue
        if in_string and char == '\r':
            continue
        if in_string and char == '\t':
            result.append('\\t')
            continue
        result.append(char)
    return ''.join(result)


def _fix_single_quotes(text):
    """Basit durumlarda tek tırnakları çift tırnağa dönüştürür."""
    # Sadece outside-of-JSON anahtarları ve değerleri için dikkatli dönüşüm
    # Tehlikeli olabileceğinden sadece basit durumları hedefle
    text = re.sub(r"(?<=[{,\[])\s*'([^']*?)'\s*(?=[},\]])", r'"\1"', text)
    text = re.sub(r"(?<=[{,\[])\s*'([^']*?)'\s*:", r'"\1":', text)
    return text


def _fix_combined(text):
    """Birden fazla onarımı birlikte uygular."""
    return text


def _aggressive_json_repair(text):
    """
    Agresif JSON onarımı: bozuk JSON'u düzeltmeye çalışır.
    Eksik kapanış parantezleri, bozuk string escape'leri vb. düzeltir.
    """
    try:
        # Eksik kapanış parantezlerini tamamla
        open_braces = text.count('{') - text.count('}')
        open_brackets = text.count('[') - text.count(']')
        
        # String içindeki kapanmamış escape'leri temizle
        result = text.rstrip()
        
        # Trailing comma sorunlarını tekrar temizle
        result = _fix_trailing_commas(result)
        
        # Eksik parantezleri ekle
        if open_brackets > 0:
            result += ']' * open_brackets
        if open_braces > 0:
            result += '}' * open_braces
        
        return result
    except Exception:
        return None


def get_article_full_content(article_url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,tr;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Referer': 'https://www.google.com/'
        }
        import random
        time.sleep(random.uniform(1, 3))
        session = requests.Session()
        retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[403, 429, 500, 502, 503, 504], allowed_methods=["GET"])
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('https://', adapter)
        session.mount('http://', adapter)

        def fetch_and_extract(url):
            resp = session.get(url, headers=headers, timeout=15)
            if resp.status_code == 403:
                return None, None
            resp.raise_for_status()
            sp = BeautifulSoup(resp.content, 'html.parser')
            og_img = sp.find('meta', property='og:image')
            img_url = og_img['content'] if og_img and og_img.get('content') else None
            paras = []
            if "livemint.com" in url:
                response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
                soup = BeautifulSoup(response.text, "html.parser")
                p_tags = soup.find_all('p')
                for p in p_tags:
                    t = p.get_text().strip()
                    if t:
                        paras.append(t)
            else:
                selectors = [
                    'article p', '.entry-content p', '.article-body p', '.post-content p', 'main p',
                    '[itemprop="articleBody"] p', '#content p', '.c-article-content p', '.content p'
                ]
                for sel in selectors:
                    found = sp.select(sel)
                    if found:
                        for p in found:
                            t = p.get_text().strip()
                            if len(t) > 40:
                                paras.append(t)
                        if len(paras) > 2:
                            break
            return img_url, "\n\n".join(paras)

        image_url, full_text = fetch_and_extract(article_url)
        
        if not full_text and "livemint.com" in article_url:
            full_text = scrape_article(article_url)
            
        if not full_text and "livemint.com" not in article_url:
            amp_url = article_url.rstrip('/') + '/amp'
            image_url, full_text = fetch_and_extract(amp_url)

        if not full_text and "livemint.com" not in article_url:
            sep = '&' if '?' in article_url else '?'
            amp2_url = f"{article_url}{sep}output=amp"
            image_url, full_text = fetch_and_extract(amp2_url)

        return image_url, full_text
    except Exception as e:
        logging.error(f"Error fetching full content from {article_url}: {e}")
        return None, None
def scrape_article(URL):
    response = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"})
    if response.status_code != 200:
        print(f"Request failed with status {response.status_code}")
        return

    soup = BeautifulSoup(response.text, "html.parser")

    # Başlık
    title = soup.find("h1")
    if title:
        print("=== Makale Başlığı ===")
        print(title.get_text(strip=True))
        print()

    # Paragraflar
    textplus = ""
    print("=== İçerik ===")
    for p in soup.find_all("p"):
        text = p.get_text(strip=True)
        if text:
             textplus += "\n" + text
        else:
            textplus = ""
    if(textplus != ""):
        return textplus
    else:
        return ""
def get_article_details(article_url):
    """
    Bir haber URL'sinden öne çıkan görsel ve kısa açıklama döner.
    Dönüş: (image_url, description)
    """
    # Önce kapsamlı içerik toplayan yardımcıyı deneyelim
    img, full_text = get_article_full_content(article_url)
    description = None
    try:
        if full_text:
            parts = [p.strip() for p in full_text.split("\n\n") if p.strip()]
            if len(parts) >= 2:
                description = (parts[0] + " " + parts[1]).strip()
            else:
                description = parts[0]
            # Çok uzun olursa kısalt
            if description and len(description) > 400:
                description = description[:400].rsplit(' ', 1)[0] + "..."
        # Eksikler için fallback: sayfayı tekrar hafifçe incele
        if not img or not description:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9,tr;q=0.8',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Referer': 'https://www.google.com/'
            }
            resp = requests.get(article_url, headers=headers, timeout=15)
            if resp.status_code != 403:
                resp.raise_for_status()
                soup = BeautifulSoup(resp.content, 'html.parser')
                if not img:
                    og_img = soup.find('meta', property='og:image')
                    if og_img and og_img.get('content'):
                        img = og_img['content']
                if not description:
                    if "livemint.com" in article_url:
                        container = soup.select_one('div.taboola-readmore div.storyPage_storyContent__3xuFc') or soup.select_one('div.storyPage_storyContent__3xuFc')
                        if container:
                            p_tags = container.select('div.storyParagraph p')
                            texts = [p.get_text().strip() for p in p_tags if p.get_text().strip()]
                            if texts:
                                description = " ".join(texts)
                                if len(description) > 400:
                                    description = description[:400].rsplit(' ', 1)[0] + "..."
                    if not description:
                        og_desc = soup.find('meta', property='og:description') or soup.find('meta', attrs={'name': 'description'})
                        if og_desc and og_desc.get('content'):
                            description = og_desc['content'].strip()
                        else:
                            p_tags = soup.select('article p, .entry-content p, .article-body p, .post-content p, main p')
                            texts = [p.get_text().strip() for p in p_tags if p.get_text().strip()]
                            if texts:
                                description = " ".join(texts[:2])
                                if len(description) > 400:
                                    description = description[:400].rsplit(' ', 1)[0] + "..."
        return img, description
    except Exception as e:
        logging.info(f"get_article_details error for {article_url}: {e}")
        return img, description
def _extract_first_image_from_html(html_content):
    """HTML içeriğinden ilk görsel URL'sini çıkarır."""
    if not html_content:
        return None
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        # <figure> içindeki <img> öncelikli
        img = soup.select_one('figure img, article img, .wp-post-image, img')
        if img:
            src = img.get('src') or img.get('data-src')
            if src and src.startswith('http'):
                return src
        # srcset'ten de deneme
        if img:
            srcset = img.get('srcset')
            if srcset:
                first = srcset.split(',')[0].strip().split(' ')[0]
                if first.startswith('http'):
                    return first
    except Exception:
        pass
    return None


def _get_entry_link(entry):
    """Atom ve RSS feed entry'lerinden güvenli bir şekilde link alır."""
    # feedparser atom ve rss için link'i normalize eder
    link = getattr(entry, 'link', None)
    if link:
        return link
    # Fallback: links listesinden alternate ara
    links = getattr(entry, 'links', [])
    for l in links:
        if l.get('rel') == 'alternate' and l.get('href'):
            return l['href']
    if links and links[0].get('href'):
        return links[0]['href']
    return None


def scrape_theverge_articles(url):
    articles = []
    try:
        session = requests.Session()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36',
            'Accept': 'application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'Referer': 'https://www.theverge.com/',
            'Connection': 'keep-alive'
        }
        response = None
        for attempt in range(3):
            try:
                resp = session.get(url, headers=headers, timeout=20)
                if resp.status_code == 200:
                    response = resp
                    break
                if resp.status_code in (403, 420, 429):
                    time.sleep(2 * (attempt + 1))
                    continue
                resp.raise_for_status()
            except requests.exceptions.RequestException:
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        if response is None:
            raise requests.exceptions.RequestException("Failed to fetch The Verge RSS after retries")

        # CDATA temizleme YAPMA - feedparser native olarak handle eder.
        # CDATA kaldırılınca HTML içindeki &nbsp; gibi entity'ler geçersiz XML'e dönüşür.

        content = response.text

        # 1. deneme: Ham text ile parse et
        feed = feedparser.parse(content)

        # 2. deneme: Bozuk XML varsa, CDATA'ları koruyarak byte olarak parse et
        if feed.bozo:
            logging.warning(f"The Verge Atom parse hatası (text): {feed.bozo_exception}")
            feed = feedparser.parse(response.content)
            if feed.bozo:
                logging.warning(f"The Verge Atom parse hatası (bytes): {feed.bozo_exception}")
                # 3. deneme: feedparser'ın kendi URL fetching'ini kullan
                feed = feedparser.parse(url)
                if feed.bozo:
                    logging.error(f"The Verge Atom tüm denemeler başarısız: {feed.bozo_exception}")
                    return articles

        logging.info(f"The Verge feed başarıyla parse edildi. {len(feed.entries)} entry bulundu.")

        for entry in feed.entries[:30]:
            entry_link = _get_entry_link(entry)
            if not entry_link:
                logging.warning(f"Entry link bulunamadı, atlanıyor: {getattr(entry, 'title', 'N/A')}")
                continue

            image_url, description = get_article_details(entry_link)

            # Atom feed'lerde özet summary veya content içinden gelir
            if not description:
                summary = getattr(entry, 'summary', None)
                if summary:
                    soup = BeautifulSoup(summary, 'html.parser')
                    description = soup.get_text(separator=' ', strip=True)
            if not description:
                content_val = getattr(entry, 'content', None)
                if content_val and isinstance(content_val, list) and len(content_val) > 0:
                    raw = content_val[0].get('value', '')
                    soup = BeautifulSoup(raw, 'html.parser')
                    description = soup.get_text(separator=' ', strip=True)
            if not description:
                description = getattr(entry, 'title', '')

            # Görsel: content HTML'inden çıkar (Atom feed'lerde genelde burada)
            if image_url is None:
                content_val = getattr(entry, 'content', None)
                if content_val and isinstance(content_val, list) and len(content_val) > 0:
                    raw_html = content_val[0].get('value', '')
                    image_url = _extract_first_image_from_html(raw_html)

            # media_content fallback
            if image_url is None:
                media = getattr(entry, 'media_content', None)
                if media:
                    images = [m for m in media if m.get('medium') == 'image']
                    if images and images[0].get('url'):
                        image_url = images[0]['url']

            # links fallback
            if image_url is None:
                links = getattr(entry, 'links', [])
                for e_link in links:
                    if e_link.get('type', '').startswith('image/') and e_link.get('href'):
                        image_url = e_link['href']
                        break

            title = getattr(entry, 'title', '')
            if title and entry_link:
                articles.append({
                    'title': title,
                    'url': entry_link,
                    'image_url': image_url,
                    'content': description
                })

        logging.info(f"The Verge'den {len(articles)} makale alındı.")
    except requests.exceptions.RequestException as e:
        logging.error(f"The Verge RSS feed URL'sinden hata: {e}")
    except Exception as e:
        logging.error(f"scrape_theverge_articles'da beklenmeyen hata: {e}")
    return articles
def get_sciencedaily_article_image(article_url):
    try:
        response = requests.get(article_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        # Find the image element with class "img-responsive"
        img_element = soup.find('img', class_='img-responsive')
        if img_element:
            # Extract the src attribute
            image_url = img_element.get('src')
            if image_url and not image_url.startswith('http'):
                # Make sure it's an absolute URL
                image_url = urljoin("https://www.sciencedaily.com", image_url)
            return image_url
    except requests.exceptions.RequestException as e:
        logging.info(f"Error fetching ScienceDaily article image from {article_url}: {e}")
    return None

def _clean_xml_content(raw_xml):
    """
    XML içeriğini temizler: geçersiz HTML entity'leri, fazla içerik, vs.
    """
    text = raw_xml if isinstance(raw_xml, str) else raw_xml.decode('utf-8', errors='replace')
    
    # 1. </rss> veya </channel> sonrasında fazla içeriği temizle
    for closing_tag in ['</rss>', '</channel>']:
        idx = text.rfind(closing_tag)
        if idx != -1:
            text = text[:idx + len(closing_tag)]
            break
    
    # 2. Geçersiz HTML entity'lerini XML uyumlu hale getir
    invalid_entities = {
        '&nbsp;': ' ',
        '&mdash;': '—',
        '&ndash;': '–',
        '&lsquo;': ''',
        '&rsquo;': ''',
        '&ldquo;': '"',
        '&rdquo;': '"',
        '&hellip;': '…',
        '&copy;': '©',
        '&reg;': '®',
        '&trade;': '™',
        '&euro;': '€',
        '&pound;': '£',
        '&yen;': '¥',
        '&times;': '×',
        '&divide;': '÷',
        '&nbsp;': ' ',
    }
    for entity, char in invalid_entities.items():
        text = text.replace(entity, char)
    
    # 3. Tanınmayan & ile başlayan entity'leri temizle (örn: &abc; gibi)
    text = re.sub(r'&(?!amp;|lt;|gt;|apos;|quot;|#\d+;|#x[0-9a-fA-F]+;)([a-zA-Z]+;)', r'\1', text)
    
    return text


def scrape_sciencedaily_articles(rss_url):
    articles = []
    try:
        response = requests.get(rss_url, timeout=20)
        response.raise_for_status()
        
        raw_content = response.text
        cleaned_xml = _clean_xml_content(raw_content)
        
        # 1. deneme: Temizlenmiş XML ile ET.parse
        try:
            root = ET.fromstring(cleaned_xml.encode('utf-8'))
        except ET.ParseError as e:
            logging.warning(f"ScienceDaily XML parse hatası (ET), feedparser deneniyor: {e}")
            # 2. deneme: feedparser ile dene (daha toleranslı)
            feed = feedparser.parse(cleaned_xml)
            if feed.bozo and not feed.entries:
                logging.error(f"ScienceDaily feedparser da başarısız: {feed.bozo_exception}")
                # 3. deneme: Ham content ile feedparser
                feed = feedparser.parse(response.content)
                if feed.bozo and not feed.entries:
                    logging.error(f"ScienceDaily tüm denemeler başarısız. Ham XML sorunlu.")
                    return articles
            
            # feedparser başarılıysa entries'den çıkar
            for entry in feed.entries[:30]:
                title = getattr(entry, 'title', '')
                link = getattr(entry, 'link', '')
                description = getattr(entry, 'summary', '') or getattr(entry, 'description', '')
                
                image_url = None
                if link:
                    image_url = get_sciencedaily_article_image(link)
                
                if title and link:
                    articles.append({
                        'title': title,
                        'url': link,
                        'image_url': image_url,
                        'content': description
                    })
            logging.info(f"ScienceDaily'den (feedparser) {len(articles)} makale alındı.")
            return articles
        
        # ET başarılıysa normal akışla devam et
        for item in root.findall('.//item'):
            if len(articles) >= 30:
                break
            title_el = item.find('title')
            link_el = item.find('link')
            desc_el = item.find('description')
            
            title = title_el.text if title_el is not None and title_el.text else ''
            link = link_el.text if link_el is not None and link_el.text else ''
            description = desc_el.text if desc_el is not None and desc_el.text else ''

            image_url = None
            if link:
                image_url = get_sciencedaily_article_image(link)

            if title and link:
                articles.append({
                    'title': title,
                    'url': link,
                    'image_url': image_url,
                    'content': description
                })
        
        logging.info(f"ScienceDaily'den (ET) {len(articles)} makale alındı.")
        
    except requests.exceptions.RequestException as e:
        logging.error(f"ScienceDaily RSS feed URL'sinden hata: {e}")
    except Exception as e:
        logging.error(f"scrape_sciencedaily_articles beklenmeyen hata: {e}")
    return articles

def scrape_livemint_articles(url):
    articles = []
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()

        # CDATA temizleme YAPMA - feedparser native olarak handle eder.
        content = response.text

        # 1. deneme: Ham text
        feed = feedparser.parse(content)
        if feed.bozo:
            logging.warning(f"Livemint RSS parse hatası (text): {feed.bozo_exception}")
            # 2. deneme: Bytes
            feed = feedparser.parse(response.content)
            if feed.bozo:
                logging.error(f"Livemint RSS tüm denemeler başarısız: {feed.bozo_exception}")
                return articles

        for entry in feed.entries[:30]:
            entry_link = getattr(entry, 'link', None)
            if not entry_link:
                links = getattr(entry, 'links', [])
                for l in links:
                    if l.get('rel') == 'alternate' and l.get('href'):
                        entry_link = l['href']
                        break
                if not entry_link and links:
                    entry_link = links[0].get('href')
            if not entry_link:
                continue

            image_url, description = get_article_details(entry_link)
            
            if not description:
                summary = getattr(entry, 'summary', None)
                if summary:
                    soup = BeautifulSoup(summary, 'html.parser')
                    description = soup.get_text(separator=' ', strip=True)
            if not description:
                description = getattr(entry, 'title', '')

            if image_url is None:
                media = getattr(entry, 'media_content', None)
                if media:
                    images = [m for m in media if m.get('medium') == 'image']
                    if images and images[0].get('url'):
                        image_url = images[0]['url']
            if image_url is None:
                links = getattr(entry, 'links', [])
                for e_link in links:
                    if e_link.get('type', '').startswith('image/') and e_link.get('href'):
                        image_url = e_link['href']
                        break
            
            title = getattr(entry, 'title', '')
            if title and entry_link:
                articles.append({
                    'title': title,
                    'url': entry_link,
                    'image_url': image_url,
                    'content': description
                })
    except requests.exceptions.RequestException as e:
        logging.error(f"Livemint RSS feed URL'sinden hata: {e}")
    except Exception as e:
        logging.error(f"scrape_livemint_articles'da beklenmeyen hata: {e}")
    return articles

def scrape_washingtonpost_articles(url):
    articles = []
    feed = feedparser.parse(url)
    if feed.bozo:
        logging.info(f"Error parsing RSS feed: {feed.bozo_exception}")
        return articles

    for entry in feed.entries[:30]:
        image_url, description = get_article_details(entry.link)
        if image_url and description:
            articles.append({
                'title': entry.title,
                'url': entry.link,
                'image_url': image_url,
                'content': description
            })
    return articles

def scrape_nytimes_articles(url):
    articles = []
    feed = feedparser.parse(url)
    if feed.bozo:
        logging.info(f"Error parsing RSS feed: {feed.bozo_exception}")
        return articles

    for entry in feed.entries[:30]:
        description = None
        if hasattr(entry, 'summary'):
            description = BeautifulSoup(entry.summary, 'html.parser').get_text(separator=' ', strip=True)
        elif hasattr(entry, 'description'):
            description = BeautifulSoup(entry.description, 'html.parser').get_text(separator=' ', strip=True)
        if not description:
            description = entry.title
        
        image_url = 'No image found'
        if hasattr(entry, 'media_content') and entry.media_content:
            image_url = entry.media_content[0]['url']
        elif hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
            image_url = entry.media_thumbnail[0]['url']

        if image_url != 'No image found': # Only add if image_url is found
            articles.append({
                'title': entry.title,
                'url': entry.link,
                'image_url': image_url,
                'content': description
            })
    return articles

def scrape_arstechnica_articles(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        articles = []
        for item in soup.select('article.card-list-square'):
            if len(articles) >= 30:
                break
            title_element = item.select_one('h2 a')
            image_element = item.select_one('img.wp-post-image')
            if title_element and image_element:
                title = title_element.get_text(strip=True)
                link = title_element['href']
                if not link.startswith('http'):
                    link = f"https://arstechnica.com{link}"
                image_url = image_element['src']
                content_element = item.select_one('p.leading-tighter')
                content = content_element.get_text(strip=True) if content_element else ''
                articles.append({'title': title, 'url': link, 'image_url': image_url, 'content': content})
        return articles
    except requests.exceptions.RequestException as e:
        logging.info(f"Error fetching URL: {e}")
    return []

def scrape_cnet_articles(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        articles = []
        for item in soup.select('a.c-storiesNeonLatest_story'):
            if len(articles) >= 30:
                break
            title_element = item.select_one('h3.c-storiesNeonLatest_hed')
            picture_element = item.select_one('picture')
            image_url = None
            if picture_element:
                source_element = picture_element.find_all('source')
                if source_element:
                    # Take the first URL from the srcset (usually the highest resolution)
                    srcset = source_element[-1].get('srcset')
                    if srcset:
                        image_url = srcset.split(',')[0].strip().split(' ')[0]

            if title_element and image_url:
                title = title_element.get_text(strip=True)
                link = item['href']
                if not link.startswith('http'):
                    link = f"https://www.cnet.com{link}"
                content = get_cnet_article_content(link)
                articles.append({'title': title, 'url': link, 'image_url': image_url, 'content': content})
        return articles
    except requests.exceptions.RequestException as e:
        logging.info(f"Error fetching URL: {e}")
    return []

def scrape_techcrunch_articles(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        articles = []
        for item in soup.select('li.wp-block-post'):
            if len(articles) >= 30:
                break
            title_element = item.select_one('h3.loop-card__title a')
            image_element = item.select_one('img.wp-post-image')
            if title_element and image_element:
                title = title_element.get_text(strip=True)
                link = title_element['href']
                image_url = image_element['src']
                content = get_techcrunch_article_content(link)
                articles.append({'title': title, 'url': link, 'image_url': image_url, 'content': content})
        return articles
    except requests.exceptions.RequestException as e:
        logging.info(f"Error fetching URL: {e}")
    return []

def scrape_wired_articles(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        articles = []
        for item in soup.select('div.SummaryItemWrapper-ircKXK'):
            if len(articles) >= 30:
                break
            title_element = item.select_one('a.SummaryItemHedLink-cxRzVg')
            picture_element = item.select_one('picture')
            image_url = None
            if picture_element:
                img_element = picture_element.select_one('img')
                if img_element and img_element.get('src'):
                    image_url = img_element.get('src')
                elif img_element and img_element.get('srcset'):
                    srcset = img_element.get('srcset')
                    image_url = srcset.split(',')[0].strip().split(' ')[0]

            if title_element and image_url:
                title = title_element.get_text(strip=True)
                link = title_element['href']
                if not link.startswith('http'):
                    link = f"https://www.wired.com{link}"
                
                content_element = item.select_one('p.SummaryItemDek-cQxVp')
                content = content_element.get_text(strip=True) if content_element else title

                articles.append({'title': title, 'url': link, 'image_url': image_url, 'content': content})
        return articles
    except requests.exceptions.RequestException as e:
        logging.info(f"Error fetching URL: {e}")
    return []

def scrape_bbc_articles(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        articles = []
        for item in soup.select('div.ixgXiW div.fKTSfm'):
            if len(articles) >= 30:
                break
            title_element = item.select_one('h2 a')
            image_element = item.select_one('div.fMwdlz img')
            if title_element and image_element:
                title = title_element.get_text(strip=True)
                link = title_element['href']
                image_url = image_element['src']
                articles.append({'title': title, 'url': link, 'image_url': image_url})
        return articles
    except requests.exceptions.RequestException as e:
        logging.info(f"Error fetching URL: {e}")
    return []

def scrape_cnbc_articles(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        articles = []
        for item in soup.select('div.Card-card'):
            if len(articles) >= 30:
                break
            title_element = item.select_one('div.Card-title a')
            image_element = item.select_one('div.Card-mediaContainer img')
            if title_element and image_element:
                title = title_element.get_text(strip=True)
                link = title_element['href']
                image_url = image_element['src']
                articles.append({'title': title, 'url': link, 'image_url': image_url})
        return articles
    except requests.exceptions.RequestException as e:
        logging.info(f"Error fetching URL: {e}")
    return []
    
    
def scrape_gamespot_feed(url="https://www.gamespot.com/feeds/news/"):
    try:
        response = requests.get(url)
        response.raise_for_status()

        # XML parse
        root = etree.fromstring(response.content)

        articles = []
        for item in root.findall(".//item")[:30]:
            title = item.findtext("title")
            link = item.findtext("link")
            pub_date = item.findtext("pubDate")
            guid = item.findtext("guid")
            creator = item.findtext("{http://purl.org/dc/elements/1.1/}creator")

            # Description içindeki CDATA HTML'i temizle
            raw_description = item.findtext("description")
            content = None
            if raw_description:
                # HTML parse edip sadece text alıyoruz
                content = html.fromstring(raw_description).text_content().strip()

            # media:content alanı namespaceli
            image_url = None
            media_content = item.find("{http://search.yahoo.com/mrss/}content")
            if media_content is not None and "url" in media_content.attrib:
                image_url = media_content.attrib["url"]

            articles.append({
                "title": title,
                "url": link,
                "content": content,
                "image_url": image_url
            })

        return articles

    except requests.exceptions.RequestException as e:
        logging.info(f"Error fetching GameSpot feed: {e}")
        return []




def scrape_gamespot_articles(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        articles = []
        # The main container for the latest stories is #river, then section.filter-results
        # Each article item is div.card-item
        for item in soup.select('section.filter-results div.card-item'):
            if len(articles) >= 30:
                break
            
            # Article Link and Title
            link_element = item.select_one('div.card-item__main a.card-item__link')
            title_element = item.select_one('div.card-item__main a.card-item__link h4.card-item__title')
            
            # Article Image
            image_element = item.select_one('div.card-item__img img')
            
            if link_element and title_element and image_element:
                title = title_element.get_text(strip=True)
                link = link_element['href']
                image_url = image_element['src']
                
                # Ensure absolute URL
                if not link.startswith('http'):
                    link = urljoin(url, link)
                if not image_url.startswith('http'):
                    image_url = urljoin(url, image_url)

                # GameSpot articles don't seem to have a short content snippet on the listing page
                # We can use the title as content for now, or fetch full content if needed later
                content = title # Placeholder content

                articles.append({'title': title, 'url': link, 'image_url': image_url, 'content': content})
        return articles
    except requests.exceptions.RequestException as e:
        logging.info(f"Error fetching GameSpot URL: {e}")
    return []

def get_gizmodo_featured_image(article_url, timeout=10, headers=None):
    """
    Verilen Gizmodo haber URL'sinden öne çıkarılmış görseli döner.
    Dönen değer: image_url (str) veya None
    """
    if headers is None:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; Bot/1.0; +https://example.com/bot)"
        }

    try:
        resp = requests.get(article_url, timeout=timeout, headers=headers)
        resp.raise_for_status()
    except requests.RequestException as e:
        logging.info(f"Error fetching article URL: {e}")
        return None

    soup = BeautifulSoup(resp.content, "html.parser")

    # Öncelikli hedef: <figure id="attachment_featured"> içindeki <img>
    fig = soup.select_one('figure#attachment_featured')
    img = None
    if fig:
        img = fig.select_one('img')

    # Eğer bulunamadıysa, istenen outer div yapısını kullanarak arama yap
    if not img:
        outer = soup.select_one('div.xl\\:w-7\\/12.flex.py-8.xl\\:pt-8.xl\\:-mb-32.justify-end')
        if outer:
            img = outer.select_one('img')

    # Ek geri dönüşümler: daha genel arama (haber body içinde featured img)
    if not img:
        possible = soup.select('article img, .wp-post-image, figure img')
        for candidate in possible:
            # tercih: id veya class içeren wp-post-image veya attachment_featured
            cls = candidate.get('class') or []
            if 'wp-post-image' in cls or candidate.find_parent('figure') and candidate.find_parent('figure').get('id') == 'attachment_featured':
                img = candidate
                break
        if not img and possible:
            img = possible[0]

    if not img:
        return None

    # Try src first, then srcset
    image_url = img.get('src')
    if not image_url:
        srcset = img.get('srcset')
        if srcset:
            # srcset format: "url1 1500w, url2 768w, ..."
            image_url = srcset.split(',')[0].strip().split(' ')[0]

    if not image_url:
        return None

    # Mutlak URL yap
    image_url = urljoin(article_url, image_url)
    return image_url

def scrape_gizmodo_articles(url):
    """
    Gizmodo liste sayfasından en fazla 30 makale çeker.
    Her makale için: title, url, image_url (haber sayfasındaki featured image), content (kart içi özet varsa)
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, 'html.parser')
        articles = []

        # Başlık seçicisi: listede <a><h3> yapısını hedefliyoruz
        title_elements = soup.select('a h3')

        for title_element in title_elements:
            if len(articles) >= 30:
                break

            # Başlık metni ve başlığa bağlı <a>
            title = title_element.get_text(strip=True)
            title_anchor = title_element.find_parent('a')
            link = title_anchor.get('href') if title_anchor else None
            if not link:
                continue
            if not link.startswith('http'):
                link = f"https://gizmodo.com{link}"

            # Kart içindeki kısa özet varsa al
            container = title_element.find_parent()
            content = ''
            if container:
                p = container.select_one('p')
                if p:
                    content = p.get_text(strip=True)

            # Haber sayfasını ziyaret edip featured image al
            image_url = None
            try:
                image_url = get_gizmodo_featured_image(link, headers=headers)
            except Exception:
                image_url = None

            articles.append({
                'title': title,
                'url': link,
                'image_url': image_url,
                'content': content
            })

        return articles
    except requests.exceptions.RequestException as e:
        logging.info(f"Error fetching URL: {e}")
    return []


def scrape_mashable_articles(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        articles = []

        # Find all <a> tags and filter for article links
        all_links = soup.find_all('a')
        for link_tag in all_links:
            if len(articles) >= 30:
                break
            href = link_tag.get('href')
            if href and '/article/' in href:
                # Construct absolute URL if it's relative
                if not href.startswith('http'):
                    link = f"https://mashable.com{href}"
                else:
                    link = href

                title_element = link_tag.select_one('h2')
                image_element = link_tag.select_one('img')

                if title_element:
                    title = title_element.get_text(strip=True)
                    image_url = image_element.get('src') if image_element else None
                    content = get_mashable_article_content(link) # Fetch content from article page
                    articles.append({'title': title, 'url': link, 'image_url': image_url, 'content': content})
        return articles
    except requests.exceptions.RequestException as e:
        logging.info(f"Error fetching URL: {e}")
    return []

def get_cnet_article_content(article_url):
    try:
        response = requests.get(article_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        content_element = soup.select_one('p.u-speakableText-dek.c-contentHeader_description')
        if content_element:
            return content_element.get_text(strip=True)
    except requests.exceptions.RequestException as e:
        logging.info(f"Error fetching CNET article content from {article_url}: {e}")
    return ''

def get_techcrunch_article_content(article_url):
    try:
        response = requests.get(article_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        content_element = soup.select_one('p#speakable-summary.wp-block-paragraph')
        if content_element:
            return content_element.get_text(strip=True)
    except requests.exceptions.RequestException as e:
        logging.info(f"Error fetching TechCrunch article content from {article_url}: {e}")
    return ''

def get_mashable_article_content(article_url):
    try:
        response = requests.get(article_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        content_element = soup.select_one('div.mt-2.leading-tight.md\\:leading-normal.text-xl.max-w-4xl')
        if content_element:
            return content_element.get_text(strip=True)
    except requests.exceptions.RequestException as e:
        logging.info(f"Error fetching Mashable article content from {article_url}: {e}")
    return ''

def scrape_pcgamer_articles(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        articles = []
        for item in soup.select('div.listingResult'):
            if len(articles) >= 30:
                break
            
            link_element = item.select_one('a.article-link')
            title_element = item.select_one('h3.article-name')
            image_element = item.select_one('picture img')
            content_element = item.select_one('p.synopsis')

            if link_element and title_element and image_element:
                title = title_element.get_text(strip=True)
                link = link_element['href']
                image_url = image_element.get('data-original-mos') or image_element.get('src')
                content = content_element.get_text(strip=True) if content_element else title

                if not link.startswith('http'):
                    link = urljoin(url, link)
                if not image_url.startswith('http'):
                    image_url = urljoin(url, image_url)

                articles.append({'title': title, 'url': link, 'image_url': image_url, 'content': content})
        return articles
    except requests.exceptions.RequestException as e:
        logging.info(f"Error fetching PC Gamer URL: {e}")
    return []

def check_if_exists(url):
    file_path = "C:/mustafabuilds/TrHaberPlatformu/data/haberler.json"
    if not os.path.exists(file_path):
        return False
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            haberler = json.load(f)
            return any(h.get('kaynak', {}).get('link') == url for h in haberler)
    except:
        return False

def save_to_json(news_data):
    file_path = "C:/mustafabuilds/TrHaberPlatformu/data/haberler.json"
    try:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                haberler = json.load(f)
        else:
            haberler = []
        
        # Check if already exists by original URL or title
        if any(h.get('kaynak', {}).get('link') == news_data['kaynak']['link'] for h in haberler):
            logging.info(f"Haber zaten var: {news_data['baslik']}")
            return

        # New ID
        max_id = max([h['id'] for h in haberler], default=0)
        news_data['id'] = max_id + 1
        
        haberler.insert(0, news_data) # Add to top
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(haberler, f, ensure_ascii=False, indent=4)
        logging.info(f"Haber JSON'a başarıyla eklendi: {news_data['baslik']}")
    except Exception as e:
        logging.error(f"Error saving to JSON: {e}")


def get_analysis_file_path():
    return "C:/mustafabuilds/data/gunluk_analiz.json"

def load_analysis_data():
    """Analiz JSON'unu yükler, yoksa boş dict döner. Fikirler alanlarını array formatına normalize eder."""
    path = get_analysis_file_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Fikirler alanlarını normalize et: string ise array'e çevir
            for date_key, entry in data.items():
                for field in ["yaratici_fikirler_tr", "yaratici_fikirler_en"]:
                    val = entry.get(field)
                    if val and not isinstance(val, list):
                        entry[field] = _ensure_fikirler_as_list(val)
            return data
        except Exception:
            return {}
    return {}

def get_analysis_status(date_str):
    """
    Belirtilen tarihe ait analizin hangi bileşenlerinin eksik olduğunu kontrol eder.
    Returns: dict - {field_name: bool (True=var, False=yok)}
    """
    data = load_analysis_data()
    entry = data.get(date_str, {})

    required_fields = {
        "ozet_tr": entry.get("ozet_tr"),
        "yorum_tr": entry.get("yorum_tr"),
        "yaratici_fikirler_tr": entry.get("yaratici_fikirler_tr"),
        "ozet_en": entry.get("ozet_en"),
        "yorum_en": entry.get("yorum_en"),
        "yaratici_fikirler_en": entry.get("yaratici_fikirler_en"),
    }

    status = {}
    for field, value in required_fields.items():
        if value is None or (isinstance(value, str) and value.strip() == ""):
            status[field] = False
        elif "fikirler" in field:
            # Fikirler için array olmasını ve gerçekten içerik içermesini kontrol et
            if isinstance(value, list):
                # En az 3 geçerli fikir olmalı (placeholder olmayan)
                valid = [f for f in value if isinstance(f, str) and len(f.strip()) > 20]
                status[field] = len(valid) >= 3
            elif isinstance(value, str):
                # String olarak kaydedilmişse, array'e çevirip kontrol et
                converted = _ensure_fikirler_as_list(value)
                valid = [f for f in converted if isinstance(f, str) and len(f.strip()) > 20]
                status[field] = len(valid) >= 3
            else:
                status[field] = False
        else:
            status[field] = True

    return status

def check_daily_analysis_exists(date_str=None):
    """Belirtilen tarihe (varsayılan: bugün) ait tüm analiz bileşenlerinin tam olup olmadığını kontrol eder."""
    if date_str is None:
        date_str = time.strftime("%Y-%m-%d")
    status = get_analysis_status(date_str)
    # Tüm 6 bileşen de varsa True döner
    return all(status.values())

def save_daily_analysis(tr_data, en_data, target_date=None):
    """
    Hem Türkçe hem İngilizce premium içerikleri aynı tarih altında
    tek bir JSON objesinde birleştirerek kaydeder.
    Mevcut verilerle merge eder (partial update destekler).
    """
    file_path = get_analysis_file_path()
    if target_date is None:
        target_date = time.strftime("%Y-%m-%d")
    
    try:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {}
        
        # Mevcut entry'yi al (varsa) ve yeni verilerle merge et
        existing = data.get(target_date, {})
        
        new_entry = {
            "tarih": target_date,
            "olusturulma_zamani": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        
        # Türkçe İçerikler - sadece yeni değer varsa güncelle, yoksa mevcudu koru
        for key, tr_key in [("ozet_tr", "ozet"), ("yorum_tr", "yorum"), ("yaratici_fikirler_tr", "fikirler")]:
            new_val = tr_data.get(tr_key) if tr_data else None
            if new_val and tr_key == "fikirler":
                new_val = _ensure_fikirler_as_list(new_val)
            new_entry[key] = new_val if new_val else existing.get(key)
        
        # İngilizce İçerikler
        for key, en_key in [("ozet_en", "ozet"), ("yorum_en", "yorum"), ("yaratici_fikirler_en", "fikirler")]:
            new_val = en_data.get(en_key) if en_data else None
            if new_val and en_key == "fikirler":
                new_val = _ensure_fikirler_as_list(new_val)
            new_entry[key] = new_val if new_val else existing.get(key)
        
        data[target_date] = new_entry
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        
        filled_fields = [k for k, v in new_entry.items() if k not in ("tarih", "olusturulma_zamani") and v]
        logging.info(f"Analiz kaydedildi/güncellendi ({target_date}): {len(filled_fields)} alan mevcut")
    except Exception as e:
        logging.error(f"Günlük analiz JSON kaydetme hatası: {e}")


def get_news_for_date(target_date):
    """Belirtilen tarihe ait haberleri tüm kaynaklardan çeker (haberler.json + decrypt + insidermonkey)."""
    articles = []

    # 1. TrHaberPlatformu haberleri
    haberler_path = "C:/mustafabuilds/TrHaberPlatformu/data/haberler.json"
    try:
        if os.path.exists(haberler_path):
            with open(haberler_path, "r", encoding="utf-8") as f:
                tum_haberler = json.load(f)
                for h in tum_haberler:
                    if h.get("tarih", "").startswith(target_date):
                        articles.append(f"[HABER] Başlık: {h['baslik']}\nÖzet: {h['ozet']}\nİçerik: {h['icerik']}\n---")
    except Exception as e:
        logging.error(f"Haberler havuzu okunurken hata ({target_date}): {e}")

    # 2. Decrypt (Kripto) haberleri - son 24 saat
    decrypt_path = "C:/mustafabuilds/PDF Creator/decrypt_news.json"
    try:
        if os.path.exists(decrypt_path):
            with open(decrypt_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for a in data.get("articles", []):
                    date_str = a.get("date", "")
                    if target_date in date_str:
                        name = a.get("name_tr") or a.get("name", "")
                        short = a.get("short_description_tr") or a.get("short_description", "")
                        long_ = a.get("long_description_tr") or a.get("long_description", "")
                        if name:
                            articles.append(f"[KRİPTO] Başlık: {name}\nÖzet: {short}\nİçerik: {long_}\n---")
    except Exception as e:
        logging.error(f"Decrypt haberleri okunurken hata: {e}")

    # 3. InsiderMonkey (Finans) haberleri - son 24 saat
    insider_path = "C:/mustafabuilds/PDF Creator/insidermonkey_news.json"
    try:
        if os.path.exists(insider_path):
            with open(insider_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for a in data.get("articles", []):
                    date_str = a.get("date", "")
                    if target_date in date_str:
                        name = a.get("name_tr") or a.get("name", "")
                        short = a.get("short_description_tr") or a.get("short_description", "")
                        long_ = a.get("long_description_tr") or a.get("long_description", "")
                        if name:
                            articles.append(f"[FİNANS] Başlık: {name}\nÖzet: {short}\nİçerik: {long_}\n---")
    except Exception as e:
        logging.error(f"InsiderMonkey haberleri okunurken hata: {e}")

    logging.info(f"{target_date} için toplam {len(articles)} haber kaynağı bulundu (TrHaber+Kripto+Finans)")
    return articles


def fill_missing_analysis(api_key, target_date):
    """
    Belirtilen tarihe ait analizdeki eksik bileşenleri tek tek doldurur.
    Eksik olan her bileşen için ayrı ayrı LLM çağrısı yapar,
    sonra çevirisini oluşturur ve partial update ile kaydeder.
    """
    status = get_analysis_status(target_date)
    missing_tr = [k for k in ["ozet_tr", "yorum_tr", "yaratici_fikirler_tr"] if not status.get(k)]
    missing_en = [k for k in ["ozet_en", "yorum_en", "yaratici_fikirler_en"] if not status.get(k)]

    if not missing_tr and not missing_en:
        logging.info(f"{target_date} tarihli analiz zaten tam. Doldurma gerekmiyor.")
        return True

    # Haberleri çek
    news_list = get_news_for_date(target_date)
    if not news_list:
        logging.warning(f"{target_date} tarihli haber bulunamadı. Analiz oluşturulamıyor.")
        return False

    news_payload = "\n".join(news_list)
    logging.info(f"{target_date} için {len(news_list)} haber bulundu. Eksik bileşenler: TR={missing_tr}, EN={missing_en}")

    tr_pack = {}
    en_pack = {}

    # Eksik Türkçe bileşenleri oluştur
    tr_task_map = {
        "ozet_tr": "ozet",
        "yorum_tr": "yorum",
        "yaratici_fikirler_tr": "fikirler"
    }

    for field in missing_tr:
        task_type = tr_task_map[field]
        logging.info(f"  → {target_date} için Türkçe '{task_type}' üretiliyor...")
        content = generate_premium_content(api_key, news_payload, task_type)
        if content:
            tr_pack[task_type] = content
            logging.info(f"  ✓ {target_date} Türkçe '{task_type}' başarıyla üretildi.")
        else:
            logging.warning(f"  ✗ {target_date} Türkçe '{task_type}' üretilemedi.")
        time.sleep(30)

    # Eksik İngilizce bileşenleri oluştur (TR karşılığı varsa)
    en_task_map = {
        "ozet_en": ("ozet_tr", "ozet", "Summary"),
        "yorum_en": ("yorum_tr", "yorum", "Commentary"),
        "yaratici_fikirler_en": ("yaratici_fikirler_tr", "fikirler", "Creative Ideas List")
    }

    for field in missing_en:
        tr_field, tr_key, en_task_type = en_task_map[field]
        # Önce mevcut TR içeriğini bul (ya yeni üretilen ya da JSON'dan gelen)
        tr_content = tr_pack.get(tr_key)
        if not tr_content:
            data = load_analysis_data()
            tr_content = data.get(target_date, {}).get(tr_field)
        
        if tr_content:
            logging.info(f"  → {target_date} için İngilizce '{en_task_type}' çevriliyor...")
            en_content = translate_content_to_english(api_key, tr_content, en_task_type)
            if en_content:
                # Fikirler her zaman array formatında olmalı
                if tr_key == "fikirler":
                    en_content = _ensure_fikirler_as_list(en_content)
                    en_content = _validate_fikirler_list(en_content)
                # tr_key ile aynı anahtarı kullan (save_daily_analysis uyumu için)
                en_pack[tr_key] = en_content
                logging.info(f"  ✓ {target_date} İngilizce '{en_task_type}' başarıyla çevrildi.")
            else:
                logging.warning(f"  ✗ {target_date} İngilizce '{en_task_type}' çevrilemedi.")
            time.sleep(30)
        else:
            logging.warning(f"  ✗ {target_date} için '{tr_field}' içeriği bulunamadığından İngilizce çeviri atlandı.")

    # Kaydet (mevcut verilerle merge edilir)
    if tr_pack or en_pack:
        save_daily_analysis(tr_pack, en_pack, target_date)
        logging.info(f"{target_date} analiz güncelleme tamamlandı.")
        return True
    else:
        logging.warning(f"{target_date} için hiçbir bileşen üretilemedi.")
        return False


def fix_existing_analysis_data():
    """
    Mevcut analiz JSON'undaki bozuk fikirler alanlarını onarır.
    String olarak kaydedilmiş array'leri düzeltir, placeholder content'leri temizler.
    """
    path = get_analysis_file_path()
    if not os.path.exists(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logging.error(f"Analiz JSON okunamadı: {e}")
        return

    changed = False
    for date_key, entry in data.items():
        for field in ["yaratici_fikirler_tr", "yaratici_fikirler_en"]:
            val = entry.get(field)
            if val is None:
                continue
            if isinstance(val, list):
                validated = _validate_fikirler_list(val)
                if validated != val:
                    entry[field] = validated
                    changed = True
                    logging.info(f"  Onarıldı ({date_key}.{field}): {len(val)} -> {len(validated)} fikir")
            elif isinstance(val, str):
                converted = _ensure_fikirler_as_list(val)
                validated = _validate_fikirler_list(converted)
                entry[field] = validated
                changed = True
                logging.info(f"  Onarıldı ({date_key}.{field}): string -> {len(validated)} fikir listesi")

    if changed:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            logging.info("Mevcut analiz verileri onarıldı ve kaydedildi.")
        except Exception as e:
            logging.error(f"Onarılmış analiz JSON yazılamadı: {e}")


def fill_all_missing_analyses(api_key):
    """
    Haberler JSON'undaki tarihleri tarar, analiz JSON'unda eksik olan
    tarihlerin TR ve EN içeriklerini sırasıyla üretir.
    Sadece 2026-06-12 sonrasında olan tarihleri işler.
    """
    from datetime import datetime

    MIN_DATE = "2026-06-13"

    haberler_path = "C:/mustafabuilds/TrHaberPlatformu/data/haberler.json"
    if not os.path.exists(haberler_path):
        logging.info("Haberler dosyası bulunamadı, analiz üretimi atlanıyor.")
        return

    try:
        with open(haberler_path, "r", encoding="utf-8") as f:
            tum_haberler = json.load(f)
    except Exception as e:
        logging.error(f"Haberler dosyası okunamadı: {e}")
        return

    # Haberlerden benzersiz tarihleri topla
    tarih_set = set()
    for h in tum_haberler:
        tarih = h.get("tarih", "")
        if tarih:
            tarih_set.add(tarih[:10])  # YYYY-MM-DD

    if not tarih_set:
        logging.info("Haberlerde tarih bilgisi bulunamadı.")
        return

    # Tarihleri kronolojik sıraya koy, sadece MIN_DATE sonrasını al
    sirali_tarihler = sorted(t for t in tarih_set if t >= MIN_DATE)

    if not sirali_tarihler:
        logging.info(f"{MIN_DATE} sonrasında haber bulunamadı.")
        return

    logging.info(f"Toplam {len(sirali_tarihler)} tarih taranacak ({MIN_DATE} sonrası). Eksik analizler kontrol ediliyor...")

    eksik_tarihler = []
    for tarih in sirali_tarihler:
        status = get_analysis_status(tarih)
        eksik = [k for k, v in status.items() if not v]
        if eksik:
            eksik_tarihler.append((tarih, eksik))

    if not eksik_tarihler:
        logging.info("Tüm tarihlerin analizleri tam. Doldurma gerekmiyor.")
        return

    logging.info(f"{len(eksik_tarihler)} tarihte eksik analiz bulundu:")
    for tarih, eksik in eksik_tarihler:
        logging.info(f"  {tarih}: {eksik}")

    # Eskiden yeniye sırayla doldur
    for tarih, eksik in eksik_tarihler:
        logging.info(f"\n{'='*50}")
        logging.info(f"{tarih} tarihli eksik analiz dolduruluyor...")
        logging.info(f"  Eksik alanlar: {eksik}")
        try:
            fill_missing_analysis(api_key, tarih)
            # Her tarih arasında bekle (API kotası için)
            time.sleep(30)
        except Exception as e:
            logging.error(f"{tarih} analiz doldurma hatası: {e}")
            continue

    logging.info(f"\nTüm eksik analiz doldurma işlemleri tamamlandı.")


def ensure_previous_day_analysis(api_key):
    """
    Program başladığında bir önceki günün analizinin eksik parçalarını doldurur.
    fill_all_missing_analyses tarafından desteklenir, geriye dönük uyumluluk sağlar.
    """
    from datetime import datetime, timedelta
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    logging.info(f"Önceki gün ({yesterday}) analiz durumu kontrol ediliyor...")
    status = get_analysis_status(yesterday)

    missing_fields = [k for k, v in status.items() if not v]
    if not missing_fields:
        logging.info(f"{yesterday} tarihli analiz zaten tam. Doldurma gerekmiyor.")
        return

    logging.info(f"{yesterday} tarihli analizde eksik alanlar: {missing_fields}")
    fill_missing_analysis(api_key, yesterday)


def generate_premium_content(api_key, news_payload, task_type):
    """
    LLM'in dil ve yaratıcılık kabiliyetini tek bir odağa yönlendirerek 
    maksimum kalitede içerik üretmesini sağlar.
    """
    genai.configure(api_key=api_key)
    # En yüksek yaratıcılık ve akıcılık için sıcaklık (temperature) ayarı yapıyoruz
    generation_config = {"temperature": 0.85, "top_p": 0.95}
    model = genai.GenerativeModel('gemma-4-26b-a4b-it', generation_config=generation_config)
    
    prompts = {
        "ozet": f"""Sen deneyimli bir haber başeditörüsün. Aşağıdaki haberleri (Teknoloji, Kripto, Finans, Oyun, Bilim) oku ve Türkçe GÜNÜN ÖZETİNİ yaz.

KURALLAR:
- En az 5 paragraf yaz, her paragraf farklı bir sektörü veya konuyu ele alsın
- Her paragraf 3-4 cümle uzunluğunda olsun, sığ kalmasın
- Haberleri birbirine bağlayarak bütüncül bir günlük analiz oluştur
- Somut veriler, rakamlar, tarihler kullan
- "Bugün şunlar oldu" değil, "şu gelişmeler yaşanıyor" tarzında analitik yaz
- Paragraflar arasında \\n\\n ile boş satır bırak
- Markdown kullanma, sade düz metin yaz
- SADECE JSON dön, başka hiçbir metin ekleme

Haberler:
{news_payload}

{{"output": "Birinci paragraf...\\n\\nİkinci paragraf...\\n\\nÜçüncü paragraf...\\n\\nDördüncü paragraf...\\n\\nBeşinci paragraf..."}}""",

        "yorum": f"""Sen saygın bir teknoloji ve ekonomi köşe yazarısın. Aşağıdaki haberleri analiz et ve Türkçe GÜNÜN YORUMUNU yaz.

KURALLAR:
- En az 5 paragraf derinlikli analiz yaz
- Her paragraf farklı bir perspektiften baksın: teknolojik, ekonomik, toplumsal, stratejik, gelecek projeksiyonu
- Haberlerin arkasındaki NEDENleri ve SONUÇLARI açıkla
- Seyirciyi düşünmeye sevk eden sorular sor
- Vizyoner, entelektüel ama anlaşılır dil kullan
- Kişisel görüş ve analizlerini cesurca belirt
- Paragraflar arasında \\n\\n ile boş satır bırak
- SADECE JSON dön, başka hiçbir metin ekleme

Haberler:
{news_payload}

{{"output": "Birinci paragraf analiz...\\n\\nİkinci paragraf analiz...\\n\\nÜçüncü paragraf analiz...\\n\\nDördüncü paragraf analiz...\\n\\nBeşinci paragraf analiz..."}}""",

        "fikirler": f"""Sen çok deneyimli bir girişimci, teknoloji visioner'ı ve endüstri analistisin. Aşağıdaki haberlerden yola çıkarak 7-10 adet DERİN VE YARATICI iş/iş modeli fikri üret.

KESINLIKLE YASAK OLANLAR (bu fikirleri üretme):
- Şifresiz/ücretsiz maç izleme, IPTV, korsan yayın
- VPN ile içerik engeli kaldırma
- Basit bir uygulama yapma fikirleri (todo, not defteri vb.)
- Klon uygulamalar (Netflix klonu, Spotify klonu vb.)
- Kripto para alım-satım botu
- ChatGPT klonu veya basit AI wrapper

İSTEDİĞİM ÖZELLİKLER:
- Her fikir, haberlerdeki bir teknolojik gelişmeden yola çıkarak SOMUT bir iş modeli önermeli
- Fikirler: B2B SaaS, altyapı, veri analitiği, otonom sistemler, biyoteknoloji, uzay, enerji, malzeme bilimi gibi DERİN alanlarda olmalı
- Her fikir için: İngilizce kısa isim + 3-4 cümlelik Türkçe detaylı açıklama (neden gerekli, hangi sorunu çözüyor, potansiyel pazar boyutu)
- Fikirler birbirinden tamamen farklı sektörlerden olsun
- "Neden bunu daha önce kimse yapmadı?" dedirten orijinal fikirler olsun
- Her fikir en az 3 cümle uzunluğunda olsun

Format: "**[İsim]:** Detaylı 3-4 cümlelik açıklama..."

Haberler:
{news_payload}

{{"output": ["**[İsim]:** Detaylı açıklama...", "**[İsim]:** Detaylı açıklama...", "**[İsim]:** Detaylı açıklama...", "**[İsim]:** Detaylı açıklama...", "**[İsim]:** Detaylı açıklama...", "**[İsim]:** Detaylı açıklama...", "**[İsim]:** Detaylı açıklama..."]}}"""
    }
    
    for attempt in range(3):
        try:
            response = model.generate_content(prompts[task_type])
            text = response.text
            
            result = extract_json_from_llm(text, expected_keys=["output"])
            if result:
                output = result.get("output")
                # Fikirler için doğrulama: placeholder ve boş entry'leri temizle
                if task_type == "fikirler" and isinstance(output, list):
                    output = _validate_fikirler_list(output)
                    if not output:
                        logging.warning(f"Premium fikirler: Doğrulama sonrası tüm fikirler filtrelendi, yeniden üretiliyor...")
                        if attempt < 2:
                            time.sleep(15 * (attempt + 1))
                            continue
                        return None
                return output
            
            if attempt < 2:
                logging.warning(f"Premium {task_type}: JSON parse başarısız (deneme {attempt + 1}/3), yeniden deneniyor...")
                time.sleep(15 * (attempt + 1))
                continue
            
            logging.error(f"Premium {task_type}: 3 deneme sonunda JSON parse başarısız. Ham çıktı: {text[:500]}")
            return None
            
        except Exception as e:
            logging.error(f"Premium {task_type} üretilirken hata (deneme {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(15 * (attempt + 1))
    return None
def _validate_fikirler_list(fikirler_list):
    """
    Fikirler listesini doğrular: boş/sadece başlık olan entry'leri temizler,
    string olarak gelmiş listeyi parse eder.
    """
    if not fikirler_list:
        return fikirler_list

    # Eğer string geldiyse, array'e çevirmeyi dene
    if isinstance(fikirler_list, str):
        # Stringified JSON array kontrolü: '["..."]' formatı
        if fikirler_list.startswith('[') and fikirler_list.endswith(']'):
            try:
                parsed = json.loads(fikirler_list)
                if isinstance(parsed, list):
                    fikirler_list = parsed
            except json.JSONDecodeError:
                pass

        # Hala string ise, _ensure_fikirler_as_list kullanarak böl
        if isinstance(fikirler_list, str):
            fikirler_list = _ensure_fikirler_as_list(fikirler_list)

    if not isinstance(fikirler_list, list):
        return fikirler_list

    validated = []
    for item in fikirler_list:
        if not isinstance(item, str):
            validated.append(item)
            continue
        item = item.strip()
        if not item:
            continue
        # Boş placeholder kontrolü: "Idea 1...", "Fikir 1...", sadece başlık
        lower = item.lower().strip('*').strip()
        if re.match(r'^(idea|fikir|fikirler|ideas?)\s*\d*\s*[:.]*\s*$', lower):
            continue
        # İçerikte ":" varsa ve ":" dan sonra en az 20 karakter varsa kabul et
        if ':' in item:
            after_colon = item.split(':', 1)[1].strip()
            # Boş veya çok kısa content varsa atla (sadece **[Name]** formatı)
            if len(after_colon) < 10:
                continue
        # "..." veya "..." ile biten çok kısa entry'leri atla
        stripped_dots = item.rstrip('.').strip()
        if len(stripped_dots) < 20:
            continue
        validated.append(item)

    return validated if validated else fikirler_list


def _ensure_fikirler_as_list(value):
    """
    Bir değerin fikirler listesi olarak uygun formatta olmasını sağlar.
    String ise array'e çevirir, stringified JSON array ise parse eder.
    """
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        return value

    # Stringified JSON array
    if value.startswith('[') and value.endswith(']'):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    # Farklı formatları dene: newline ile, **[ ile, **Name ile ayrılmış fikirleri böl
    patterns = [
        r'\n\s*(?=\*\*)',                              # \n** pattern
        r'(?<=\])\s*\*\*(?=\[)',                       # ] **[ pattern (kapalı parantez sonrası)
        r'(?<=[a-zA-Z.!])\s+(?=\*\*\[)',               # text **[ pattern
        r'(?<=[a-zA-Z.!])\s+(?=\*\*[A-Z])',            # text **Name pattern
    ]
    for pattern in patterns:
        parts = re.split(pattern, value)
        parts = [p.strip() for p in parts if p.strip()]
        # Her parçanın ** ile başladığından ve yeterince uzun olduğundan emin ol
        valid_parts = [p for p in parts if p.startswith('**') and len(p) > 20]
        if len(valid_parts) > 1:
            return valid_parts

    # Tek fikir olarak döndür
    return [value] if value.strip() else []


def translate_content_to_english(api_key, text_or_list, task_type):
    """
    LLM'in dil kabiliyetini kullanarak üretilen premium Türkçe içeriği 
    profesyonel, akıcı ve doğal bir İngilizceye (Localization) çevirir.
    Liste (fikirler) geldiğinde array olarak çevirir.
    """
    genai.configure(api_key=api_key)
    generation_config = {"temperature": 0.3, "top_p": 0.95} # Çeviride sadık kalması için temperature'ı düşük tutuyoruz
    model = genai.GenerativeModel('gemma-4-26b-a4b-it', generation_config=generation_config)
    
    is_list = isinstance(text_or_list, list)
    content_to_translate = json.dumps(text_or_list, ensure_ascii=False) if is_list else text_or_list

    if is_list:
        prompt = f"""Sen profesyonel bir çevirmensin. Aşağıdaki Türkçe metin listesini İngilizceye çevir.

Çeviri türü: {task_type}
Çevrilecek metin listesi:
{content_to_translate}

KURALLAR:
- Her maddeyi (fikri) ayrı ayrı çevir
- Doğal ve akıcı İngilizce yaz
- Her çeviriyi array içinde ayrı bir string olarak döndür
- Orijinal sayısında aynı sayıda madde döndür
- SADECE JSON dön, başka metin ekleme

{{"translated_output": ["Translated item 1...", "Translated item 2...", "Translated item 3..."]}}"""
    else:
        prompt = f"""Sen profesyonel bir çevirmensin. Aşağıdaki Türkçe metni İngilizceye çevir.

Çeviri türü: {task_type}
Çevrilecek metin:
{content_to_translate}

KURALLAR:
- Doğal ve akıcı İngilizce yaz
- SADECE JSON dön, başka metin ekleme

{{"translated_output": "translated text here..."}}"""
    
    for attempt in range(3):
        try:
            response = model.generate_content(prompt)
            text = response.text
            
            result = extract_json_from_llm(text, expected_keys=["translated_output"])
            if result:
                output = result.get("translated_output")
                # Liste bekleniyorsa ve string döndüyse, parse et
                if is_list and isinstance(output, str):
                    output = _ensure_fikirler_as_list(output)
                # Liste bekleniyorsa doğrula
                if is_list and isinstance(output, list):
                    output = _validate_fikirler_list(output)
                return output
            
            if attempt < 2:
                logging.warning(f"İngilizce çeviri ({task_type}): JSON parse başarısız (deneme {attempt + 1}/3), yeniden deneniyor...")
                time.sleep(15 * (attempt + 1))
                continue
            
            logging.error(f"İngilizce çeviri ({task_type}): 3 deneme sonunda JSON parse başarısız. Ham çıktı: {text[:500]}")
            return None
            
        except Exception as e:
            logging.error(f"İngilizce çeviri hatası ({task_type}, deneme {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(15 * (attempt + 1))
    return None

def translate_news_to_english(api_key, tr_title, tr_summary, tr_content):
    """Türkçe haberi Gemini ile İngilizce'ye çevirir."""
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

            result = translate_extract_json(text)
            if result and result.get("baslik_en") and result.get("icerik_en"):
                return result

            logging.warning(f"İngilizce çeviri JSON parse başarısız (deneme {attempt + 1}/3)")
            if attempt < 2:
                time.sleep(10 * (attempt + 1))
        except Exception as e:
            logging.error(f"İngilizce çeviri hatası (deneme {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(10 * (attempt + 1))
    return None


def translate_extract_json(raw_text):
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
                    fixed = re.sub(r',\s*([}\]])', r'\1', candidate)
                    result = json.loads(fixed)
                    if isinstance(result, dict):
                        return result
                except:
                    pass
    return None


def main():
    # Target categories from TrHaber
    site_categories = load_site_categories()
    
    logging.info("Scraper döngüsü başlatıldı.")
    
    # PROGRAM BAŞLANGICINDA: Mevcut analiz verilerindeki bozuklukları onar
    try:
        fix_existing_analysis_data()
    except Exception as e:
        logging.error(f"Mevcut analiz verisi onarma hatası: {e}")

    # PROGRAM BAŞLANGICINDA: Tüm eksik analizleri (geçmiş dahil) doldur
    try:
        config_init = load_config()
        fill_all_missing_analyses(config_init['gemini_api_key'])
    except Exception as e:
        logging.error(f"Eksik analiz doldurma hatası: {e}")
    
    # PROGRAM BASLANGICINDA: PDF Scraper'ı calistir
    try:
        answer = input("PDF Scraper (Decrypt+InsiderMonkey) calistirilsin mi? (y/n): ").strip().lower()
        if answer == 'y' or answer == 'yes':
            logging.info("PDF Scraper baslatiliyor...")
            pdf_scraper = r"C:\mustafabuilds\PDF Creator\scraper.py"
            result = subprocess.run(
                ["python", pdf_scraper],
                timeout=900,
                cwd=r"C:\mustafabuilds\PDF Creator"
            )
            if result.returncode == 0:
                logging.info("PDF Scraper basariyla tamamlandi.")
            else:
                logging.warning(f"PDF Scraper hata ile dondu (kod: {result.returncode})")
    except Exception as e:
        logging.warning(f"PDF Scraper prompt/calistirma hatasi: {e} (konsol olmayabilir, normal devam)")

    while(True):
        try:
            sleep_until_after_first_quarter()

            # LLM Takip scraper'ını çalıştır (bitmesini bekle)
            llmtakip_script = "C:/mustafabuilds/llmTakip/scraper/scraper.py"
            logging.info("LLM Takip scraper başlatılıyor...")
            try:
                result = subprocess.run(
                    ["python", llmtakip_script],
                    timeout=600,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace"
                )
                if result.returncode == 0:
                    logging.info("LLM Takip scraper başarıyla tamamlandı.")
                else:
                    logging.warning(f"LLM Takip scraper hata ile döndü (kod: {result.returncode}): {result.stderr[:500]}")
            except subprocess.TimeoutExpired:
                logging.error("LLM Takip scraper 600 saniye timeout'a uğradı, durduruldu.")
            except Exception as e:
                logging.error(f"LLM Takip scraper çalıştırma hatası: {e}")

            config = load_config()
            logging.info("Yeni tarama döngüsü başlıyor...")
            
            for url in config['scrape_urls']:
                logging.info(f"Scraping {url}")
                articles = []
                url = (url or "").strip().replace("`", "").strip()
                if not re.match(r'^https?://', url):
                    logging.info(f"Geçersiz URL atlandı: {url}")
                    continue
                url_lower = url.lower()
                source_name = "Haber Merkezi"
                source_logo = "https://cdn-icons-png.flaticon.com/512/2991/2991148.png" # Default
                
                if "nytimes.com" in url_lower: 
                    source_name = "The New York Times"
                    source_logo = "https://www.nytimes.com/favicon.ico"
                elif "theverge.com" in url_lower: 
                    source_name = "The Verge"
                    source_logo = "https://www.theverge.com/favicon.ico"
                elif "techcrunch.com" in url_lower: 
                    source_name = "TechCrunch"
                    source_logo = "https://techcrunch.com/wp-content/uploads/2015/02/tc-logo-200x200.png"
                elif "wired.com" in url_lower: 
                    source_name = "Wired"
                    source_logo = "https://www.wired.com/favicon.ico"
                elif "gizmodo.com" in url_lower: 
                    source_name = "Gizmodo"
                    source_logo = "https://gizmodo.com/favicon.ico"
                elif "arstechnica.com" in url_lower: 
                    source_name = "Ars Technica"
                    source_logo = "https://arstechnica.com/favicon.ico"
                elif "pcgamer.com" in url_lower: 
                    source_name = "PC Gamer"
                    source_logo = "https://www.pcgamer.com/favicon.ico"
                elif "gamespot.com" in url_lower: 
                    source_name = "GameSpot"
                    source_logo = "https://www.gamespot.com/favicon.ico"
                elif "cnet.com" in url_lower: 
                    source_name = "CNET"
                    source_logo = "https://www.cnet.com/favicon.ico"
                elif "sciencedaily.com" in url_lower:
                    source_name = "ScienceDaily"
                    source_logo = "https://www.sciencedaily.com/favicon.ico"
                elif "livemint.com" in url_lower:
                    source_name = "Livemint"
                    source_logo = "https://www.livemint.com/favicon.ico"
                
                try:
                    if "nytimes.com" in url: articles = scrape_nytimes_articles(url)
                    elif "theverge.com" in url: articles = scrape_theverge_articles(url)
                    elif "sciencedaily.com" in url: articles = scrape_sciencedaily_articles(url)
                    elif "livemint.com" in url: articles = scrape_livemint_articles(url)
                    elif "pcgamer.com" in url: articles = scrape_pcgamer_articles(url)
                    elif "gamespot.com" in url: articles = scrape_gamespot_feed(url)
                    elif "gizmodo.com" in url: articles = scrape_gizmodo_articles(url)
                    elif "arstechnica.com" in url: articles = scrape_arstechnica_articles(url)
                    elif "techcrunch.com" in url: articles = scrape_techcrunch_articles(url)
                    elif "wired.com" in url: articles = scrape_wired_articles(url)
                    elif "cnet.com" in url: articles = scrape_cnet_articles(url)
                except Exception as e:
                    logging.error(f"Scrape error for {url}: {e}")
                    continue

                logging.info(f"Found {len(articles)} items. Processing titles...")
                
                for item in articles:
                    # PRE-CHECK: Duplicate URL check before processing anywhere
                    if check_if_exists(item['url']):
                        logging.info(f"Atlanıyor (Zaten var): {item['title'][:50]}")
                        continue
                    
                    if not ("gamespot.com" in item['url']):
                        
                        if ("nytimes.com" in item['url']):
                            img = item.get('image_url')
                            full_text = item.get('content') or item['title']
                        else:
                            img, full_text = get_article_full_content(item['url'])
                            if not full_text:
                                full_text = item.get('content') or item['title']
                                logging.info(f"Tam içerik alınamadı, kısa özet kullanılıyor: {item['url']}")
                    else:
                        full_text = item.get('content')
                        img = item.get('image_url')
                        
                    # Clean the content before sending to Gemini
                    full_text = fix_encoding(full_text)
                    item['title'] = fix_encoding(item['title'])
                    
                    final_img = img if img else item.get('image_url')

                    # GenAI Rewrite
                    logging.info(f"Yapay zeka ile yeniden yazılıyor: {item['url']}{item['title'][:50]}...")
                    
                    result = rewrite_with_gemini(config['gemini_api_key'], item['title'], full_text, site_categories)
                    
                    if result and isinstance(result, dict):
                        baslik = result.get('baslik')
                        icerik_out = result.get('icerik')
                        if not baslik or not icerik_out:
                            logging.info("Eksik alan (baslik/icerik) nedeniyle haber atlandı.")
                            continue
                        kisa_baslik = result.get('kisa_baslik') or baslik
                        ozet = result.get('ozet') or "boş"
                        kategori_out = normalize_category(result.get('kategori') or "Gündem", site_categories)
                        logging.info(f"Başarıyla Türkçe'ye çevrildi/yazıldı: {baslik[:50]}...")
                        news_item = {
                            "baslik": fix_encoding(baslik),
                            "kisa_baslik": fix_encoding(kisa_baslik),
                            "ozet": fix_encoding(ozet),
                            "icerik": fix_encoding(icerik_out),
                            "resim_url": final_img,
                            "kategori": kategori_out,
                            "kaynak": {
                                "isim": source_name,
                                "logo": source_logo,
                                "link": item['url']
                            },
                            "adult_only": False,
                            "tarih": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "goruntulenme": 0,
                            "begeni_sayisi": 0
                        }

                        # İngilizce çeviri
                        en_result = translate_news_to_english(config['gemini_api_key'], baslik, ozet, icerik_out)
                        if en_result:
                            news_item["baslik_en"] = fix_encoding(en_result.get("baslik_en", baslik))
                            news_item["ozet_en"] = fix_encoding(en_result.get("ozet_en", ozet))
                            news_item["icerik_en"] = fix_encoding(en_result.get("icerik_en", icerik_out))
                            logging.info(f"İngilizce çeviri tamam: {news_item['baslik_en'][:50]}...")
                        else:
                            logging.warning(f"İngilizce çeviri başarısız, sadece Türkçe kaydediliyor: {baslik[:50]}")
                            news_item["baslik_en"] = fix_encoding(baslik)
                            news_item["ozet_en"] = fix_encoding(ozet)
                            news_item["icerik_en"] = fix_encoding(icerik_out)

                        save_to_json(news_item)
                        
                        # Kotayı korumak için 15 saniye bekle
                        logging.info("Kotayı korumak için 15 saniye bekleniyor...")
                        time.sleep(15)
                    else:
                        logging.warning(f"Gemini haberi işleyemedi: {item['title'][:50]}")

            logging.info("Tüm siteler tarandı.")
            
            # GÜNLÜK ANALİZ: Bugün ve dünün eksik parçalarını doldur
            today_str = time.strftime("%Y-%m-%d")
            from datetime import datetime, timedelta
            yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            
            # Bugün tamamlandı mı kontrol et
            if not check_daily_analysis_exists(today_str):
                logging.info(f"Bugünün ({today_str}) analizi eksik. Dolduruluyor...")
                fill_missing_analysis(config['gemini_api_key'], today_str)
            else:
                logging.info(f"Bugünün ({today_str}) analizi zaten tam.")
            
            # Dünün de tamamlandığından emin ol (gecikmeli veri olabilir)
            if not check_daily_analysis_exists(yesterday_str):
                logging.info(f"Dünün ({yesterday_str}) analizi eksik. Dolduruluyor...")
                fill_missing_analysis(config['gemini_api_key'], yesterday_str)
            else:
                logging.info(f"Dünün ({yesterday_str}) analizi zaten tam.")

            # GÜNLÜK PDF SCRAPER: Her saat çalıştır
            logging.info("PDF scraper başlatılıyor...")
            try:
                pdf_scraper = "C:/mustafabuilds/PDF Creator/scraper.py"
                result = subprocess.run(
                    ["python", pdf_scraper],
                    timeout=900,
                    cwd="C:/mustafabuilds/PDF Creator"
                )
                if result.returncode == 0:
                    logging.info("PDF scraper başarıyla tamamlandı.")
                else:
                    logging.warning(f"PDF scraper hata ile döndü (kod: {result.returncode})")
            except subprocess.TimeoutExpired:
                logging.error("PDF scraper 900 sn timeout'a uğradı, durduruldu.")
            except Exception as e:
                logging.error(f"PDF scraper çalıştırma hatası: {e}")

            # GÜNLÜK PDF: Bugün üretilmediyse generate_pdf çalıştır
            today_pdf = f"BlokHaber_{time.strftime('%d-%m-%Y')}.pdf"
            pdf_path = os.path.join("C:/mustafabuilds/PDF Creator", today_pdf)
            if not os.path.exists(pdf_path):
                logging.info(f"Bugünkü PDF ({today_pdf}) henüz üretilmemiş. PDF oluşturuluyor...")
                try:
                    pdf_script = "C:/mustafabuilds/PDF Creator/generate_pdf.py"
                    result = subprocess.run(
                        ["python", pdf_script],
                        timeout=300,
                        cwd="C:/mustafabuilds/PDF Creator"
                    )
                    if result.returncode == 0:
                        logging.info(f"PDF başarıyla oluşturuldu: {today_pdf}")
                    else:
                        logging.warning(f"PDF oluşturma hatası (kod: {result.returncode})")
                except subprocess.TimeoutExpired:
                    logging.error("PDF oluşturma 300 sn timeout'a uğradı.")
                except Exception as e:
                    logging.error(f"PDF oluşturma çalıştırma hatası: {e}")
            else:
                logging.info(f"Bugünkü PDF zaten mevcut: {today_pdf}")
        # GÜNLÜK PDF: Bugün üretilmediyse generate_pdf çalıştır
            today_pdf_en = f"BlockNews_{time.strftime('%d-%m-%Y')}.pdf"
            pdf_path = os.path.join("C:/mustafabuilds/PDF Creator", today_pdf_en)
            if not os.path.exists(pdf_path):
                logging.info(f"Bugünkü PDF ({today_pdf_en}) henüz üretilmemiş. PDF oluşturuluyor...")
                try:
                    pdf_script = "C:/mustafabuilds/PDF Creator/generate_pdf_en.py"
                    result = subprocess.run(
                        ["python", pdf_script],
                        timeout=300,
                        cwd="C:/mustafabuilds/PDF Creator"
                    )
                    if result.returncode == 0:
                        logging.info(f"PDF başarıyla oluşturuldu: {today_pdf_en}")
                    else:
                        logging.warning(f"PDF oluşturma hatası (kod: {result.returncode})")
                except subprocess.TimeoutExpired:
                    logging.error("PDF oluşturma 300 sn timeout'a uğradı.")
                except Exception as e:
                    logging.error(f"PDF oluşturma çalıştırma hatası: {e}")
            else:
                logging.info(f"Bugünkü PDF zaten mevcut: {today_pdf_en}")
                    
        except Exception as e:
            logging.error(f"Kritik hata: {e}")
            time.sleep(60)
        time.sleep(6000)
def rewrite_and_translate(api_key, english_name, english_short, english_long):
    """
    scraper.py icin: Ingilizce haberi yeniden yazar ve Turkce'ye cevirir.
    return: {"name_en", "short_en", "long_en", "name_tr", "short_tr", "long_tr"}
    """
    prompt = f"""Sen bir haber editorusun. Asagidaki Ingilizce haberi al ve su iki adimi uygula:

1. REWRITE: Haberi tamamen kendi kelimelerinle yeniden yaz. Hiçbir cumleyi birebir kopyalama.
2. TRANSLATE: Yeniden yazdigin Ingilizce metni Turkce'ye cevir.

Input:
Title: {english_name}
Short: {english_short}
Long: {english_long}

SADECE JSON don, baska metin ekleme:
{{"name_en": "Rewritten English title", "short_en": "Rewritten English short", "long_en": "Rewritten English long", "name_tr": "Turkish title", "short_tr": "Turkish short", "long_tr": "Turkish long"}}"""

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemma-4-31b-it')

    for attempt in range(3):
        try:
            response = model.generate_content(prompt)
            text = response.text
            result = extract_json_from_llm(text, expected_keys=["name_en", "name_tr"])
            if result:
                return {
                    "name_en": result.get("name_en", english_name),
                    "short_en": result.get("short_en", english_short),
                    "long_en": result.get("long_en", english_long),
                    "name_tr": result.get("name_tr", ""),
                    "short_tr": result.get("short_tr", ""),
                    "long_tr": result.get("long_tr", ""),
                }
            if attempt < 2:
                time.sleep(10 * (attempt + 1))
        except Exception as e:
            msg = str(e)
            if "403" in msg and "unregistered callers" in msg:
                logging.error(f"rewrite_and_translate 403: {e}")
                time.sleep(600)
                continue
            logging.error(f"rewrite_and_translate hatasi (deneme {attempt+1}/3): {e}")
            if attempt < 2:
                time.sleep(10 * (attempt + 1))
    return None


if __name__ == "__main__":
    main()
