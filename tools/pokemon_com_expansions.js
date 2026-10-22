// Fetch pokemon.com's expansion lists (en, de, it, es, fr) and each US expansion page's language links, from inside
// a browser tab on www.pokemon.com (the site refuses scripted clients; see pokemon_com_crawl.js).
//
// Each list entry has the expansion's name as printed on its packs, its logo and its release date. Black Bolt and
// White Flare share one logo folder and the lists order them differently, so languages are joined through each US
// page's hreflang links, not by position. Save the returned object as JSON and pass it to tools/import_sets.py.
async () => {
  const DELAY_MS = 1000;
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const out = { fetchedAt: new Date().toISOString(), alternates: {} };
  for (const locale of ["us", "de", "it", "es", "fr"]) {
    const response = await fetch(`/api/1/${locale}/expansions/get-expansions.json?index=0&count=500`);
    out[locale] = await response.json();
    await sleep(DELAY_MS);
  }
  for (const expansion of out.us) {
    const url = expansion.url.replace(/\/$/, "");
    const response = await fetch(url);
    const d = new DOMParser().parseFromString(await response.text(), "text/html");
    out.alternates[url] = {
      status: response.status,
      alts: Object.fromEntries([...d.querySelectorAll("link[hreflang]")]
        .filter((l) => ["de", "it", "es", "fr"].includes(l.hreflang))
        .map((l) => [l.hreflang, new URL(l.href).pathname.replace(/\/$/, "")])),
    };
    await sleep(DELAY_MS);
  }
  return out;
}
