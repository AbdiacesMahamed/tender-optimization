"""
Carrier SCAC to Name Mapping

This mapping is used for display purposes and SCAC resolution from scorecard names.
Source: DCM SCAC carrier list.
"""

CARRIER_NAMES = {
    'ATMI': 'Cargomatic',
    'ULSE': 'CDS (Century Distribution Services)',
    'DMCQ': 'Maersk Damco',
    'HDDR': 'HUDD Transportation',
    'HJBT': 'JB Hunt',
    'RKNE': 'RoadOne Intermodal',
    'RDXY': 'RoadEx',
    'SONW': 'Steam Logistics',
    'XPDR': 'STG Logistics',
    'PGLT': 'Premier Global Logistics',
    'AOYV': 'Waterfront Logistics',
    'FRQT': 'Forrest Logistics',
    'ARVY': 'Arrive Logistics',
    'AZGM': 'Relay',
    'DNSL': 'DSL Logistics',
}

# Reverse mapping: common display name variations → SCAC code
# Used when scorecard files use carrier names instead of SCAC codes.
# Keys are lowercased for case-insensitive matching.
NAME_TO_SCAC = {
    'cargomatic': 'ATMI',
    'atlas': 'ATMI',
    'atmi': 'ATMI',
    'cds': 'ULSE',
    'century': 'ULSE',
    'century distribution': 'ULSE',
    'maersk': 'DMCQ',
    'damco': 'DMCQ',
    'maersk damco': 'DMCQ',
    'hudd': 'HDDR',
    'hudd transportation': 'HDDR',
    'jb hunt': 'HJBT',
    'j.b. hunt': 'HJBT',
    'jbhunt': 'HJBT',
    'hunt': 'HJBT',
    'roadone': 'RKNE',
    'road one': 'RKNE',
    'roadone intermodal': 'RKNE',
    'roadex': 'RDXY',
    'road express': 'RDXY',
    'steam': 'SONW',
    'steam logistics': 'SONW',
    'stg': 'XPDR',
    'stg logistics': 'XPDR',
    'pglt': 'PGLT',
    'premier': 'PGLT',
    'premier global': 'PGLT',
    'premier global logistics': 'PGLT',
    'waterfront': 'AOYV',
    'waterfront logistics': 'AOYV',
    'forrest': 'FRQT',
    'forrest logistics': 'FRQT',
    'arrive': 'ARVY',
    'arrive logistics': 'ARVY',
    'relay': 'AZGM',
    'dsl': 'DNSL',
    'dsl logistics': 'DNSL',
    'nfi': 'NFI',
}


def get_carrier_name(scac: str) -> str:
    """Get the full carrier name for a SCAC code, or return the SCAC if unknown."""
    return CARRIER_NAMES.get(scac, scac)


def resolve_scac(name: str) -> str:
    """
    Resolve a carrier display name to its SCAC code.

    Tries exact match first, then partial/fuzzy matching.
    Returns the original name if no match is found.
    """
    if not name or not isinstance(name, str):
        return name

    cleaned = name.strip().lower()

    # Direct lookup
    if cleaned in NAME_TO_SCAC:
        return NAME_TO_SCAC[cleaned]

    # Check if it's already a known SCAC code (uppercase 4-char)
    upper = name.strip().upper()
    if upper in CARRIER_NAMES:
        return upper

    # Partial match: check if any key is contained in the name
    for key, scac in NAME_TO_SCAC.items():
        if key in cleaned:
            return scac

    return name.strip().upper()
