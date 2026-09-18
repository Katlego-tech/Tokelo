# Security basics

The kit's entire prior coverage of this was one line — *"Never commit `.env`, credentials, uploaded
user content, or generated artifacts."* True, and not enough: it names the rule without giving anyone
a way to follow it or a way to notice they didn't.

This is the practitioner's floor, drawn from Curriculum 200's Security Basics topic. Not a security
course — the handful of things that, left undone, cause the incident.

## Secrets

> A secret is any piece of information that we need to keep secure: private and confidential.
> — Curriculum 200, *Secrets and Password Management*

### The one property that changes how you treat them

A secret in git history is compromised **permanently**. Not "until you fix the commit" —
permanently. `git commit --amend`, a force-push, a rewritten branch: none of them help, because the
object may already be fetched, cached by the host, indexed by a scanner, or sitting in someone's
`reflog`. Public repos get scraped by bots within minutes.

So there is only one correct response to a leaked credential, and it is not deleting the commit:

1. **Rotate it.** Revoke the old value at the provider. Do this first, before anything else.
2. Then clean the history if you like — but the security work was step 1.

This asymmetry is why the gate blocks secrets *before* the push rather than scanning after: pre-push
is the last moment the fix is still free.

### Basic principles

- **Secrets live in the environment, never in source.** `os.environ["API_KEY"]`, not `API_KEY = "sk-..."`.
- **`.env` is git-ignored; `.env.example` is committed** — same keys, dummy values, so a new
  contributor knows what to set without ever seeing a real one.
- **Never paste a secret into a chat with an AI copilot.** It goes into a transcript you don't
  control. Give it the variable name and let it write the lookup.
- **Different secret per environment.** A dev key that also works in prod is a prod key.
- **Use a password manager** for anything a human has to hold. A shared vault beats a shared doc,
  and both beat "it's in the group chat".
- **Least privilege, short life.** A token scoped to one repo and expiring in 90 days limits what a
  leak costs. Most tokens are created with far more power than the job needs.

### What the gate checks

[`scripts/gate.sh`](../scripts/gate.sh) sweeps the files being pushed for committed `.env` files,
well-known key shapes (AWS, OpenAI, GitHub, Slack, PEM private keys), and secret-shaped assignments
to string literals. It deliberately ignores `os.environ[...]`, `process.env`, and obvious placeholders.

Pattern-matching cannot catch every secret and doesn't claim to. It catches the ones that actually
leak: a committed `.env`, a pasted key, a hardcoded password. Treat a clean sweep as "no known
pattern matched", not "no secrets here".

## Dependencies with known vulnerabilities

Most of the code you ship is code you didn't write — every dependency, and everything *they* depend
on. When a vulnerability is published against one of them, your code becomes vulnerable without a
line of it changing.

The gate checks for this on every push and in CI: [osv-scanner](https://google.github.io/osv-scanner/)
reads every project's **committed lockfile** and checks each pinned version against
[OSV](https://osv.dev), which collects the GitHub, PyPI, npm and other advisory feeds.

- **A lockfile is required.** Without one there is no exact version to check, so a project with no
  committed lockfile fails the gate. (It also breaks reproducible installs —
  [architecture-defaults.md](architecture-defaults.md) §5.)
- **The result can change while your code doesn't.** An advisory published tonight fails
  tomorrow's push on a branch nobody touched. That isn't the gate being flaky; it's the gate
  telling you something new and true.
- **The fix is to upgrade** to the version the report lists as fixed.
- **Only when no fix exists yet**, declare it in `osv-scanner.toml` at the repo root, with the task
  that will close it and a date the exemption runs out:
  ```toml
  [[IgnoredVulns]]
  id = "GHSA-xxxx-xxxx-xxxx"
  ignoreUntil = 2026-12-31
  reason = "T045: no patched release yet; upgrade when 2.4 ships"
  ```
  The gate rejects an exemption whose reason names no task, and prints every accepted one on every
  run, so none goes quiet. After `ignoreUntil`, the vulnerability fails the gate again.
- **Every machine that pushes needs osv-scanner installed**
  ([installation](https://google.github.io/osv-scanner/installation/)). CI installs a pinned,
  checksum-verified release.

## SSH — how you authenticate to the remote

> Secure Shell (SSH) is a network protocol that allows us to access a computer over a network
> securely by encrypting the connection. — Curriculum 200, *SSH Authentication*

Use SSH remotes rather than HTTPS-with-a-token: the key never leaves your machine, and there's no
token to accidentally paste somewhere.

```bash
ssh-keygen -t ed25519 -C "you@example.com"   # ed25519, not RSA
cat ~/.ssh/id_ed25519.pub                     # add THIS to GitHub/GitLab
```

The `.pub` file is the one you share. The other one never leaves the machine, never gets copied to a
second machine "just this once", and never gets committed — generate a separate key per machine, and
revoke by removing that one key.

Set a passphrase on the key. Without one, anyone with your laptop has your repos.

## Signing — proving a commit is yours

> You will use PGP with Git to prove that your work (git commits) belong to you and not anyone else.
> — Curriculum 200, *PGP Signing*

`git config user.name` is an unverified claim. Anyone can set it to yours and push. Signing makes
authorship checkable.

This matters more here than on a typical project, because on a repo with several AI copilots the
STATUS.md Log is the record of who did what — and a record that can be forged trivially is a record
you can't lean on when something goes wrong.

```bash
# SSH signing — simplest if you already have an SSH key
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519.pub
git config --global commit.gpgsign true
```

Then add the key as a **signing key** on GitHub/GitLab (a separate setting from the auth key, even if
it's the same key) and commits show as **Verified**.

## Encryption, briefly

Enough to reason about the choices you'll actually face:

- **Hash** — one-way. Same input, same output; can't be reversed. Used to *verify*, not to hide.
  **Passwords are hashed, never encrypted** — with a slow, salted algorithm (`argon2`, `bcrypt`),
  never `md5`/`sha1`, and never one you wrote.
- **Symmetric** — one key encrypts and decrypts. Fast; the problem is getting the key to the other
  side safely.
- **Asymmetric** — a public key encrypts, a private key decrypts. Solves key distribution, which is
  what makes HTTPS possible between strangers.
- **Signing** — asymmetric in reverse: the *private* key signs, and anyone with the public key can
  verify it. Proves origin and integrity; proves nothing about secrecy.

Two rules that follow from this and cover most real decisions:

- **Don't implement crypto.** Use the vetted library. Every rule here is a summary of a mistake
  someone shipped.
- **TLS everywhere, including internally.** Service-to-service traffic inside a private network is
  still traffic on a network someone can be inside of.

## Checklist

- [ ] `.env` in `.gitignore`; `.env.example` committed with dummy values
- [ ] No secret in any tracked file — `bash scripts/gate.sh` sweeps for the common shapes
- [ ] Lockfiles committed, `osv-scanner` installed, and no known vulnerability without a
      task-linked, expiring exemption in `osv-scanner.toml`
- [ ] Secrets read from the environment, injected by the platform in deploys
- [ ] SSH key is `ed25519`, has a passphrase, is per-machine
- [ ] Commit signing on, key registered, commits show **Verified**
- [ ] Passwords hashed with `argon2`/`bcrypt` — never encrypted, never `md5`
- [ ] TLS on every external endpoint
- [ ] Tokens scoped to the minimum and given an expiry
- [ ] A leaked credential is **rotated first**, cleaned from history second

## Where this shows up

- [`scripts/gate.sh`](../scripts/gate.sh) — the secret sweep and the dependency vulnerability scan
  run on every push and in CI.
- [git-workflow.md](git-workflow.md#signing-your-commits) — signing setup, secrets & artifacts.
- [architecture-defaults.md](architecture-defaults.md) — pinned versions; an unpinned dependency is a
  supply-chain decision made by whoever published last.
