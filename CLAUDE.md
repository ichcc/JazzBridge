# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**GetMusic** is an automation tool that collects new jazz album mentions from All About Jazz RSS feed, searches for them on Album.link, and generates a consolidated list with universal music streaming links.

See `allaboutjazz_albumlink.md` for the complete specification.

## Core Workflow

1. **Fetch RSS**: Parse `https://www.allaboutjazz.com/rss/` for new album mentions
2. **Extract & Clean**: Parse titles (format: "Artist: Album Title") and strip suffixes like "album review"
3. **Search Album.link**: Query `https://album.link/search?q=<artist+album>` and extract first matching result
4. **Output**: Generate Markdown or CSV with artist, album, and Album.link URL

## Project Structure (Expected)

When implementing, the structure should be:
- Main script for RSS parsing and Album.link search
- Output module for generating Markdown/CSV
- Optional: scheduler/automation configuration (GitHub Actions, Lambda, etc.)

## Implementation Notes

### Python Dependencies
The spec suggests using:
- `feedparser` - RSS feed parsing
- `requests` - HTTP requests
- `beautifulsoup4` - HTML parsing for Album.link search results
- `urllib.parse` - URL encoding

### Key Implementation Details

**Title Parsing**:
- Split on first `:` to separate artist from album
- Handle edge cases where title may not contain `:`
- Strip whitespace and remove review-type suffixes

**Album.link Search**:
- URL-encode query parameters
- Look for links matching pattern `album.link/i/[ID]`
- Select first result (usually most relevant)
- Handle cases where no results found

**Output Formats**:
- Markdown: `- [Artist — Album](https://album.link/i/ID)`
- CSV: `artist,album,album_link,date`

## Development Commands

### Setup
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Running the Script
```bash
# Basic usage (creates jazz_albums.md)
python getmusic.py

# With verbose output
python getmusic.py -v

# Specify output file and format
python getmusic.py -o albums.csv -f csv

# Run test with sample data
python test_sample.py
```

### Testing
```bash
# Show help
python getmusic.py --help

# Test with sample data (bypasses RSS)
python test_sample.py
```

## Files Structure

- `getmusic.py` - Main script with AlbumFetcher and OutputGenerator classes
- `test_sample.py` - Test script using sample data (bypasses RSS)
- `requirements.txt` - Python dependencies
- `allaboutjazz_albumlink.md` - Original specification document

## Known Implementation Challenges

### Cloudflare Protection
The All About Jazz RSS feed is protected by Cloudflare, which blocks most automated requests. The script includes proper User-Agent headers, but may still be blocked depending on IP/network.

### Album.link JavaScript Rendering
Album.link uses client-side JavaScript (Next.js) to render search results. The current implementation using BeautifulSoup cannot access dynamically-loaded content.

**Solutions to consider:**
1. **Browser Automation**: Replace BeautifulSoup with Selenium/Playwright to render JavaScript
2. **Spotify + Song.link API**: Search Spotify API → get URL → use `api.song.link` to generate Album.link URL
3. **Alternative Services**: Use MusicBrainz, Last.fm, or other music databases

The code structure is designed to make these replacements straightforward - just modify the `search_album_link()` method in the `AlbumFetcher` class.

## Automation Options

The spec mentions several automation approaches:
- **GitHub Actions**: Schedule daily runs, commit output to repo
- **AWS Lambda / Azure Function**: Serverless 24h scheduling
- **Cron Job**: Local scheduled execution
- **Apple Shortcut**: Manual trigger option

When implementing automation, ensure proper error handling for:
- RSS feed unavailability
- Album.link search failures
- Rate limiting considerations
- Network/IP blocking issues
