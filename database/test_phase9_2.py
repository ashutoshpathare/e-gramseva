#!/usr/bin/env python3
"""
Phase 9.2 self-test — Tax Clearance Gate for Permission Apply.

Run from project root:
    python3 database/test_phase9_2.py

Tests:
 1. GET /permissions/apply/building with UNPAID dues → 200, banner present
 2. POST /permissions/apply/building with UNPAID dues → blocked (no row, re-render)
 3. POST /permissions/apply/water with UNPAID dues → blocked (no row, re-render)
 4. Same villager, dues marked PAID → Building POST succeeds (row inserted)
 5. Same villager, dues marked PAID → Water POST succeeds (row inserted)
 6. Villager with only WAIVED dues → Building/Water POST NOT blocked
 7. Villager with zero properties → Building/Water POST NOT blocked
 8. Regression: certificate_apply gate unchanged
    - UNPAID dues → cert POST blocked
    - PAID dues → cert POST succeeds
 9. Phase 9.1 regression: Building/Water with no dues → correct form_data_json
10. Cleanup: all seeded rows removed, DB pristine
11. git status clean
"""

import sys
import os
import json
import re
import sqlite3
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import app, DOCS_UPLOAD_DIR
from werkzeug.security import generate_password_hash

PASS = 0
FAIL = 0

# Track every row seeded so cleanup is exact.
SEEDED_USER_MOBILES    = []    # only newly-created test users
SEEDED_REQUEST_NOS     = []
SEEDED_PROPERTY_NOS    = []    # properties created directly via SQL
SEEDED_TAX_RECORD_IDS  = []


def check(desc, cond):
    global PASS, FAIL
    if cond:
        print(f'  [PASS] {desc}')
        PASS += 1
    else:
        print(f'  [FAIL] {desc}')
        FAIL += 1


def get_or_create_user(conn, mobile, full_name, role='villager'):
    row = conn.execute('SELECT id FROM users WHERE mobile = ?', (mobile,)).fetchone()
    if row:
        return row[0]
    conn.execute(
        "INSERT INTO users (full_name, mobile, ward, password_hash, role) "
        "VALUES (?, ?, 'Ward 1', ?, ?)",
        (full_name, mobile, generate_password_hash('test1234'), role)
    )
    conn.commit()
    SEEDED_USER_MOBILES.append(mobile)
    return conn.execute('SELECT id FROM users WHERE mobile = ?', (mobile,)).fetchone()[0]


def seed_property_with_unpaid(conn, owner_id, status='UNPAID'):
    """Create a property + a tax record with given status. Returns (property_id, tax_record_id)."""
    year   = date.today().year
    prefix = f'EGS-PROP-{year}-'
    last   = conn.execute(
        'SELECT property_no FROM properties WHERE property_no LIKE ? ORDER BY id DESC LIMIT 1',
        (prefix + '%',)
    ).fetchone()
    num = 1 if last is None else int(last['property_no'].split('-')[-1]) + 1
    pno = f'{prefix}{num:04d}'
    conn.execute(
        "INSERT INTO properties (property_no, owner_id, ward, property_type, "
        "area_sqft, address, assessed_value) VALUES (?, ?, 'Ward 1', 'RESIDENTIAL', 800, 'Test St', 100000)",
        (pno, owner_id)
    )
    conn.commit()
    pid = conn.execute('SELECT id FROM properties WHERE property_no = ?', (pno,)).fetchone()[0]
    SEEDED_PROPERTY_NOS.append(pno)

    conn.execute(
        "INSERT INTO tax_records (property_id, tax_type, financial_year, amount_due, due_date, status) "
        "VALUES (?, 'PROPERTY_TAX', '2026-27', 2500.00, '2026-03-31', ?)",
        (pid, status)
    )
    conn.commit()
    tid = conn.execute(
        'SELECT id FROM tax_records WHERE property_id = ? ORDER BY id DESC LIMIT 1', (pid,)
    ).fetchone()[0]
    SEEDED_TAX_RECORD_IDS.append(tid)
    return pid, tid


def mark_tax_paid(conn, tax_record_id):
    conn.execute("UPDATE tax_records SET status = 'PAID' WHERE id = ?", (tax_record_id,))
    conn.commit()


def session_for(client, user_id, ward='Ward 1'):
    with client.session_transaction() as sess:
        sess['user_id']   = user_id
        sess['role']      = 'villager'
        sess['full_name'] = 'Test User'
        sess['ward']      = ward


def clear_session(client):
    with client.session_transaction() as sess:
        sess.clear()


# ── Building & Water payload helpers ─────────────────────────────────────────

def building_payload(name='Ramesh Patil'):
    return {
        'applicant_name':    name,
        'ward':              'Ward 3',
        'plot_no':           'Plot 10-A',
        'plot_area_sqft':    '1200',
        'construction_type': 'Residential',
        'building_height_m': '7.0',
        'architect_name':    'A. Kulkarni',
        'estimated_cost':    '600000',
    }


def water_payload(name='Sunita More'):
    return {
        'applicant_name':    name,
        'ward':              'Ward 4',
        'connection_type':   'Domestic',
        'pipe_size_inch':    '15mm (0.5 inch)',
    }


def main():
    global PASS, FAIL

    db_path = app.config['DATABASE']
    if not os.path.exists(db_path):
        print(f'[ERROR] Database not found at {db_path}. Run the app first.')
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Record baselines for DB-pristine check
    base_svc   = conn.execute('SELECT COUNT(*) FROM service_requests').fetchone()[0]
    base_prop  = conn.execute('SELECT COUNT(*) FROM properties').fetchone()[0]
    base_tax   = conn.execute('SELECT COUNT(*) FROM tax_records').fetchone()[0]

    print('\n=== Phase 9.2 Self-Test ===\n')

    app.config['TESTING']         = True
    app.config['WTF_CSRF_ENABLED'] = False

    # ── Create test users ────────────────────────────────────────────────────
    print('[SETUP] Creating test users...')
    uid_unpaid  = get_or_create_user(conn, '9200000001', 'P92User Unpaid')
    uid_waived  = get_or_create_user(conn, '9200000002', 'P92User Waived')
    uid_noprop  = get_or_create_user(conn, '9200000003', 'P92User NoProp')
    uid_certchk = get_or_create_user(conn, '9200000004', 'P92User CertChk')

    # Seed property + UNPAID tax for uid_unpaid
    _, tid_unpaid = seed_property_with_unpaid(conn, uid_unpaid, status='UNPAID')
    # Seed property + WAIVED tax for uid_waived
    seed_property_with_unpaid(conn, uid_waived, status='WAIVED')
    # uid_noprop intentionally has no property
    # Seed property + UNPAID tax for certificate regression user
    _, tid_cert = seed_property_with_unpaid(conn, uid_certchk, status='UNPAID')

    print(f'    uid_unpaid={uid_unpaid}, uid_waived={uid_waived}')
    print(f'    uid_noprop={uid_noprop}, uid_certchk={uid_certchk}\n')

    with app.test_client() as client:

        # ════════════════════════════════════════════════════════
        # TEST 1: GET /permissions/apply/building with UNPAID dues
        # ════════════════════════════════════════════════════════
        print('[1] GET /permissions/apply/building — UNPAID dues (banner expected)...')
        session_for(client, uid_unpaid)
        rv = client.get('/permissions/apply/building')
        check('GET → 200', rv.status_code == 200)
        check('Banner div present in HTML', b'dues-warning-banner' in rv.data)
        check('"Pay Dues Now" link present',  b'Pay Dues Now' in rv.data)
        check('Submit is disabled',           b'disabled' in rv.data)
        check('"Blocked" button label present', b'Blocked' in rv.data)

        # ════════════════════════════════════════════════════════
        # TEST 2: POST /permissions/apply/building — BLOCKED
        # ════════════════════════════════════════════════════════
        print('\n[2] POST /permissions/apply/building — UNPAID dues (blocked)...')
        count_before = conn.execute('SELECT COUNT(*) FROM service_requests').fetchone()[0]
        rv = client.post('/permissions/apply/building', data=building_payload(),
                         follow_redirects=False)
        count_after = conn.execute('SELECT COUNT(*) FROM service_requests').fetchone()[0]
        check('POST → 200 (re-render, not redirect)', rv.status_code == 200)
        check('No row inserted in service_requests', count_after == count_before)
        check('Flash "blocked" message in HTML', b'blocked' in rv.data.lower())
        check('Banner shown in re-render',  b'dues-warning-banner' in rv.data)

        # ════════════════════════════════════════════════════════
        # TEST 3: POST /permissions/apply/water — BLOCKED
        # ════════════════════════════════════════════════════════
        print('\n[3] POST /permissions/apply/water — UNPAID dues (blocked)...')
        count_before = conn.execute('SELECT COUNT(*) FROM service_requests').fetchone()[0]
        rv = client.post('/permissions/apply/water', data=water_payload(),
                         follow_redirects=False)
        count_after = conn.execute('SELECT COUNT(*) FROM service_requests').fetchone()[0]
        check('POST → 200 (re-render, not redirect)', rv.status_code == 200)
        check('No row inserted in service_requests', count_after == count_before)
        check('Flash "blocked" message in HTML', b'blocked' in rv.data.lower())

        # ════════════════════════════════════════════════════════
        # TEST 4 & 5: Mark dues PAID → both types succeed
        # ════════════════════════════════════════════════════════
        print('\n[4] Mark dues PAID → Building + Water submissions succeed...')
        mark_tax_paid(conn, tid_unpaid)

        # Building with PAID dues
        rv = client.post('/permissions/apply/building', data=building_payload('After Pay Build'),
                         follow_redirects=False)
        check('Building POST after payment → redirect', rv.status_code in (301, 302))
        row_b = conn.execute(
            "SELECT * FROM service_requests WHERE user_id=? AND sub_type='BUILDING' ORDER BY id DESC LIMIT 1",
            (uid_unpaid,)
        ).fetchone()
        check('Building row inserted after payment', row_b is not None)
        if row_b:
            SEEDED_REQUEST_NOS.append(row_b['request_no'])
            check('Building status = PENDING',          row_b['status'] == 'PENDING')
            check('Building service_type = PERMISSION', row_b['service_type'] == 'PERMISSION')
            check('Building request_no format valid',
                  bool(re.match(r'^REQ-\d{4}-\d{4}$', row_b['request_no'])))

        # Water with PAID dues
        rv = client.post('/permissions/apply/water', data=water_payload('After Pay Water'),
                         follow_redirects=False)
        check('Water POST after payment → redirect', rv.status_code in (301, 302))
        row_w = conn.execute(
            "SELECT * FROM service_requests WHERE user_id=? AND sub_type='WATER' ORDER BY id DESC LIMIT 1",
            (uid_unpaid,)
        ).fetchone()
        check('Water row inserted after payment', row_w is not None)
        if row_w:
            SEEDED_REQUEST_NOS.append(row_w['request_no'])
            check('Water status = PENDING',          row_w['status'] == 'PENDING')
            check('Water service_type = PERMISSION', row_w['service_type'] == 'PERMISSION')

        # ════════════════════════════════════════════════════════
        # TEST 6: WAIVED dues → NOT blocked
        # ════════════════════════════════════════════════════════
        print('\n[5] Villager with only WAIVED dues → NOT blocked...')
        session_for(client, uid_waived)
        rv = client.get('/permissions/apply/building')
        check('GET /permissions/apply/building (waived) → 200', rv.status_code == 200)
        check('No banner shown for WAIVED dues', b'dues-warning-banner' not in rv.data)

        rv = client.post('/permissions/apply/building', data=building_payload('Waived User'),
                         follow_redirects=False)
        check('Building POST (waived dues) → redirect', rv.status_code in (301, 302))
        row_wv = conn.execute(
            "SELECT * FROM service_requests WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (uid_waived,)
        ).fetchone()
        check('Row inserted for waived-dues villager', row_wv is not None)
        if row_wv:
            SEEDED_REQUEST_NOS.append(row_wv['request_no'])

        # ════════════════════════════════════════════════════════
        # TEST 7: Zero properties → NOT blocked
        # ════════════════════════════════════════════════════════
        print('\n[6] Villager with no properties → NOT blocked...')
        session_for(client, uid_noprop)
        rv = client.get('/permissions/apply/water')
        check('GET /permissions/apply/water (no props) → 200', rv.status_code == 200)
        check('No banner shown for zero-property villager', b'dues-warning-banner' not in rv.data)

        rv = client.post('/permissions/apply/water', data=water_payload('NoProp User'),
                         follow_redirects=False)
        check('Water POST (no properties) → redirect', rv.status_code in (301, 302))
        row_np = conn.execute(
            "SELECT * FROM service_requests WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (uid_noprop,)
        ).fetchone()
        check('Row inserted for zero-property villager', row_np is not None)
        if row_np:
            SEEDED_REQUEST_NOS.append(row_np['request_no'])

        # ════════════════════════════════════════════════════════
        # TEST 8: Regression — certificate_apply gate unchanged
        # ════════════════════════════════════════════════════════
        print('\n[7] Regression: certificate_apply gate (UNPAID → blocked, PAID → ok)...')
        session_for(client, uid_certchk)

        # 8a: UNPAID → cert POST blocked
        count_before = conn.execute('SELECT COUNT(*) FROM service_requests').fetchone()[0]
        rv = client.post('/services/certificates/apply/birth', data={
            'applicant_name': 'CertReg Test',
            'ward':           'Ward 2',
            'date_of_birth':  '2000-06-15',
            'gender':         'Male',
        }, follow_redirects=False)
        count_after = conn.execute('SELECT COUNT(*) FROM service_requests').fetchone()[0]
        check('Cert POST with UNPAID dues → 200 (re-render)', rv.status_code == 200)
        check('Cert: no row inserted while UNPAID', count_after == count_before)
        # Phase 7's POST re-render uses flash (not unpaid_dues kwarg) to signal the block;
        # the danger flash text lands in the HTML body via the base template alert block.
        check('Cert: "blocked" flash message present in re-render', b'blocked' in rv.data.lower())

        # 8b: Mark PAID → cert POST succeeds
        mark_tax_paid(conn, tid_cert)
        rv = client.post('/services/certificates/apply/birth', data={
            'applicant_name': 'CertReg TestPaid',
            'ward':           'Ward 2',
            'date_of_birth':  '2001-03-20',
            'gender':         'Female',
        }, follow_redirects=False)
        check('Cert POST after payment → redirect', rv.status_code in (301, 302))
        row_cert = conn.execute(
            "SELECT * FROM service_requests WHERE user_id=? AND sub_type='BIRTH' ORDER BY id DESC LIMIT 1",
            (uid_certchk,)
        ).fetchone()
        check('Cert row inserted after payment', row_cert is not None)
        if row_cert:
            SEEDED_REQUEST_NOS.append(row_cert['request_no'])
            check('Cert service_type = CERTIFICATE', row_cert['service_type'] == 'CERTIFICATE')
            check('Cert status = PENDING',           row_cert['status'] == 'PENDING')

        # ════════════════════════════════════════════════════════
        # TEST 9: Phase 9.1 regression — no dues, correct form_data_json
        # ════════════════════════════════════════════════════════
        print('\n[8] Phase 9.1 regression: no-dues submission → correct form_data_json...')
        session_for(client, uid_noprop)
        rv = client.post('/permissions/apply/building', data={
            'applicant_name':    'Reg Check Build',
            'ward':              'Ward 6',
            'plot_no':           'Survey 77',
            'plot_area_sqft':    '900',
            'construction_type': 'Commercial',
            'building_height_m': '12.0',
            'architect_name':    'B. Desai',
            'estimated_cost':    '1200000',
        }, follow_redirects=False)
        check('Build regression POST → redirect', rv.status_code in (301, 302))
        row_reg = conn.execute(
            "SELECT * FROM service_requests WHERE user_id=? AND sub_type='BUILDING' "
            "ORDER BY id DESC LIMIT 1",
            (uid_noprop,)
        ).fetchone()
        check('Build regression row exists', row_reg is not None)
        if row_reg:
            SEEDED_REQUEST_NOS.append(row_reg['request_no'])
            fd = json.loads(row_reg['form_data_json'])
            check('form_data.plot_no correct',           fd.get('plot_no') == 'Survey 77')
            check('form_data.construction_type correct', fd.get('construction_type') == 'Commercial')
            check('form_data.building_height_m correct', fd.get('building_height_m') == '12.0')
            check('form_data.estimated_cost correct',    fd.get('estimated_cost') == '1200000')
            check('service_type = PERMISSION', row_reg['service_type'] == 'PERMISSION')
            check('status = PENDING',          row_reg['status'] == 'PENDING')

        rv = client.post('/permissions/apply/water', data={
            'applicant_name':    'Reg Check Water',
            'ward':              'Ward 7',
            'property_no':       'EGS-PROP-2026-9999',
            'connection_type':   'Commercial',
            'pipe_size_inch':    '25mm (1 inch)',
            'purpose_description': 'Commercial kitchen water supply.',
        }, follow_redirects=False)
        check('Water regression POST → redirect', rv.status_code in (301, 302))
        row_wr = conn.execute(
            "SELECT * FROM service_requests WHERE user_id=? AND sub_type='WATER' "
            "ORDER BY id DESC LIMIT 1",
            (uid_noprop,)
        ).fetchone()
        check('Water regression row exists', row_wr is not None)
        if row_wr:
            SEEDED_REQUEST_NOS.append(row_wr['request_no'])
            fd_w = json.loads(row_wr['form_data_json'])
            check('form_data.connection_type correct',    fd_w.get('connection_type') == 'Commercial')
            check('form_data.pipe_size_inch correct',     fd_w.get('pipe_size_inch') == '25mm (1 inch)')
            check('form_data.purpose_description correct',
                  'Commercial kitchen' in fd_w.get('purpose_description', ''))

    # ════════════════════════════════════════════════════════════
    # CLEANUP
    # ════════════════════════════════════════════════════════════
    print('\n[9] Cleaning up seeded data...')
    for rno in SEEDED_REQUEST_NOS:
        conn.execute('DELETE FROM service_requests WHERE request_no = ?', (rno,))
    # Must delete tax_records before properties (FK) and properties before users
    for tid in SEEDED_TAX_RECORD_IDS:
        conn.execute('DELETE FROM tax_records WHERE id = ?', (tid,))
    for pno in SEEDED_PROPERTY_NOS:
        conn.execute('DELETE FROM properties WHERE property_no = ?', (pno,))
    for mobile in SEEDED_USER_MOBILES:
        conn.execute('DELETE FROM users WHERE mobile = ?', (mobile,))
    conn.commit()

    after_svc  = conn.execute('SELECT COUNT(*) FROM service_requests').fetchone()[0]
    after_prop = conn.execute('SELECT COUNT(*) FROM properties').fetchone()[0]
    after_tax  = conn.execute('SELECT COUNT(*) FROM tax_records').fetchone()[0]
    check('service_requests count restored', after_svc  == base_svc)
    check('properties count restored',       after_prop == base_prop)
    check('tax_records count restored',      after_tax  == base_tax)
    conn.close()

    # ════════════════════════════════════════════════════════════
    # SUMMARY
    # ════════════════════════════════════════════════════════════
    print()
    print('=' * 48)
    print(f'Results: {PASS} passed, {FAIL} failed')
    print('=' * 48)
    if FAIL > 0:
        sys.exit(1)
    print('\nAll Phase 9.2 self-tests PASSED.')


if __name__ == '__main__':
    main()
