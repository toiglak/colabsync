# `colabsync`

1. Respects git global and local ignores
2. Ignores directories with huge amounts of files (like pycache or node_modules but doesn't hardcode the logic for them since this is a fallback check when I forgot to include them in gitignore). Logs warning if gitignore doesn't include them and this rule caught that.
3. Ignores files larger than 2MB and logs that.
4. Respects .colabignore (e.g. you'd put there the notebook you're opening)
5. Automatically syncs repository changes from local to remote, where remote is Google Colab.

Typical Workflow:

1. Use colab vscode extension to open notebook (git-synced) in colab.
2. Local edits to that notebook sync automatically to colab through the extension.
3. This tool runs in the background and syncs the remaining repository files live from local to remote as the complementary to the extension which only syncs the notebook itself.
4. I can make changes, stage, edit with llms, commit locally, without ever having to resync anything manually to colab through awkward github push/pull, making tens of `chore` and `.` commits. It feels like working locally 99% of the time and I can iterate on the whole repository fast.
5. For persistent files, I do not sync them with colabsync, they're saved to a mounted google drive folder so they persist and stay close to google servers for faster syncs (checkpoints, datasets, etc.).

Yeah, so this tool will be called colabsync. Ignore file for this tool will be called .colabignore.

Would web sockets work?

As for sync itself cloudflare tunnel likely.

Installing this would probably be as simple as `curl github.com/toiglak/colabsync/colab-hook.sh && bash colab-hook.sh` or something and locally... probably `uvx tool install github.com/toiglak/colabsync` then -> `colabsync <url from colab>`?

Right, the hook script should install cloudflared, set up colabsync server, run it, receive url from cloudflared, generate an ssh key, and respond to the user with a formatted "join link" that local colabsync cli understands, for example: `colabsync_base64_or_something_encoded_tunnel_url_and_security_key_not_too_long_not_too_short`.

```shell
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update && sudo apt-get install cloudflared
```
