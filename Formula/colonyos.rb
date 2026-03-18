# Homebrew formula for ColonyOS
# Install: brew tap colonyos/tap && brew install colonyos
# Or:      brew install colonyos/tap/colonyos
#
# NOTE: The url and sha256 below are automatically updated by the
# release workflow (.github/workflows/release.yml) on each tagged release.
# Before the first release, sha256 is a placeholder and `brew install` will
# fail with a checksum mismatch. This is intentional — the formula becomes
# functional after the first `v*` tag triggers the release workflow.
class Colonyos < Formula
  include Language::Python::Virtualenv

  desc "Autonomous agent loop that turns prompts into shipped PRs"
  homepage "https://github.com/rangelak/ColonyOS"
  url "https://files.pythonhosted.org/packages/source/c/colonyos/colonyos-0.0.2.tar.gz"
  sha256 "f6b681586b967b44a68e97b30d1e8c151e02137df0110c61557c41a32442916e"
  license "MIT"

  depends_on "python@3.11"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/colonyos --version")
  end
end
