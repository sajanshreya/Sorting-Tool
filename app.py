"""
ShipSort — Flask Backend
Handles scan requests: fetches address from shipment API, returns sort code
"""

import os
import time
import sqlite3
import logging
from datetime import datetime
from functools import wraps

import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

from matcher import match_sort_code

# ─── Config ──────────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests from your frontend

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

# Load from environment variables (set in your cloud host or .env file)
SHIPMENT_API_BASE  = os.environ['SHIPMENT_API_BASE']       # e.g. https://api.yourcompany.com
SHIPMENT_API_TOKEN = os.environ['SHIPMENT_API_TOKEN']      # Bearer token
DB_PATH            = os.environ.get('DB_PATH', 'sort_cache.db')
RATE_LIMIT_RPS     = int(os.environ.get('RATE_LIMIT_RPS', '20'))  # max scans/second per IP


# ─── Simple in-memory rate limiter ───────────────────────────────────────────

_rate_store: dict[str, list[float]] = {}

def rate_limit(max_per_second: int):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            ip  = request.remote_addr or 'unknown'
            now = time.time()
            hits = _rate_store.get(ip, [])
            hits = [t for t in hits if now - t < 1.0]  # last 1 second
            if len(hits) >= max_per_second:
                return jsonify({'error': 'Too many requests, slow down'}), 429
            hits.append(now)
            _rate_store[ip] = hits
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ─── DB setup ────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS scan_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                scanned_at  TEXT NOT NULL,
                shipment_id TEXT NOT NULL,
                address     TEXT,
                pincode     TEXT,
                sort_code   TEXT,
                rider_zone  TEXT,
                match_method TEXT,
                confidence  INTEGER,
                latency_ms  INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_scanned_at  ON scan_log(scanned_at);
            CREATE INDEX IF NOT EXISTS idx_shipment_id ON scan_log(shipment_id);
        """)
    log.info('DB initialised at %s', DB_PATH)


# ─── Shipment API client ──────────────────────────────────────────────────────

def fetch_shipment_address(shipment_id: str) -> dict:
    """
    Call your company's shipment REST API and return the seller address.
    Adjust the URL pattern and response field names to match your API.

    Expected response shape (adjust as needed):
    {
      "shipment_id": "SHP123",
      "seller": {
        "address": "123 MG Road, Koramangala, Bangalore 560034, Karnataka",
        "pincode": "560034"   ← optional; we also extract from address string
      }
    }
    """
    url = f"{SHIPMENT_API_BASE.rstrip('/')}/shipments/{shipment_id}"
    headers = {
        'Authorization': f'Bearer {SHIPMENT_API_TOKEN}',
        'Accept': 'application/json',
    }
    resp = requests.get(url, headers=headers, timeout=5)
    resp.raise_for_status()
    data = resp.json()

    # ── ADAPT THIS BLOCK to match your actual API response structure ──────────
    # Common patterns:
    # data['seller']['address']       → seller address string
    # data['pickup_address']          → pickup/seller address
    # data['consignor_address']       → some APIs call it consignor
    # data['shipment']['from_address']['full_address']
    address = (
        data.get('seller', {}).get('address')
        or data.get('pickup_address')
        or data.get('consignor_address')
        or data.get('from_address')
        or ''
    )
    pincode = (
        data.get('seller', {}).get('pincode')
        or data.get('pickup_pincode')
        or ''
    )
    # ─────────────────────────────────────────────────────────────────────────

    if not address:
        raise ValueError(f'No seller address found in API response for {shipment_id}')

    return {'address': address, 'pincode': str(pincode) if pincode else None}


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get('/')
def index():
    """Serve the scanner UI directly from Flask — no separate static host needed."""
    return send_from_directory('.', 'index.html')


@app.get('/api/health')
def health():
    try:
        with get_db() as conn:
            conn.execute('SELECT 1 FROM sort_master LIMIT 1').fetchone()
        db_ok = True
    except Exception:
        db_ok = False
    return jsonify({'status': 'ok', 'db': 'ok' if db_ok else 'empty', 'ts': datetime.utcnow().isoformat()})


@app.post('/api/scan')
@rate_limit(RATE_LIMIT_RPS)
def scan():
    body = request.get_json(silent=True) or {}
    shipment_id = (body.get('shipment_id') or '').strip().upper()

    if not shipment_id:
        return jsonify({'error': 'shipment_id is required'}), 400
    if len(shipment_id) > 50:
        return jsonify({'error': 'shipment_id too long'}), 400

    t0 = time.perf_counter()

    # 1) Fetch address from your shipment API
    try:
        shipment = fetch_shipment_address(shipment_id)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response else 0
        if status == 404:
            return jsonify({'error': f'Shipment {shipment_id} not found'}), 404
        log.error('Shipment API error for %s: %s', shipment_id, e)
        return jsonify({'error': 'Shipment API unavailable, try again'}), 502
    except requests.RequestException as e:
        log.error('Network error fetching %s: %s', shipment_id, e)
        return jsonify({'error': 'Cannot reach shipment API'}), 503
    except ValueError as e:
        return jsonify({'error': str(e)}), 422

    address = shipment['address']
    hint_pincode = shipment.get('pincode')

    # 2) Match to sort code
    result = match_sort_code(address, DB_PATH, hint_pincode=hint_pincode)

    latency_ms = int((time.perf_counter() - t0) * 1000)

    # 3) Log the scan
    _log_scan(
        shipment_id=shipment_id,
        address=address,
        pincode=result.get('pincode'),
        sort_code=result.get('sort_code'),
        rider_zone=result.get('rider_zone'),
        match_method=result.get('match_method'),
        confidence=result.get('confidence'),
        latency_ms=latency_ms,
    )

    return jsonify({
        'shipment_id':  shipment_id,
        'address':      address,
        'pincode':      result.get('pincode'),
        'sort_code':    result.get('sort_code'),
        'rider_zone':   result.get('rider_zone'),
        'match_method': result.get('match_method'),
        'confidence':   result.get('confidence'),
        'latency_ms':   latency_ms,
    })


@app.get('/api/stats')
def stats():
    """Basic stats for ops managers — today's scan counts, top sort codes, unmatched rate."""
    today = datetime.utcnow().date().isoformat()
    with get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM scan_log WHERE scanned_at >= ?", (today,)
        ).fetchone()[0]
        unmatched = conn.execute(
            "SELECT COUNT(*) FROM scan_log WHERE scanned_at >= ? AND (sort_code IS NULL OR sort_code = 'UNKNOWN')",
            (today,)
        ).fetchone()[0]
        top_codes = conn.execute(
            """SELECT sort_code, COUNT(*) as cnt FROM scan_log
               WHERE scanned_at >= ? AND sort_code IS NOT NULL AND sort_code != 'UNKNOWN'
               GROUP BY sort_code ORDER BY cnt DESC LIMIT 10""",
            (today,)
        ).fetchall()

    return jsonify({
        'date':          today,
        'total_scans':   total,
        'unmatched':     unmatched,
        'unmatched_pct': round(unmatched / total * 100, 1) if total else 0,
        'top_sort_codes': [{'code': r['sort_code'], 'count': r['cnt']} for r in top_codes],
    })


def _log_scan(**kwargs):
    try:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO scan_log
                   (scanned_at, shipment_id, address, pincode, sort_code,
                    rider_zone, match_method, confidence, latency_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.utcnow().isoformat(),
                    kwargs['shipment_id'],
                    kwargs.get('address'),
                    kwargs.get('pincode'),
                    kwargs.get('sort_code'),
                    kwargs.get('rider_zone'),
                    kwargs.get('match_method'),
                    kwargs.get('confidence'),
                    kwargs.get('latency_ms'),
                )
            )
    except Exception as e:
        log.error('Failed to log scan: %s', e)


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)
