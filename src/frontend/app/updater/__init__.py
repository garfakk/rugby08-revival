"""
app/updater — online updates from GitHub Releases, with no Qt in here.

Two channels, each with its own life cycle and versions:

  program   releases tagged v<version>: the program-only installer, checked
            against the release's SHA256SUMS, then run (visibly) to upgrade
            this install in place (program.py)
  data      releases tagged data-<version>: a data_manifest.json listing every
            data pack file with its sha256 and the commit holding them; only
            the files that differ from this install are downloaded, verified,
            and applied through app/updates.py (backups, undo) (data.py)

Where each channel lives (repo, tag prefix, asset names) is configuration
(sources.py): app_data/update_sources.json, overridable in config.ini
[Updates]. The data files are fetched from wherever the data manifest says
(repo + commit + prefix), so moving the data to its own repository only
changes configuration and the release scripts, not the program.

Nothing here rewrites the program's own files or runs anything hidden: see
program.py for why that matters (antivirus heuristics).
"""
