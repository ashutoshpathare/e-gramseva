#!/usr/bin/env python3
"""
Phase 8 self-test — Nondi Register Views.

Run from the project root:
    python database/test_phase8.py

What it does:
1. Seeds test data (3 approved birth, 3 approved death, 1 pending, 1 rejected, 3 properties)
2. Hits all three register routes + print route as admin
3. Verifies PENDING/REJECTED certs do NOT appear in birth/death registers
4. Tests ward filter (narrows to 1 row)
5. Tests date-range filter (narrows to 0 rows for far-future date)
6. Verifies villager session gets a redirect (not 200) on all three routes
7. Verifies print view renders without errors
8. Cleans up all seeded rows
9. Asserts DB is pristine (seed counts are back to baseline)
"""

import sys
import os
import json
import sqlite3

# ── path setup ─────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import app, get_db
from werkzeug.security import generate_password_hash

# ── constants ──────────────────────────────────────────────────────
SEED_TAG   = 'P8TEST'          # marker embedded in request_no prefix
BIRTH_RNOs = [f'{SEED_TAG}-BIRTH-{i}' for i in range(1, 4)]
DEATH_RNOs = [f'{SEED_TAG}-DEATH-{i}' for i in range(1, 4)]
PEND_RNO   = f'{SEED_TAG}-PEND-1'
REJ_RNO    = f'{SEED_TAG}-REJECT-1'
PROP_NOs   = [f'{SEED_TAG}-PROP-{i}' for i in range(1, 4)]

PASS       = 0
FAIL       = 0

def check(desc, cond):
    global PASS, FAIL
    if cond:
        print(f'  [PASS] {desc}')
        PASS += 1
    else:
        print(f'  [FAIL] {desc}')
        FAIL += 1

# ── helpers ────────────────────────────────────────────────────────

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


def seed(conn, villager_id):
    """Insert all test rows."""
    now = '2026-06-15 10:00:00'

    # 3 approved birth certs, different wards
    for i, rno in enumerate(BIRTH_RNOs, 1):
        fd = json.dumps({'date_of_birth': f'200{i}-0{i}-0{i}', 'gender': 'Male'})
        conn.execute('''
            INSERT OR IGNORE INTO service_requests
              (request_no, user_id, service_type, sub_type, applicant_name,
               ward, form_data_json, status, created_at, updated_at)
            VALUES (?, ?, 'CERTIFICATE', 'BIRTH', ?, ?, ?, 'APPROVED', ?, ?)
        ''', (rno, villager_id, f'BirthApplicant{i}', f'Ward {i}', fd, now, now))

    # 3 approved death certs, different wards
    for i, rno in enumerate(DEATH_RNOs, 1):
        fd = json.dumps({'date_of_death': f'202{i}-0{i}-0{i}', 'cause_of_death': 'Natural'})
        conn.execute('''
            INSERT OR IGNORE INTO service_requests
              (request_no, user_id, service_type, sub_type, applicant_name,
               ward, form_data_json, status, created_at, updated_at)
            VALUES (?, ?, 'CERTIFICATE', 'DEATH', ?, ?, ?, 'APPROVED', ?, ?)
        ''', (rno, villager_id, f'DeathApplicant{i}', f'Ward {i}', fd, now, now))

    # 1 PENDING birth cert (must NOT appear in register)
    conn.execute('''
        INSERT OR IGNORE INTO service_requests
          (request_no, user_id, service_type, sub_type, applicant_name,
           ward, form_data_json, status, created_at, updated_at)
        VALUES (?, ?, 'CERTIFICATE', 'BIRTH', 'PendingPerson', 'Ward 5', '{}', 'PENDING', ?, ?)
    ''', (PEND_RNO, villager_id, now, now))

    # 1 REJECTED death cert (must NOT appear in register)
    conn.execute('''
        INSERT OR IGNORE INTO service_requests
          (request_no, user_id, service_type, sub_type, applicant_name,
           ward, form_data_json, status, created_at, updated_at)
        VALUES (?, ?, 'CERTIFICATE', 'DEATH', 'RejectedPerson', 'Ward 5', '{}', 'REJECTED', ?, ?)
    ''', (REJ_RNO, villager_id, now, now))

    # 3 properties, different wards
    for i, pno in enumerate(PROP_NOs, 1):
        conn.execute('''
            INSERT OR IGNORE INTO properties
              (property_no, owner_id, ward, property_type, area_sqft, address, assessed_value)
            VALUES (?, ?, ?, 'RESIDENTIAL', 1200, ?, 500000)
        ''', (pno, villager_id, f'Ward {i}', f'{i} Test Street'))

    conn.commit()


def cleanup(conn):
    """Remove all seeded test rows (by request_no/property_no prefix)."""
    all_rnos = BIRTH_RNOs + DEATH_RNOs + [PEND_RNO, REJ_RNO]
    for rno in all_rnos:
        conn.execute('DELETE FROM service_requests WHERE request_no = ?', (rno,))
    for pno in PROP_NOs:
        conn.execute('DELETE FROM properties WHERE property_no = ?', (pno,))
    conn.commit()


# ══════════════════════════════════════════════════════════════════
# Main self-test
# ══════════════════════════════════════════════════════════════════

def main():
    global PASS, FAIL

    db_path = app.config['DATABASE']
    if not os.path.exists(db_path):
        print(f'[ERROR] Database not found at {db_path}. Run the app first.')
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Baseline counts before seeding
    base_birth = conn.execute(
        "SELECT COUNT(*) FROM service_requests WHERE sub_type='BIRTH' AND status='APPROVED'"
    ).fetchone()[0]
    base_death = conn.execute(
        "SELECT COUNT(*) FROM service_requests WHERE sub_type='DEATH' AND status='APPROVED'"
    ).fetchone()[0]
    base_props = conn.execute('SELECT COUNT(*) FROM properties').fetchone()[0]
    base_svc   = conn.execute('SELECT COUNT(*) FROM service_requests').fetchone()[0]

    print('\n=== Phase 8 Self-Test ===\n')

    # ── SEED ──────────────────────────────────────────────────────
    print('[1] Seeding test data...')
    villager_id = get_or_create_user(conn, '9000000001', role='villager')
    admin_id    = get_or_create_user(conn, '9000000002', role='admin')
    seed(conn, villager_id)
    print(f'    Seeded: {len(BIRTH_RNOs)} birth, {len(DEATH_RNOs)} death, '
          f'1 pending, 1 rejected, {len(PROP_NOs)} properties\n')

    # ── ROUTE TESTS via test client ────────────────────────────────
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False

    with app.test_client() as client:

        # ── Admin session ──────────────────────────────────────────
        with client.session_transaction() as sess:
            sess['user_id']   = admin_id
            sess['role']      = 'admin'
            sess['full_name'] = 'Test Admin'
            sess['ward']      = ''

        print('[2] Route tests as admin...')

        # Birth register — all 3 seeded approved birth should appear
        rv = client.get('/admin/registers/birth')
        check('GET /admin/registers/birth → 200', rv.status_code == 200)
        body = rv.data.decode()
        for rno in BIRTH_RNOs:
            check(f'  Birth register contains {rno}', rno in body)
        check('  PENDING cert NOT in birth register', PEND_RNO not in body)

        # Death register — all 3 seeded approved death should appear
        rv = client.get('/admin/registers/death')
        check('GET /admin/registers/death → 200', rv.status_code == 200)
        body = rv.data.decode()
        for rno in DEATH_RNOs:
            check(f'  Death register contains {rno}', rno in body)
        check('  REJECTED cert NOT in death register', REJ_RNO not in body)
        check('  Birth cert NOT in death register', BIRTH_RNOs[0] not in body)

        # Property register — all 3 seeded properties should appear
        rv = client.get('/admin/registers/property')
        check('GET /admin/registers/property → 200', rv.status_code == 200)
        body = rv.data.decode()
        for pno in PROP_NOs:
            check(f'  Property register contains {pno}', pno in body)

        print()
        print('[3] Ward filter tests...')

        # Ward 1 filter — birth register should return exactly 1 seeded row
        rv = client.get('/admin/registers/birth?ward=Ward+1')
        check('GET /admin/registers/birth?ward=Ward+1 → 200', rv.status_code == 200)
        body = rv.data.decode()
        check('  Ward 1 birth: contains Ward-1 record', BIRTH_RNOs[0] in body)
        check('  Ward 1 birth: excludes Ward-2 record', BIRTH_RNOs[1] not in body)
        check('  Ward 1 birth: excludes Ward-3 record', BIRTH_RNOs[2] not in body)

        rv = client.get('/admin/registers/death?ward=Ward+2')
        check('GET /admin/registers/death?ward=Ward+2 → 200', rv.status_code == 200)
        body = rv.data.decode()
        check('  Ward 2 death: contains Ward-2 record', DEATH_RNOs[1] in body)
        check('  Ward 2 death: excludes Ward-1 record', DEATH_RNOs[0] not in body)

        rv = client.get('/admin/registers/property?ward=Ward+3')
        check('GET /admin/registers/property?ward=Ward+3 → 200', rv.status_code == 200)
        body = rv.data.decode()
        check('  Ward 3 property: contains Ward-3 record', PROP_NOs[2] in body)
        check('  Ward 3 property: excludes Ward-1 record', PROP_NOs[0] not in body)

        print()
        print('[4] Date-range filter tests (far-future date → 0 seeded rows)...')

        rv = client.get('/admin/registers/birth?date_from=2099-01-01&date_to=2099-12-31')
        check('Birth date filter 2099 → 200', rv.status_code == 200)
        body = rv.data.decode()
        for rno in BIRTH_RNOs:
            check(f'  {rno} NOT in 2099 filtered birth register', rno not in body)

        rv = client.get('/admin/registers/death?date_from=2099-01-01&date_to=2099-12-31')
        check('Death date filter 2099 → 200', rv.status_code == 200)
        body = rv.data.decode()
        for rno in DEATH_RNOs:
            check(f'  {rno} NOT in 2099 filtered death register', rno not in body)

        rv = client.get('/admin/registers/property?date_from=2099-01-01&date_to=2099-12-31')
        check('Property date filter 2099 → 200', rv.status_code == 200)
        body = rv.data.decode()
        for pno in PROP_NOs:
            check(f'  {pno} NOT in 2099 filtered property register', pno not in body)

        print()
        print('[5] Print view tests (admin)...')
        for rt in ('birth', 'death', 'property'):
            rv = client.get(f'/admin/registers/{rt}/print')
            check(f'GET /admin/registers/{rt}/print → 200', rv.status_code == 200)
            body = rv.data.decode()
            check(f'  {rt} print contains letterhead (Gram Panchayat)', 'Gram Panchayat' in body)
            check(f'  {rt} print contains signature block', 'Sarpanch' in body)

        # Invalid print type
        rv = client.get('/admin/registers/invalid/print')
        check('Invalid register type /print → redirect (not 200)', rv.status_code in (301, 302))

        print()
        print('[6] Access control — villager should be redirected...')

        # Switch to villager session
        with client.session_transaction() as sess:
            sess['user_id']   = villager_id
            sess['role']      = 'villager'
            sess['full_name'] = 'Test Villager'
            sess['ward']      = 'Ward 1'

        for path in ('/admin/registers/birth', '/admin/registers/death',
                     '/admin/registers/property', '/admin/registers/birth/print'):
            rv = client.get(path)
            check(f'  {path} as villager → redirect (not 200)', rv.status_code in (301, 302))

        # Unauthenticated
        with client.session_transaction() as sess:
            sess.clear()

        for path in ('/admin/registers/birth', '/admin/registers/death', '/admin/registers/property'):
            rv = client.get(path)
            check(f'  {path} unauthenticated → redirect', rv.status_code in (301, 302))

    # ── CLEANUP ───────────────────────────────────────────────────
    print()
    print('[7] Cleaning up seeded data...')
    cleanup(conn)

    # Verify DB is pristine
    after_birth = conn.execute(
        "SELECT COUNT(*) FROM service_requests WHERE sub_type='BIRTH' AND status='APPROVED'"
    ).fetchone()[0]
    after_death = conn.execute(
        "SELECT COUNT(*) FROM service_requests WHERE sub_type='DEATH' AND status='APPROVED'"
    ).fetchone()[0]
    after_props = conn.execute('SELECT COUNT(*) FROM properties').fetchone()[0]
    after_svc   = conn.execute('SELECT COUNT(*) FROM service_requests').fetchone()[0]

    check('Approved birth count restored to baseline', after_birth == base_birth)
    check('Approved death count restored to baseline', after_death == base_death)
    check('Properties count restored to baseline',    after_props == base_props)
    check('service_requests count restored to baseline', after_svc == base_svc)

    conn.close()

    # ── Summary ───────────────────────────────────────────────────
    print()
    print('=' * 40)
    print(f'Results: {PASS} passed, {FAIL} failed')
    print('=' * 40)
    if FAIL > 0:
        sys.exit(1)
    print('\nAll Phase 8 self-tests PASSED.')


if __name__ == '__main__':
    main()
