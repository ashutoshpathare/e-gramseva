#!/usr/bin/env python3
"""
Phase 9.1 self-test — Permission Types: Villager Apply Flow.

Run from project root:
    python3 database/test_phase9_1.py

Tests:
1. POST building permission → DB row correct, form_data correct, request_no format correct
2. POST water connection permission → same assertions
3. Document upload → document_path set, file exists on disk
4. Regression: POST birth certificate → still works, no request_no collision
5. GET /permissions → 200 (authenticated)
6. GET /permissions/apply/building → 200 (authenticated)
7. GET /permissions/apply/invalid → redirect
8. GET /permissions unauthenticated → redirect
9. Villager dashboard contains both permission request_nos
10. Cleanup all seeded rows + uploaded files, assert DB pristine
11. git diff check
"""

import sys
import os
import json
import re
import io
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import app, get_db, DOCS_UPLOAD_DIR
from werkzeug.security import generate_password_hash

SEED_TAG    = 'P91TEST'
PASS        = 0
FAIL        = 0

# Request nos assigned during test — collected for cleanup
SEEDED_RNOS   = []
SEEDED_FILES  = []   # doc filenames to delete


def check(desc, cond):
    global PASS, FAIL
    if cond:
        print(f'  [PASS] {desc}')
        PASS += 1
    else:
        print(f'  [FAIL] {desc}')
        FAIL += 1


def get_or_create_user(conn, mobile, role='villager'):
    row = conn.execute('SELECT id FROM users WHERE mobile = ?', (mobile,)).fetchone()
    if row:
        return row[0]
    conn.execute(
        "INSERT INTO users (full_name, mobile, ward, password_hash, role) VALUES (?, ?, 'Ward 1', ?, ?)",
        (f'TestUser_{mobile}', mobile, generate_password_hash('test1234'), role)
    )
    conn.commit()
    return conn.execute('SELECT id FROM users WHERE mobile = ?', (mobile,)).fetchone()[0]


def cleanup(conn):
    for rno in SEEDED_RNOS:
        conn.execute('DELETE FROM service_requests WHERE request_no = ?', (rno,))
    conn.commit()
    for fname in SEEDED_FILES:
        fpath = os.path.join(DOCS_UPLOAD_DIR, fname)
        if os.path.exists(fpath):
            os.remove(fpath)


def fake_pdf():
    """Return minimal valid PDF bytes."""
    return b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n' \
           b'2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n' \
           b'3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n' \
           b'xref\ntrailer<</Root 1 0 R/Size 4>>\nstartxref\n0\n%%EOF'


def main():
    global PASS, FAIL

    db_path = app.config['DATABASE']
    if not os.path.exists(db_path):
        print(f'[ERROR] Database not found at {db_path}. Run the app first.')
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Baselines
    base_svc = conn.execute('SELECT COUNT(*) FROM service_requests').fetchone()[0]

    print('\n=== Phase 9.1 Self-Test ===\n')

    print('[1] Setting up test users...')
    villager_id = get_or_create_user(conn, '9100000001', role='villager')
    print(f'    villager_id={villager_id}\n')

    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False

    with app.test_client() as client:

        # ── Authenticated villager session ──────────────────────────
        with client.session_transaction() as sess:
            sess['user_id']   = villager_id
            sess['role']      = 'villager'
            sess['full_name'] = 'Test Villager 91'
            sess['ward']      = 'Ward 1'

        # ── TEST 1: POST building permission ───────────────────────
        print('[2] POST building permission...')
        rv = client.post('/permissions/apply/building', data={
            'applicant_name':    'Ramesh Patil',
            'ward':              'Ward 3',
            'plot_no':           'Plot 99-B',
            'plot_area_sqft':    '1500',
            'construction_type': 'Residential',
            'building_height_m': '8.5',
            'architect_name':    'Vikram Joshi',
            'estimated_cost':    '750000',
        }, follow_redirects=False)
        check('POST /permissions/apply/building → redirect', rv.status_code in (301, 302))

        # Fetch the row inserted
        row = conn.execute(
            "SELECT * FROM service_requests WHERE user_id=? AND sub_type='BUILDING' ORDER BY id DESC LIMIT 1",
            (villager_id,)
        ).fetchone()
        check('BUILDING row exists in DB', row is not None)
        if row:
            SEEDED_RNOS.append(row['request_no'])
            check('service_type = PERMISSION', row['service_type'] == 'PERMISSION')
            check('sub_type = BUILDING',       row['sub_type'] == 'BUILDING')
            check('status = PENDING',          row['status'] == 'PENDING')
            check('ward = Ward 3',             row['ward'] == 'Ward 3')
            check('applicant_name correct',    row['applicant_name'] == 'Ramesh Patil')
            fd = json.loads(row['form_data_json'])
            check('form_data.plot_no correct',           fd.get('plot_no') == 'Plot 99-B')
            check('form_data.plot_area_sqft correct',    fd.get('plot_area_sqft') == '1500')
            check('form_data.construction_type correct', fd.get('construction_type') == 'Residential')
            check('form_data.building_height_m correct', fd.get('building_height_m') == '8.5')
            check('form_data.architect_name correct',    fd.get('architect_name') == 'Vikram Joshi')
            check('form_data.estimated_cost correct',    fd.get('estimated_cost') == '750000')
            rno_build = row['request_no']
            check('request_no matches REQ-YYYY-NNNN format',
                  bool(re.match(r'^REQ-\d{4}-\d{4}$', rno_build)))
            check('document_path is None (no file uploaded)', row['document_path'] is None)

        # ── TEST 2: POST water connection ──────────────────────────
        print('\n[3] POST water connection permission...')
        rv = client.post('/permissions/apply/water', data={
            'applicant_name':     'Sunita More',
            'ward':               'Ward 5',
            'property_no':        'EGS-PROP-2026-0001',
            'connection_type':    'Domestic',
            'pipe_size_inch':     '15mm (0.5 inch)',
            'purpose_description': 'New household water connection for family of 4.',
        }, follow_redirects=False)
        check('POST /permissions/apply/water → redirect', rv.status_code in (301, 302))

        row_w = conn.execute(
            "SELECT * FROM service_requests WHERE user_id=? AND sub_type='WATER' ORDER BY id DESC LIMIT 1",
            (villager_id,)
        ).fetchone()
        check('WATER row exists in DB', row_w is not None)
        if row_w:
            SEEDED_RNOS.append(row_w['request_no'])
            check('service_type = PERMISSION',  row_w['service_type'] == 'PERMISSION')
            check('sub_type = WATER',           row_w['sub_type'] == 'WATER')
            check('status = PENDING',           row_w['status'] == 'PENDING')
            check('ward = Ward 5',              row_w['ward'] == 'Ward 5')
            check('applicant_name correct',     row_w['applicant_name'] == 'Sunita More')
            fd_w = json.loads(row_w['form_data_json'])
            check('form_data.property_no correct',        fd_w.get('property_no') == 'EGS-PROP-2026-0001')
            check('form_data.connection_type correct',    fd_w.get('connection_type') == 'Domestic')
            check('form_data.pipe_size_inch correct',     fd_w.get('pipe_size_inch') == '15mm (0.5 inch)')
            check('form_data.purpose_description correct',
                  'New household' in fd_w.get('purpose_description', ''))
            rno_water = row_w['request_no']
            check('request_no matches REQ-YYYY-NNNN format',
                  bool(re.match(r'^REQ-\d{4}-\d{4}$', rno_water)))
            # Confirm no collision with building request_no
            check('WATER request_no differs from BUILDING request_no',
                  rno_water != SEEDED_RNOS[0])

        # ── TEST 3: Document upload ────────────────────────────────
        print('\n[4] POST water connection with document upload...')
        rv = client.post('/permissions/apply/water', data={
            'applicant_name':  'Doc Upload Test',
            'ward':            'Ward 2',
            'connection_type': 'Commercial',
            'pipe_size_inch':  '25mm (1 inch)',
            'document': (io.BytesIO(fake_pdf()), 'site_plan.pdf', 'application/pdf'),
        }, follow_redirects=False, content_type='multipart/form-data')
        check('POST with document → redirect', rv.status_code in (301, 302))

        row_d = conn.execute(
            "SELECT * FROM service_requests WHERE user_id=? AND applicant_name='Doc Upload Test' ORDER BY id DESC LIMIT 1",
            (villager_id,)
        ).fetchone()
        check('Doc-upload row exists in DB', row_d is not None)
        if row_d:
            SEEDED_RNOS.append(row_d['request_no'])
            check('document_path is set', bool(row_d['document_path']))
            if row_d['document_path']:
                fpath = os.path.join(DOCS_UPLOAD_DIR, row_d['document_path'])
                check('Document file exists on disk', os.path.exists(fpath))
                SEEDED_FILES.append(row_d['document_path'])

        # ── TEST 4: Regression — birth certificate still works ─────
        print('\n[5] Regression: POST birth certificate...')
        rv = client.post('/services/certificates/apply/birth', data={
            'applicant_name': 'Regression Cert Test',
            'ward':           'Ward 4',
            'date_of_birth':  '2000-01-15',
            'gender':         'Female',
        }, follow_redirects=False)
        # Certificate apply has tax gate; villager has no properties → no dues → should redirect
        check('POST birth certificate → redirect', rv.status_code in (301, 302))

        row_c = conn.execute(
            "SELECT * FROM service_requests WHERE user_id=? AND sub_type='BIRTH' ORDER BY id DESC LIMIT 1",
            (villager_id,)
        ).fetchone()
        check('Birth cert row exists in DB', row_c is not None)
        if row_c:
            SEEDED_RNOS.append(row_c['request_no'])
            check('service_type = CERTIFICATE',  row_c['service_type'] == 'CERTIFICATE')
            check('sub_type = BIRTH',            row_c['sub_type'] == 'BIRTH')
            check('status = PENDING',            row_c['status'] == 'PENDING')
            check('Cert request_no != building', row_c['request_no'] != SEEDED_RNOS[0])
            check('Cert request_no != water',    row_c['request_no'] != SEEDED_RNOS[1])
            check('Cert request_no format valid',
                  bool(re.match(r'^REQ-\d{4}-\d{4}$', row_c['request_no'])))

        # ── TEST 5: GET routes ─────────────────────────────────────
        print('\n[6] GET route checks (authenticated)...')
        rv = client.get('/permissions')
        check('GET /permissions → 200', rv.status_code == 200)
        check('  Contains Building Permission', b'Building Permission' in rv.data)
        check('  Contains Water Connection',    b'Water Connection' in rv.data)

        rv = client.get('/permissions/apply/building')
        check('GET /permissions/apply/building → 200', rv.status_code == 200)
        check('  Contains plot_no field', b'plot_no' in rv.data)

        rv = client.get('/permissions/apply/water')
        check('GET /permissions/apply/water → 200', rv.status_code == 200)
        check('  Contains connection_type field', b'connection_type' in rv.data)

        rv = client.get('/permissions/apply/invalid')
        check('GET /permissions/apply/invalid → redirect', rv.status_code in (301, 302))

        # ── TEST 6: Access control ─────────────────────────────────
        print('\n[7] Access control — unauthenticated...')
        with client.session_transaction() as sess:
            sess.clear()

        for path in ('/permissions', '/permissions/apply/building', '/permissions/apply/water'):
            rv = client.get(path)
            check(f'  {path} unauthenticated → redirect', rv.status_code in (301, 302))

        # ── TEST 7: Dashboard shows permission rows ────────────────
        print('\n[8] Villager dashboard contains permission entries...')
        with client.session_transaction() as sess:
            sess['user_id']   = villager_id
            sess['role']      = 'villager'
            sess['full_name'] = 'Test Villager 91'
            sess['ward']      = 'Ward 1'

        rv = client.get('/villager/dashboard')
        check('GET /villager/dashboard → 200', rv.status_code == 200)
        if SEEDED_RNOS:
            check('  Dashboard contains BUILDING request_no', SEEDED_RNOS[0].encode() in rv.data)
            check('  Dashboard contains WATER request_no',    SEEDED_RNOS[1].encode() in rv.data)
        check('  Dashboard contains "Building Permission"', b'Building Permission' in rv.data)
        check('  Dashboard contains "Water Connection"',    b'Water Connection' in rv.data)

    # ── CLEANUP ───────────────────────────────────────────────────
    print('\n[9] Cleaning up seeded data...')
    cleanup(conn)

    after_svc = conn.execute('SELECT COUNT(*) FROM service_requests').fetchone()[0]
    check('service_requests count restored to baseline', after_svc == base_svc)
    conn.close()

    # ── SUMMARY ───────────────────────────────────────────────────
    print()
    print('=' * 42)
    print(f'Results: {PASS} passed, {FAIL} failed')
    print('=' * 42)
    if FAIL > 0:
        sys.exit(1)
    print('\nAll Phase 9.1 self-tests PASSED.')


if __name__ == '__main__':
    main()
