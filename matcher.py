"""
ShipSort — Address Matching Engine
3-tier matching: pincode regex → keyword map → RapidFuzz fuzzy match
"""

import re
import sqlite3
import logging

log = logging.getLogger(__name__)

# Minimum fuzzy match score to accept (0–100). Lower = more matches but more wrong ones.
FUZZY_THRESHOLD = 80


def match_sort_code(address: str, db_path: str, hint_pincode: str = None) -> dict:
    """
    Given a full seller address string, return the best matching sort code.

    Returns a dict with:
        sort_code     – e.g. "1A01"  (or "UNKNOWN" if no match)
        rider_zone    – e.g. "North Delhi R1"
        area_name     – e.g. "Connaught Place"
        pincode       – the matched pincode (str)
        match_method  – "pincode" | "keyword" | "fuzzy" | "none"
        confidence    – 0–100 int
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    import re as _re
    address_upper = _re.sub(r'\s+', ' ', address.strip()).upper()  # normalise multi-spaces

    # ── Tier 0: hint pincode from API ────────────────────────────────────────
    # If the shipment API already returned a pincode, trust it first
    if hint_pincode and re.match(r'^[1-9][0-9]{5}$', str(hint_pincode).strip()):
        result = _lookup_pincode(conn, hint_pincode.strip())
        if result:
            conn.close()
            return {**result, 'match_method': 'pincode', 'confidence': 100,
                    'pincode': hint_pincode.strip()}

    # ── Tier 1: extract pincode from address string ──────────────────────────
    pincode = _extract_pincode(address_upper)
    if pincode:
        result = _lookup_pincode(conn, pincode)
        if result:
            conn.close()
            return {**result, 'match_method': 'pincode', 'confidence': 100, 'pincode': pincode}
        else:
            log.warning('Pincode %s found in address but not in sort_master', pincode)

    # ── Tier 2: keyword match ─────────────────────────────────────────────────
    keywords = conn.execute(
        "SELECT keyword, pincode, priority FROM keyword_map WHERE active=1 ORDER BY priority ASC"
    ).fetchall()
    for row in keywords:
        if row['keyword'].upper() in address_upper:
            result = _lookup_pincode(conn, row['pincode'])
            if result:
                conn.close()
                return {**result, 'match_method': 'keyword', 'confidence': 85,
                        'pincode': row['pincode']}

    # ── Tier 3: fuzzy match on area names ─────────────────────────────────────
    try:
        from rapidfuzz import process, fuzz
    except ImportError:
        log.error('rapidfuzz not installed. Run: pip install rapidfuzz')
        conn.close()
        return _no_match()

    areas = conn.execute(
        "SELECT area_name, pincode FROM sort_master WHERE active=1"
    ).fetchall()

    if areas:
        area_names = [a['area_name'] for a in areas]
        best = process.extractOne(
            address_upper, area_names,
            scorer=fuzz.partial_ratio,
            score_cutoff=FUZZY_THRESHOLD
        )
        if best:
            matched_pincode = areas[area_names.index(best[0])]['pincode']
            result = _lookup_pincode(conn, matched_pincode)
            if result:
                conn.close()
                return {**result, 'match_method': 'fuzzy',
                        'confidence': int(best[1]), 'pincode': matched_pincode}

    conn.close()
    log.warning('No sort code match found for address: %.80s', address)
    return _no_match()


def _extract_pincode(address_upper: str) -> str | None:
    """Extract a valid Indian 6-digit pincode from an address string."""
    # Look for standalone 6-digit number starting with non-zero
    matches = re.findall(r'\b([1-9][0-9]{5})\b', address_upper)
    return matches[-1] if matches else None  # last match is usually most specific


def _lookup_pincode(conn: sqlite3.Connection, pincode: str) -> dict | None:
    row = conn.execute(
        """SELECT sort_code, rider_zone, area_name, city
           FROM sort_master WHERE pincode=? AND active=1""",
        (str(pincode),)
    ).fetchone()
    if row:
        return {
            'sort_code':  row['sort_code'],
            'rider_zone': row['rider_zone'],
            'area_name':  row['area_name'],
            'city':       row['city'],
        }
    return None


def _no_match() -> dict:
    return {
        'sort_code': 'UNKNOWN', 'rider_zone': None, 'area_name': None,
        'city': None, 'pincode': None, 'match_method': 'none', 'confidence': 0
    }
