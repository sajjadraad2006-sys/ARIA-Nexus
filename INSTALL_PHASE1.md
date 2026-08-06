# ARIA Windows Phase 1 scripts

This package adds the first two real Windows files:

- `scripts/doctor.py` — read-only project/runtime diagnostics using only Python's standard library.
- `scripts/setup_windows.ps1` — idempotent Python 3.12 core setup and baseline tests.

It intentionally does **not** install CUDA, download models, or start ARIA services yet.

## Install into the repository

Extract this package so the files appear under:

```text
C:\ARIA\Jaston-project\scripts\doctor.py
C:\ARIA\Jaston-project\scripts\setup_windows.ps1
```

## Run the doctor

```powershell
Set-Location C:\ARIA\Jaston-project
.\.venv\Scripts\python.exe .\scripts\doctor.py
```

Warnings about models, native binaries, and optional AI packages are expected.

## Run core setup

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

Do not pass `-InstallFullRequirements` yet. The optional AI stack will be installed and debugged separately.

## Verify and commit

```powershell
.\.venv\Scripts\python.exe .\backend\test_smoke.py
git diff --check
git status --short
git add scripts\doctor.py scripts\setup_windows.ps1
git commit -m "feat: add Windows setup and diagnostics"
git push
```
