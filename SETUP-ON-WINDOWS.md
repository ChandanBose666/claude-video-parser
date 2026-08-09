# Setting this up on `E:\` with VSCode and GitHub

I could not reach your machine from this session — the desktop bridge never
attached, so `E:\` was not writable from here. Everything below is the manual
equivalent, and it takes about two minutes.

The zip already contains a git repo with the first commit made. You are not
starting from scratch.

## 1. Unzip

Extract `claude-skills.zip` so you end up with:

```
E:\Claude-skills\
    README.md
    skills\
    tests\
    ...
```

Not `E:\Claude-skills\claude-skills\` — check for a doubled folder after extracting.

## 2. Open in VSCode

```powershell
cd E:\Claude-skills
code .
```

VSCode will offer the recommended extensions from `.vscode\extensions.json`
(Python, Pylance, Claude Code, EditorConfig). Accept them.

`Ctrl+Shift+P` -> **Tasks: Run Task** gives you four preconfigured tasks:
run the tests, build the fixture video, extract keyframes from any video,
and install the skill.

## 3. Install ffmpeg

```powershell
winget install Gyan.FFmpeg
```

Open a **new** terminal afterwards so PATH refreshes, then confirm:

```powershell
ffmpeg -version
```

This is the only hard runtime dependency.

## 4. Verify the repo works

```powershell
python -m pip install pillow
python tests\test_extract.py
```

Expect 18 `PASS` lines and `all checks passed`. Pillow is only needed to
generate the synthetic test video — the skill itself does not use it.

## 5. Install the skill into Claude Code

```powershell
.\scripts\install.ps1
```

Installs to `%USERPROFILE%\.claude\skills\claude-video-parser`. Use
`-Project` instead to install into a single repo's `.claude\skills\`.

Restart Claude Code. Confirm it registered by asking Claude what skills it has.

## 6. Push to GitHub

The repo is already initialised on branch `main` with one commit, authored as
`Chandan Bose <bosechandan21@gmail.com>`. Change that first if you want a
different identity:

```powershell
git config user.name  "Your Name"
git config user.email "you@example.com"
git commit --amend --reset-author --no-edit
```

Then, with the GitHub CLI:

```powershell
winget install GitHub.cli
gh auth login
gh repo create claude-skills --public --source=. --remote=origin --push
```

Or manually — create an empty repo on github.com (no README, no .gitignore,
it would conflict), then:

```powershell
git remote add origin https://github.com/<your-username>/claude-skills.git
git push -u origin main
```

CI runs on push: Ubuntu + macOS + Windows, Python 3.10 and 3.12, plus a lint
job. It should go green without changes.

## 7. Resume work

When you resume work, open the repo in VSCode and start Claude Code — the README
and `skills/claude-video-parser/SKILL.md` carry everything needed to pick the
project back up.
