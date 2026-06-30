[![CI](https://github.com/Toshik1978/social-media-downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/Toshik1978/social-media-downloader/actions)
![Tests](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/Toshik1978/12cd45e3eeec8924632d8f5ef6041735/raw/tests.json&maxAge=180)
![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/Toshik1978/12cd45e3eeec8924632d8f5ef6041735/raw/coverage.json&maxAge=180)

# Social Media Downloader

A self-hosted Telegram bot that downloads media from social media links and sends it back to you
in the best available quality. Send it a link, get the photos / GIFs / videos in chat.

Supported sources:

| Source | What it downloads | Backend |
|--------|-------------------|---------|
| **Twitter / X** (`twitter.com`, `x.com`, `t.co`) | Photos (upscaled to original quality), GIFs, videos | [vxtwitter](https://github.com/dylanpdx/BetterTwitterEmbeds) public API |
| **Instagram** (`instagram.com`) | Videos from posts | [instagram-looter2](https://rapidapi.com/) via RapidAPI (key required) |
| **YouTube** (`youtube.com`, `youtu.be`) | Progressive video, best quality that fits Telegram's upload limit | [pytubefix](https://github.com/JuanBindez/pytubefix) |

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

To find your numeric Telegram user ID, message a bot such as [@userinfobot](https://t.me/userinfobot).

## Running

### Locally (with [uv](https://docs.astral.sh/uv/))

The bot is exposed as the `social-media-downloader` console script. `uv run` builds/installs the
project into a managed environment automatically. Requires Python 3.14+.

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
└── twitter/twitter.py             Twitter/X adapter
└── instagram/instagram.py         Instagram adapter
└── yt/youtube.py                  YouTube adapter
```

Each adapter implements `SocialMedia` (`is_valid_url` + `get_media`). The bot tries every adapter
whose `is_valid_url` matches the incoming link and replies with whatever media is found. Videos are
sent by direct URL when small enough, uploaded from a temporary file when larger, or returned as a
direct link when they exceed Telegram's upload limit.

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

CI (`.github/workflows/ci.yml`) runs `ruff check`, `ruff format --check`, and `pytest --cov` on
push to `main` and on PRs, and publishes the Tests/Coverage badges above by updating a gist. A
[gitleaks secret scan](.github/workflows/secret-scan.yml) also runs on every push/PR, and a tagged
push builds and publishes the Docker image.

## Limitations

- The Instagram adapter currently handles single videos (`GraphVideo`) only — image posts and
  carousels are not downloaded.
- Twitter/Instagram downloads depend on third-party APIs that may rate-limit or change.

## Special thanks

The original idea was taken from the
[twitter_downloader_bot](https://github.com/skrimix/twitter_downloader_bot/) repository.

## License

See [LICENSE](LICENSE).
