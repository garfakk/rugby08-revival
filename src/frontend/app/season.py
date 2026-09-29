"""app/season.py — season display formatting

The mod's data stores a season as a single year ("2024"), the year the
season ENDS in. Everywhere that year is shown to the user it's written as
the "x-y" range it actually covers (y=stored year, x=y-1) — "2024" reads as
"2023-2024". The stored key itself never changes; only display text runs
through this.
"""


def season_label(season) -> str:
    """"2024" -> "2023-2024". Anything that isn't a plain year passes
    through unchanged (blank seasons, "—" placeholders, etc.)."""
    if not season:
        return season
    try:
        year = int(str(season))
    except ValueError:
        return str(season)
    return f"{year - 1}-{year}"
