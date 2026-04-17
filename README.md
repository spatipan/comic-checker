# comic-checker

Polls configured manga series for new chapters by HTTP-probing sequential chapter URLs, and sends a Telegram notification when a new one is live. State (last-seen chapter per series) is persisted to `src/state.json`.

## Requirements

- Python 3.10+
- [`uv`](https://docs.astral.sh/uv/)

## Local run

```sh
uv sync
uv run python main.py
```

### Environment variables

Set in `.env` (gitignored) or your shell:

| Var          | Purpose                                     |
| ------------ | ------------------------------------------- |
| `TG_TOKEN`   | Telegram bot token (optional in dev)        |
| `TG_CHAT_ID` | Telegram chat ID to notify                  |
| `LOG_LEVEL`  | `DEBUG` / `INFO` / `WARNING` (default INFO) |

If `TG_TOKEN` or `TG_CHAT_ID` is unset, the checker still runs and logs results — it just skips notifications.

## Configuration

Edit `config/subscription.yaml`:

```yaml
subscription:
  - name: "Eternally Regressing Knight"
    url: "https://w8.regressingknight.com/eternally-regressing-knight-chapter-{chapter}/"
    notify: true
```

`{chapter}` is the integer placeholder (no padding). To add a series, append another entry. To stop notifying for a series, set `notify: false`.

State is tracked per `name`, so renaming a series resets its state.

## Scheduled runs (GitHub Actions)

`.github/workflows/check-manga.yml` runs the checker at 08:00 / 14:00 / 20:00 Bangkok time (`0 1,7,13 * * *` UTC), plus on-demand via the Actions tab → *Run workflow*.

The workflow commits `src/state.json` back to the default branch after each run so state survives across ephemeral runners. Commits are authored by `github-actions[bot]` with `[skip ci]` to keep history readable.

### Setup

1. Push this repo to GitHub.
2. Add repository secrets (Settings → Secrets and variables → Actions):
   - `TG_TOKEN`
   - `TG_CHAT_ID`
3. The schedule only runs on the default branch.
