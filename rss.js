const fs = require('fs');
const path = require('path');

const BASE_URL = process.env.SITE_BASE_URL || 'https://tech.mustafabuilds.com';
const DATA_FILE = path.join(__dirname, 'data', 'haberler.json');
const PUBLIC_DIR = path.join(__dirname, 'public');

function readNews() {
  if (!fs.existsSync(DATA_FILE)) return [];
  try {
    const data = JSON.parse(fs.readFileSync(DATA_FILE, 'utf8'));
    return Array.isArray(data) ? data : [];
  } catch (_) { return []; }
}

function escapeCdata(str) {
  return String(str || '').replace(/]]>/g, ']]]]><![CDATA[>');
}

function toRfc2822(dateStr) {
  try { return new Date(dateStr).toUTCString(); } catch (_) { return new Date().toUTCString(); }
}

function slugify(s) {
  const map = { 'ş':'s','Ş':'s','ç':'c','Ç':'c','ö':'o','Ö':'o','ğ':'g','Ğ':'g','ü':'u','Ü':'u','ı':'i','İ':'i' };
  return String(s || '').split('').map(ch=>map[ch]||ch).join('')
    .toLowerCase().replace(/[^a-z0-9\s-]/g,'').trim().replace(/\s+/g,'-').replace(/-+/g,'-').substring(0,80);
}

function buildRssXml(news, opts = {}) {
  const title = opts.title || 'TechHaber — Teknoloji Haberleri';
  const description = opts.description || 'TechHaber: Yapay zeka, bilim, uzay, güvenlik ve teknoloji gündemi — son 100 haber.';
  const nowRfc = new Date().toUTCString();
  // lastBuildDate = en yeni haber tarihi veya now
  const lastBuildDate = news.length ? toRfc2822(news[0].tarih || nowRfc) : nowRfc;

  const channelLink = BASE_URL + '/';
  const selfLink = BASE_URL + '/rss.xml';

  const items = news.map(n => {
    const id = typeof n.id === 'number' ? n.id : parseInt(String(n.id||'').match(/^\d+/)?.[0]||'0');
    const slug = slugify(n.kisa_baslik || n.baslik || '');
    const link = `${BASE_URL}/?haber=${encodeURIComponent(id)}${slug ? `&name=${encodeURIComponent(slug)}` : ''}`;
    const guid = `${BASE_URL}/?haber=${id}`;
    const pubDate = toRfc2822(n.tarih);
    const img = n.resim_url ? String(n.resim_url).trim() : '';
    const category = n.kategori || 'Teknoloji';
    const sourceName = (n.kaynak && n.kaynak.isim) ? n.kaynak.isim : 'TechHaber';
    const sourceLink = (n.kaynak && n.kaynak.link) ? n.kaynak.link : link;
    // description: ozet + icerik'ten ilk 500 karakter fallback
    const rawDesc = n.ozet || (n.icerik ? String(n.icerik).replace(/<[^>]+>/g,'').substring(0,300) : '');
    const contentEncoded = n.icerik || n.icerik_en || rawDesc;

    // Google News için keywords: kategori + başlıktan kelimeler
    const keywords = [category, ...(String(n.baslik||'').split(/\s+/).slice(0,5))].join(', ');

    let item = `  <item>
    <title><![CDATA[${escapeCdata(n.baslik || '')}]]></title>
    <link>${link}</link>
    <guid isPermaLink="true">${guid}</guid>
    <pubDate>${pubDate}</pubDate>
    <description><![CDATA[${escapeCdata(rawDesc)}]]></description>
    <content:encoded><![CDATA[${escapeCdata(contentEncoded)}]]></content:encoded>
    <category><![CDATA[${escapeCdata(category)}]]></category>
    <dc:creator><![CDATA[${escapeCdata(sourceName)}]]></dc:creator>
    <source url="${selfLink}">TechHaber</source>
    <news:publication>
      <news:name>TechHaber</news:name>
      <news:language>tr</news:language>
    </news:publication>
    <news:keywords><![CDATA[${escapeCdata(keywords)}]]></news:keywords>`;
    if (img) {
      const type = img.endsWith('.png') ? 'image/png' : img.endsWith('.webp') ? 'image/webp' : 'image/jpeg';
      item += `\n    <enclosure url="${img.replace(/&/g,'&amp;')}" type="${type}" />`;
      item += `\n    <media:content url="${img.replace(/&/g,'&amp;')}" type="${type}" medium="image" />`;
      item += `\n    <media:thumbnail url="${img.replace(/&/g,'&amp;')}" />`;
    }
    item += `\n  </item>`;
    return item;
  }).join('\n');

  return `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
  xmlns:content="http://purl.org/rss/1.0/modules/content/"
  xmlns:dc="http://purl.org/dc/elements/1.1/"
  xmlns:atom="http://www.w3.org/2005/Atom"
  xmlns:media="http://search.yahoo.com/mrss/"
  xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
  <channel>
    <title><![CDATA[${escapeCdata(title)}]]></title>
    <link>${channelLink}</link>
    <description><![CDATA[${escapeCdata(description)}]]></description>
    <language>tr</language>
    <lastBuildDate>${lastBuildDate}</lastBuildDate>
    <ttl>720</ttl>
    <atom:link href="${selfLink}" rel="self" type="application/rss+xml" />
    <image>
      <url>${BASE_URL}/light-logo.png</url>
      <title><![CDATA[${escapeCdata(title)}]]></title>
      <link>${channelLink}</link>
    </image>
${items}
  </channel>
</rss>
`;
}

function generateRss() {
  let news = readNews();
  // en yeniye göre sırala, adult_only hariç, son 100
  news = news
    .filter(n => !n.adult_only)
    .sort((a,b) => new Date(b.tarih || 0) - new Date(a.tarih || 0))
    .slice(0, 100);

  const xml = buildRssXml(news);

  // Yaz: rss.xml + alias dosyalar (Google News uyumlu aynı içerik)
  const files = ['rss.xml', 'feed.xml', 'google-news.xml', 'googlerss.xml', 'rss', 'google-rss'];
  // fiziksel dosya olarak .xml olanları yaz, uzantısız olanlar da xml içerikle yaz (bazı okuyucular için)
  const toWrite = ['rss.xml', 'feed.xml', 'google-news.xml', 'googlerss.xml'];
  for (const f of toWrite) {
    const out = path.join(PUBLIC_DIR, f);
    fs.mkdirSync(path.dirname(out), { recursive: true });
    fs.writeFileSync(out, xml, 'utf8');
  }
  // alias dosyaları da aynı dizine kopyala (nginx/static için)
  // Express zaten alias route'larla serve edecek, dosyalar opsiyonel
  const sizeKB = (Buffer.byteLength(xml,'utf8')/1024).toFixed(1);
  console.log(`[rss] Yazıldı: ${toWrite.join(', ')} (${news.length} haber, ${sizeKB} KB) — ${BASE_URL}/rss.xml`);
  return { count: news.length, files: toWrite, sizeKB };
}

if (require.main === module) {
  generateRss();
}

module.exports = { generateRss, buildRssXml };
