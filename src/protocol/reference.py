"""Large, open, display only reference tables from the F1 25 / F1 26 UDP appendices.

These map spec IDs to readable labels for display (grids, chart axes, results, cards, etc...).
The App never branches on them - it only turns IDs into names - so they are plain dicts, not enums,
with a gracefull fallback: an unknown ID yields a readable placeholder instead of raising an error.
As these lists grow/change every season, and a missing label must never crash a capture replay.

The 2026 tables are supersets of 2025 (entries are added; core IDs are not renumbered), so one merged 
table labels both formats.

NOTE: This is static game date. League / multiplayer roster (alais -> person, which drifts per season/session)
is separate, user-maintained data and lives in a JSON file, not here.
"""
from __future__ import annotations


def _name(table: dict[int, str], value: int, kind: str) -> str:
    """Return a human-friendly name for ``value`` from ``table``, or a readable placeholder if unknown."""
    return table.get(value, f"Unknown {kind} ({value})")


# --- Teams (appendix: Team IDs) -----------------------------------------------
TEAM_NAMES: dict[int, str] = {
    0: "Mercedes",
    1: "Ferrari",
    2: "Red Bull Racing",
    3: "Williams",
    4: "Aston Martin",
    5: "Alpine",
    6: "RB",
    7: "Haas",
    8: "McLaren",
    9: "Sauber",
    41: "F1 Generic",
    104: "F1 Custom Team",
    129: "Konnersport",
    142: "APXGP '24",
    154: "APXGP '25",
    155: "Konnersport '25",
    158: "Art GP '24",
    159: "Campos '24",
    160: "Rodin Motorsport '24",
    161: "AIX Racing '24",
    162: "DAMS '24",
    163: "Hitech '24",
    164: "MP Motorsport '24",
    165: "Prema '24",
    166: "Trident '24",
    167: "Van Amersfoort Racing '24",
    168: "Invicta '24",
    185: "Mercedes '24",
    186: "Ferrari '24",
    187: "Red Bull Racing '24",
    188: "Williams '24",
    189: "Aston Martin '24",
    190: "Alpine '24",
    191: "RB '24",
    192: "Haas '24",
    193: "McLaren '24",
    194: "Sauber '24",
    465: "Art GP '25",
    466: "Campos '25",
    467: "Rodin Motorsport '25",
    468: "AIX Racing '25",
    469: "DAMS '25",
    470: "Hitech '25",
    471: "MP Motorsport '25",
    472: "Prema '25",
    473: "Trident '25",
    474: "Van Amersfoort Racing '25",
    475: "Invicta '25",
    476: "Mercedes '26",
    477: "Ferrari '26",
    478: "Red Bull Racing '26",
    479: "Williams '26",
    480: "Aston Martin '26",
    481: "Alpine '26",
    482: "RB '26",
    483: "Haas '26",
    484: "McLaren '26",
    485: "Audi '26",
    486: "Cadillac '26"
}


# --- Tracks (appendix: Track IDs) ---------------------------------------------
TRACK_NAMES: dict[int, str] = {
    0: "Melbourne",
    2: "Shanghai",
    3: "Sakhir (Bahrain)",
    4: "Catalunya",
    5: "Monaco",
    6: "Montreal",
    7: "Silverstone",
    9: "Hungaroring",
    10: "Spa",
    11: "Monza",
    12: "Singapore",
    13: "Suzuka",
    14: "Abu Dhabi",
    15: "Texas",
    16: "Brazil",
    17: "Austria",
    19: "Mexico",
    20: "Baku (Azerbaijan)",
    26: "Zandvoort",
    27: "Imola",
    29: "Jeddah",
    30: "Miami",
    31: "Las Vegas",
    32: "Losail",
    39: "Silverstone (Reverse)",
    40: "Austria (Reverse)",
    41: "Zandvoort (Reverse)",
    42: "Madrid"
}


# --- Drivers (appendix: Driver IDs) -------------------------------------------
DRIVER_NAMES: dict[int, str] = {
    0: "Carlos Sainz",
    2: "Daniel Ricciardo",
    3: "Fernando Alonso",
    7: "Lewis Hamilton",
    9: "Max Verstappen",
    10: "Nico Hulkenberg",
    11: "Kevin Magnussen",
    14: "Sergio Perez",
    15: "Valtteri Bottas",
    17: "Esteban Ocon",
    19: "Lance Stroll",
    20: "Arron Barnes",
    21: "Martin Giles",
    22: "Alex Murray",
    23: "Lucas Roth",
    24: "Igor Correia",
    25: "Sophie Levasseur",
    26: "Jonas Schiffer",
    27: "Alain Forest",
    28: "Jay Letourneau",
    29: "Esto Saari",
    30: "Yasar Atiyeh",
    31: "Callisto Calabresi",
    32: "Naota Izum",
    33: "Howard Clarke",
    34: "Lars Kaufmann",
    35: "Marie Laursen",
    36: "Flavio Nieves",
    38: "Klimek Michalski",
    39: "Santiago Moreno",
    40: "Benjamin Coppens",
    41: "Noah Visser",
    50: "George Russell",
    54: "Lando Norris",
    58: "Charles Leclerc",
    59: "Pierre Gasly",
    62: "Alexander Albon",
    70: "Rashid Nair",
    71: "Jack Tremblay",
    77: "Ayrton Senna",
    80: "Guanyu Zhou",
    83: "Juan Manuel Correa",
    90: "Michael Schumacher",
    94: "Yuki Tsunoda",
    102: "Aiden Jackson",
    109: "Jenson Button",
    110: "David Coulthard",
    112: "Oscar Piastri",
    113: "Liam Lawson",
    116: "Richard Verschoor",
    123: "Enzo Fittipaldi",
    125: "Jacques Villeneuve",
    127: "Callie Mayer",
    132: "Logan Sargeant",
    136: "Jack Doohan",
    137: "Amaury Cordeel",
    138: "Dennis Hauger",
    145: "Zane Maloney",
    146: "Victor Martins",
    147: "Oliver Bearman",
    148: "Jak Crowford",
    149: "Isack Hadjar",    
    152: "Roman Stanek",
    153: "Kush Maini",
    156: "Brendon Leigh",
    157: "David Tonizza",
    158: "Jarno Opmeer",
    159: "Lucas Blakeley",
    160: "Paul Aron",
    161: "Gabriel Bortoleto",
    162: "Franco Colapinto",
    163: "Taylor Barnard",
    164: "Joshua Dürksen",
    165: "Andra-Kimi Antonelli",
    166: "Ritomo Miyata",
    167: "Rafael Villagómez",
    168: "Zak O'Sullivan",
    169: "Pepe Martí",
    170: "Sonny Hayes",
    171: "Joshua Pearce",
    172: "Callum Voisin",
    173: "Matias Zagazeta",
    174: "Nikola Tsolov",
    175: "Tim Tramnitz",
    185: "Luca Cortez",
    186: "Luke Browning",
    187: "Cian Shields",
    188: "Arvid Lindblad",
    189: "Dino Beganovic",
    190: "Leonardo Fornaroli",
    191: "Oliver Goethe",
    192: "Gabrielle Mini",
    193: "Sebastián Montoya",
    194: "Alex Dunne",
    195: "Max Esterson",
    196: "Sami Meguetounif",
    197: "John Bennett"
}


# --- Nationalities (appendix: Nationality IDs) --------------------------------
NATIONALITY_NAMES: dict[int, str] = {
    1: "American",
    2: "Argentine",
    3: "Australian",
    4: "Austrian",
    5: "Azerbaijani",
    6: "Bahraini",
    7: "Belgian",
    8: "Bolivian",
    9: "Brazilian",
    10: "British",
    11: "Bulgarian",
    12: "Cameroonian",
    13: "Canadian",
    14: "Chilean",
    15: "Chinese",
    16: "Colombian",
    17: "Costa Rican",
    18: "Croatian",
    19: "Cypriot",
    20: "Czech",
    21: "Danish",
    22: "Dutch",
    23: "Ecuadorean",
    24: "English",
    25: "Emirian",
    26: "Estonian",
    27: "Finnish",
    28: "French",
    29: "German",
    30: "Ghanaian",
    31: "Greek",
    32: "Guatemalan",
    33: "Honduran",
    34: "Hong Konger",
    35: "Hungarian",
    36: "Icelander",
    37: "Indian",
    38: "Indonesian",
    39: "Irish",
    40: "Israeli",
    41: "Italian",
    42: "Jamaican",
    43: "Japanese",
    44: "Jordanian",
    45: "Kuwaiti",
    46: "Latvian",
    47: "Lebanese",
    48: "Lithuanian",
    49: "Luxembourger",
    50: "Malaysian",
    51: "Maltese",
    52: "Mexican",
    53: "Monegasque",
    54: "New Zealander",
    55: "Nicaraguan",
    56: "Northern Irish",
    57: "Norwegian",
    58: "Omani",
    59: "Pakistani",
    60: "Panamanian",
    61: "Paraguayan",
    62: "Peruvian",
    63: "Polish",
    64: "Portuguese",
    65: "Qatari",
    66: "Romanian",
    68: "Salvadoran",
    69: "Saudi",
    70: "Scottish",
    71: "Serbian",
    72: "Singaporean",
    73: "Slovakian",
    74: "Slovenian",
    75: "South Korean",
    76: "South African",
    77: "Spanish",
    78: "Swedish",
    79: "Swiss",
    80: "Thai",
    81: "Turkish",
    82: "Uruguayan",
    83: "Ukrainian",
    84: "Venezuelan",
    85: "Barbadian",
    86: "Welsh",
    87: "Vietnamese",
    88: "Algerian",
    89: "Bosnian",
    90: "Filipino",
}


# --- Game modes (appendix: Game Mode IDs) -------------------------------------
GAME_MODE_NAMES: dict[int, str] = {
    4: "Grand Prix '23",
    5: "Time Trial",
    6: "Splitscreen",
    7: "Online Custom",
    15: "Online Weekly Event",
    17: "Story Mode (Braking Point)",
    27: "My Team Career '25",
    28: "Driver Career '25",
    29: "Career '25 Online",
    30: "Challenge Career '25",
    75: "Story Mode (APXGP)",
    127: "Benchmark",
}


# --- Penalty types (appendix: Penalty types) ----------------------------------
PENALTY_NAMES: dict[int, str] = {
    0: "Drive through",
    1: "Stop Go",
    2: "Grid penalty",
    3: "Penalty reminder",
    4: "Time penalty",
    5: "Warning",
    6: "Disqualified",
    7: "Removed from formation lap",
    8: "Parked too long timer",
    9: "Tyre regulations",
    10: "This lap invalidated",
    11: "This and next lap invalidated",
    12: "This lap invalidated without reason",
    13: "This and next lap invalidated without reason",
    14: "This and previous lap invalidated",
    15: "This and previous lap invalidated without reason",
    16: "Retired",
    17: "Black flag timer",
}

# --- Infringement types (appendix: Infringement types) ------------------------
INFRINGEMENT_NAMES: dict[int, str] = {
    0: "Blocking by slow driving",
    3: "Big Collision",
    4: "Small Collision",
    5: "Collision failed to hand back position single",
    6: "Collision failed to hand back position multiple",
    7: "Corner cutting gained time",
    8: "Corner cutting overtake single",
    9: "Corner cutting overtake multiple",
    10: "Crossed pit exit lane",
    11: "Ignoring blue flags",
    12: "Ignoring yellow flags",
    13: "Ignoring drive through",
    14: "Too many drive throughs",
    15: "Drive trough reminder serve within n laps",
    16: "Drive trough reminder serve this lap",
    17: "Pit lane speeding",
    18: "Parked for too long",
    19: "Ignoring tyre regulations",
    20: "Too many penalties",
    21: "Multiple warnings",
    22: "Approaching disqualification",
    23: "Tyre regulations select single",
    24: "Tyre regulations select multiple",
    25: "Lap invalidated corner cutting",
    26: "Lap invalidated running wide",
    27: "Corner cutting ran wide gained time minor",
    28: "Corner cutting ran wide gained time significant",
    29: "Corner cutting ran wide gained time extreme",
    30: "Lap invalidated wall riding",
    31: "Lap invalidated flashback used",
    32: "Lap invalidated reset to track",
    33: "Blocking the pitlane",
    34: "Jump start",
    35: "Safety car to car collision",
    36: "Safety car illegal overtake",
    37: "Safety car exceeding allowed pace",
    38: "Virtual safety car exceeding allowed pace",
    39: "Formation lap below allowed speed",
    40: "Formation lap parking",
    41: "Retired mechanical failure",
    42: "Retired terminally damaged",
    43: "Safety car falling too far back",
    44: "Black flag timer",
    45: "Unserved stop go penalty",
    46: "Unserved drive through penalty",
    47: "Engine component change",
    48: "Gearbox component change",
    49: "Parc Fermé change",
    50: "League grid penalty",
    51: "Retry penalty",
    52: "Illegal time gain",
    53: "Mandatory pit stop",
    54: "Attribute assigned",
}


def team_name(team_id: int) -> str:
    """Return a human-friendly team name for ``team_id``."""
    return _name(TEAM_NAMES, team_id, "team")


def track_name(track_id: int) -> str:
    """Return a human-friendly track name for ``track_id``."""
    return _name(TRACK_NAMES, track_id, "track")


def driver_name(driver_id: int) -> str:
    """Return a human-friendly driver name for ``driver_id``."""
    return _name(DRIVER_NAMES, driver_id, "driver")


def nationality_name(nationality_id: int) -> str:
    """Return a human-friendly nationality name for ``nationality_id``."""
    return _name(NATIONALITY_NAMES, nationality_id, "nationality")


def game_mode_name(game_mode_id: int) -> str:
    """Return a human-friendly game mode name for ``game_mode_id``."""
    return _name(GAME_MODE_NAMES, game_mode_id, "game mode")


def penalty_name(penalty_id: int) -> str:
    """Return a human-friendly penalty name for ``penalty_id``."""
    return _name(PENALTY_NAMES, penalty_id, "penalty")


def infringement_name(infringement_id: int) -> str:
    """Return a human-friendly infringement name for ``infringement_id``."""
    return _name(INFRINGEMENT_NAMES, infringement_id, "infringement")

