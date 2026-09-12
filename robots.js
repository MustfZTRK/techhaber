const fs = require('fs');
const path = require('path');

function writePublicFile(filename, content) {
    const outPath = path.join(__dirname, 'public', filename);
    fs.writeFileSync(outPath, content, 'utf8');
    return outPath;
}

function generateRobots() {
    const baseUrl = process.env.SITE_BASE_URL || 'https://tech.mustafabuilds.com';
    const aiBots = [
        'GPTBot','ChatGPT-User','OAI-SearchBot','ClaudeBot','Claude-Web','Anthropic-AI',
        'PerplexityBot','Google-Extended','CCBot','Bytespider','FacebookBot','Meta-ExternalAgent',
        'Applebot-Extended','cohere-ai','Diffbot','YouBot','Ai2Bot-Dolma'
    ];
    const lines = [
        'User-agent: *',
        'Allow: /',
        'Disallow: /admin/',
        'Disallow: /login/',
        '',
        '# AI / LLM botlarina acik — engelleme kaldirildi',
        ...aiBots.flatMap(bot => [`User-agent: ${bot}`, 'Allow: /']),
        '',
        `Sitemap: ${baseUrl}/site_map.xml`
    ];
    const content = lines.join('\n') + '\n';
    writePublicFile('robots.txt', content);
    return true;
}

module.exports = { generateRobots };
