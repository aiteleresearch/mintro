"""Publisher settings: fill these in before releasing your build. Empty values switch the feature off."""

# Your GitHub repository, "owner/name". Installed copies fall back to its latest release for updates
# (see docs/UPDATES.md).
GITHUB_REPO = "aiteleresearch/mintro"

# Where installed copies look for updates first: the release feed on MINTRO's website, in the same shape as
# GitHub's "latest release" API (the Aitele deployment serves it with the installer and the signed update).
UPDATE_FEED = "https://mintro.aiteleresearch.com/download/release.json"

# The public miner counter (server/stats, see docs/STATS.md), e.g. "https://mintro-stats.you.workers.dev".
# Installed copies send it an anonymous "I'm mining" heartbeat unless the person turns that off in Settings.
STATS_URL = ""

# The coin listings feed (listings.py). Leave empty to use listings/listings.json in GITHUB_REPO.
LISTINGS_URL = ""

# Your exchange referral codes, as the query string each exchange expects, e.g. {"mexc": "inviteCode=ABCD"}.
# Links get an "affiliate" label only when a code is set.
EXCHANGE_REFERRALS: dict[str, str] = {}

# Hardware wallets to suggest for coins they can hold, with your referral links if you have them.
HARDWARE_WALLETS = {
    "Ledger": {"url": "https://shop.ledger.com/", "ref": "", "coins": ["XMR"]},
    "Trezor": {"url": "https://trezor.io/", "ref": "", "coins": ["XMR"]},
}

# Your website
WEBSITE_URL = "https://mintro.aiteleresearch.com/"
