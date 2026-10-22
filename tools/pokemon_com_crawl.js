// Crawl pokemon.com's product gallery in every language it links, from inside a browser tab on www.pokemon.com.
//
// pokemon.com sits behind an anti-bot wall that refuses scripted HTTP clients and headless browsers, so this runs
// in a real browser: open any www.pokemon.com page, then evaluate this file's function (DevTools console, or a
// browser automation tool). It reads the US gallery's year pages, every product page they list, and each page's
// de, it, es and fr versions (its hreflang links), one request per second. Save the returned object as JSON and
// pass it to tools/import_pokemon_com.py.
async () => {
  const DELAY_MS = 1000;
  const LANGUAGES = ["de", "it", "es", "fr"];
  const HEAD = /(includes|enthält|contiene|incluye|contient|comprend|beinhaltet|contains)[^:]*:\s*$/i;
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const norm = (s) => s.replace(/\s+/g, " ").trim();

  // Title, launch line, the bullet list under "... includes:", and the page's other-language versions.
  const parse = (html) => {
    const d = new DOMParser().parseFromString(html, "text/html");
    const h1 = d.querySelector("h1");
    const title = norm(h1 ? h1.textContent : d.title.split(" | ")[0]);
    let date = null;
    for (let e = h1 && h1.nextElementSibling, i = 0; e && i < 4; e = e.nextElementSibling, i++) {
      const t = norm(e.textContent);
      if (/:\s*\S/.test(t) && t.length < 80 && !HEAD.test(t)) { date = t; break; }
    }
    let header = null, items = [];
    const blocks = [...d.querySelectorAll("p, h2, h3, h4, strong, div")]
      .filter((e) => e.children.length <= 2 && HEAD.test(norm(e.textContent)) && norm(e.textContent).length < 250);
    for (const block of blocks) {
      const walker = d.createTreeWalker(d.body, NodeFilter.SHOW_ELEMENT);
      walker.currentNode = block;
      let list;
      while ((list = walker.nextNode())) if (list.tagName === "UL" || list.tagName === "OL") break;
      if (list) {
        header = norm(block.textContent);
        items = [...list.querySelectorAll(":scope > li")].map((li) => norm(li.textContent)).filter(Boolean);
        break;
      }
    }
    const alts = Object.fromEntries([...d.querySelectorAll("link[hreflang]")]
      .filter((l) => LANGUAGES.includes(l.hreflang)).map((l) => [l.hreflang, l.href]));
    return { title, date, header, items, alts };
  };

  const paths = new Set();
  for (let year = 2013; year <= new Date().getFullYear(); year++) {
    const response = await fetch(`/us/pokemon-tcg/product-gallery/${year}`);
    if (response.ok) {
      const d = new DOMParser().parseFromString(await response.text(), "text/html");
      for (const a of d.querySelectorAll("a[href]")) {
        const href = a.getAttribute("href").replace(/\/$/, "");
        if (/^\/us\/pokemon-tcg\/product-gallery\/[a-z0-9-]+$/.test(href) && !/\/\d{4}$/.test(href)) paths.add(href);
      }
    }
    await sleep(DELAY_MS);
  }

  const products = {};
  for (const path of paths) {
    const out = {};
    const response = await fetch(path);
    out.status = response.status;
    if (response.ok) {
      out.us = parse(await response.text());
      out.alt = {};
      for (const [language, url] of Object.entries(out.us.alts)) {
        await sleep(DELAY_MS);
        const alt = await fetch(url);
        const page = alt.ok ? parse(await alt.text()) : null;
        out.alt[language] = { url, status: alt.status, ...(page ? { title: page.title, date: page.date, header: page.header, items: page.items } : {}) };
      }
    }
    products[path] = out;
    await sleep(DELAY_MS);
  }
  return { crawledAt: new Date().toISOString(), products };
}
