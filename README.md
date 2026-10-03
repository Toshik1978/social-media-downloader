[![CI](https://github.com/Toshik1978/social-media-downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/Toshik1978/social-media-downloader/actions)
![Tests](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/Toshik1978/12cd45e3eeec8924632d8f5ef6041735/raw/tests.json&maxAge=180)
![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/Toshik1978/12cd45e3eeec8924632d8f5ef6041735/raw/coverage.json&maxAge=180)

# Social Media Downloader

A self-hosted Telegram bot that downloads media from social media links and sends it back to you
in the best available quality. Send it a link, get the photos / GIFs / videos / audio in chat.

Supported sources:

| Source | What it downloads | Backend |
|--------|-------------------|---------|
| **Twitter / X** (`twitter.com`, `x.com`, `t.co`) | Photos (upscaled to original quality), GIFs, videos (the best version that fits Telegram's upload limit) | [fxtwitter](https://github.com/FxEmbed/FxEmbed) public API |
| **Instagram** (`instagram.com`) | Photos and videos from posts, reels and carousels | [instagram-looter2](https://rapidapi.com/) via RapidAPI (key required) |
| **YouTube** (`youtube.com`, `youtu.be`) | H.264 video with AAC audio, best quality that fits Telegram's upload limit | [pytubefix](https://github.com/JuanBindez/pytubefix) + ffmpeg |
| **YouTube Music** (`music.youtube.com`) | Audio only (highest bitrate M4A/AAC), sent as a music track with title, artist and duration | [pytubefix](https://github.com/JuanBindez/pytubefix) |

The bot is **whitelist-only**: it ignores everyone except the user IDs you configure.

## Commands

- `/start` – greeting
- `/help` – usage hint
- `/stats` – per-user counters (messages handled, media downloaded)
- `/resetstats` – reset your counters

Anything else you send that contains a supported link is treated as a download request.

## Configuration

The bot is configured through environment variables (a `.env` file in the working directory is
loaded automatically — see [`.env.dist`](.env.dist)):

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | yes | Telegram bot token from [@BotFather](https://t.me/BotFather) |
| `USER_ID` | yes | Comma-separated list of Telegram user IDs allowed to use the bot (e.g. `123,456`) |
| `RAPID_API_KEY` | no | [RapidAPI](https://rapidapi.com/) key for the `instagram-looter2` API. Required only for Instagram downloads |
| `CAPTIONS` | no | Send the post text (tweet text, Instagram caption, YouTube title) as the media caption. Default `true`; set `false` to send media only |

To find your numeric Telegram user ID, message a bot such as [@userinfobot](https://t.me/userinfobot).

## Running

### Locally (with [uv](https://docs.astral.sh/uv/))

The bot is exposed as the `social-media-downloader` console script. `uv run` builds/installs the
project into a managed environment automatically. Requires Python 3.14+ and [ffmpeg](https://ffmpeg.org/)
(`ffmpeg` and `ffprobe` on `PATH`; the Docker image ships it). Without ffmpeg the bot still runs, but videos
over Telegram's upload limit are sent as links and YouTube is limited to its rare single-file streams.

```bash
cp .env.dist .env   # then fill in BOT_TOKEN and USER_ID
uv run social-media-downloader
```

### Docker

```bash
docker run -d \
  -e BOT_TOKEN=your-token \
  -e USER_ID=123456789 \
  -e RAPID_API_KEY=optional-key \
  -v "$PWD/.data:/app/.data" \
  ghcr.io/toshik1978/social-media-downloader:latest
```

The image is published to GitHub Container Registry on every git tag (see
[`.github/workflows/docker-publish.yml`](.github/workflows/docker-publish.yml)).

Mount `/app/.data` to a volume to persist per-user stats across restarts.

## How it works

```
main.py                            entry point: loads env, wires adapters, starts polling
└── bot/
    ├── telegram_bot.py            generic TelegramBot base: dispatch, auth whitelist, error reporting
    └── social_media_bot.py        bot logic: commands, stats, sending media back to Telegram
└── media/media.py                 SocialMedia interface + Medias result container
└── media/ffmpeg.py                ffmpeg helpers: join streams, re-encode to fit, probe duration
└── twitter/twitter.py             Twitter/X adapter
└── instagram/instagram.py         Instagram adapter
└── yt/youtube.py                  YouTube adapter
└── yt/youtube_music.py            YouTube Music adapter (audio only)
```

Each adapter implements `SocialMedia` (`is_valid_url` + `get_media`). The bot tries every adapter
whose `is_valid_url` matches the incoming link and replies with whatever media is found. Photos (and
the videos of an Instagram carousel, keeping the carousel's order) are sent as albums of up to 10. The post text, when there is one, becomes the caption of the first message
sent for that link (truncated to Telegram's 1024-character limit). Videos go
out in the best version that fits Telegram's limits: by direct URL up to 20 MB, uploaded from a
temporary file up to 50 MB (Twitter offers several versions of each video). When no version fits, the bot
re-encodes the video with ffmpeg (H.264/AAC, at most 720p and 30 fps) if 50 MB still leaves at least 500 kbps for the picture
— roughly videos up to 10 minutes — and otherwise replies with a direct link. YouTube serves video and audio as
separate streams; the bot joins them with ffmpeg, using the original-language audio track. Anything that takes more
than a few seconds gets a "Downloading…" status message. Audio is uploaded as a Telegram music track.

Per-user stats are persisted to `.data/persistence` via `python-telegram-bot`'s `PicklePersistence`.

## Development

Dependencies live in one place (`pyproject.toml`); `uv` manages the environment.

```bash
uv sync                      # install runtime + dev dependencies
uv run ruff check .          # lint (rules E/F/I/UP/B, line-length 120)
uv run ruff format .         # format
uv run pytest                # tests (tests/, pure logic: url matching, Medias, decorator)
uv run pytest --cov          # tests + coverage
```

The ffmpeg tests run real ffmpeg on tiny generated clips and are skipped when it isn't installed; CI installs it.

CI (`.github/workflows/ci.yml`) runs `ruff check`, `ruff format --check`, and `pytest --cov` on
push to `main` and on PRs, and publishes the Tests/Coverage badges above by updating a gist. A
[gitleaks secret scan](.github/workflows/secret-scan.yml) also runs on every push/PR, and a tagged
push builds and publishes the Docker image.

## Limitations

- The YouTube Music adapter downloads single tracks only — playlist and album links are not supported.
- A video with no version under 50 MB that is longer than about 10 minutes is sent as a direct link (a
  re-encode would look too poor). Twitter usually has a small enough version; YouTube picks the best stream
  that fits, down to 144p, and otherwise replies "No media found". Re-encodes run one at a time and take a
  while (about 25 s for a 4.5-minute 1080p video on 12 cores; a small host may take longer than the video lasts).
- Tweets mixing photos and videos are sent as photos first, then videos. A carousel video too large
  for Telegram to fetch by URL (over 20 MB) makes its album fall back to the same photos-then-videos order.
- Twitter/Instagram downloads depend on third-party APIs that may rate-limit or change.

## Special thanks

The original idea was taken from the
[twitter_downloader_bot](https://github.com/skrimix/twitter_downloader_bot/) repository.

## License

See [LICENSE](LICENSE).
