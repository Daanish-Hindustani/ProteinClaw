# SETUP.md — Lambda Labs VM for `proteinclaw` development

**Target:** Lambda Labs **A100 40GB** instance, **persistent filesystem** for caches, **interactive Claude Code over SSH + tmux**.

> **GPU note:** A100 40GB is the comfortable target, but the pipeline also runs on **22 GB-class cards** — verified on an **NVIDIA A10 (reports ~23028 MiB → 22 GB)**, which clears the global VRAM floor (lowered 24→22 in commit `b5e222d`) exactly. On a 22 GB card, AF2-multimer on large binder+target complexes (>~400 residues) is the tightest step and may OOM — keep binders short. The fix for OOM is a smaller binder / fewer recycles, **not** lowering the floor (that only removes the guardrail). The §1–§2 commands below also assume a bare Ubuntu 24.04 image (no preinstalled driver/Docker) and a persistent-FS mount name that varies per account (e.g. `/lambda/nfs/Daanish2`) — see the dated `NOTES.md` "Tooling & environment" entries for the exact, current bring-up.

This is the "build & test" environment. You'll SSH in, attach to tmux, run `claude`, and let it work through `PLAN.md` Task 1 → Task 12 with you steering.

---

## 0. What you'll need before starting

| | Where to get it |
|---|---|
| Lambda Labs account + payment method | https://lambdalabs.com |
| GitHub access to this repo | (already set up — `git remote -v` confirms) |
| **Claude Pro/Max subscription** | https://claude.ai — `claude login` (NOT an API key) so the Agent SDK uses OAuth + your subscription credit pool. Do NOT set `ANTHROPIC_API_KEY` (it silently overrides OAuth and switches you to pay-as-you-go). |
| Your local SSH public key | `~/.ssh/id_ed25519.pub` or similar |

Keep both API keys handy — they live on the VM, never in the repo.

---

## 1. Launch the VM

1. Lambda console → **Launch instance** → **1× A100 40GB SXM4** (or PCIe; either is fine for this workload).
2. **Region:** pick one with persistent-filesystem support (us-east-1, us-west-1, us-west-2 all have it as of writing).
3. **Filesystems:** create or attach a persistent filesystem — call it `proteinclaw-cache`, size **200 GB** to start (weights ~50 GB, run artifacts grow). You can resize later.
4. **SSH key:** upload your public key if not already there.
5. Launch. Note the public IP.

```bash
ssh ubuntu@<vm-ip>
```

Lambda's base image ships with NVIDIA drivers, CUDA, Docker, and the NVIDIA Container Toolkit pre-installed. Verify:

```bash
nvidia-smi                                          # should show A100 40GB
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi  # GPU visible inside container
df -h /home/ubuntu/<persist-mount>                  # persistent FS mounted
```

If `docker` requires sudo, add yourself once: `sudo usermod -aG docker $USER && newgrp docker`.

---

## 2. Wire up the persistent filesystem **(do this FIRST, before anything else downloads)**

Lambda mounts persistent filesystems under `/lambda/nfs/<filesystem-name>/` via virtiofs. Confirm the actual mount path on your VM:

```bash
mount | grep -i lambda          # e.g.  /lambda/nfs/Daanishfiles  (virtiofs)
df -h /lambda/nfs/*             # confirm the FS is mounted + has space
```

Symlink every cache directory into it BEFORE running `proteinclaw doctor` or any other tool — once weights start downloading to the ephemeral boot disk they're a 23 GB+ headache to migrate later:

```bash
PERSIST=/lambda/nfs/Daanishfiles   # your filesystem name varies — `ls /lambda/nfs/`

# Create the canonical cache layout on the persistent FS
mkdir -p $PERSIST/proteinclaw-cache/{huggingface,rfdiffusion,proteinmpnn,openfold}
mkdir -p $PERSIST/proteinclaw-home          # for ~/.proteinclaw (runs.db, doctor_ok, config.toml)

# Symlink the standard paths to it
mkdir -p ~/.cache
ln -sfn $PERSIST/proteinclaw-cache/huggingface   ~/.cache/huggingface
ln -sfn $PERSIST/proteinclaw-cache/rfdiffusion   ~/.cache/rfdiffusion
ln -sfn $PERSIST/proteinclaw-cache/proteinmpnn   ~/.cache/proteinmpnn
ln -sfn $PERSIST/proteinclaw-cache/openfold      ~/.cache/openfold
ln -sfn $PERSIST/proteinclaw-home                ~/.proteinclaw

# Sanity — every entry should be a symlink (l) pointing into /lambda/nfs/
ls -la ~/.cache ~/.proteinclaw
```

After this, weights download once and persist across any VM lifecycle. Everything else (Docker images, the venv, the repo) is reproducible from the code in `git`, so it lives on the ephemeral boot disk by design — DO NOT put the repo on the persistent FS (one corrupted working tree would poison shared storage).

> ⚠️ **The 2026-05-23 session this codebase was built in did NOT wire up
> these symlinks** before model downloads happened. Result: 23 GB of
> weights + 60 GB of Docker images lived on the boot disk and died with
> the VM. Don't repeat that mistake — do §2 first.

### Resuming on a fresh VM (re-attaching the persistent FS)

If you killed the VM and are bringing up a new one with the same persistent filesystem attached:

```bash
# 1. Confirm the FS re-attached.
ls /lambda/nfs/Daanishfiles/proteinclaw-cache/    # huggingface/ etc. should be here

# 2. Re-create the symlinks (boot disk is fresh).
PERSIST=/lambda/nfs/Daanishfiles
mkdir -p ~/.cache
for d in huggingface rfdiffusion proteinmpnn openfold; do
  ln -sfn $PERSIST/proteinclaw-cache/$d ~/.cache/$d
done
ln -sfn $PERSIST/proteinclaw-home ~/.proteinclaw

# 3. Re-install everything that lives on the boot disk (drivers, Docker,
#    nvidia-ctk, Node, claude, uv, the repo, the venv). Walk §1, §3-§6 again.

# 4. Re-build the Docker images from the repo's tools/*/Dockerfile.
#    The build context is staged automatically by LocalRunner the first
#    time you `proteinclaw run`; or trigger explicitly with the steps
#    in NOTES.md (search for "rebuild image" entries per tool).
#    Each image is ~3-15 GB; full rebuild is ~30-60 min on a fresh VM
#    with a cold pip cache.

# 5. claude login (OAuth re-issue) + proteinclaw doctor (should pass once
#    everything above is done).
```

---

## 3. Install Claude Code

```bash
# Install Node (Lambda image ships an older one; Claude Code wants 18+)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# Install Claude Code
npm install -g @anthropic-ai/claude-code

# Authenticate with your Claude.ai subscription (OAuth — NOT an API key; see §5).
# Choose "Claude.ai", not "Anthropic Console". Do NOT set ANTHROPIC_API_KEY.
claude login
```

`claude login` will walk you through pasting / exchanging the Anthropic key. Verify:

```bash
claude --version
which claude
```

---

## 4. Clone the repo

```bash
mkdir -p ~/code && cd ~/code
git clone <your-github-url> ProteinClaw
cd ProteinClaw
git checkout dvelopment        # current working branch
ls -la                          # README, PRD, ARCHITECTURE, PLAN, NOTES, CLAUDE all present
```

If you push from the VM, you'll need a deploy key or HTTPS token. Easiest path: `gh auth login` after installing GitHub CLI (`sudo apt install gh`).

---

## 5. Authenticate Claude — `claude login` (subscription path)

The `proteinclaw` agent runs on the **Claude Agent SDK**. The SDK reads
OAuth credentials from `~/.claude/.credentials.json` — the same file
`claude login` writes — so a Pro/Max subscriber gets **subscription
billing automatically** with no API key.

```bash
# Install Claude Code (you almost certainly already did this in §3).
npm install -g @anthropic-ai/claude-code

# Authenticate with your Claude.ai subscription account. When prompted
# for an account type, choose "Claude.ai" (NOT "Anthropic Console" — that
# would set up an API-key-billed account instead).
claude login
```

After login, verify by checking the credentials file:

```bash
ls -la ~/.claude/.credentials.json   # 0600, owned by you
```

**One-time setup on Claude.ai**: visit your plan settings on
https://claude.ai and **claim your Agent SDK credit**. Each user must
claim their own; credits cannot be pooled, transferred, or shared. See
https://support.claude.com/en/articles/15036540 for the exact link in
plan settings.

### ⚠️ Trap to avoid: do NOT set `ANTHROPIC_API_KEY`

If `ANTHROPIC_API_KEY` is set in any shell that runs `proteinclaw`,
**the API key silently takes precedence** over your OAuth credentials,
and your run is billed against pay-as-you-go API credits — *not* your
subscription. `proteinclaw doctor` surfaces this as a `claude-auth WARN`,
but you should unset the variable up-front:

```bash
unset ANTHROPIC_API_KEY                 # current shell
sed -i '/ANTHROPIC_API_KEY/d' ~/.bashrc # any future shells
```

### Optional model selection (no key needed)

`~/.proteinclaw/config.toml` is for model selection only — no api_key
field needed for subscription billing:

```bash
mkdir -p ~/.proteinclaw
cat > ~/.proteinclaw/config.toml <<'EOF'
[anthropic]
model = "claude-opus-4-7"   # Sonnet/Haiku also fine
EOF
chmod 600 ~/.proteinclaw/config.toml
```

### When to use the API-key path instead

For shared CI, team automation, or any case where multiple users share
one execution environment, set `ANTHROPIC_API_KEY` and accept
pay-as-you-go billing. The subscription path is **per-individual-user
local use only** (Anthropic prohibits routing other users' traffic
through one subscription).

**Watch your subscription credit.** Pro = $20/month Agent SDK credit,
Max-5x = $100, Max-20x = $200. Unused credit does NOT roll over. A 1+
hour design campaign with many tool calls can consume a meaningful
slice; monitor via the Anthropic Console "Usage & Cost" page.

**Never commit `config.toml`.** It lives on the persistent FS (via the §2 symlink), so it survives VM restarts but never enters the repo.

---

## 6. Install tmux and a baseline Python toolchain

```bash
sudo apt-get install -y tmux python3.11 python3.11-venv python3-pip
curl -LsSf https://astral.sh/uv/install.sh | sh        # uv for fast envs
source $HOME/.local/bin/env
```

Once Task 1 lands `pyproject.toml`:

```bash
cd ~/code/ProteinClaw
uv venv && source .venv/bin/activate
uv pip install -e .
```

Until then, there's nothing to install — Claude will create `pyproject.toml` in Task 1.1.

---

## 7. The actual working loop

This is what you'll do every session:

```bash
ssh ubuntu@<vm-ip>
tmux new -s claw         # or `tmux attach -t claw` if it already exists
cd ~/code/ProteinClaw
git pull
claude                   # opens the interactive Claude Code prompt
```

Inside Claude Code, point it at the plan:

```
Read PLAN.md and NOTES.md. We're starting Task 1.1 (repo scaffolding + packaging). Follow the workflow in CLAUDE.md.
```

Detach with `Ctrl-b d`; the session keeps running even if your SSH drops. Re-attach anytime with `tmux attach -t claw`.

---

## 8. Cost discipline

A100 40GB is ~$1.30/hr on-demand. To avoid burn:

- **Stop the VM** (Lambda console → Stop) when you're not actively working. The persistent FS survives stop/start; the boot disk does too on stop (but not on terminate). Stopped VMs cost ~$0.
- **Terminate** only when you're done for a while; reprovisioning a fresh A100 in the same region usually takes <10 min, and your persistent FS re-attaches.
- **Watch ColabFold + AF2 runs** — a stuck AF2 job can burn an hour. Set conservative `--max-designs` early.
- Lambda doesn't bill while a VM is stopped, only while running.

---

## 9. First-session checklist for Claude Code

Paste this into your first Claude session so it knows the environment:

```
You're on a Lambda Labs A100 40GB VM. Persistent FS is mounted; ~/.cache, ~/.proteinclaw, and ~/.claude are symlinked into it (so weight caches AND Claude Code OAuth survive VM restarts). Docker + NVIDIA Container Toolkit are installed. `claude login` has been run (OAuth credentials at ~/.claude/.credentials.json) and ANTHROPIC_API_KEY is unset — the Claude Agent SDK uses OAuth and bills against the Pro/Max subscription credit pool.

Workflow per CLAUDE.md: read NOTES.md first, then start Task 1.1 from PLAN.md. Plan → Design → Test (RED) → Implement (GREEN) → Manual test → Code review → Update docs. Append to NOTES.md as you discover anything non-obvious.
```

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `docker: permission denied` | User not in docker group | `sudo usermod -aG docker $USER && newgrp docker` |
| `nvidia-smi: command not found` | NVIDIA drivers missing (rare on Lambda) | Reprovision; pick a Lambda Stack image |
| `docker run --gpus all` says no GPU | Container Toolkit not registered | `sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker` |
| Weights re-download every restart | Symlinks point at wrong path | Re-check §2; `readlink ~/.cache/huggingface` should resolve into the persistent FS mount |
| Claude Code asks to re-login | Token expired | `claude login` again |
| Out of disk on `/` | Repo or `/tmp` filling up | `du -sh ~/code/*`; persistent FS is for caches, not the repo |

---

## 11. What to add to `NOTES.md` once you're up

After the first successful boot, append a `Tooling & environment` entry to `NOTES.md`:

- Exact Lambda region + instance type used.
- Persistent FS mount path (varies by Lambda account).
- Any non-default sysctl / driver versions you ended up on.
- Pinned versions of `node`, `claude`, `uv`, `python` that worked.

This makes the next setup (or a teammate's) faster.

---

## 12. Non-goals for this setup

- **No CI on the VM.** Push to GitHub, let CI (when it exists) run there. The VM is for build + manual + GPU integration tests.
- **No multi-user.** One developer per VM; concurrent users will fight over the GPU.
- **No production hosting.** This is dev/test only. Production deployment isn't in scope for v1.
