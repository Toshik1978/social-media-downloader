# CLAUDE.md

Guidance for working in this repository.

## What this project is

A self-hosted Telegram bot (`python-telegram-bot`, async) that downloads media from social media
links (Twitter/X, Instagram, YouTube) and sends it back to the user. Whitelist-only access.
Python 3.14+, managed with `uv`.

## Commands

This is an installable project (hatchling build backend) exposing the `social-media-downloader`
console script. `uv run` builds/installs it into a managed env automatically. Dependencies live in
**one place**: `pyproject.toml`.

```bash
cp .env.dist .env            # fill in BOT_TOKEN, USER_ID, (optional) RAPID_API_KEY
uv run social-media-downloader
```

`BOT_TOKEN`, `USER_ID` (comma-separated IDs), and `RAPID_API_KEY` come from env vars or a `.env`
file (loaded via `load_dotenv()`).

### Quality checks

```bash
uv run ruff check .          # lint
uv run ruff format .         # format (config: line-length 120, rules E/F/I/UP/B)
uv run pytest                # tests (tests/, pure logic: url matching, Medias, decorator)
uv run pytest --cov          # tests + coverage (config in [tool.coverage.run])
```

CI (`.github/workflows/ci.yml`) runs `ruff check`, `ruff format --check`, and `pytest --cov` on
push to `main` and on PRs. There is no coverage gate (it's informational). On push to `main` it
publishes Tests/Coverage badges by updating gist `12cd45e3eeec8924632d8f5ef6041735` (referenced in
the README badge URLs). This needs repo secrets `GIST_ID` (set it to that gist id) and
`GIST_SECRET_TOKEN` (a PAT with `gist` scope — must be created by a maintainer; the badge JSON is
seeded so badges render even before the first CI publish).

Two more workflows: `.github/workflows/secret-scan.yml` (gitleaks on push/PR) and
`.github/workflows/docker-publish.yml` (builds/pushes the image to GHCR on git **tags**).

## Architecture

The entry point is `main.py` (`main:main`). Adapters + the bot:

- **`media/media.py`** — `SocialMedia` abstract base (`is_valid_url`, `get_media`) and the `Medias`
  result container. **`Medias.__init__` takes four lists, all required:**
  `photo_urls, gif_urls, video_urls, video_files`. Every construction site must pass all four.
- **`bot/telegram_bot.py`** — generic `TelegramBot` base class. Handlers are discovered by naming
  convention: methods ending in `_command_handler` become `/command` handlers, methods ending in
  `_message_handler` become text-message handlers. Command descriptions come from the
  `@command_description(...)` decorator. A whitelist `MessageHandler` denies any chat not in
  `USER_ID`.
- **`bot/social_media_bot.py`** — concrete bot: `/start`, `/help`, `/stats`, `/resetstats`, and the
  `download_message_handler` that runs each matching adapter and replies with the media. Stats live
  in `context.bot_data['stats'][user_id]`.
- **`twitter/`, `instagram/`, `yt/`** — one adapter per source, each implementing `SocialMedia`.

### Adding a new source

1. Create `newsource/newsource.py` with a class extending `SocialMedia`, implementing
   `is_valid_url(url)` and `get_media(url) -> Medias`.
2. Instantiate it in the `sm = [...]` list in `main.py`.
3. Return a `Medias(photo_urls, gif_urls, video_urls, video_files)` with all four lists (use `[]`
   for the ones you don't produce).
4. Add the new package to `only-include` in `pyproject.toml` (see below) or it won't ship in the
   wheel, and add a `__init__.py` to it.

## Conventions

- Python ≥ 3.14. Modern typing (`str | None`, builtin generics).
- Heavy use of "private" name-mangled attributes (`self.__x`) and class-level type annotations
  documenting structure.
- Network calls use `requests` with an explicit `timeout`; keep timeouts on any new outbound call.
- Adapter exceptions in `download_message_handler` are caught and logged per-adapter, then the bot
  moves on; a totally failed message replies "No media found".
- Telegram has size limits (`constants.FileSizeLimit`): videos are sent by URL, uploaded from a
  temp file, or returned as a direct link depending on size.
- Persistence is a pickle file at `.data/persistence`; the `.data/` dir is gitignored.
- Secrets (`.env`, `RAPID_API_KEY`, `BOT_TOKEN`) must never be committed.
- Flat layout: `main.py` plus the packages, all listed in
  `[tool.hatch.build.targets.wheel].only-include`. Add new top-level modules/packages there or they
  won't ship in the wheel. Imports are absolute (`from bot...`, `from media...`).

## Git conventions

- **Never add `Co-Authored-By` trailers** (or any AI attribution) to commit messages.

## Known limitations

- The Instagram adapter handles single videos (`GraphVideo`) only — image posts and carousels are
  not downloaded.
- Twitter/Instagram downloads depend on third-party APIs that may rate-limit or change.
