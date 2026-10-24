Rugby 08 Revival
============
Run R08Revival.exe.

Where things live (everything is inside the one install folder; nothing in AppData)
  R08Revival.exe, _internal\   the program (replaced when the program is updated)
  app_data\                    assets, README, credits (read-only)
  mod_data\                    players, teams, kits, stadiums, tournaments. Updated by installing
                               a data pack; edited files are copied to mod_data\_backup\<date> first.
  user_data\                   config.ini (game folder), user_prefs.ini, game_profile.ini and
                               R08Revival.log (attach it to bug reports). For more detail set
                               log_level = DEBUG in the [Options] section of config.ini
                               (levels: DEBUG, INFO (default), WARNING, ERROR).
                               edits\ holds your changes made in the team and player editors:
                               they are used instead of mod_data\ and a new data pack never
                               overwrites them (Tools > My edits: turn them off/on, settle
                               what a new data pack changed too, drop an edit, export your
                               edits to send them to the mod's maintainers).
  game_files\                  the copy of Rugby 08 the mod works on (your original is untouched)

Updates
  Tools > Updates looks on GitHub for a new program version and a new data pack (also once a
  day at startup; Settings > Check For Updates turns that off). The program and the data are
  updated separately:
    - program: DOWNLOAD & INSTALL fetches the program-only installer, checks it, closes the mod
      and runs it on this folder; the mod reopens when it is done. Your data, settings, edits
      and tournaments are kept. Or download the installer from the release page yourself.
    - data: only the files that changed are downloaded (checked one by one) and installed;
      the files replaced are kept so the update can be undone (UNDO THE LAST UPDATE).
  It only talks to github.com over HTTPS and never runs anything without asking.

The install folder must be writable: do not install under Program Files (setup refuses it).
Default: Documents\R08Revival.

Portable copy (zip): same layout; the file portable.txt marks it. On first launch the mod looks
for Rugby 08 (the folder containing Rugby08.exe) and asks if it can't find it.
