# 🎷 All About Jazz → Album.link Automation

## 🧩 Goal
Automatically collect new jazz album mentions from **All About Jazz RSS**, find their corresponding albums on **Album.link**, and generate a neat list with universal music links.

---

## 🪄 Workflow Overview

### 1. Fetch RSS Feed
Use the main feed:
```
https://www.allaboutjazz.com/rss/
```

Each `<item>` contains:
```xml
<title>Martin Nodeland: Tributaries</title>
<link>https://www.allaboutjazz.com/martin-nodeland-tributaries-album-review</link>
<pubDate>Fri, 1 Nov 2025 13:00:00 +0000</pubDate>
```

### 2. Extract Relevant Info
For each RSS item:
- Extract `<title>`
- Remove trailing info like “album review”, “concert review”, etc.
- Example cleaned title:  
  **Martin Nodeland: Tributaries**

---

### 3. Search on Album.link
Use query syntax:
```
https://album.link/search?q=<artist+album>
```

Example:
```
https://album.link/search?q=Martin+Nodeland+Tributaries
```

From the HTML, grab the **first result link** that matches the artist and album (it usually looks like):
```
https://album.link/i/1234567890
```

This URL redirects automatically to Spotify/Apple/Tidal/YouTube etc.

---

### 4. Output Format
Generate Markdown or CSV list:

**Markdown Example**
```markdown
## 🎶 New Jazz Albums

- [Martin Nodeland — Tributaries](https://album.link/i/1234567890)
- [Jane Doe — Midnight Smoke](https://album.link/i/0987654321)
```

**CSV Example**
```
artist,album,album_link,date
Martin Nodeland,Tributaries,https://album.link/i/1234567890,2025-11-01
```

---

## ⚙️ Implementation (Python Example)

```python
import feedparser
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote

rss_url = "https://www.allaboutjazz.com/rss/"
feed = feedparser.parse(rss_url)

results = []

for entry in feed.entries:
    title = entry.title
    if ":" in title:
        artist, album = title.split(":", 1)
        query = quote(f"{artist.strip()} {album.strip()}")
        search_url = f"https://album.link/search?q={query}"

        r = requests.get(search_url)
        soup = BeautifulSoup(r.text, "html.parser")
        first_result = soup.select_one("a[href*='album.link/i/']")
        if first_result:
            album_link = first_result["href"]
            results.append((artist.strip(), album.strip(), album_link))

# Output as Markdown
with open("jazz_albums.md", "w") as f:
    f.write("## 🎶 New Jazz Albums\n\n")
    for artist, album, link in results:
        f.write(f"- [{artist} — {album}]({link})\n")
```

---

## 🕓 Optional: Automation
- **GitHub Actions:** run script daily and push Markdown to repo.
- **AWS Lambda / Azure Function:** run every 24h and send to Telegram or email.
- **Apple Shortcut:** fetch feed and open first few album links manually.

---

## 🚀 Possible Add-ons
- Filter by keywords: *album review*, *premiere*, etc.  
- Enrich with cover art using MusicBrainz or Spotify API.  
- Publish automatically to Telegram, Mastodon, or Notion.

---

## 🧭 Summary
| Step | Action | Tool |
|------|---------|------|
| 1 | Parse AllAboutJazz RSS | `feedparser` |
| 2 | Extract title & clean text | Python string ops |
| 3 | Search on Album.link | `requests + BeautifulSoup` |
| 4 | Save results | Markdown/CSV |
| 5 | Optional automation | GitHub Actions / Lambda |

---

🪶 **End Result:**  
A daily-updated jazz album digest linking each mention on *All About Jazz* directly to its streaming page on *Album.link* — perfect for playlist curators, radio hosts, or jazz lovers.
