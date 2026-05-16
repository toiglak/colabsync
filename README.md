# `colabsync`

Syncs a local repository into a running Google Colab session, live.

The Colab VS Code extension handles the notebook file itself. colabsync handles everything else: source files, configs, scripts — whatever is in your repo. Changes appear in Colab the moment you save them locally.

No GitHub push/pull. No manual uploads. No `chore: sync` commits.

## How it works

1. You run a setup cell in Colab that installs cloudflared, starts a small WebSocket server, and opens a Cloudflare Quick Tunnel to expose it.
2. The cell prints a join link.
3. You run `colabsync <join-link>` locally. It performs an initial full sync, then watches for file changes using your OS's native file-change notifications.

Changes flow one way: local to Colab. Persistent outputs (checkpoints, datasets) live in mounted Google Drive and are never touched by this tool.

## Colab setup

Paste this into Colab terminal and run it:

```python
uv tool install git+https://github.com/toiglak/colabsync.git
colabsync start
```

It will print something like:

```sh
colabsync cs1_aHR0cHM6Ly9...
```

## Local usage

Install:

```sh
uv tool install git+https://github.com/toiglak/colabsync.git
```

Run, pointing at the root of the repository you want to sync:

```sh
colabsync cs1_aHR0cHM6Ly9...
```

Or with an explicit root:

```sh
colabsync join colabsync_... --root ~/projects/myrepo
```

colabsync keeps running and reconnects automatically if the connection drops. Stop it with Ctrl-C.

## What gets synced

colabsync filters files using the same rules as git, plus a few extras:

- **`.gitignore`** — global and all local `.gitignore` files are respected.
- **`.colabignore`** — an optional file in your repo root, same syntax as `.gitignore`. Use it to exclude the notebook itself or any other files you don't want pushed.
- **Large directories** — any directory with 1,000+ entries is skipped automatically. If it isn't already covered by `.gitignore`, a warning is printed reminding you to add it.
- **Large files** — individual files over 2 MB are skipped and logged.

A typical `.colabignore`:

```
# Don't push the notebook — the Colab extension handles that
my_experiment.ipynb
```

## License

MIT
