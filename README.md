# TechHaber (TrHaber) — AI Destekli Teknoloji Haber Platformu

> GitHub: https://github.com/MustfZTRK/techhaber | Canlı: https://tech.mustafabuilds.com

## TR Türkçe

Uluslararası kaynaklardan (GameSpot, TechCrunch, The Verge, Ars Technica, Livemint...) çekilen teknoloji/bilim haberlerini Gemini ile Türkçeye çevirip özgünleştiren, sosyal özellikli tam otomatik haber platformu. Express API (port 3008) + PHP görünüm + Python scraper hattı içerir.

### Özellikler
- Otomatik scraper hattı (`scraper/`): çekme → Gemini ile çeviri/özgünleştirme (gemma-3-27b-it) → çeviri → analiz
- Kullanıcı sistemi: kayıt/giriş, profil + avatar, takip, beğeni, yorum, bildirim, okuma geçmişi
- Piyasa verileri akışı (`GET /api/market-data`)
- Yönetim paneli (`public/admin.html`)
- RSS çıktıları: `rss.xml`, `googlerss.xml`, `google-news.xml`, `feed.xml` (+ `rss.js` üretici)
- Karanlık/aydınlık logo, SEO ve site haritaları

### Kurulum
```bash
npm install
npm start   # http://127.0.0.1:3008
```
Scraper için Python bağımlılıkları ve `scraper/scraper_config.json` içine kendi `gemini_api_key` değeriniz gerekir (repoda yalnızca `YOUR_GEMINI_API_KEY` şablonu vardır).

### API (özet)
- `GET /api/haberler`, `GET /api/haberler/:id`, `POST /api/haberler/:id/view`
- `GET /api/kategoriler`, `GET /api/market-data`
- `POST /api/register`, `POST /api/login`
- `GET|PUT /api/user/profile/:username`, `POST /api/user/avatar`, `POST /api/follow`, `POST /api/like`
- `GET|POST /api/comments`, `POST /api/notifications/clear`
- `GET|POST /api/admin/:type`, `POST /api/user/news`

> Not: Gerçek API anahtarları/şifreler repoya **dahil değildir**.

---

## EN English

Fully automatic tech news platform: pulls global tech/science news (GameSpot, TechCrunch, The Verge, Ars Technica, Livemint...), translates and rewrites them in Turkish with Gemini, and serves them with social features. Express API (port 3008) + PHP views + Python scraper pipeline.

### Features
- Automatic scraper pipeline (`scraper/`): fetch → Gemini translate/rewrite (gemma-3-27b-it) → translate → analyze
- User system: register/login, profiles + avatars, follow, like, comments, notifications, reading history
- Market data stream (`GET /api/market-data`)
- Admin panel (`public/admin.html`)
- RSS outputs: `rss.xml`, `googlerss.xml`, `google-news.xml`, `feed.xml` (built by `rss.js`)
- Dark/light logos, SEO and sitemaps

### Installation
```bash
npm install
npm start   # http://127.0.0.1:3008
```
The scraper needs Python dependencies and your own `gemini_api_key` in `scraper/scraper_config.json` (repo ships only the `YOUR_GEMINI_API_KEY` template).

### API (summary)
- `GET /api/haberler`, `GET /api/haberler/:id`, `POST /api/haberler/:id/view`
- `GET /api/kategoriler`, `GET /api/market-data`
- `POST /api/register`, `POST /api/login`
- `GET|PUT /api/user/profile/:username`, `POST /api/user/avatar`, `POST /api/follow`, `POST /api/like`
- `GET|POST /api/comments`, `POST /api/notifications/clear`
- `GET|POST /api/admin/:type`, `POST /api/user/news`

> Note: Real API keys/passwords are **not** included.

---

## Lisans / License

MIT — dilediğiniz gibi kullanın. / Use freely under MIT.
