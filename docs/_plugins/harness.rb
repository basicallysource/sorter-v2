# Derives where this build's harness renders live, from the ref being built.
#
# CI publishes renders to harness/<ref>/ in the assets bucket (see
# electronics/wire_harness/AGENTS.md). This plugin computes the matching base
# URL for the ref THIS Jekyll build is building, so a branch preview links its
# own drawings and production links main's. Refs are mutable, so pages append
# {{ site.harness_v }} (a per-deploy ?v= cache-buster) to every harness URL;
# the objects themselves carry a short TTL as well.
#
# Ref resolution: Vercel exposes VERCEL_GIT_COMMIT_REF at build time; local
# `./serve.sh` falls back to the checked-out git branch. Both sides must use
# the ref RAW (no slugging) so the plugin and CI compute identical keys.

Jekyll::Hooks.register :site, :after_init do |site|
  ref = ENV["VERCEL_GIT_COMMIT_REF"].to_s
  ref = `git rev-parse --abbrev-ref HEAD 2>/dev/null`.strip if ref.empty?
  ref = "main" if ref.empty? || ref == "HEAD"

  sha = ENV["VERCEL_GIT_COMMIT_SHA"].to_s
  sha = `git rev-parse HEAD 2>/dev/null`.strip if sha.empty?

  site.config["harness_base"] = "https://img.basically.website/harness/#{ref}"
  site.config["harness_v"] = sha.empty? ? "" : "?v=#{sha[0, 12]}"
end
