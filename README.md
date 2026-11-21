# Fullframe News

The whole picture of every story. Fullframe News is a free, independent news-comparison website. It groups reports from outlets across the political spectrum into one story, shows how the coverage tilts left, center or right, and has an AI write a neutral summary of each story with a side-by-side comparison of the framing.

- **Top Stories / Latest:** stories ranked by how many outlets cover them, each with a left/center/right coverage bar
- **Coverage Gaps:** stories one side of the spectrum is barely covering
- **Country tabs:** created automatically, one for every country that has 2 or more outlets in `sources.json`
- **Story pages:** a neutral headline and summary, how each side framed the story, contested claims, loaded language, and links to every report

**Read now at: https://klaas-vanlisht.github.io/fullframe/#/**

## Search engines (SEO)

The public page has a full title and description, structured data that names the site "Fullframe News", a social preview image, favicons, a sitemap (`sitemap.xml`) and the top headlines baked into the HTML so crawlers see real content.

To get it into Google quickly:
1. Open [Google Search Console](https://search.google.com/search-console), add a **URL prefix** property for `https://klaas-vanlisht.github.io/fullframe/`, and pick the **HTML tag** verification method.
2. Copy only the code inside `content="..."` into `publish.google_site_verification` in `config.json` and commit. Wait for the next site build, then press **Verify**.
3. Under **Sitemaps**, submit `sitemap.xml`. Under **URL inspection**, inspect the home page and click **Request indexing**.
4. Optional: do the same in [Bing Webmaster Tools](https://www.bing.com/webmasters) (`publish.bing_site_verification`); Bing also feeds DuckDuckGo and Yahoo.
