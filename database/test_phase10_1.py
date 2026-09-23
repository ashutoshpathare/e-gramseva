#!/usr/bin/env python3
"""
Phase 10.1 self-test — Government Schemes catalog + villager apply flow.

Run from project root:
    python3 database/test_phase10_1.py

Tests:
 1. POST pmay — DB row, service_type='SCHEME', sub_type='pmay', correct form_data_json
 2. POST ujjwala — DB row, sub_type='ujjwala', correct form_data_json
 3. POST kisan_samman — DB row, sub_type='kisan_samman', correct form_data_json
 4. All three have status=PENDING
 5. request_no format REQ-YYYY-NNNN; no collisions among the three
 6. Document upload — document_path stored + file exists on disk
 7. GET /schemes → 200, all three scheme cards + Apply links present
 8. GET /schemes/apply/<each valid slug> → 200, correct form fields rendered
 9. GET /schemes/apply/<invalid_slug> → redirect
10. Villager dashboard shows all three scheme request_nos with friendly labels
11. Regression: certificate POST + permission POST still work unchanged
12. Cleanup — DB pristine after (service_requests count restored)
"""

import sys
import os
import json
import re
import io
import sqlite3
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import app
from werkzeug.security import generate_password_hash

PASS = 0
FAIL = 0

SEEDED_USER_MOBILES = []
SEEDED_REQUEST_NOS  = []
SEEDED_DOC_PATHS    = []


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


def session_for(client, user_id, ward='Ward 2'):
    with client.session_transaction() as sess:
        sess['user_id']   = user_id
        sess['role']      = 'villager'
        sess['full_name'] = 'P101 Test User'
        sess['ward']      = ward


def main():
    global PASS, FAIL

    db_path = app.config['DATABASE']
    if not os.path.exists(db_path):
        print(f'[ERROR] Database not found: {db_path}')
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    base_svc = conn.execute('SELECT COUNT(*) FROM service_requests').fetchone()[0]

    print('\n=== Phase 10.1 Self-Test ===\n')
    app.config['TESTING']          = True
    app.config['WTF_CSRF_ENABLED'] = False

    print('[SETUP] Creating test user...')
    uid = get_or_create_user(conn, '9100000001', 'P101 Villager')
    print(f'    uid={uid}\n')

    with app.test_client() as client:
        session_for(client, uid)

        # ════════════════════════════════════════════════════════
        # TEST 1: POST pmay
        # ════════════════════════════════════════════════════════
        print('[1] POST /schemes/apply/pmay...')
        rv = client.post('/schemes/apply/pmay', data={
            'applicant_name':       'Ramesh Patil',
            'ward':                 'Ward 3',
            'family_income_annual': '95000',
            'house_status':         'Kachha',
            'aadhaar_last4':        '1234',
            'bank_account_no':      '1234567890123',
        }, follow_redirects=False)
        check('POST /schemes/apply/pmay → redirect', rv.status_code in (301, 302))
        row_pmay = conn.execute(
            "SELECT * FROM service_requests WHERE user_id=? AND sub_type='pmay' ORDER BY id DESC LIMIT 1",
            (uid,)
        ).fetchone()
        check('pmay row exists in DB', row_pmay is not None)
        if row_pmay:
            SEEDED_REQUEST_NOS.append(row_pmay['request_no'])
            check('service_type = SCHEME',       row_pmay['service_type'] == 'SCHEME')
            check('sub_type = pmay',             row_pmay['sub_type'] == 'pmay')
            check('status = PENDING',            row_pmay['status'] == 'PENDING')
            check('applicant_name correct',      row_pmay['applicant_name'] == 'Ramesh Patil')
            check('ward = Ward 3',               row_pmay['ward'] == 'Ward 3')
            fd = json.loads(row_pmay['form_data_json'])
            check('form_data.family_income_annual correct', fd.get('family_income_annual') == '95000')
            check('form_data.house_status correct',         fd.get('house_status') == 'Kachha')
            check('form_data.aadhaar_last4 correct',        fd.get('aadhaar_last4') == '1234')
            check('form_data.bank_account_no correct',      fd.get('bank_account_no') == '1234567890123')
            check('request_no format REQ-YYYY-NNNN',
                  bool(re.match(r'^REQ-\d{4}-\d{4}$', row_pmay['request_no'])))
            check('document_path is None (no file)', row_pmay['document_path'] is None)

        # ════════════════════════════════════════════════════════
        # TEST 2: POST ujjwala
        # ════════════════════════════════════════════════════════
        print('\n[2] POST /schemes/apply/ujjwala...')
        rv = client.post('/schemes/apply/ujjwala', data={
            'applicant_name':          'Sunita More',
            'ward':                    'Ward 5',
            'family_income_annual':    '60000',
            'existing_lpg_connection': 'No',
            'aadhaar_last4':           '5678',
        }, follow_redirects=False)
        check('POST /schemes/apply/ujjwala → redirect', rv.status_code in (301, 302))
        row_ujj = conn.execute(
            "SELECT * FROM service_requests WHERE user_id=? AND sub_type='ujjwala' ORDER BY id DESC LIMIT 1",
            (uid,)
        ).fetchone()
        check('ujjwala row exists in DB', row_ujj is not None)
        if row_ujj:
            SEEDED_REQUEST_NOS.append(row_ujj['request_no'])
            check('service_type = SCHEME',    row_ujj['service_type'] == 'SCHEME')
            check('sub_type = ujjwala',       row_ujj['sub_type'] == 'ujjwala')
            check('status = PENDING',         row_ujj['status'] == 'PENDING')
            fd = json.loads(row_ujj['form_data_json'])
            check('form_data.family_income_annual correct',    fd.get('family_income_annual') == '60000')
            check('form_data.existing_lpg_connection correct', fd.get('existing_lpg_connection') == 'No')
            check('form_data.aadhaar_last4 correct',           fd.get('aadhaar_last4') == '5678')
            check('request_no format valid',
                  bool(re.match(r'^REQ-\d{4}-\d{4}$', row_ujj['request_no'])))
            check('ujjwala request_no != pmay request_no',
                  row_pmay is None or row_ujj['request_no'] != row_pmay['request_no'])

        # ════════════════════════════════════════════════════════
        # TEST 3: POST kisan_samman
        # ════════════════════════════════════════════════════════
        print('\n[3] POST /schemes/apply/kisan_samman...')
        rv = client.post('/schemes/apply/kisan_samman', data={
            'applicant_name': 'Vijay Kale',
            'ward':           'Ward 7',
            'land_survey_no': '45/B',
            'land_area_acres': '1.75',
            'aadhaar_last4':  '9012',
            'bank_account_no': '9876543210987',
        }, follow_redirects=False)
        check('POST /schemes/apply/kisan_samman → redirect', rv.status_code in (301, 302))
        row_ks = conn.execute(
            "SELECT * FROM service_requests WHERE user_id=? AND sub_type='kisan_samman' ORDER BY id DESC LIMIT 1",
            (uid,)
        ).fetchone()
        check('kisan_samman row exists in DB', row_ks is not None)
        if row_ks:
            SEEDED_REQUEST_NOS.append(row_ks['request_no'])
            check('service_type = SCHEME',     row_ks['service_type'] == 'SCHEME')
            check('sub_type = kisan_samman',   row_ks['sub_type'] == 'kisan_samman')
            check('status = PENDING',          row_ks['status'] == 'PENDING')
            fd = json.loads(row_ks['form_data_json'])
            check('form_data.land_survey_no correct',  fd.get('land_survey_no') == '45/B')
            check('form_data.land_area_acres correct', fd.get('land_area_acres') == '1.75')
            check('form_data.aadhaar_last4 correct',   fd.get('aadhaar_last4') == '9012')
            check('form_data.bank_account_no correct', fd.get('bank_account_no') == '9876543210987')
            check('request_no format valid',
                  bool(re.match(r'^REQ-\d{4}-\d{4}$', row_ks['request_no'])))
            check('kisan_samman request_no unique vs pmay',
                  row_pmay is None or row_ks['request_no'] != row_pmay['request_no'])
            check('kisan_samman request_no unique vs ujjwala',
                  row_ujj is None or row_ks['request_no'] != row_ujj['request_no'])

        # ════════════════════════════════════════════════════════
        # TEST 4: Document upload (kisan_samman + doc)
        # ════════════════════════════════════════════════════════
        print('\n[4] POST kisan_samman with document upload...')
        fake_pdf = (io.BytesIO(b'%PDF-1.4 fake land record'), 'land_record.pdf')
        rv = client.post('/schemes/apply/kisan_samman', data={
            'applicant_name': 'Doc Upload Test',
            'ward':           'Ward 1',
            'land_survey_no': '88/C',
            'land_area_acres': '0.50',
            'aadhaar_last4':  '3456',
            'bank_account_no': '1111111111111',
            'document':       fake_pdf,
        }, content_type='multipart/form-data', follow_redirects=False)
        check('POST with document → redirect', rv.status_code in (301, 302))
        row_doc = conn.execute(
            "SELECT * FROM service_requests WHERE user_id=? AND sub_type='kisan_samman' "
            "ORDER BY id DESC LIMIT 1",
            (uid,)
        ).fetchone()
        check('Doc-upload row exists', row_doc is not None)
        if row_doc:
            SEEDED_REQUEST_NOS.append(row_doc['request_no'])
            check('document_path is set', row_doc['document_path'] is not None)
            if row_doc['document_path']:
                doc_on_disk = os.path.join(
                    ROOT, 'static', 'uploads', 'docs', row_doc['document_path']
                )
                check('Document file exists on disk', os.path.exists(doc_on_disk))
                SEEDED_DOC_PATHS.append(doc_on_disk)

        # ════════════════════════════════════════════════════════
        # TEST 5: GET /schemes — catalog page
        # ════════════════════════════════════════════════════════
        print('\n[5] GET /schemes — catalog page...')
        rv = client.get('/schemes')
        check('GET /schemes → 200', rv.status_code == 200)
        check('Page contains "PM Awas Yojana"',      b'PM Awas Yojana' in rv.data)
        check('Page contains "Ujjwala Yojana"',       b'Ujjwala Yojana' in rv.data)
        check('Page contains "Kisan Samman Nidhi"',   b'Kisan Samman Nidhi' in rv.data)
        check('Apply link for pmay present',
              b'/schemes/apply/pmay' in rv.data)
        check('Apply link for ujjwala present',
              b'/schemes/apply/ujjwala' in rv.data)
        check('Apply link for kisan_samman present',
              b'/schemes/apply/kisan_samman' in rv.data)

        # ════════════════════════════════════════════════════════
        # TEST 6: GET /schemes/apply/<each slug> — form pages
        # ════════════════════════════════════════════════════════
        print('\n[6] GET form pages — correct fields...')
        rv = client.get('/schemes/apply/pmay')
        check('GET /schemes/apply/pmay → 200',        rv.status_code == 200)
        check('pmay form has family_income_annual',   b'family_income_annual' in rv.data)
        check('pmay form has house_status',           b'house_status' in rv.data)
        check('pmay form has bank_account_no',        b'bank_account_no' in rv.data)

        rv = client.get('/schemes/apply/ujjwala')
        check('GET /schemes/apply/ujjwala → 200',         rv.status_code == 200)
        check('ujjwala form has existing_lpg_connection', b'existing_lpg_connection' in rv.data)
        check('ujjwala form has family_income_annual',    b'family_income_annual' in rv.data)

        rv = client.get('/schemes/apply/kisan_samman')
        check('GET /schemes/apply/kisan_samman → 200',   rv.status_code == 200)
        check('kisan_samman form has land_survey_no',    b'land_survey_no' in rv.data)
        check('kisan_samman form has land_area_acres',   b'land_area_acres' in rv.data)

        # ════════════════════════════════════════════════════════
        # TEST 7: GET /schemes/apply/<invalid> → redirect
        # ════════════════════════════════════════════════════════
        print('\n[7] GET /schemes/apply/<invalid> → redirect...')
        rv = client.get('/schemes/apply/fakescheme', follow_redirects=False)
        check('GET /schemes/apply/fakescheme → redirect', rv.status_code in (301, 302))

        # ════════════════════════════════════════════════════════
        # TEST 8: Villager dashboard — scheme rows appear
        # ════════════════════════════════════════════════════════
        print('\n[8] Villager dashboard — scheme rows appear...')
        rv = client.get('/villager/dashboard')
        check('GET /villager/dashboard → 200', rv.status_code == 200)
        if row_pmay:
            check('Dashboard contains pmay request_no', row_pmay['request_no'].encode() in rv.data)
        if row_ujj:
            check('Dashboard contains ujjwala request_no', row_ujj['request_no'].encode() in rv.data)
        if row_ks:
            check('Dashboard contains kisan_samman request_no', row_ks['request_no'].encode() in rv.data)
        check('Dashboard shows "PM Awas Yojana" label',    b'PM Awas Yojana' in rv.data)
        check('Dashboard shows "Ujjwala Yojana" label',    b'Ujjwala Yojana' in rv.data)
        check('Dashboard shows "Kisan Samman Nidhi" label', b'Kisan Samman Nidhi' in rv.data)

        # ════════════════════════════════════════════════════════
        # TEST 9: Regression — certificate + permission still work
        # ════════════════════════════════════════════════════════
        print('\n[9] Regression: certificate + permission unchanged...')
        rv = client.post('/services/certificates/apply/birth', data={
            'applicant_name': 'Reg Cert Test',
            'ward':           'Ward 2',
            'date_of_birth':  '2002-01-15',
            'gender':         'Male',
        }, follow_redirects=False)
        check('Cert POST → redirect', rv.status_code in (301, 302))
        row_cert = conn.execute(
            "SELECT * FROM service_requests WHERE user_id=? AND sub_type='BIRTH' ORDER BY id DESC LIMIT 1",
            (uid,)
        ).fetchone()
        check('Cert row exists, service_type=CERTIFICATE', row_cert is not None and
              row_cert['service_type'] == 'CERTIFICATE')
        if row_cert:
            SEEDED_REQUEST_NOS.append(row_cert['request_no'])

        rv = client.post('/permissions/apply/building', data={
            'applicant_name':    'Reg Perm Test',
            'ward':              'Ward 4',
            'plot_no':           'Plot 99',
            'plot_area_sqft':    '800',
            'construction_type': 'Residential',
            'building_height_m': '5.0',
            'architect_name':    'K. Shah',
            'estimated_cost':    '300000',
        }, follow_redirects=False)
        check('Permission POST → redirect', rv.status_code in (301, 302))
        row_perm = conn.execute(
            "SELECT * FROM service_requests WHERE user_id=? AND sub_type='BUILDING' ORDER BY id DESC LIMIT 1",
            (uid,)
        ).fetchone()
        check('Permission row exists, service_type=PERMISSION', row_perm is not None and
              row_perm['service_type'] == 'PERMISSION')
        if row_perm:
            SEEDED_REQUEST_NOS.append(row_perm['request_no'])
        # Confirm scheme request_nos are unique vs cert/perm
        if row_pmay and row_cert:
            check('pmay request_no != cert request_no',
                  row_pmay['request_no'] != row_cert['request_no'])
        if row_ks and row_perm:
            check('kisan_samman request_no != permission request_no',
                  row_ks['request_no'] != row_perm['request_no'])

    # ════════════════════════════════════════════════════════════
    # CLEANUP
    # ════════════════════════════════════════════════════════════
    print('\n[10] Cleaning up seeded data...')
    for rno in SEEDED_REQUEST_NOS:
        conn.execute('DELETE FROM service_requests WHERE request_no = ?', (rno,))
    for mobile in SEEDED_USER_MOBILES:
        conn.execute('DELETE FROM users WHERE mobile = ?', (mobile,))
    conn.commit()
    for path in SEEDED_DOC_PATHS:
        try:
            os.remove(path)
        except OSError:
            pass

    after_svc = conn.execute('SELECT COUNT(*) FROM service_requests').fetchone()[0]
    check('service_requests count restored', after_svc == base_svc)
    conn.close()

    print()
    print('=' * 50)
    print(f'Results: {PASS} passed, {FAIL} failed')
    print('=' * 50)
    if FAIL > 0:
        sys.exit(1)
    print('\nAll Phase 10.1 self-tests PASSED.')


if __name__ == '__main__':
    main()
