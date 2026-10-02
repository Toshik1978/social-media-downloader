# CLAUDE.md

Guidance for working in this repository.

## What this project is

A self-hosted Telegram bot (`python-telegram-bot`, async) that downloads media from social media
links (Twitter/X, Instagram, YouTube, YouTube Music) and sends it back to the user. Whitelist-only access.
Python 3.14+, managed with `uv`.

## Commands

This is an installable project (hatchling build backend) exposing the `social-media-downloader`
console script. `uv run` builds/installs it into a managed env automatically. Dependencies live in
**one place**: `pyproject.toml`.

```bash
cp .env.dist .env            # fill in BOT_TOKEN, USER_ID, (optional) RAPID_API_KEY, CAPTIONS
uv run social-media-downloader
```

`BOT_TOKEN`, `USER_ID` (comma-separated IDs), `RAPID_API_KEY`, and `CAPTIONS` (default `true`;
`false`/`0`/`no`/`off` disables captions) come from env vars or a `.env` file (loaded via
`load_dotenv()`).

### Quality checks

```bash
uv run ruff check .          # lint
uv run ruff format .         # format (config: line-length 120, rules E/F/I/UP/B)
uv run pytest                # tests (tests/)
uv run pytest --cov          # tests + coverage (config in [tool.coverage.run])
```

Tests cover the full codebase (100%): the async Telegram handlers and the adapters are tested
with `requests`/`pytubefix` mocked and a fake `Update`/`CallbackContext` (helpers in
`tests/conftest.py`). `asyncio_mode = "auto"` (pytest-asyncio) means async tests need no decorator.
The bot is built offline with a dummy token in an isolated cwd (the `bot` fixture).

CI (`.github/workflows/ci.yml`) runs `ruff check`, `ruff format --check`, and `pytest --cov` on
push to `main` and on PRs. There is no coverage gate (the badge is informational; green at ≥80%).
On push to `main` it publishes Tests/Coverage badges by updating gist
`12cd45e3eeec8924632d8f5ef6041735` (referenced in the README badge URLs). This needs repo secrets
`GIST_ID` (set it to that gist id) and
`GIST_SECRET_TOKEN` (a PAT with `gist` scope — must be created by a maintainer; the badge JSON is
seeded so badges render even before the first CI publish).

Two more workflows: `.github/workflows/secret-scan.yml` (gitleaks on push/PR) and
`.github/workflows/docker-publish.yml` (builds/pushes the image to GHCR on git **tags**).

## Architecture

The entry point is `main.py` (`main:main`). Adapters + the bot:

- **`media/media.py`** — `SocialMedia` abstract base (`is_valid_url`, `get_media`), the `Medias`
  result container, and one dataclass per media kind: `Photo(url)`, `Gif(url, duration, width,
  height)`, `Video(source, duration, width, height)` (`source` is a URL **or** a downloaded file; the
  bot picks the send path by type), and `Audio(file, title, performer, duration)`. Metadata fields are
  optional (`None` = let Telegram work it out). `Medias` lists all default to empty:
  `album, gifs, videos, audios`, plus an optional post-level `caption` (tweet text minus trailing
  `t.co` links, Instagram caption, YouTube title). Pass only what an adapter produces, by keyword
  (e.g. `Medias(videos=[Video(f)], caption=title)`, `Medias()` for nothing). `album` is an ordered
  `list[Photo | Video]` sent as media groups; only put URL videos Telegram can fetch (≤ 20 MB) there,
  e.g. Instagram carousel items. Standalone videos go to `videos`, which take the size-aware send path.
- **`bot/telegram_bot.py`** — generic `TelegramBot` base class. Handlers are discovered by naming
  convention: methods ending in `_command_handler` become `/command` handlers, methods ending in
  `_message_handler` become text-message handlers. Command descriptions come from the
  `@command_description(...)` decorator. A whitelist `MessageHandler` denies any chat not in
  `USER_ID`.
- **`bot/social_media_bot.py`** — concrete bot: `/start`, `/help`, `/stats`, `/resetstats`, and the
  `download_message_handler` that runs **every** matching adapter (not just the first) and replies with
  the media, so adapters' `is_valid_url` must not overlap. The caption goes on the first message sent
  for a link only (album caption = first photo's caption), as plain text truncated to
  `constants.MessageLimit.CAPTION_LENGTH` UTF-16 code units; `captions=False` drops it. Stats live
  in `context.bot_data['stats'][user_id]`.
- **`twitter/`, `instagram/`, `yt/`** — one adapter per source, each implementing `SocialMedia`.
  `yt/` holds two: `YouTube` (video) and `YouTubeMusic` (`music.youtube.com`, audio only via
  `streams.get_audio_only()` — M4A/AAC, which Telegram plays as a music track). `YouTube` excludes
  `music.youtube.com` so a music link isn't answered twice. `Instagram` handles `GraphVideo`,
  `GraphImage` and `GraphSidecar` (carousel children are typed `XDTGraph*`, so it branches on
  `is_video`, and keeps them in order in `album`); the API reports errors as HTTP 200 with
  `"status": false`.

### Adding a new source

1. Create `newsource/newsource.py` with a class extending `SocialMedia`, implementing
   `is_valid_url(url)` and `get_media(url) -> Medias`.
2. Instantiate it in the `sm = [...]` list in `main.py`.
3. Return a `Medias(...)` with only the lists you produce, by keyword. Make sure `is_valid_url`
   doesn't overlap an existing adapter's.
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
  temp file, or returned as a direct link depending on size. Audio is always uploaded from a temp
  file; `YouTubeMusic` returns nothing if the stream exceeds the upload limit. `album` items go out as
  media groups of at most 10 (`constants.MediaGroupLimit.MAX_MEDIA_LENGTH`); if Telegram rejects a group
  that has videos (`BadRequest`, e.g. a video over 20 MB), that batch is resent per kind (photos group,
  then videos via the size-aware path). Media uploads get a 300 s write timeout (`MEDIA_WRITE_TIMEOUT`).
- Persistence is a pickle file at `.data/persistence`; the `.data/` dir is gitignored.
- Secrets (`.env`, `RAPID_API_KEY`, `BOT_TOKEN`) must never be committed.
- Flat layout: `main.py` plus the packages, all listed in
  `[tool.hatch.build.targets.wheel].only-include`. Add new top-level modules/packages there or they
  won't ship in the wheel. Imports are absolute (`from bot...`, `from media...`).

## Known limitations

- The YouTube Music adapter handles single tracks only — playlist/album links are not downloaded.
- Tweets mixing photos and videos are sent photos first, then videos (Twitter videos stay out of
  `album` because they can exceed the 20 MB URL-fetch limit). A rejected carousel group loses its order
  the same way.
- Twitter/Instagram downloads depend on third-party APIs that may rate-limit or change.
