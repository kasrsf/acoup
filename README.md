# acoup-reader

Fetches articles from [acoup.blog](https://acoup.blog) and exports them as EPUB files for reading in Apple Books on iPhone.

## Requirements

[uv](https://docs.astral.sh/uv/getting-started/installation/) — no other setup needed.

## Usage

### Single article

```bash
uv run acoup_reader.py "https://acoup.blog/2026/01/30/collections-the-late-bronze-age-collapse-a-very-brief-introduction/"
```

Saves an `.epub` file in the current directory, named after the article title.

### Whole multi-part series

```bash
uv run acoup_reader.py --series "https://acoup.blog/2026/01/30/collections-the-late-bronze-age-collapse-a-very-brief-introduction/"
```

Follows "next post" links automatically and bundles all parts into a single EPUB.

### Custom output filename

```bash
uv run acoup_reader.py --output lba_collapse.epub "https://acoup.blog/..."
```

### All options

```
usage: acoup_reader.py [-h] [--series] [--output OUTPUT] [--max-parts N] url

positional arguments:
  url                   URL of the first (or only) article

options:
  --series              Follow next-post links and bundle the whole series into one EPUB
  --output, -o OUTPUT   Output filename (default: derived from article title)
  --max-parts N         Max parts to collect in series mode (default: 20)
```

## Getting the EPUB onto your iPhone

AirDrop the generated `.epub` file to your iPhone — it opens directly in Apple Books.

Alternatively, save it to iCloud Drive and open it from the Files app on your iPhone.
