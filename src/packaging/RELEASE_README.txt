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
  game_files\                  the copy of Rugby 08 the mod works on (your original is untouched)

The install folder must be writable: do not install under Program Files (setup refuses it).
Default: Documents\R08Revival.

Portable copy (zip): same layout; the file portable.txt marks it. On first launch the mod looks
for Rugby 08 (the folder containing Rugby08.exe) and asks if it can't find it.
