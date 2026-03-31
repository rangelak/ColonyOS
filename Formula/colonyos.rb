# Homebrew formula for ColonyOS — DEVELOPMENT REFERENCE ONLY
#
# The canonical formula lives in the Homebrew tap repository:
#   https://github.com/rangelak/homebrew-colonyos
#
# Install: brew install rangelak/colonyos/colonyos
#
# This in-repo copy is kept for reference only. The release workflow
# auto-generates the tap formula using scripts/generate-homebrew-formula.sh
# which includes all Python dependency resource blocks required by Homebrew.
#
# To regenerate the formula locally:
#   scripts/generate-homebrew-formula.sh <version> <sha256>
class Colonyos < Formula
  include Language::Python::Virtualenv

  desc "Autonomous agent loop that turns prompts into shipped PRs"
  homepage "https://github.com/rangelak/ColonyOS"
  url "https://files.pythonhosted.org/packages/source/c/colonyos/colonyos-0.0.3.tar.gz"
  sha256 "5fb79f63618de2a525a6545e87eefb594dd31e790ec77ee282da1d66878c8bdd"
  license "MIT"

  depends_on "python@3.11"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/colonyos --version")
  end
end
