"""
ShipSort — Mock Shipment API
Simulates your company's shipment REST API.
Swap this out with your real API in production.

Endpoints:
  GET  /v1/shipments/:id      → shipment details with seller address
  GET  /v1/shipments          → list all mock shipments (for testing)
  GET  /v1/health             → health check
"""

import os
from functools import wraps
from flask import Flask, jsonify, request

app = Flask(__name__)

VALID_TOKEN = os.environ.get('SHIPMENT_API_TOKEN', 'demo-token-2026')

# ─── 25 realistic mock shipments ─────────────────────────────────────────────
# Covers Tier 1 (pincode in address), Tier 2 (keyword match),
# Tier 3 (fuzzy match), and deliberate edge cases.

MOCK_SHIPMENTS = {

    # ── Tier 1: pincode clearly present in address ────────────────────────────

    'SHP100001': {'seller': {'name': 'Kapoor Textiles Pvt Ltd',
        'address': 'Shop 14, Connaught Place Inner Circle, New Delhi - 110001', 'pincode': '110001'},
        'weight_kg': 2.4, 'product': 'Fabric rolls'},

    'SHP100002': {'seller': {'name': 'Singh Electronics',
        'address': '47, Civil Lines, Near Metro Gate 3, Delhi 110002', 'pincode': '110002'},
        'weight_kg': 0.8, 'product': 'Phone accessories'},

    'SHP100003': {'seller': {'name': 'Arora Fashion House',
        'address': 'Plot 88B, Ajmal Khan Road, Karol Bagh, New Delhi 110005', 'pincode': '110005'},
        'weight_kg': 1.5, 'product': 'Ethnic wear'},

    'SHP100004': {'seller': {'name': 'Sea Breeze Exports',
        'address': '12/A, Fort Market Rd, Near GPO, Mumbai - 400001', 'pincode': '400001'},
        'weight_kg': 5.0, 'product': 'Spice packets'},

    'SHP100005': {'seller': {'name': 'Sharma Boutique',
        'address': 'Turner Road, Bandra West, Mumbai, Maharashtra 400050', 'pincode': '400050'},
        'weight_kg': 0.4, 'product': 'Jewellery'},

    'SHP100006': {'seller': {'name': 'TechZone Gadgets',
        'address': '80 Feet Road, Koramangala 4th Block, Bangalore 560034', 'pincode': '560034'},
        'weight_kg': 1.2, 'product': 'Laptop stand'},

    'SHP100007': {'seller': {'name': 'Brigade Books',
        'address': 'Residency Road, Near MG Road Metro, Bangalore - 560001', 'pincode': '560001'},
        'weight_kg': 3.1, 'product': 'Books (bulk)'},

    'SHP100025': {'seller': {'name': 'All Caps Address',
        'address': 'KAROL BAGH MARKET, NEW DELHI - 110005', 'pincode': '110005'},
        'weight_kg': 2.0, 'product': 'Clothing'},

    'SHP100023': {'seller': {'name': 'Bandra with Pincode',
        'address': 'Waterfield Road, Bandra West, Mumbai 400050', 'pincode': '400050'},
        'weight_kg': 0.7, 'product': 'Candles'},

    # ── Tier 2: no pincode — matched via area keyword ─────────────────────────

    'SHP100008': {'seller': {'name': 'CP Leather Works',
        'address': 'CP Outer Circle, Block F, New Delhi', 'pincode': ''},
        'weight_kg': 2.0, 'product': 'Leather wallets'},

    'SHP100009': {'seller': {'name': 'Karol Bagh Sarees',
        'address': 'Ajmal Khan Market, Karol Bagh, ND', 'pincode': ''},
        'weight_kg': 0.9, 'product': 'Silk sarees'},

    'SHP100010': {'seller': {'name': 'Bandra Arts Studio',
        'address': 'Hill Road, Bandra, Mumbai - Maharashtra', 'pincode': ''},
        'weight_kg': 1.8, 'product': 'Art prints'},

    'SHP100011': {'seller': {'name': 'Kora Gadgets',
        'address': '3rd Floor, HSR Layout to Koramangala Link Rd, Bangalore', 'pincode': ''},
        'weight_kg': 0.6, 'product': 'Smart watch'},

    'SHP100012': {'seller': {'name': 'MG Road Jewellers',
        'address': 'Cunningham Road, Near MG Road, Bengaluru', 'pincode': ''},
        'weight_kg': 0.1, 'product': 'Gold chain'},

    'SHP100013': {'seller': {'name': 'Fort Antiques',
        'address': 'Horniman Circle, Fort Area, Bombay', 'pincode': ''},
        'weight_kg': 4.2, 'product': 'Brass showpiece'},

    'SHP100014': {'seller': {'name': 'Civil Lines Bakery',
        'address': 'Behind St Stephens, Civil Lines Metro, Delhi', 'pincode': ''},
        'weight_kg': 2.5, 'product': 'Gift hamper'},

    'SHP100015': {'seller': {'name': 'N.Delhi Traders',
        'address': 'Connaught Circus, N.Delhi', 'pincode': ''},
        'weight_kg': 7.0, 'product': 'Office supplies'},

    'SHP100016': {'seller': {'name': 'Koramangala Flowers',
        'address': 'Koramangla 1st Block, Blore 56', 'pincode': ''},  # misspelled
        'weight_kg': 0.3, 'product': 'Dried flowers'},

    # ── Tier 3: fuzzy match — vague address, no clean keyword ─────────────────

    'SHP100017': {'seller': {'name': 'South Mumbai Spices',
        'address': 'Near Victoria Terminus, Bombay Central business area', 'pincode': ''},
        'weight_kg': 3.4, 'product': 'Premium tea'},

    'SHP100018': {'seller': {'name': 'North Delhi Crafts',
        'address': 'Rajiv Chowk area, Central Delhi commercial zone', 'pincode': ''},
        'weight_kg': 1.1, 'product': 'Wooden toys'},

    # ── Edge cases ────────────────────────────────────────────────────────────

    'SHP100019': {'seller': {'name': 'Unknown Pincode Seller',
        'address': 'Some Street, Unknown Town 999999, India', 'pincode': '999999'},
        'weight_kg': 0.5, 'product': 'Test item'},  # pincode not in sort master → UNKNOWN

    'SHP100020': {'seller': {'name': 'No Info Seller',
        'address': 'India', 'pincode': ''},  # too vague → UNKNOWN
        'weight_kg': 1.0, 'product': 'Unknown'},

    'SHP100021': {'seller': {'name': 'Duplicate Check',
        'address': 'F-12, Connaught Place, New Delhi 110001, INDIA', 'pincode': '110001'},
        'weight_kg': 0.2, 'product': 'Mobile case'},

    'SHP100022': {'seller': {'name': 'Pin-Only Address',
        'address': '560034', 'pincode': '560034'},  # just a pincode string
        'weight_kg': 8.5, 'product': 'Electronic parts'},

    'SHP100024': {'seller': {'name': 'Extra Whitespace Seller',
        'address': '  MG  Road  ,  Bangalore  ', 'pincode': ''},
        'weight_kg': 1.3, 'product': 'Sunglasses'},
}


# ─── Auth ─────────────────────────────────────────────────────────────────────

def require_bearer(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer ') or auth[7:].strip() != VALID_TOKEN:
            return jsonify({'error': 'Unauthorized'}), 401
        return fn(*args, **kwargs)
    return wrapper


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get('/v1/health')
def health():
    return jsonify({'status': 'ok', 'shipments_available': len(MOCK_SHIPMENTS)})


@app.get('/v1/shipments')
@require_bearer
def list_shipments():
    """List all mock IDs — useful for testing."""
    return jsonify({
        'shipments': [
            {
                'shipment_id': sid,
                'seller_name': d['seller']['name'],
                'address': d['seller']['address'],
                'pincode': d['seller']['pincode'] or '(none)',
                'product': d['product'],
                'expected_tier': _tier_hint(d['seller']['address'], d['seller']['pincode']),
            }
            for sid, d in MOCK_SHIPMENTS.items()
        ],
        'total': len(MOCK_SHIPMENTS),
    })


@app.get('/v1/shipments/<shipment_id>')
@require_bearer
def get_shipment(shipment_id):
    data = MOCK_SHIPMENTS.get(shipment_id.upper().strip())
    if not data:
        return jsonify({'error': f'Shipment not found: {shipment_id}'}), 404
    return jsonify({
        'shipment_id': shipment_id.upper(),
        'seller':      data['seller'],
        'weight_kg':   data['weight_kg'],
        'product':     data['product'],
    })


def _tier_hint(address, pincode):
    if pincode and pincode.isdigit() and len(pincode) == 6 and pincode not in ('999999',):
        return 'Tier 1 (pincode)'
    kws = ['connaught', 'cp', 'civil lines', 'karol bagh', 'fort',
           'bandra', 'koramangala', 'mg road']
    for kw in kws:
        if kw in address.lower():
            return 'Tier 2 (keyword)'
    return 'Tier 3 / UNKNOWN'


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 9100))
    print(f'\n  Mock Shipment API  →  http://localhost:{port}')
    print(f'  Auth token         →  Bearer {VALID_TOKEN}')
    print(f'  Shipments loaded   →  {len(MOCK_SHIPMENTS)}\n')
    app.run(host='0.0.0.0', port=port)
