# Homebrew Tap: One-Time Setup Guide

This document describes the one-time setup steps required for the automated
Homebrew tap update to work in the release workflow.

## Overview

When a new version is tagged (`v*`), the release workflow:
1. Builds and publishes the package to PyPI
2. Generates an updated Homebrew formula with all dependency resource blocks
3. Pushes the formula to the `rangelak/homebrew-colonyos` tap repository

Step 3 requires a fine-grained Personal Access Token (PAT) with write access to
the tap repository.

## Step 1: Create the Tap Repository

If not already created:

```bash
gh repo create rangelak/homebrew-colonyos --public \
  --description "Homebrew tap for ColonyOS"
```

Add a minimal `README.md` to the tap repo:

```bash
cd /tmp && git clone https://github.com/rangelak/homebrew-colonyos.git
cd homebrew-colonyos
mkdir -p Formula
cat > README.md << 'EOF'
# homebrew-colonyos

Homebrew tap for [ColonyOS](https://github.com/rangelak/ColonyOS).

## Install

```bash
brew install rangelak/colonyos/colonyos
```
EOF
git add . && git commit -m "Initial tap setup" && git push
```

## Step 2: Create a Fine-Grained PAT

1. Go to https://github.com/settings/personal-access-tokens/new
2. **Token name**: `colonyos-homebrew-tap`
3. **Expiration**: 1 year (set a calendar reminder to rotate)
4. **Repository access**: Select "Only select repositories" → `rangelak/homebrew-colonyos`
5. **Permissions**:
   - **Contents**: Read and write (required to push formula updates)
6. Click **Generate token** and copy the value

## Step 3: Add the PAT as a Repository Secret

1. Go to https://github.com/rangelak/ColonyOS/settings/secrets/actions
2. Click **New repository secret**
3. **Name**: `HOMEBREW_TAP_TOKEN`
4. **Value**: Paste the PAT from Step 2
5. Click **Add secret**

> **Note**: The secret is available to all workflow jobs by default. The
> `update-homebrew` job is the only one that references it.

## Step 4: Verify

Push a test tag to trigger the release workflow:

```bash
git tag v0.0.0-test
git push origin v0.0.0-test
```

Check the Actions tab to confirm the `update-homebrew` job succeeds, then
delete the test tag:

```bash
git push origin --delete v0.0.0-test
git tag -d v0.0.0-test
```

## Rotating the PAT

When the PAT expires:
1. Create a new PAT following Step 2
2. Update the `HOMEBREW_TAP_TOKEN` secret following Step 3
3. No workflow changes needed

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `update-homebrew` job fails with 403 | PAT expired or insufficient permissions | Rotate the PAT (Steps 2-3) |
| `update-homebrew` job fails with "repo not found" | Tap repo doesn't exist | Create it (Step 1) |
| Formula generation fails | `homebrew-pypi-poet` can't install deps | Check PyPI availability; ensure `colonyos` is published first |
