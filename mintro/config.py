"""Publisher settings: fill these in before releasing your build. Empty values switch the feature off."""

# Your GitHub repository, "owner/name". Installed copies update themselves from its latest release
# (see docs/UPDATES.md), and the website's download counter reads its release downloads.
GITHUB_REPO = "aiteleresearch/mintro"

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
WEBSITE_URL = "https://aiteleresearch.github.io/mintro/"
