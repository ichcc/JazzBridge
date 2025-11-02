# 🎷 GetMusic - All About Jazz to Album.link Automation

Automatically collect new jazz album mentions from All About Jazz RSS feed, find their corresponding albums on Album.link, and generate a consolidated list with universal music streaming links.

## Features

- 🎵 Fetches latest jazz album reviews from All About Jazz RSS
- 🔍 Searches and matches albums on Album.link
- 📝 Generates output in Markdown or CSV format
- 🎯 Clean, structured data with artist, album, link, and date
- 📊 Verbose mode for debugging and monitoring

## Installation

1. Clone the repository
2. Create a virtual environment and install dependencies:

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

Basic usage (outputs to `jazz_albums.md`):

```bash
python getmusic.py
```

### Options

```bash
python getmusic.py [OPTIONS]

Options:
  -o, --output FILE         Output file path (default: jazz_albums.md)
  -f, --format FORMAT       Output format: markdown or csv (default: markdown)
  -v, --verbose            Enable verbose logging
  -h, --help               Show help message
```

### Examples

Generate Markdown output with verbose logging:
```bash
python getmusic.py -v -o albums.md
```

Generate CSV output:
```bash
python getmusic.py -f csv -o albums.csv
```

## Output Formats

### Markdown
```markdown
## 🎶 New Jazz Albums

- [Martin Nodeland — Tributaries](https://album.link/i/1234567890) _(2025-11-01)_
- [Jane Doe — Midnight Smoke](https://album.link/i/0987654321) _(2025-10-31)_
```

### CSV
```csv
artist,album,album_link,date
Martin Nodeland,Tributaries,https://album.link/i/1234567890,2025-11-01
Jane Doe,Midnight Smoke,https://album.link/i/0987654321,2025-10-31
```

## How It Works

1. **Fetch RSS**: Parses `https://www.allaboutjazz.com/rss/` for new album mentions
2. **Extract & Clean**: Parses titles (format: "Artist: Album Title") and strips review-type suffixes
3. **Search Album.link**: Queries Album.link for each album and extracts the first matching result
4. **Output**: Generates formatted Markdown or CSV with artist, album, Album.link URL, and publication date

## Known Limitations

### 1. Cloudflare Protection on RSS Feed
The All About Jazz RSS feed may be protected by Cloudflare, which can block automated requests. If you encounter this issue:
- Run from a different IP address or network
- Use a VPN
- Run less frequently to avoid rate limiting
- Consider using RSS feed readers/aggregators that handle Cloudflare

### 2. Album.link JavaScript Rendering
Album.link uses client-side JavaScript rendering, which means the search results aren't available in the initial HTML response. The current implementation may not find results reliably.

**Recommended Solutions:**
- **Browser Automation**: Use Selenium or Playwright to render JavaScript
  ```bash
  pip install selenium
  # or
  pip install playwright
  ```
- **Alternative Approach**: Search Spotify API first, then use Song.link API:
  1. Search Spotify for the album
  2. Get the Spotify URL
  3. Use `https://api.song.link/v1-alpha.1/links?url={spotify_url}` to get Album.link URL
- **Different Service**: Consider using MusicBrainz or other music databases with public APIs

## Automation

You can automate this script using:

- **Cron Job**: Schedule daily runs
  ```bash
  # Run daily at 9 AM
  0 9 * * * cd /path/to/GetMusic && source venv/bin/activate && python getmusic.py
  ```

- **GitHub Actions**: Schedule workflow to run and commit results
- **AWS Lambda / Azure Function**: Serverless scheduling with notifications

## Dependencies

- `feedparser` - RSS feed parsing
- `requests` - HTTP requests
- `beautifulsoup4` - HTML parsing for Album.link search

## License

Open source - use freely for personal projects.
