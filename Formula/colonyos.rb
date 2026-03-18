# Homebrew formula for ColonyOS
# Install: brew tap colonyos/tap && brew install colonyos
# Or:      brew install colonyos/tap/colonyos
#
# NOTE: The url and sha256 below are automatically updated by the
# release workflow (.github/workflows/release.yml) on each tagged release.
class Colonyos < Formula
  include Language::Python::Virtualenv

  desc "Autonomous agent loop that turns prompts into shipped PRs"
  homepage "https://github.com/rangelak/ColonyOS"
  url "https://pypi.io/packages/source/c/colonyos/colonyos-0.1.0.tar.gz"
  sha256 "PLACEHOLDER_SHA256_UPDATED_BY_RELEASE_WORKFLOW"
  license "MIT"

  depends_on "python@3.11"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/colonyos --version")
  end
end
