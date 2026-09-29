# This file contains all the game specific variables for the mod

# These are the ID of the set plays in the roster file
set_plays_id = {"classic": 0, "pivot": 1, "pocket": 2, "dummy_switch": 3, "miss": 4, "cross_kick": 5, "loop": 6, "miss_pivot": 7}

# These are the roles names in a team order by their position in the roster file
team_roles = ['captain', 'vice-captain', 'long_GK', 'short_GK', 'long_punt', 'short_punt', 'kick_off']

# Players positions ID for the roster file
# Note: it seems that the game makes no difference between loosehead and tighthead props, and between openside and blindside flankers (?)
positions_id = {
    'loosehead_prop': 1,
    'hooker': 2,
    'tighthead_prop': 3,
    'second_row': 4,
    'blindside_flanker': 5,
    'openside_flanker': 6,
    'number_eight': 7,
    'scrum_half': 8,
    'fly_half': 9,
    'winger': 10,
    'centre': 11,
    'fullback': 12
}

# Foot values for the roster file
foot_id = {'left': 0, 'right': 128}

# Boot style values
boot_style_id = range(0, 10)

# Skin tone values for the roster file . DEPRECATED, the skin is now loaded by texture ID using the exe patch.
skin_tone_id = {'light': 96, 'l_medium': 97, 'd_medium': 98, 'dark': 99}

# Skin texture values for the roster file
skin_texture_id = {'light': 1, 'l_medium': 3, 'd_medium': 5, 'dark': 7}

# Tape values for the roster file
tape_id = {'none': 0, 'left': 1, 'right': 2, 'both': 3}

# Special abilities for the roster file
special_ability_id = {'default': 0, 'scrum': 1, 'lineout': 2, 'tackler':3, 'runner': 4, 'passer': 5, 'kicker': 6, 'crasher': 7, 'ruck': 8, 'goalkicker': 9, 'playmaker': 10}

# Length of the half-times for the mission file
halftime_length = {"2m": 0, "5m": 1, "10m": 2, "20m": 3, "40m": 4}

# Difficulty for the mission file
difficulty = {"club": 0, "pro": 1, "elite":2}

# Match type for the mission file (this only influence the commentaries)
match_type = {"exhibition": 0, "world_cup": 1, "tri_nations": 2, "six_nations": 3, "ten_nations": 5, "european_cup": 6, "super_14": 7, "premiership": 8}
match_subtype = {"none": 0, "pool": 5, "quarter_final": 8, "semi_final": 9, "final": 10}

# Weather precipitation IDs. Note: this is a custom setting that works only with the DLL patch
precipitation_id = {"none": 0, "rain": 1, "snow": 3}

# .mis <WEATHER anthem="..."> (reR08 ENABLE_ANTHEM). The patch also accepts
# an arbitrary team CodeId to force any nation's anthem regardless of who's
# playing, but that table isn't available to the mod (team records carry no
# CodeId) — home/away/stock is the reachable subset.
anthem_choices = ["stock", "home", "away"]

# .mis trophy_lift="..." (reR08 ENABLE_TROPHY_LIFT). "on" = the match's own
# competition trophy (World Cup if none); a named trophy forces that one
# regardless of competition. Skipped by the patch when the stock game
# already awards a trophy (a real tournament final).
trophy_lift_choices = [
    "stock", "off", "on",
    "WorldCup", "TriNations", "SixNations", "TenNations", "EuroCup",
    "Super12", "Premiership", "Bledisloe", "Elite", "WL1", "WL2", "WL3", "WLKO",
]

# .mis <STATE><MODE name="..."> — the values actually seen across the 93
# stock .mis files in data.gob (KICK OFF dominates; the others are
# challenge/story-mission restart points). "" = today's default: no name/
# time/period override, match starts at a normal kickoff.
mission_mode_names = ["", "KICK OFF", "FORMATION", "LINE OUT", "PEN K", "FREE"]

# .mis <SCORE><EVENT type="..."> — the only 4 event types found in any stock
# mission (no reversed code found for this reader; kept to the values proven
# to load in EA's own shipped missions rather than guessing at others).
score_event_types = ["SS_TRY", "SS_CONVERSION", "SS_PENALTY", "SS_DROPGOAL"]

# .mis <OBJECTIVES><OBJECTIVE type="..."> — the objective Type strings
# code-verified against the mission-objective factory's dispatch chain (see
# reverse-engineering notes: parsers 0x4bec00/
# 0x4bef30, dispatcher 0x4c3550). A handful of other Type strings appear in
# stock missions too (ScoreWithPlayerRange, ScoreType, WinMatch, GamePlay,
# SellPlayer, BuyPlayer) but aren't in that dispatch chain — an unmatched
# Type falls back to a no-op UnknownObjective, so they're left out here as
# "no effect" rather than offered as if they did something.
objective_types = [
    "WinGame", "PlayerEvent", "RangedDropGoal", "Possession", "MinScore",
    "HalfTimeLead", "Waltz", "DoNotLoseAt80Minutes",
    "WinAndScoreWithDifferentBacks", "HandleBallWithPlayers", "MultiScore",
    "PositionScore", "DropGoalShootout", "SoccerKick", "Turnover",
    "ScrumScore", "NoCheat", "KickForTouch", "CatchKick", "Run", "LineOut",
]

# .mis <STATE><NIS> — the restart-position element that usually accompanies
# a non-kickoff MODE (where to place the ball/players for a scrum, lineout,
# penalty...). Up to 2 per stock mission, sometimes 0 even alongside a named
# MODE (a KICK OFF's own NIS looks like uninitialized noise — controller
# values like -842150451 are not meaningful; left as free fields rather
# than validated, same reasoning as PARAMETER above).
#
# script_name below is offered as autocomplete only, never enforced — the
# fixed names are every Team-suffixed / _NN-suffixed restart-script string
# in the exe's own string table matching the exact naming convention stock
# .mis NIS elements actually use (Rugby08.exe strings, cross-checked against
# every script_name the 93 stock missions use — none of those are missing
# here). Deliberately excludes the much larger set of ALL_CAPS_WITH_
# UNDERSCORE strings nearby (SCRUM_HOLD_LOOP_COLLAPSE_9, LINEOUT_JUMPCLOSE,
# KICK_OFF_TORPEDO...) — those are the animation-BANK clip names a
# different subsystem selects by, a different naming convention than the
# restart-SCENE scripts NIS actually references, and offering them here
# would just be wrong, not merely unverified.
_scrum_scene_names = (
    # Scrum_Home_%d / ScrumAway%d are honest-to-god printf templates in the
    # exe (found as literal format strings), not a fixed list — so this
    # range is GENERATED, not observed. Stock missions only ever used
    # 9-36; 1-40 gives room either side without claiming a confirmed
    # ceiling that doesn't exist in any reversed code.
    [f"Scrum_Home_{n:02d}" for n in range(1, 41)]
    + [f"ScrumAway{n:02d}" for n in range(1, 41)]
)
nis_script_names = [
    "",
    "kick_off",
    "lineout01_teama", "lineout01_teamb",
    "lineout_kick_teama", "lineout_kick_teamb",
    "lineout_catch", "lineout_tap",
    "scrum_cockup_TeamA", "scrum_cockup_TeamB",
    "scrum_decision_teamA_01", "scrum_decision_teamB_01",
    "penalty_general_TeamA", "penalty_general_TeamB",
    "Penalty_kick_chosen_01", "Penalty_kick_miss_01",
    "Penalty_kick_success_01", "Penalty_kick_success_big_01",
    "Penalty_punt_TeamA_01", "Penalty_punt_TeamB_01",
    "Penalty_run_01", "Penalty_try_TeamA_01", "Penalty_try_TeamB_01",
    "Ref_collapse_scrum_penalty_01",
    "Ref_free_kick_TeamA_01", "Ref_free_kick_TeamB_01",
    "ref_lecture_home", "ref_lecture_away",
    "ref_offside_TeamA_01", "ref_offside_TeamB_01",
    "Ref_quick_penalty_TeamA_01", "Ref_quick_penalty_TeamB_01",
    "Ref_ruck_penalty_TeamA_01", "Ref_ruck_penalty_TeamB_01",
    "Restart_TeamA_01", "Restart_TeamB_01",
    "knock_on_TeamA_01", "mark_TeamA", "mark_TeamB",
    "ART_scene_test1",
] + _scrum_scene_names

# PARAMETER name= values seen under stock OBJECTIVE elements — offered as
# autocomplete only; PARAMETER is a free name/value pair (no per-type schema
# was reversed), so the editor doesn't restrict input to this list.
objective_parameter_names = [
    "player_start", "player_end", "amount", "try", "num_required_before_score",
    "num_required", "longpass", "dropgoal", "any_score", "distance", "setplay",
    "num_players", "minrange", "sidestep", "handoff", "and_win", "wingers",
    "standing", "player_winger", "offload", "scrumhalf", "rucks", "player_id",
    "interception", "in_extra_time", "first_half", "dummypass", "dive_on_ball",
    "with_one_player", "use_to_score", "up_and_under", "time_limit", "time",
    "shoulder_charge", "scrums", "props", "prop_must_score", "percent", "pass",
    "or_tie", "num_action_required", "max_x", "locations", "lineouts",
    "in_end_zone", "flyhalf", "dropkick", "dont_need_to_score",
    "both_props_must_score",
]

# These are the pitch textures available in the game
pitch_textures = [
  "Reg1_08_hard_d", "Reg1_08_hard_n", "Reg1_08_norm_d", "Reg1_08_norm_n",
  "Reg2_08_best_d", "Reg2_08_best_n", "Reg2_08_best_o", 
  # "Reg2_08_best_t",
  "Reg2_08_norm_d", "Reg2_08_norm_n", "Reg2_08_norm_o",
  "Reg2_08_soggy_d", "Reg2_08_soggy_n", "Reg2_08_soggy_o",
  "Reg2_08_light_Mud_n", "Reg2_08_light_Mud_o",
  "Reg2_08_muddy_n", "Reg2_08_muddy_o", "Reg2_08_muddier_n", "Reg2_08_muddier_o",
  # "Reg2_08_fried_d",
  "Reg2_08_frosty_n", "Reg2_08_frosty_o",
  "Reg2_08_snow_n", "Reg2_08_snow_o",
  "Reg3_08_best_d", "Reg3_08_best_n", "Reg3_08_dry_d",
  "Reg3_08_hard_d", "Reg3_08_hard_n", "Reg4_08_hard_d", "Reg4_08_hard_n",
]

# These are the name of the game files that should be created/edited by the mod
game_filenames={
  'roster': "73cb47d1d69c90f28fd1cc4186ac1926.rdf", # Default roster
  'ball': "313d4a95ec2acea949c53fa28e1e8ab6.fsh",
  'stadium_graphics': "9b569b7cf7da2ee6ca753256884a6718.fsh",
  'tournament_logo': "df8c343a1c88fade15492c0eb1079877.fsh",
  'pitch_logo': "b95c433dfa0054d5bda8fbedd0df61d0.fsh",
  'crowd': "8bded45ac947bbcebc2bd17f63b396c3.fsh",
  'skins': "e6032b2303f4b08e2765786e39b6a5f0.fsh",
  'boots': "5f1c1437ecb6fb9c7f280f5b54e47f7e.fsh",
  'game_strings_english': "dc371d84ed78d4cf88a641a8d8abc38a.english",
  'game_strings_french': "dc371d84ed78d4cf88a641a8d8abc38a.french",
  'missionFile': "cf12092fb7b5ff22912df9cca89d0c30.mis",

  # Toulouse
  'team_A': {
    'banners': "c27080d73bf5f8b2417710602515153e.fsh",
    'logos': "26476cb81a1912eee33ab218a8b499b6.fsh",
    'kit_front': "185e5b1413336cc8fb1d3592fc1236e6.big",	# Toulouse home kit front
    'kit_back': "5c654389f32b72567c92de52fc65cdb9.fsh",		# Toulouse home kit back
   },

  # Clermont
  'team_B': {
    'banners': "99cabc43472a3c9e3b9b5b17b188e406.fsh",
    'logos': "1ac3c7e1589343c5b3c91be148dd5571.fsh",
    'kit_front': "48907084330b37ed8a59352b7c098652.big",	# Clermont home kit front
    'kit_back': "2135ae8bb4df0dc91849cd78000467f1.fsh",		# Clermont home kit back

  }
}

# Teams ID
teams_id = {
 'team_A': 59,	# Toulouse
 'team_B': 56,	# Clermont
}

# These are the adresses of team data in the roster file
roster_data_addresses = {
  'team_A': 0x3253C,	# Toulouse
  'team_B': 0x32404,	# Clermont
}

# These are the ID of the strings in the files .english & .french
teams_string_id = {
  'team_A': b'\x39\x04',  # Toulouse
  'team_B': b'\x7E\x08',  # Clermont
}

# These are the roster ID to use for each player from number 1 to 22
players_roster_id = {
    'team_A': [24114, 248, 11478, 23199, 27938, 13064, 467, 745, 27008, 24648, 17807, 14310, 1620, 5249, 9961, 13712, 29996, 21136, 18058, 26667, 3487, 10883],
    'team_B': [16439, 12508, 24722, 750, 18238, 32498, 2995, 58, 27595, 28633, 22648, 24750, 20326, 24021, 7462, 31762, 31758, 31754, 31690, 31673, 31647, 31601],
}

# These are the filenames and ID of the faces for each player from 1 to 22 when using a custom face
face_id_for_custom_faces = {
  'team_A': [
    {'face_id': 10202, 'filename': "decedf4a5f531cfb420072621f0b2190.big"},
    {'face_id': 10816, 'filename': "5217b83315b531cfb420072621f0b2190.big"},
    {'face_id': 11075, 'filename': "4461fb5d77a4658c7e3933abe53f46e4.big"},
    {'face_id': 12779, 'filename': "a5af13e645bef96d7d86c510d70c8fcf.big"},
    {'face_id': 12859, 'filename': "8fe5e6f57e912f09ad2839e0180b6569.big"},
    {'face_id': 13392, 'filename': "9d1346022b2b40cf8712d76c85044a8b.big"},
    {'face_id': 144, 'filename': "f3315270acb4877a300dee0bc026b8d1.big"},
    {'face_id': 14507, 'filename': "de2af6a04670a769ebc648b7feb6f099.big"},
    {'face_id': 14625, 'filename': "b9d830b35b54c31bcdf454a100a661f9.big"},
    {'face_id': 14688, 'filename': "703d69cd2e07b12c38bf517cef9e51e4.big"},
    {'face_id': 15264, 'filename': "90a2f4f98f9728d185f600110d4c552f.big"},
    {'face_id': 1543, 'filename': "42c71ea185dd8ba879632a5caecb3715.big"},
    {'face_id': 15629, 'filename': "d51635f7de061a36208cd699653f76a8.big"},
    {'face_id': 16139, 'filename': "7519a8b52e59217de6af1c9519f284e5.big"},
    {'face_id': 16202, 'filename': "efb68c2c103aa9c1d8056a024c795909.big"},
    {'face_id': 16279, 'filename': "f43dcc85acff71fd7b9b101b05359d3b.big"},
    {'face_id': 16290, 'filename': "ee322aaeb51def5912e66028d27ee533.big"},
    {'face_id': 16398, 'filename': "11fb440ac4b70ffd433d4c34c83db601.big"},
    {'face_id': 17192, 'filename': "6dacead972129e2f9b1ad2be320d386f.big"},
    {'face_id': 18538, 'filename': "e3748fc3496ffa60453df3b1ee4bceb3.big"},
    {'face_id': 19264, 'filename': "de3716110fed8e6c8cd0d0444ef65fd4.big"},
    {'face_id': 19357, 'filename': "8cec961eb710c5e766fbf80bd984a829.big"},
  ],
  'team_B': [
    {'face_id': 19711, 'filename': "d081507ef57cc3a6e53012b45139524c.big"},
    {'face_id': 19866, 'filename': "2e017ea9835d12cdc1ead3831fc27ae2.big"},
    {'face_id': 19949, 'filename': "6c4ff8f89bfc94e2f4c07883251af7d8.big"},
    {'face_id': 20078, 'filename': "d3e5d62fcecbb1b36718839adad70609.big"},
    {'face_id': 20489, 'filename': "ae8281d1bad94a80efa54ab8218cdbd3.big"},
    {'face_id': 20537, 'filename': "6d5dca4a2939fec62bd1d72c96742bb2.big"},
    {'face_id': 21543, 'filename': "edb84591db19a98f40b86bdb8b2c6c9d.big"},
    {'face_id': 21577, 'filename': "165518eea871c04a3ce6a9548a2b3cfa.big"},
    {'face_id': 21911, 'filename': "9f1ab4b29fd3eb6d7e162436ef48c13d.big"},
    {'face_id': 21979, 'filename': "3039bd6a7b04aae138d3e51356473d05.big"},
    {'face_id': 226, 'filename': "a45a79de683e2d7a4041995ff3d5cf8c.big"},
    {'face_id': 22867, 'filename': "ad417653e603eac0cce51682d2c32c35.big"},
    {'face_id': 2368, 'filename': "fc49174bf501d129dd1867a38e585bfe.big"},
    {'face_id': 23811, 'filename': "61dd64285b8ba71443e57b98118e7232.big"},
    {'face_id': 23831, 'filename': "c94bd1f0304438a8cc6dd68216c8dc08.big"},
    {'face_id': 23955, 'filename': "539bd7843354cd011248fea34aacdff0.big"},
    {'face_id': 2598, 'filename': "dce420932510b39d5a78d7059710c6d1.big"},
    {'face_id': 26018, 'filename': "bdf5cb889009a126cb55e2011cab8cbd.big"},
    {'face_id': 2623, 'filename': "a264e97f82d181eb2996b716c9a25d7c.big"},
    {'face_id': 27352, 'filename': "caad8fcaa5306e24604cd35077fc3a92.big"},
    {'face_id': 27529, 'filename': "af404738de26f8be44a038397c0d5149.big"},
    {'face_id': 27594, 'filename': "607c4f526a9eb7cdb5c983df01b246cc.big"},
  ]}

# The following code assigns the roster ID from players_roster_id with the faces ID in face_id_for_custom_faces
face_id_for_custom_faces_by_roster_id = {}

for team, players in players_roster_id.items():
    face_ids = face_id_for_custom_faces[team]
    face_id_for_custom_faces_by_roster_id.update({roster_id: face for roster_id, face in zip(players, face_ids)})

# These are the default values for a player if the fields are missing
player_default_values = {
    "commentary": 0, "name": "Unknown", "pos1": None, "pos2": None, "pos3": None, "weight": 70, "height": 180, "age": 24,
    "special_ability": 0, "attack": 0, "defense": 0, "speed": 0, "acceleration": 0, "agility": 0, "handling": 0,  "passing": 0,
    "kicking": 0, "kicking_power": 0, "goal_kicking": 0, "tackling": 0, "strength": 0, "rucking": 0, "scrummaging": 0, "hooking": 0,
    "line_out": 0, "discipline": 0, "aggression": 0, "stamina": 0, "consistency": 0, "temperament": 0, "creativity": 0, "bravery": 0,
    "fitness": 0, "crashball": 0, "gap_defense": 0, "ss_command": 0, "ss_passer": 0, "ss_play_maker": 0, "ss_scoring": 0,
    "ss_goal_kicker": False, "ss_tactical_kicking": False, "ss_crashball": False, "ss_tackle_breaker": False, "ss_tackling": False,
    "ss_ball_winner": False, "ss_defensive_organisation": False, "ss_scrummager": False, "ss_jumper": False,
    "headgear": 0, "boot_style": 0, "socks_up": False, "face": 666, "skin": 'light', "gloves": False,
    "best_foot": "right", "finger_tape": "none", "wrist_tape": "none", "thigh_tape": "none",
    "skin_overlay": False,
}

# Goal kicking style: single-byte index (1..20) written at record offset +0x50
goal_kicking_style_values = {
    "default": 0,
    "flatley": 1,
    "mortlock": 2,
    "hill": 3,
    "ogara": 4,
    "henson": 5,
    "carter": 6,
    "gopperth": 7,
    "wilkinson": 8,
    "barkley": 9,
    "hodgson": 10,
    "humphreys": 11,
    "quesada": 12,
    "yachivilli": 13,
    "spencer": 14,
    "conrad": 15,
    "hewat": 16,
    "huxley": 17,
    "michalak": 18,
    "macdonald": 19,
    "pretorious": 20,
}

# These are the template filenames (located in config/templates)
template_filenames = {  
  'roster': "roster.rdf",
  'tournament': "tournament.tmt", # Not used
  'tournament_logo': "tournament_logo.fsh",
  'pitch_logo': "pitch_logo.fsh",
  'ball': "ball.fsh",
  'banners': "banners.fsh",
  'crowd': "crowd.fsh",
  'skins': "skins.fsh",
  'boots': "boots.fsh",
  'game_strings_english': "game_strings.english",
  'game_strings_french': "game_strings.french",

  'team_A': {
    'minikit': "minikit_team_A.fsh",
    'logos': "logos_team_A.fsh",
    'kit_front_fsh': "kit.fsh",
    'kit_front_big': "kit_front.big",
    'kit_back': "kit_back.fsh",
  },

  'team_B': {
    'minikit': "minikit_team_B.fsh",
    'logos': "logos_team_B.fsh",
    'kit_front_fsh': "kit.fsh",
    'kit_front_big': "kit_front.big",
    'kit_back': "kit_back.fsh",
  }
}

# Offsets of items in the .fsh files
fsh_files_offsets = {
  'minikit': 0x30,
  'logo_main': 0x40,
  'logo_small': 0x400C0,
  'logo_left': 0x48130,
  'logo_right': 0x501A0,
  'front_kit': 0x30,
  'back_kit_0': 0xD0,
  'back_kit_n': 512*512*4 + 320 - 0xD0,
  'tournament_logo': 0x30,
  'pitch_logo_1': 0x30,
  'pitch_logo_2': 0x400A0,
  'ball_1': 0x30,
  'ball_2': 0x000200F0,
  'banner_1': 0x40,
  'banner_n': 512*128*4 + 256 - 0x40,
  'crowd_1': 0x98,
  # 'crowd_n': 512*128*4 + 0x110 - 0x98,
  'crowd_n': 0x40070
  }

# Images sizes for the .fsh files
fsh_image_sizes = {
  'minikit': (256,256),
  'logo_main':(256,256),
  'logo_small': (128, 64),
  'logo_left': (128, 64),
  'logo_right': (128, 64),
  'front_kit': (512, 512),
  'back_kit': (512, 512),
  'tournament_logo': (256,256),
  'pitch_logo_1': (256,256),
  'pitch_logo_2': (128,128),
  'ball': (256, 128),
  'banners': (512, 128),
  'crowd': (512, 128),
  }
