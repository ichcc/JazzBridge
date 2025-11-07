#!/usr/bin/env python3
"""
GetMusic - All About Jazz to Album.link automation

Fetches new jazz album mentions from All About Jazz RSS feed,
searches for them on Album.link, and generates a consolidated list.
"""

import feedparser
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote
import argparse
import csv
import sys
import re
import time
from datetime import datetime
from typing import List, Tuple, Optional


class AlbumFetcher:
    """Handles fetching and processing jazz albums from All About Jazz."""

    RSS_URL = "https://www.allaboutjazz.com/rss_reviews.xml"
    ALBUM_LINK_SEARCH = "https://album.link/search?q={}"

    # Patterns to remove from titles
    REMOVE_PATTERNS = [
        r'\s*album review\s*$',
        r'\s*concert review\s*$',
        r'\s*premiere\s*$',
        r'\s*review\s*$',
    ]

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })

    def log(self, message: str):
        """Print message if verbose mode is enabled."""
        if self.verbose:
            print(f"[INFO] {message}")

    def fetch_rss(self) -> List[dict]:
        """Fetch and parse the All About Jazz RSS feed."""
        self.log(f"Fetching RSS from {self.RSS_URL}")
        try:
            feed = feedparser.parse(self.RSS_URL)
            if feed.bozo:
                self.log(f"Warning: RSS feed parsing had errors: {feed.get('bozo_exception', 'Unknown error')}")
            self.log(f"Found {len(feed.entries)} entries")
            return feed.entries
        except Exception as e:
            self.log(f"Error fetching RSS feed: {e}")
            import traceback
            self.log(traceback.format_exc())
            return []

    def clean_title(self, title: str) -> Optional[Tuple[str, str]]:
        """
        Clean title and extract artist and album.

        Args:
            title: Raw title from RSS feed

        Returns:
            Tuple of (artist, album) or None if parsing fails
        """
        # Remove common suffixes
        cleaned = title
        for pattern in self.REMOVE_PATTERNS:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

        cleaned = cleaned.strip()

        # Split on first colon
        if ':' not in cleaned:
            self.log(f"Skipping title without colon separator: {title}")
            return None

        parts = cleaned.split(':', 1)
        if len(parts) != 2:
            return None

        artist = parts[0].strip()
        album = parts[1].strip()

        if not artist or not album:
            return None

        return (artist, album)

    def search_apple_music(self, artist: str, album: str) -> Optional[str]:
        """
        Search Apple Music for the album and return the Apple Music album URL.

        Uses the public iTunes Search API which doesn't require authentication.

        Args:
            artist: Artist name
            album: Album title

        Returns:
            Apple Music album URL or None if not found
        """
        query = f"{artist} {album}"

        self.log(f"Searching Apple Music for: {query}")

        try:
            # iTunes Search API
            search_url = "https://itunes.apple.com/search"
            params = {
                'term': query,
                'media': 'music',
                'entity': 'album',
                'limit': 5
            }

            response = self.session.get(search_url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            results = data.get('results', [])

            if results:
                # Get the first result's collection view URL
                first_result = results[0]
                apple_url = first_result.get('collectionViewUrl')

                if apple_url:
                    self.log(f"Found Apple Music URL: {apple_url}")
                    return apple_url
                else:
                    self.log("No URL in Apple Music result")
                    return None
            else:
                self.log(f"No Apple Music results for: {query}")
                return None

        except requests.RequestException as e:
            self.log(f"Error searching Apple Music: {e}")
            return None
        except ValueError as e:
            self.log(f"Error parsing Apple Music response: {e}")
            return None

    def convert_url_to_album_link(self, music_url: str) -> Optional[str]:
        """
        Convert any music streaming URL to Album.link URL using song.link API.

        Args:
            music_url: URL from any music service (Spotify, Apple Music, etc.)

        Returns:
            Album.link URL or None if conversion fails
        """
        api_url = f"https://api.song.link/v1-alpha.1/links?url={quote(music_url)}"

        self.log(f"Converting to Album.link via API...")

        # Rate limiting: 10 requests/minute without API key
        # Sleep 6 seconds between requests to stay safe
        time.sleep(6)

        try:
            response = self.session.get(api_url, timeout=10)
            response.raise_for_status()

            data = response.json()
            page_url = data.get('pageUrl')

            if page_url:
                # Remove country code from URL (e.g., /us/i/ -> /i/)
                # The canonical URLs work better without country codes
                page_url = page_url.replace('/us/i/', '/i/')
                page_url = page_url.replace('/uk/i/', '/i/')
                page_url = page_url.replace('/ca/i/', '/i/')

                self.log(f"Got Album.link: {page_url}")
                return page_url
            else:
                self.log("No pageUrl in API response")
                return None

        except requests.RequestException as e:
            self.log(f"Error calling song.link API: {e}")
            return None
        except ValueError as e:
            self.log(f"Error parsing API response: {e}")
            return None

    def search_album_link(self, artist: str, album: str) -> Optional[str]:
        """
        Search for album and return Album.link URL.

        Uses a two-step process:
        1. Search Apple Music for the album
        2. Convert Apple Music URL to Album.link using song.link API

        Args:
            artist: Artist name
            album: Album title

        Returns:
            Album.link URL or None if not found
        """
        # First, try to find on Apple Music
        apple_url = self.search_apple_music(artist, album)

        if apple_url:
            # Then try to convert to Album.link
            album_link = self.convert_url_to_album_link(apple_url)
            if album_link:
                return album_link

        self.log(f"No album.link found for: {artist} - {album}")
        return None

    def process_feed(self) -> List[Tuple[str, str, str, str, str]]:
        """
        Process RSS feed and search for albums.

        Returns:
            List of tuples: (artist, album, album_link, apple_music_link, date)
        """
        entries = self.fetch_rss()
        results = []

        for entry in entries:
            title = entry.get('title', '')
            pub_date = entry.get('published', '')

            # Parse date
            date_str = ''
            if pub_date:
                try:
                    date_obj = datetime.strptime(pub_date, '%a, %d %b %Y %H:%M:%S %z')
                    date_str = date_obj.strftime('%Y-%m-%d')
                except:
                    date_str = pub_date.split(',')[1].strip().split()[0:3]
                    date_str = ' '.join(date_str) if isinstance(date_str, list) else pub_date

            # Clean and parse title
            parsed = self.clean_title(title)
            if not parsed:
                continue

            artist, album = parsed
            self.log(f"Processing: {artist} - {album}")

            # Search Apple Music first
            apple_url = self.search_apple_music(artist, album)
            album_link = None

            if apple_url:
                # Then get album.link URL
                album_link = self.convert_url_to_album_link(apple_url)

            # Add to results even if link not found (will show as placeholder)
            results.append((artist, album, album_link or '', apple_url or '', date_str))

        return results


class JazzProfilesFetcher(AlbumFetcher):
    """Handles fetching and processing jazz albums from Jazz Profiles blog."""

    RSS_URL = "https://jazzprofiles.blogspot.com/feeds/posts/default"

    # Jazz Profiles specific patterns (album mentions, reviews, etc.)
    REMOVE_PATTERNS = [
        r'\s*album review\s*$',
        r'\s*review\s*$',
        r'\s*-\s*album\s*$',
        r'\s*\[album\]\s*$',
    ]

    def clean_title(self, title: str) -> Optional[Tuple[str, str]]:
        """
        Clean title and extract artist and album from Jazz Profiles format.

        Jazz Profiles may use different formats:
        - "Artist - Album"
        - "Artist: Album"
        - "Album by Artist"
        - Or just descriptive titles

        Args:
            title: Raw title from RSS feed

        Returns:
            Tuple of (artist, album) or None if parsing fails
        """
        # Remove common suffixes
        cleaned = title
        for pattern in self.REMOVE_PATTERNS:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

        cleaned = cleaned.strip()

        # Try different separator patterns
        # First try colon (like All About Jazz)
        if ':' in cleaned:
            parts = cleaned.split(':', 1)
            if len(parts) == 2:
                artist = parts[0].strip()
                album = parts[1].strip()
                if artist and album:
                    return (artist, album)

        # Try hyphen separator
        if ' - ' in cleaned:
            parts = cleaned.split(' - ', 1)
            if len(parts) == 2:
                artist = parts[0].strip()
                album = parts[1].strip()
                if artist and album:
                    return (artist, album)

        # Try "Album by Artist" format
        if ' by ' in cleaned.lower():
            match = re.search(r'^(.+?)\s+by\s+(.+?)$', cleaned, re.IGNORECASE)
            if match:
                album = match.group(1).strip()
                artist = match.group(2).strip()
                if artist and album:
                    return (artist, album)

        self.log(f"Skipping title - couldn't parse: {title}")
        return None


class OutputGenerator:
    """Handles output generation in various formats."""

    @staticmethod
    def generate_markdown(results: List[Tuple[str, str, str, str, str]], output_file: str):
        """Generate Markdown output."""
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("## 🎶 New Jazz Albums\n\n")
            f.write("_Links: [All Platforms] | [Apple Music]_\n\n")
            if not results:
                f.write("No albums found.\n")
            else:
                for artist, album, album_link, apple_link, date in results:
                    f.write(f"- **{artist} — {album}** [[All]({album_link})] [[Apple]({apple_link})]")
                    if date:
                        f.write(f" _{date}_")
                    f.write("\n")
        print(f"Markdown output written to: {output_file}")

    @staticmethod
    def generate_csv(results: List[Tuple[str, str, str, str, str]], output_file: str):
        """Generate CSV output."""
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['artist', 'album', 'album_link', 'apple_music_link', 'date'])
            for row in results:
                writer.writerow(row)
        print(f"CSV output written to: {output_file}")

    @staticmethod
    def generate_html(results: List[Tuple[str, str, str, str, str]], output_file: str,
                     jazz_profiles_results: Optional[List[Tuple[str, str, str, str, str]]] = None):
        """Generate HTML output with embedded album.link widgets from multiple sources."""
        total_albums = len(results) + (len(jazz_profiles_results) if jazz_profiles_results else 0)

        html_content = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🎷 Latest Jazz Albums</title>

    <!-- Favicon -->
    <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🎷</text></svg>">

    <!-- Open Graph / Facebook -->
    <meta property="og:type" content="website">
    <meta property="og:url" content="https://jazzbridge.pages.dev/">
    <meta property="og:title" content="🎷 Latest Jazz Albums">
    <meta property="og:description" content="Daily updated collection of new jazz album releases with universal streaming links. Discover ''' + str(total_albums) + ''' albums from All About Jazz and Jazz Profiles.">
    <meta property="og:image" content="https://jazzbridge.pages.dev/og-image.png">

    <!-- Twitter -->
    <meta property="twitter:card" content="summary_large_image">
    <meta property="twitter:url" content="https://jazzbridge.pages.dev/">
    <meta property="twitter:title" content="🎷 Latest Jazz Albums">
    <meta property="twitter:description" content="Daily updated collection of new jazz album releases with universal streaming links.">
    <meta property="twitter:image" content="https://jazzbridge.pages.dev/og-image.png">

    <!-- Telegram -->
    <meta name="description" content="Daily updated collection of ''' + str(total_albums) + ''' new jazz albums with universal streaming links.">

    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            background: #1a1a1a;
            color: #fff;
            padding: 20px;
        }

        header {
            text-align: center;
            margin-bottom: 30px;
        }

        h1 {
            font-size: 2em;
            margin-bottom: 10px;
        }

        h2 {
            font-size: 1.5em;
            margin: 40px 0 20px 0;
            text-align: center;
            color: #fff;
        }

        h2:first-of-type {
            margin-top: 0;
        }

        .update-time {
            color: #888;
            font-size: 0.9em;
        }

        .section-container {
            max-width: 1400px;
            margin: 0 auto;
        }

        .grid-container {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 20px;
            max-width: 1400px;
            margin: 0 auto;
        }

        .album-embed {
            aspect-ratio: 480/199;
            width: 100%;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
            background: #2a2a2a;
        }

        .album-embed iframe {
            width: 100%;
            height: 100%;
            border: none;
        }

        .placeholder {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            color: #666;
            font-size: 0.9em;
            text-align: center;
            padding: 20px;
        }

        .placeholder-icon {
            font-size: 2em;
            margin-bottom: 10px;
        }

        footer {
            text-align: center;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #333;
            color: #666;
            font-size: 0.85em;
        }

        footer a {
            color: #888;
            text-decoration: none;
        }

        footer a:hover {
            color: #fff;
        }

        /* Responsive design */
        @media (max-width: 1200px) {
            .grid-container {
                grid-template-columns: repeat(3, 1fr);
            }
        }

        @media (max-width: 900px) {
            .grid-container {
                grid-template-columns: repeat(2, 1fr);
            }

            h1 {
                font-size: 1.5em;
            }
        }

        @media (max-width: 600px) {
            .grid-container {
                grid-template-columns: 1fr;
            }

            h1 {
                font-size: 1.2em;
            }
        }
    </style>
</head>
<body>
    <header>
        <h1>🎷 Latest Jazz Albums</h1>
        <p class="update-time">Updated: ''' + datetime.now().strftime('%B %d, %Y at %I:%M %p') + '''</p>
    </header>

    <div class="section-container">
        <h2>🎺 All About Jazz</h2>
        <div class="grid-container">
'''

        # Add All About Jazz album embeds or placeholders
        for artist, album, album_link, apple_link, date in results:
            if album_link:
                # Album found - show embed
                encoded_url = quote(album_link)
                html_content += f'''        <div class="album-embed">
            <iframe src="https://song.link/embed?url={encoded_url}"
                    frameborder="0"
                    allowtransparency
                    allowfullscreen
                    title="{artist} - {album}">
            </iframe>
        </div>
'''
            else:
                # Album not found - show placeholder with artist and album name
                html_content += f'''        <div class="album-embed placeholder">
            <div class="placeholder-icon">🎵</div>
            <div><strong>{artist}</strong></div>
            <div style="font-size: 0.85em; margin-top: 5px;">{album}</div>
            <div style="font-size: 0.75em; color: #555; margin-top: 10px;">Not available on streaming</div>
        </div>
'''

        html_content += '''        </div>
'''

        # Add Jazz Profiles section if results provided
        if jazz_profiles_results:
            html_content += '''
        <h2>🎹 Jazz Profiles</h2>
        <div class="grid-container">
'''
            for artist, album, album_link, apple_link, date in jazz_profiles_results:
                if album_link:
                    # Album found - show embed
                    encoded_url = quote(album_link)
                    html_content += f'''        <div class="album-embed">
            <iframe src="https://song.link/embed?url={encoded_url}"
                    frameborder="0"
                    allowtransparency
                    allowfullscreen
                    title="{artist} - {album}">
            </iframe>
        </div>
'''
                else:
                    # Album not found - show placeholder
                    html_content += f'''        <div class="album-embed placeholder">
            <div class="placeholder-icon">🎵</div>
            <div><strong>{artist}</strong></div>
            <div style="font-size: 0.85em; margin-top: 5px;">{album}</div>
            <div style="font-size: 0.75em; color: #555; margin-top: 10px;">Not available on streaming</div>
        </div>
'''
            html_content += '''        </div>
'''

        html_content += '''    </div>

    <footer>
        <p>Data from <a href="https://www.allaboutjazz.com/" target="_blank">All About Jazz</a>'''

        if jazz_profiles_results:
            html_content += ''' and <a href="https://jazzprofiles.blogspot.com/" target="_blank">Jazz Profiles</a>'''

        html_content += ''' |
           Links via <a href="https://album.link" target="_blank">Album.link</a></p>
        <p style="margin-top: 10px;">Generated by GetMusic</p>
    </footer>
</body>
</html>
'''

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

        # Count how many have links vs placeholders
        aaj_with_links = sum(1 for _, _, link, _, _ in results if link)
        aaj_without_links = len(results) - aaj_with_links

        print(f"HTML output written to: {output_file}")
        print(f"All About Jazz: {aaj_with_links} album embeds and {aaj_without_links} placeholders from {len(results)} total albums")

        if jazz_profiles_results:
            jp_with_links = sum(1 for _, _, link, _, _ in jazz_profiles_results if link)
            jp_without_links = len(jazz_profiles_results) - jp_with_links
            print(f"Jazz Profiles: {jp_with_links} album embeds and {jp_without_links} placeholders from {len(jazz_profiles_results)} total albums")


def main():
    """Main entry point."""
    try:
        parser = argparse.ArgumentParser(
            description='Fetch jazz albums from All About Jazz and Jazz Profiles, find them on Album.link'
        )
        parser.add_argument(
            '-o', '--output',
            default='jazz_albums.md',
            help='Output file path (default: jazz_albums.md)'
        )
        parser.add_argument(
            '-f', '--format',
            choices=['markdown', 'csv', 'html'],
            default='markdown',
            help='Output format (default: markdown)'
        )
        parser.add_argument(
            '-v', '--verbose',
            action='store_true',
            help='Enable verbose output'
        )
        parser.add_argument(
            '--skip-jazz-profiles',
            action='store_true',
            help='Skip fetching from Jazz Profiles (only fetch All About Jazz)'
        )

        args = parser.parse_args()

        # Fetch and process albums from All About Jazz
        print("\n=== Fetching from All About Jazz ===")
        aaj_fetcher = AlbumFetcher(verbose=args.verbose)
        aaj_results = aaj_fetcher.process_feed()

        # Count All About Jazz results
        aaj_with_links = sum(1 for _, _, link, _, _ in aaj_results if link)
        aaj_without_links = len(aaj_results) - aaj_with_links

        print(f"\nAll About Jazz - Processed {len(aaj_results)} albums:")
        print(f"  - {aaj_with_links} found on streaming services")
        print(f"  - {aaj_without_links} not found (will show as placeholders)")

        # Fetch and process albums from Jazz Profiles (unless skipped)
        jp_results = None
        if not args.skip_jazz_profiles:
            print("\n=== Fetching from Jazz Profiles ===")
            jp_fetcher = JazzProfilesFetcher(verbose=args.verbose)
            jp_results = jp_fetcher.process_feed()

            # Count Jazz Profiles results
            jp_with_links = sum(1 for _, _, link, _, _ in jp_results if link)
            jp_without_links = len(jp_results) - jp_with_links

            print(f"\nJazz Profiles - Processed {len(jp_results)} albums:")
            print(f"  - {jp_with_links} found on streaming services")
            print(f"  - {jp_without_links} not found (will show as placeholders)")

        # Generate output
        if args.format == 'markdown':
            OutputGenerator.generate_markdown(aaj_results, args.output)
            print("\nNote: Markdown format only includes All About Jazz results")
        elif args.format == 'csv':
            OutputGenerator.generate_csv(aaj_results, args.output)
            print("\nNote: CSV format only includes All About Jazz results")
        elif args.format == 'html':
            OutputGenerator.generate_html(aaj_results, args.output, jazz_profiles_results=jp_results)
            print()

        return 0

    except Exception as e:
        print(f"\n❌ Fatal error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
