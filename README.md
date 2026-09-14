# Bazzite Sunshine Manager

> **This is 4o66's fork**, version **`2.0+4o66.0.1.0`** -- upstream's 2.0 with
> this fork's 0.1.0 on top -- built on upstream
> [wadiebs/bazzite-sunshine-manager](https://github.com/wadiebs/bazzite-sunshine-manager)
> **2.0** at commit [`4bedee5`](https://github.com/wadiebs/bazzite-sunshine-manager/commit/4bedee5)
> (2026-04-19). The part after `+` is build metadata in the SemVer sense, so
> this never claims to be newer or older than upstream's 2.0, only to be built
> from it. Upstream publishes no tags or releases and has called itself 2.0 in
> every commit it has made, so the commit is the only exact way to say what this
> is built on. Every plan document repeats both, under `generator`.
>
> **What this fork adds.** Upstream rewrote `apps.json` from scratch on every
> run, which deleted anything added through Sunshine's own web UI, including the
> entries Sunshine ships with. This fork merges instead:
>
> - A three-way reconcile that records which entries and which individual fields
>   it owns, so anything edited by hand is kept and stops being overwritten.
> - Tombstones: something deleted stays deleted rather than reappearing on the
>   next scan, and can be restored deliberately.
> - Sunshine's own default entries are recognised, preserved, and restorable.
> - A JSON contract (`--state`, `--dry-run --json`, `--mutate`, `--browse`,
>   `--art-search`) so a front end can drive it without reimplementing any of
>   those rules. [sunshine-apps-ui](https://github.com/4o66/sunshine-apps-ui) is
>   that front end.
> - Reload without restarting: changes reach Sunshine through its own API, so
>   applying them does not require restarting the service.
> - An artwork picker that offers every cover it can find -- Steam's local
>   library cache, Valve's CDN, SteamGridDB -- rather than the first that works.
> - Credentials and the SteamGridDB key read on stdin and stored mode 600,
>   instead of `--sgdb-key` on the command line where `ps` can read it.
>
> Upstream's own README follows.

A lightweight tool to import Steam, Heroic (Epic/GOG/Amazon), and Lutris games into [Sunshine](https://github.com/LizardByte/Sunshine).  
It scans local libraries, applies blacklists, fetches cover art (Steam CDN or SteamGridDB), and safely merges everything into Sunshine’s `apps.json`.

this tool is optimized to run under [Bazzite](https://github.com/ublue-os/bazzite).

## ✨ Features
- Import installed Steam games
- Import installed Heroic games (GOG, Epic, Amazon, Standalone)
- Blacklist by AppID or regex
- Cover art via Steam CDN, Heroic cache or SteamGrid

## 🚀 Quick start
Ensure sunshine is enabled
```bash
ujust setup-sunshine
```
Choice enable is not enabled yet

1. Init command
Launch the init script, it will:
- create clone the repository into /var/home/steam/.config/sunshine/helper and configure ownership/permissions
- create a symbolic link for sunshine-import.sh in `~/.local/bin` for easy further use
- In case it is not the first run, the init command will update the existing files 
```bash
curl -fsSL https://raw.githubusercontent.com/wadiebs/bazzite-sunshine-manager/main/common/init.sh | bash
```

2. Import Script 
To run the import of games to sunshine process:
```bash
sunshine-import
```

To run it with steamgrid enabled and restart sunshine service after import:
```bash
sunshine-import --sgdb-key "YOUR_STEAMGRID_API" --restart
```


