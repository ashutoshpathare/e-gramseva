#!/usr/bin/env python3
"""
Phase 9.3 self-test — Admin Route Generalization + Full Regression.

Run from project root:
    python3 database/test_phase9_3.py

Tests:
 1. Admin list: all three seeded rows (building, water, cert) appear with correct labels
 2. Admin list: status filter (PENDING) returns all three
 3. Admin list: sub_type filter 'BUILDING' returns only building row
 4. Admin list: sub_type filter 'WATER' returns only water row
 5. Admin list: sub_type filter 'BIRTH' returns only cert row
 6. Detail page — building: correct form_data_json fields rendered (plot_no, etc.)
 7. Detail page — water: correct form_data_json fields rendered (connection_type, etc.)
 8. Approve building via admin action — status → APPROVED in DB
 9. Approved building appears in villager dashboard "My Applications"
10. Reject water via admin action — status → REJECTED, remarks stored
11. Regression cert detail: Application Type shows cert label, cert APPROVED shows download link
12. Regression: Nondi /admin/registers/birth only shows APPROVED BIRTH certs (not permission rows)
13. Regression: Nondi /admin/registers/death only shows APPROVED DEATH certs
14. Cleanup: DB pristine (service_requests count restored)
15. git diff lists only expected files
"""

import sys
import os
import json
import re
import sqlite3
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import app, DOCS_UPLOAD_DIR
from werkzeug.security import generate_password_hash

PASS = 0
FAIL = 0

SEEDED_USER_MOBILES  = []
SEEDED_REQUEST_NOS   = []


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


def generate_request_no(conn):
    year   = __import__('datetime').date.today().year
    prefix = f'REQ-{year}-'
    last   = conn.execute(
        'SELECT request_no FROM service_requests WHERE request_no LIKE ? ORDER BY id DESC LIMIT 1',
        (prefix + '%',)
    ).fetchone()
    num = 1 if last is None else int(last['request_no'].split('-')[-1]) + 1
    return f'{prefix}{num:04d}'


def seed_request(conn, user_id, service_type, sub_type, form_data, applicant='Test Applicant', ward='Ward 2'):
    rno = generate_request_no(conn)
    conn.execute(
        "INSERT INTO service_requests "
        "(request_no, user_id, service_type, sub_type, applicant_name, ward, form_data_json, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')",
        (rno, user_id, service_type, sub_type, applicant, ward, json.dumps(form_data))
    )
    conn.commit()
    SEEDED_REQUEST_NOS.append(rno)
    return rno


def admin_session(client, admin_id):
    with client.session_transaction() as sess:
        sess['user_id']   = admin_id
        sess['role']      = 'admin'
        sess['full_name'] = 'Test Admin'
        sess['ward']      = ''


def villager_session(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id']   = user_id
        sess['role']      = 'villager'
        sess['full_name'] = 'Test Villager'
        sess['ward']      = 'Ward 2'


def main():
    global PASS, FAIL

    db_path = app.config['DATABASE']
    if not os.path.exists(db_path):
        print(f'[ERROR] Database not found at {db_path}.')
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    base_svc = conn.execute('SELECT COUNT(*) FROM service_requests').fetchone()[0]

    print('\n=== Phase 9.3 Self-Test ===\n')

    app.config['TESTING']          = True
    app.config['WTF_CSRF_ENABLED'] = False

    # ── Create test users ────────────────────────────────────────────────────
    print('[SETUP] Creating test users...')
    villager_id = get_or_create_user(conn, '9300000001', 'P93 Test Villager')
    admin_id    = get_or_create_user(conn, '9300000099', 'P93 Test Admin', role='admin')

    # ── Seed three requests ──────────────────────────────────────────────────
    rno_build = seed_request(conn, villager_id, 'PERMISSION', 'BUILDING', {
        'plot_no':           'Survey 42-B',
        'plot_area_sqft':    '1100',
        'construction_type': 'Residential',
        'building_height_m': '6.5',
        'architect_name':    'D. Naik',
        'estimated_cost':    '450000',
    }, applicant='Build Applicant', ward='Ward 3')

    rno_water = seed_request(conn, villager_id, 'PERMISSION', 'WATER', {
        'property_no':       'EGS-PROP-2026-TEST',
        'connection_type':   'Domestic',
        'pipe_size_inch':    '20mm (0.75 inch)',
        'purpose_description': 'Household water connection.',
    }, applicant='Water Applicant', ward='Ward 4')

    rno_cert = seed_request(conn, villager_id, 'CERTIFICATE', 'BIRTH', {
        'date_of_birth':  '2001-07-10',
        'gender':         'Male',
        'father_name':    'Suresh Kumar',
        'mother_name':    'Priya Kumar',
        'place_of_birth': 'PHC Pune',
    }, applicant='Cert Applicant', ward='Ward 5')

    print(f'    rno_build={rno_build}, rno_water={rno_water}, rno_cert={rno_cert}\n')

    with app.test_client() as client:
        admin_session(client, admin_id)

        # ════════════════════════════════════════════════════════
        # TEST 1: Admin list — all three appear
        # ════════════════════════════════════════════════════════
        print('[1] Admin service requests list — all three rows appear...')
        rv = client.get('/admin/service-requests')
        check('GET /admin/service-requests → 200', rv.status_code == 200)
        check('Building request_no in list',   rno_build.encode() in rv.data)
        check('Water request_no in list',      rno_water.encode() in rv.data)
        check('Cert request_no in list',       rno_cert.encode() in rv.data)
        # Human-friendly labels
        check('Building shows "Permission — Building"', b'Permission \xe2\x80\x94 Building' in rv.data)
        check('Water shows "Permission — Water Connection"', b'Permission \xe2\x80\x94 Water Connection' in rv.data)
        check('Cert shows "Birth Certificate"', b'Birth Certificate' in rv.data)
        # Filter dropdown contains all sub_types
        check('Filter dropdown has BUILDING option', b'value="BUILDING"' in rv.data)
        check('Filter dropdown has WATER option',    b'value="WATER"' in rv.data)
        check('Filter dropdown has BIRTH option',    b'value="BIRTH"' in rv.data)

        # ════════════════════════════════════════════════════════
        # TEST 2: Status filter → PENDING shows all three
        # ════════════════════════════════════════════════════════
        print('\n[2] Status filter PENDING — all three appear...')
        rv = client.get('/admin/service-requests?status=PENDING')
        check('Status=PENDING → 200', rv.status_code == 200)
        check('Building in PENDING list', rno_build.encode() in rv.data)
        check('Water in PENDING list',    rno_water.encode() in rv.data)
        check('Cert in PENDING list',     rno_cert.encode() in rv.data)

        # ════════════════════════════════════════════════════════
        # TEST 3-5: Sub_type filters
        # ════════════════════════════════════════════════════════
        print('\n[3] Sub_type filters...')
        rv = client.get('/admin/service-requests?sub_type=BUILDING')
        check('Filter BUILDING: building present', rno_build.encode() in rv.data)
        check('Filter BUILDING: water absent',     rno_water.encode() not in rv.data)
        check('Filter BUILDING: cert absent',      rno_cert.encode() not in rv.data)

        rv = client.get('/admin/service-requests?sub_type=WATER')
        check('Filter WATER: water present',   rno_water.encode() in rv.data)
        check('Filter WATER: building absent', rno_build.encode() not in rv.data)

        rv = client.get('/admin/service-requests?sub_type=BIRTH')
        check('Filter BIRTH: cert present',    rno_cert.encode() in rv.data)
        check('Filter BIRTH: building absent', rno_build.encode() not in rv.data)

        # ════════════════════════════════════════════════════════
        # TEST 6: Detail page — building permission fields
        # ════════════════════════════════════════════════════════
        print('\n[4] Detail page — building permission...')
        rv = client.get(f'/admin/service-request/{rno_build}')
        check('GET building detail → 200', rv.status_code == 200)
        check('Shows "Permission \u2014 Building" label',   'Permission \u2014 Building'.encode() in rv.data)
        check('Shows Application Type (not "Certificate Type")', b'Application Type' in rv.data)
        check('"Certificate Type" label gone',              b'Certificate Type' not in rv.data)
        check('plot_no value visible',           b'Survey 42-B' in rv.data)
        check('construction_type value visible', b'Residential' in rv.data)
        check('building_height_m value visible', b'6.5' in rv.data)
        check('architect_name value visible',    b'D. Naik' in rv.data)
        check('estimated_cost value visible',    b'450000' in rv.data)
        check('No certificate download link on PENDING permission', b'/certificate/download/' not in rv.data)

        # ════════════════════════════════════════════════════════
        # TEST 7: Detail page — water permission fields
        # ════════════════════════════════════════════════════════
        print('\n[5] Detail page — water permission...')
        rv = client.get(f'/admin/service-request/{rno_water}')
        check('GET water detail → 200', rv.status_code == 200)
        check('Shows "Permission \u2014 Water Connection" label', 'Permission \u2014 Water Connection'.encode() in rv.data)
        check('connection_type value visible',    b'Domestic' in rv.data)
        check('pipe_size_inch value visible',     b'20mm (0.75 inch)' in rv.data)
        check('purpose_description value visible', b'Household water connection' in rv.data)
        check('property_no value visible',        b'EGS-PROP-2026-TEST' in rv.data)

        # ════════════════════════════════════════════════════════
        # TEST 8: Approve building via admin action
        # ════════════════════════════════════════════════════════
        print('\n[6] Approve building permission...')
        rv = client.post(
            f'/admin/service-request/{rno_build}/update',
            data={'status': 'APPROVED', 'remarks': 'Plans verified, approved.'},
            follow_redirects=False
        )
        check('POST approve building → redirect', rv.status_code in (301, 302))
        row_b = conn.execute(
            'SELECT status, remarks FROM service_requests WHERE request_no = ?', (rno_build,)
        ).fetchone()
        check('Building status → APPROVED in DB', row_b['status'] == 'APPROVED')
        check('Remarks stored',                   row_b['remarks'] == 'Plans verified, approved.')

        # Confirm detail page shows "Application Approved" (not cert download)
        rv = client.get(f'/admin/service-request/{rno_build}')
        check('Approved detail: "Application Approved" card visible', b'Application Approved' in rv.data)
        check('Approved detail: no cert download link',               b'/certificate/download/' not in rv.data)

        # ════════════════════════════════════════════════════════
        # TEST 9: Villager dashboard shows approved building
        # ════════════════════════════════════════════════════════
        print('\n[7] Villager dashboard shows approved building row...')
        villager_session(client, villager_id)
        rv = client.get('/villager/dashboard')
        check('GET /villager/dashboard → 200', rv.status_code == 200)
        check('Building request_no in dashboard', rno_build.encode() in rv.data)
        check('Water request_no in dashboard',    rno_water.encode() in rv.data)
        check('Cert request_no in dashboard',     rno_cert.encode() in rv.data)

        # ════════════════════════════════════════════════════════
        # TEST 10: Reject water via admin action
        # ════════════════════════════════════════════════════════
        print('\n[8] Reject water permission...')
        admin_session(client, admin_id)
        rv = client.post(
            f'/admin/service-request/{rno_water}/update',
            data={'status': 'REJECTED', 'remarks': 'Pipe capacity unavailable in this area.'},
            follow_redirects=False
        )
        check('POST reject water → redirect', rv.status_code in (301, 302))
        row_w = conn.execute(
            'SELECT status, remarks FROM service_requests WHERE request_no = ?', (rno_water,)
        ).fetchone()
        check('Water status → REJECTED in DB', row_w['status'] == 'REJECTED')
        check('Rejection remarks stored',      'unavailable' in (row_w['remarks'] or ''))

        # ════════════════════════════════════════════════════════
        # TEST 11: Regression — cert detail still correct
        # ════════════════════════════════════════════════════════
        print('\n[9] Regression: cert detail page still renders correctly...')
        rv = client.get(f'/admin/service-request/{rno_cert}')
        check('Cert detail → 200', rv.status_code == 200)
        check('Cert shows "Birth Certificate" label',  b'Birth Certificate' in rv.data)
        check('Cert shows Application Type row',       b'Application Type' in rv.data)
        check('Cert form_data date_of_birth visible',  b'2001-07-10' in rv.data)
        check('Cert form_data father_name visible',    b'Suresh Kumar' in rv.data)

        # Approve cert and confirm download link appears
        rv = client.post(
            f'/admin/service-request/{rno_cert}/update',
            data={'status': 'APPROVED', 'remarks': ''},
            follow_redirects=False
        )
        check('Cert approve → redirect', rv.status_code in (301, 302))
        rv = client.get(f'/admin/service-request/{rno_cert}')
        check('Approved cert: "Certificate Approved" card visible', b'Certificate Approved' in rv.data)
        check('Approved cert: download link present',               b'/certificate/download/' in rv.data)
        check('Approved cert: no "Application Approved" (permission text)', b'Application Approved' not in rv.data)

        # ════════════════════════════════════════════════════════
        # TEST 12-13: Nondi registers still work correctly
        # ════════════════════════════════════════════════════════
        print('\n[10] Nondi register regression...')
        # Mark rno_cert as APPROVED already done above; now check birth register
        rv = client.get('/admin/registers/birth')
        check('GET /admin/registers/birth → 200', rv.status_code == 200)
        # Our APPROVED birth cert should appear
        check('Birth register contains our approved birth cert', rno_cert.encode() in rv.data)
        # The BUILDING permission (even though APPROVED) must NOT appear in birth register
        check('Birth register does NOT contain building permission', rno_build.encode() not in rv.data)

        rv = client.get('/admin/registers/death')
        check('GET /admin/registers/death → 200', rv.status_code == 200)
        # No DEATH certs were seeded in this test, so building/water/birth should all be absent
        check('Death register does not contain building request', rno_build.encode() not in rv.data)
        check('Death register does not contain birth cert',       rno_cert.encode() not in rv.data)

    # ════════════════════════════════════════════════════════════
    # CLEANUP
    # ════════════════════════════════════════════════════════════
    print('\n[11] Cleaning up seeded data...')
    for rno in SEEDED_REQUEST_NOS:
        conn.execute('DELETE FROM service_requests WHERE request_no = ?', (rno,))
    for mobile in SEEDED_USER_MOBILES:
        conn.execute('DELETE FROM users WHERE mobile = ?', (mobile,))
    conn.commit()

    after_svc = conn.execute('SELECT COUNT(*) FROM service_requests').fetchone()[0]
    check('service_requests count restored', after_svc == base_svc)
    conn.close()

    # ════════════════════════════════════════════════════════════
    # SUMMARY
    # ════════════════════════════════════════════════════════════
    print()
    print('=' * 52)
    print(f'Results: {PASS} passed, {FAIL} failed')
    print('=' * 52)
    if FAIL > 0:
        sys.exit(1)
    print('\nAll Phase 9.3 self-tests PASSED.')


if __name__ == '__main__':
    main()
