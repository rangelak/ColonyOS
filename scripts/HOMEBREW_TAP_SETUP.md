# Homebrew Tap Repository Setup

One-time manual steps to create the `rangelak/homebrew-colonyos` tap repository.

## Step 1: Create the Tap Repository

```bash
gh repo create rangelak/homebrew-colonyos \
  --public \
  --description "Homebrew tap for ColonyOS" \
  --clone
```

## Step 2: Initialize the Repository

```bash
cd homebrew-colonyos
mkdir -p Formula

cat > README.md << 'EOF'
# Homebrew Tap for ColonyOS

Autonomous agent loop that turns prompts into shipped PRs.

## Install

```bash
brew install rangelak/colonyos/colonyos
```

## Upgrade

```bash
brew upgrade colonyos
```

## About

This tap is auto-updated by the [ColonyOS release workflow](https://github.com/rangelak/ColonyOS/blob/main/.github/workflows/release.yml) on every tagged release. Do not edit the formula manually.
EOF

git add .
git commit -m "Initial tap repository setup"
git push origin main
```

## Step 3: Create a Fine-Grained PAT

1. Go to https://github.com/settings/personal-access-tokens/new
2. Name: `colonyos-homebrew-tap`
3. Expiration: 1 year (set a reminder to rotate)
4. Repository access: Only select `rangelak/homebrew-colonyos`
5. Permissions:
   - Contents: **Read and write**
   - (No other permissions needed)
6. Generate token and copy it

## Step 4: Add the PAT as a Repository Secret

```bash
# In the ColonyOS repo:
gh secret set HOMEBREW_TAP_TOKEN --env pypi
# Paste the PAT when prompted
```

## Step 5: Verify

After the next tagged release (`v*`), the `update-homebrew` job in the release
workflow will automatically generate and push an updated formula to the tap repo.

To test manually:

```bash
# Generate a formula (requires the package to be on PyPI)
scripts/generate-homebrew-formula.sh 0.0.3 5fb79f63618de2a525a6545e87eefb594dd31e790ec77ee282da1d66878c8bdd
```
