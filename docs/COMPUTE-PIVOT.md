# Design note: from mining to idle compute

Status: idea, not built. Written so the option is ready if mining stays marginal for laptops.

## Why

A laptop's mining earns cents a day, and miners are flagged by every antivirus. The same idle CPU and GPU time
can be sold to compute networks that pay in dollars or stablecoins for AI inference, rendering or batch jobs,
without the antivirus problem. MINTRO's real assets carry over: a floating card people trust to run in the
background, per-PC tuning, activity-aware throttling, battery and memory safety, and a one-click setup.

## Shape

- **Workloads instead of coins.** The basket becomes a list of workloads (a mining coin is one kind). Each has
  an estimated $/hour on this PC, requirements (GPU memory, RAM, disk, uptime) and a driver, like today's
  engine drivers in `mintro/miners.py`.
- **Same lanes.** `cpu` and `gpu` lanes stay; the scheduler picks the best-paying workload per lane, with the
  same rules: back off when the person is active, pause on battery, never swap.
- **Providers as drivers.** Each network has its own client and terms. A driver installs the provider's
  official client, starts and stops it, and reads its earnings. Candidates to evaluate: Salad (consumer GPUs),
  Vast.ai and similar marketplaces (hosts with good GPUs and uptime), Golem and Akash (decentralised), and
  BOINC projects as a no-payout "donate to science" option.
- **Earnings in one place.** The ledger keeps per-workload earnings in USD, and the tax report covers both.

## Questions to answer first

1. Which providers accept small, intermittent laptop hosts? Most want GPUs with 8 GB+ and long uptime.
2. Can a third-party app run their client within their terms, or does each user need their own account?
   (Likely the latter: MINTRO would then guide sign-up rather than hold accounts.)
3. Payout minimums and methods per provider.
4. Security: running other people's jobs needs strong isolation (the provider's container or VM), and the
   card must say plainly what runs on the PC.

## Smallest useful step

Add one provider as a GPU-lane driver, behind a toggle, and show its $/hour next to the mining
estimate. If it consistently pays more on common laptop GPUs, make it the GPU lane's default.
