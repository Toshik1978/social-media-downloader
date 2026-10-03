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

ffmpeg (`ffmpeg` + `ffprobe` on `PATH`) is a system dependency, installed in the Docker image and in CI.

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
with `requests`/`pytubefix` mocked, `media.ffmpeg` stubbed (monkeypatch `media.ffmpeg.<name>`), and a fake
`Update`/`CallbackContext` (helpers in `tests/conftest.py`). `asyncio_mode = "auto"` (pytest-asyncio) means
async tests need no decorator.
The bot is built offline with a dummy token in an isolated cwd (the `bot` fixture).
`tests/test_ffmpeg.py` runs real ffmpeg on lavfi-generated clips (skipped without ffmpeg).

CI (`.github/workflows/ci.yml`) installs ffmpeg and runs `ruff check`, `ruff format --check`, and `pytest --cov` on
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
  height)`, `Video(source, duration, width, height, fallbacks)` (`source` is a URL **or** a downloaded file; the
  bot picks the send path by type; `fallbacks` are lower-quality URLs of the same video, best first — Twitter fills
  them), and `Audio(file, title, performer, duration)`. Metadata fields are
  optional (`None` = let Telegram work it out). `Medias` lists all default to empty:
  `album, gifs, videos, audios`, plus an optional post-level `caption` (tweet text minus trailing
  `t.co` links, Instagram caption, YouTube title). Pass only what an adapter produces, by keyword
  (e.g. `Medias(videos=[Video(f)], caption=title)`, `Medias()` for nothing). `album` is an ordered
  `list[Photo | Video]` sent as media groups; only put URL videos Telegram can fetch (≤ 20 MB) there,
  e.g. Instagram carousel items. Standalone videos go to `videos`, which take the size-aware send path.
- **`media/ffmpeg.py`** — synchronous ffmpeg/ffprobe helpers, always called from a worker thread: `available()`,
  `video_bitrate(duration, limit)` (video bit/s that fits, `None` below the 500 kbps floor ≈ 10 min for 50 MB),
  `duration(source)`, `mux(video_path, audio_path)` (stream copy) and `transcode(inputs, duration, limit)` (H.264/AAC,
  shorter side ≤ 720 or 480, even sizes, 8-bit yuv420p, ≤ 30 fps, never upscaled; `None` on failure or if still
  too big). One re-encode at a time (lock); every call has a timeout (re-encodes: `max(600, 3 × duration)` s).
  Call it through the module (`from media import ffmpeg`; `ffmpeg.transcode(...)`).
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
- **Blocking work** (adapters' `get_media`, video size probes and downloads, ffmpeg) runs in the bot's own
  32-thread pool via `_run_blocking` in `bot/social_media_bot.py`, never on the event loop; the Application uses
  `concurrent_updates(True)`, so a long download doesn't block other messages. An adapter still running after
  `SLOW_DOWNLOAD_NOTICE` (5 s) gets a "Downloading…" status message, deleted when it returns.
- **`twitter/`, `instagram/`, `yt/`** — one adapter per source, each implementing `SocialMedia`.
  Twitter uses `api.fxtwitter.com` (errors arrive as JSON `code`/`message` or an HTML `og:description`) and
  puts every MP4 rendition, best first, in `source` + `fallbacks`. `yt/` holds two: `YouTube` (video: the best H.264
  adaptive stream + the original-language M4A audio track that fit, joined with `ffmpeg.mux`; else a re-encode
  from the best stream ≤ 720p; progressive streams only when ffmpeg is missing) and `YouTubeMusic`
  (`music.youtube.com`, audio only via `streams.get_audio_only()` — M4A/AAC, which Telegram plays as a music
  track). `YouTube` excludes `music.youtube.com` so a music link isn't answered twice. `Instagram` handles `GraphVideo`,
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
- Telegram has size limits (`constants.FileSizeLimit`): a URL video is sent as the first of `[source, *fallbacks]`
  that fits (by URL ≤ 20 MB, uploaded ≤ 50 MB; a version that errors or has no `Content-Length` is skipped); if
  none fits, the smallest that responded is re-encoded with `ffmpeg.transcode` when `ffmpeg.video_bitrate` allows,
  else the bot sends a direct link to the best one. Audio is always uploaded from a temp
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
- A URL video with no version ≤ 50 MB that is longer than ~10 minutes gets a direct link (the re-encode floor is
  500 kbps of video); a YouTube video picks the best stream that fits (down to 144p), else "No media found".
