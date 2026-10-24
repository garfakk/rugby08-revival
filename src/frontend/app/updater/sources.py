"""
app/updater/sources.py — where each update channel lives.

app_data/update_sources.json (shipped with the program, src/ from source):

  {"program": {"repo": "owner/repo", "tag_prefix": "v",
               "installer": "R08Revival_{version}_program_only.exe",
               "checksums": "SHA256SUMS"},
   "data":    {"repo": "owner/repo", "tag_prefix": "data-",
               "manifest": "data_manifest.json"}}

Any key can be overridden in user_data/config.ini:

  [Updates]
  data_repo = owner/rugby08-data
  data_tag_prefix = data-

Splitting the data into its own repository is a change of `data.repo` here
(and in the release scripts); the data files themselves are fetched from
wherever each data release's manifest says.
"""
import configparser
import json
import os

DEFAULTS = {
    "program": {"repo": "garfakk/rugby08-revival", "tag_prefix": "v",
                "installer": "R08Revival_{version}_program_only.exe", "checksums": "SHA256SUMS"},
    "data": {"repo": "garfakk/rugby08-revival", "tag_prefix": "data-",
             "manifest": "data_manifest.json"},
}
FILE = "update_sources.json"


def load(app_data_dir=None, config_ini=None):
    """{channel: {key: value}}: the defaults, then the shipped file, then
    config.ini [Updates] <channel>_<key> overrides."""
    if app_data_dir is None or config_ini is None:
        from shared.app_paths import app_data_directory, user_data_directory
        app_data_dir = app_data_dir or app_data_directory()
        config_ini = config_ini or os.path.join(user_data_directory(), "config.ini")
    out = {ch: dict(v) for ch, v in DEFAULTS.items()}
    try:
        with open(os.path.join(app_data_dir, FILE), encoding="utf-8") as fh:
            shipped = json.load(fh)
        for ch, values in (shipped or {}).items():
            if ch in out and isinstance(values, dict):
                out[ch].update({k: str(v) for k, v in values.items()})
    except (OSError, ValueError):
        pass
    cp = configparser.ConfigParser(strict=False)
    try:
        cp.read(config_ini, encoding="utf-8")
    except (OSError, configparser.Error):
        pass
    if cp.has_section("Updates"):
        for key, value in cp.items("Updates"):
            ch, _, name = key.partition("_")
            if ch in out and name and value.strip():
                out[ch][name] = value.strip()
    return out
