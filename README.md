# `colabsync`

Sync local files into a running Google Colab session. No GitHub push/pull, no
manual uploads, and no Colab-side server or tunnel setup.

The Colab VS Code extension handles the notebook file itself. `colabsync`
handles everything else: source files, configs, scripts, and other files in
your local repository. Changes appear in Colab after you save them locally.

## How it works

`colabsync` uses the official Colab CLI's one-shot SSH command for every batch:

```text
colab ssh -s <session> -- python3
```

It pipes a generated Python script to that command. The script writes files
under `/content`, supports binary data, and removes only files that
`colabsync` previously synchronized. Each operation is serialized, so changes
that arrive during an SSH transfer remain queued. A failed transfer is retried;
after the connection returns, `colabsync` reconciles the current local tree
before applying queued changes.

## Setup and usage

Install both CLIs:

```sh
uv tool install google-colab-cli
uv tool install git+https://github.com/toiglak/colabsync.git
```

Create or select a Colab session with the Colab CLI. A session name makes the
target unambiguous:

```sh
colab new -s dev
```

From the local repository root, start the watcher:

```sh
colabsync --session dev
```

Use `--root` when the repository is elsewhere:

```sh
colabsync --session dev --root ~/projects/myrepo
```

If your SSH private key is passphrase-protected and is not loaded in an SSH
agent, pass it through to the Colab CLI:

```sh
colabsync --session dev --identity ~/.ssh/id_ed25519
```

`colabsync` performs an initial synchronization, reports transfer and
connection status, and keeps watching until Ctrl-C. Stop the runtime when you
are finished:

```sh
colab stop -s dev
```

## What gets synced

`colabsync` uses the existing file watcher and ignore filtering rules:

- **`.gitignore`** — global and local Git ignore rules are respected.
- **`.colabignore`** — an optional repository-root ignore file with Gitignore
  syntax.
- **Large directories** — directories with 100 or more entries are skipped,
  with a warning when Git does not already ignore them.
- **Large files** — individual files over 2 MB are skipped and logged.

Ignored files are never written or removed remotely. Remote-only files and
runtime-generated artifacts are preserved because reconciliation does not
delete paths that were not owned by this sync process.

A typical `.colabignore`:

```text
# The Colab extension handles the notebook.
my_experiment.ipynb
```

Changes flow one way: local to Colab. Persistent outputs such as checkpoints
and datasets should live in mounted Google Drive or another remote-managed
location.

## License

MIT
