# SETUP.md — Lambda Labs VM for `proteinclaw` development

**Target:** Lambda Labs **A100 40GB** instance, **persistent filesystem** for caches, **interactive development over SSH + tmux**.

> **GPU note:** A100 40GB is the comfortable target, but the pipeline also runs on **22 GB-class cards** — verified on an **NVIDIA A10 (reports ~23028 MiB → 22 GB)**, which clears the global VRAM floor (lowered 24→22 in commit `b5e222d`) exactly. On a 22 GB card, AF2-multimer on large binder+target complexes (>~400 residues) is the tightest step and may OOM — keep binders short. The fix for OOM is a smaller binder / fewer recycles, **not** lowering the floor (that only removes the guardrail). The §1–§2 commands below also assume a bare Ubuntu 24.04 image (no preinstalled driver/Docker) and a persistent-FS mount name that varies per account (e.g. `/lambda/nfs/Daanish2`) — see the dated `NOTES.md` "Tooling & environment" entries for the exact, current bring-up.

This is the "build & test" environment. You'll SSH in, attach to tmux, install ProteinClaw with `uv`, configure Hermes/provider credentials, and run `proteinclaw doctor` before campaigns.

---

## 0. What you'll need before starting

| | Where to get it |
|---|---|
| Lambda Labs account + payment method | https://lambdalabs.com |
| GitHub access to this repo | (already set up — `git remote -v` confirms) |
| **Hermes provider credential** | Recommended: `OPENROUTER_API_KEY`. Direct provider keys such as `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` also work when supported by Hermes. |
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
mkdir -p $PERSIST/proteinclaw-home          # for ~/.proteinclaw (runs.db, doctor_ok)
mkdir -p $PERSIST/hermes-home               # for $HERMES_HOME (config.yaml, .env, skills)

# Symlink the standard paths to it
mkdir -p ~/.cache
ln -sfn $PERSIST/proteinclaw-cache/huggingface   ~/.cache/huggingface
ln -sfn $PERSIST/proteinclaw-cache/rfdiffusion   ~/.cache/rfdiffusion
ln -sfn $PERSIST/proteinclaw-cache/proteinmpnn   ~/.cache/proteinmpnn
ln -sfn $PERSIST/proteinclaw-cache/openfold      ~/.cache/openfold
ln -sfn $PERSIST/proteinclaw-home                ~/.proteinclaw
ln -sfn $PERSIST/hermes-home                     ~/.hermes

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

# 5. Re-create Hermes provider config / .env if needed, then run
#    proteinclaw doctor (should pass once everything above is done).
```

---

## 3. Configure Hermes provider auth

```bash
mkdir -p ~/.hermes
chmod 700 ~/.hermes

# Recommended: OpenRouter, because Hermes can route the default
# anthropic/claude-sonnet-4.6 model through it.
cat > ~/.hermes/.env <<'EOF'
OPENROUTER_API_KEY=sk-or-...
EOF
chmod 600 ~/.hermes/.env
```

Alternative: export a provider key in the shell that runs ProteinClaw:

```bash
export OPENROUTER_API_KEY=sk-or-...
# or ANTHROPIC_API_KEY / OPENAI_API_KEY / another provider key supported by Hermes
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

## 5. Hermes auth and model selection

The `proteinclaw` agent runs on **hermes-agent** (`run_agent.AIAgent`).
Hermes reads provider credentials from environment variables, `$HERMES_HOME/.env`,
and `$HERMES_HOME/config.yaml`. For Codex subscription-backed runs, install and
log in to the Codex CLI, then use a Codex model at runtime:

```bash
codex login
uv run proteinclaw run "..." --model gpt-5.1-codex
```

```bash
mkdir -p ~/.hermes
cat > ~/.hermes/.env <<'EOF'
OPENROUTER_API_KEY=sk-or-...
EOF
chmod 600 ~/.hermes/.env
```

Optional Hermes config:

```bash
cat > ~/.hermes/config.yaml <<'EOF'
model:
  provider: openrouter
  model: anthropic/claude-sonnet-4.6
EOF
chmod 600 ~/.hermes/config.yaml
```

`proteinclaw doctor` checks for `hermes-agent` importability plus either a
provider key, Hermes config, or Codex CLI auth. A real campaign still fails at
`AIAgent` construction if Hermes cannot resolve a usable provider credential or
Codex CLI session for the model you selected. For Codex runs, ProteinClaw writes
a per-run MCP bridge into Codex config so the Codex app-server can call
ProteinClaw's domain tools.

**Never commit provider keys.** Keep them in the VM environment or
`~/.hermes/.env`, which should live on the persistent FS via the §2 symlink.

---

## 6. Install tmux and a baseline Python toolchain

```bash
sudo apt-get install -y tmux python3.11 python3.11-venv python3-pip
curl -LsSf https://astral.sh/uv/install.sh | sh        # uv for fast envs
source $HOME/.local/bin/env
```

```bash
cd ~/code/ProteinClaw
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

---

## 7. The actual working loop

This is what you'll do every session:

```bash
ssh ubuntu@<vm-ip>
tmux new -s claw         # or `tmux attach -t claw` if it already exists
cd ~/code/ProteinClaw
git pull
proteinclaw doctor
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
You're on a Lambda Labs A100 40GB VM. Persistent FS is mounted; ~/.cache, ~/.proteinclaw, and ~/.hermes are symlinked into it (so weight caches, Hermes config, and active skills survive VM restarts). Docker + NVIDIA Container Toolkit are installed. Hermes provider credentials are present in ~/.hermes/.env or the shell environment.

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
| `hermes-auth FAIL` | Missing provider key/config | Add `OPENROUTER_API_KEY` to `~/.hermes/.env` or export it in the shell |
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
- **No multi-user.** One developer per VM; concurrent users will fight over the GPU (and could race on agent self-evolution skill edits).
- **No production hosting.** This is dev/test only. Production deployment isn't in scope for v1.

**Self-evolution note:** repo skill files seed active Hermes skills under `$HERMES_HOME/skills/proteinclaw`. During a run the agent may use Hermes `skill_manage` to append durable lessons there. After a self-evolving run, review with `proteinclaw skills diff` / `skills log`, validate with `skills check`, then commit the intended seed-file changes manually or `skills reset`.
