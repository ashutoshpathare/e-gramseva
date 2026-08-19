"""
VCMS Seed Data Script
---------------------
Creates the SQLite database at ../instance/vcms.db with demo data.

Usage:
    python database/seed.py

This script:
  - Drops and recreates all tables (SQLite-compatible schema)
  - Hashes all passwords using Werkzeug (same library Flask uses)
  - Inserts 5 users, 10 complaints, full status timelines,
    feedback for resolved complaints, and notifications

Demo credentials printed at the end.
"""

import os
import sqlite3
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'instance', 'vcms.db')

# SQLite-compatible version of the MySQL schema.
# ENUMs become TEXT + CHECK constraints; BOOLEAN becomes INTEGER.
CREATE_TABLES = """
CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name     TEXT    NOT NULL,
    mobile        TEXT    NOT NULL UNIQUE,
    ward          TEXT    CHECK(ward IN (
                      'Ward 1','Ward 2','Ward 3','Ward 4','Ward 5',
                      'Ward 6','Ward 7','Ward 8','Ward 9','Ward 10')),
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'villager'
                          CHECK(role IN ('villager','admin')),
    created_at    TEXT    DEFAULT (datetime('now','localtime'))
);

CREATE TABLE complaints (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id   TEXT    NOT NULL UNIQUE,
    user_id        INTEGER NOT NULL,
    category       TEXT    NOT NULL CHECK(category IN (
                       'Road','Water','Street Lights','Garbage',
                       'Drainage','Electricity','Other')),
    description    TEXT    NOT NULL,
    ward           TEXT    NOT NULL CHECK(ward IN (
                       'Ward 1','Ward 2','Ward 3','Ward 4','Ward 5',
                       'Ward 6','Ward 7','Ward 8','Ward 9','Ward 10')),
    address_detail TEXT,
    latitude       REAL,
    longitude      REAL,
    photo_path     TEXT,
    status         TEXT    NOT NULL DEFAULT 'Pending'
                           CHECK(status IN ('Pending','In Progress','Resolved','Rejected')),
    priority       TEXT    NOT NULL DEFAULT 'Normal'
                           CHECK(priority IN ('Normal','High')),
    assigned_to    TEXT,
    created_at     TEXT    DEFAULT (datetime('now','localtime')),
    resolved_at    TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT
);

CREATE TABLE status_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id  INTEGER NOT NULL,
    old_status    TEXT    CHECK(old_status IN ('Pending','In Progress','Resolved','Rejected')),
    new_status    TEXT    NOT NULL
                          CHECK(new_status IN ('Pending','In Progress','Resolved','Rejected')),
    changed_by    INTEGER NOT NULL,
    note          TEXT,
    changed_at    TEXT    DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (complaint_id) REFERENCES complaints(id) ON DELETE CASCADE,
    FOREIGN KEY (changed_by)   REFERENCES users(id)      ON DELETE RESTRICT
);

CREATE TABLE feedback (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id  INTEGER NOT NULL UNIQUE,
    user_id       INTEGER NOT NULL,
    rating        INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
    comment       TEXT,
    submitted_at  TEXT    DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (complaint_id) REFERENCES complaints(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id)      REFERENCES users(id)      ON DELETE RESTRICT
);

CREATE TABLE notifications (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    complaint_id  INTEGER NOT NULL,
    message       TEXT    NOT NULL,
    is_read       INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (user_id)      REFERENCES users(id)      ON DELETE CASCADE,
    FOREIGN KEY (complaint_id) REFERENCES complaints(id) ON DELETE CASCADE
);

CREATE TABLE properties (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    property_no     TEXT    NOT NULL UNIQUE,
    owner_id        INTEGER NOT NULL,
    ward            TEXT    NOT NULL,
    property_type   TEXT    NOT NULL CHECK(property_type IN (
                        'RESIDENTIAL','COMMERCIAL','AGRICULTURAL')),
    area_sqft       REAL    NOT NULL,
    address         TEXT    NOT NULL,
    assessed_value  REAL    NOT NULL,
    registered_at   TEXT    DEFAULT (datetime('now','localtime')),
    status          TEXT    NOT NULL DEFAULT 'ACTIVE'
                            CHECK(status IN ('ACTIVE','DISPUTED','TRANSFERRED')),
    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE RESTRICT
);

CREATE TABLE tax_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id     INTEGER NOT NULL,
    tax_type        TEXT    NOT NULL CHECK(tax_type IN ('PROPERTY_TAX','WATER_TAX')),
    financial_year  TEXT    NOT NULL,
    amount_due      REAL    NOT NULL,
    due_date        TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'UNPAID'
                            CHECK(status IN ('UNPAID','PAID','OVERDUE','WAIVED')),
    created_at      TEXT    DEFAULT (datetime('now','localtime')),
    UNIQUE (property_id, tax_type, financial_year),
    FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE CASCADE
);

CREATE TABLE payments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    tax_record_id       INTEGER NOT NULL,
    payer_id            INTEGER NOT NULL,
    amount_paid         REAL    NOT NULL,
    payment_method      TEXT,
    razorpay_order_id   TEXT,
    razorpay_payment_id TEXT,
    payment_status      TEXT    NOT NULL DEFAULT 'CREATED'
                                CHECK(payment_status IN ('CREATED','SUCCESS','FAILED')),
    paid_at             TEXT,
    receipt_no          TEXT    UNIQUE,
    FOREIGN KEY (tax_record_id) REFERENCES tax_records(id) ON DELETE CASCADE,
    FOREIGN KEY (payer_id)      REFERENCES users(id)       ON DELETE RESTRICT
);
"""


def ts(days_ago=0, hours_ago=0):
    """Return an ISO datetime string offset from now."""
    return (datetime.now() - timedelta(days=days_ago, hours=hours_ago)) \
           .strftime('%Y-%m-%d %H:%M:%S')


def run():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print("Removed existing database.")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(CREATE_TABLES)
    cur = conn.cursor()

    # ----------------------------------------------------------
    # Users
    # ----------------------------------------------------------
    # (full_name, mobile, ward, plaintext_password, role)
    users = [
        ('Gram Panchayat Admin', '9999900000', None,      'admin123',   'admin'),
        ('Rajesh Patil',         '9876543210', 'Ward 3',  'village123', 'villager'),
        ('Sunita Kamble',        '9876543211', 'Ward 1',  'village123', 'villager'),
        ('Mohan Shinde',         '9876543212', 'Ward 7',  'village123', 'villager'),
        ('Priya Deshpande',      '9876543213', 'Ward 5',  'village123', 'villager'),
    ]
    # IDs will be: admin=1, Rajesh=2, Sunita=3, Mohan=4, Priya=5

    for full_name, mobile, ward, password, role in users:
        cur.execute(
            """INSERT INTO users (full_name, mobile, ward, password_hash, role, created_at)
               VALUES (?,?,?,?,?,?)""",
            (full_name, mobile, ward, generate_password_hash(password), role, ts(30))
        )

    ADMIN = 1

    # ----------------------------------------------------------
    # Complaints
    # ----------------------------------------------------------
    # (complaint_id, user_id, category, description, ward,
    #  address_detail, status, priority, assigned_to, created_at, resolved_at)
    complaints = [
        ('VCMS-2026-0001', 2, 'Road',
         'Large pothole near the primary school entrance causing vehicle damage.',
         'Ward 3', 'Near ZP School, Shivaji Nagar',
         'Resolved', 'Normal', 'Ramesh Naik', ts(20), ts(12)),

        ('VCMS-2026-0002', 3, 'Water',
         'No water supply for 3 days. Pipeline appears broken near the main road junction.',
         'Ward 1', 'Main Road, Ambedkar Chowk',
         'In Progress', 'Normal', 'Suresh Jadhav', ts(15), None),

        ('VCMS-2026-0003', 4, 'Garbage',
         'Garbage not collected for over a week. Waste overflowing onto the street.',
         'Ward 7', 'Ganesh Mandir Road',
         'Pending', 'Normal', None, ts(10), None),

        ('VCMS-2026-0004', 5, 'Street Lights',
         'Three consecutive street lights not working since last month. Very dark at night.',
         'Ward 5', 'Bus stop to railway crossing stretch',
         'Pending', 'Normal', None, ts(8), None),

        ('VCMS-2026-0005', 2, 'Drainage',
         'Drain blocked, causing waterlogging in front of our house after any rainfall.',
         'Ward 3', 'House No. 45, Phule Nagar',
         'Rejected', 'Normal', None, ts(18), None),

        ('VCMS-2026-0006', 3, 'Electricity',
         'Electric wire hanging low over the footpath — dangerous for pedestrians and children.',
         'Ward 1', 'Near St. Mary High School gate',
         'Resolved', 'High', 'Vijay More', ts(25), ts(18)),

        ('VCMS-2026-0007', 4, 'Other',
         'Stray dogs gathering near the community hall. Residents feel unsafe.',
         'Ward 7', 'Community Hall, Ward 7',
         'In Progress', 'Normal', 'Prakash Sawant', ts(6), None),

        ('VCMS-2026-0008', 5, 'Road',
         'Road broken after pipeline construction work. No repairs done after the work was completed.',
         'Ward 5', 'Tilak Road, opposite Hanuman temple',
         'Pending', 'Normal', None, ts(3), None),

        ('VCMS-2026-0009', 2, 'Water',
         'Water supplied for only 15 minutes per day — insufficient for daily household needs.',
         'Ward 3', 'Sector B, Panchayat Colony',
         'Pending', 'Normal', None, ts(2), None),

        ('VCMS-2026-0010', 3, 'Garbage',
         'Garbage truck has not come in 5 days. Waste pile growing near society gate.',
         'Ward 1', 'Housing Society, Near Post Office',
         'In Progress', 'Normal', 'Suresh Jadhav', ts(5), None),
    ]

    cur.executemany(
        """INSERT INTO complaints
           (complaint_id, user_id, category, description, ward, address_detail,
            status, priority, assigned_to, created_at, resolved_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        complaints
    )
    # DB ids: VCMS-2026-0001 → id=1, ..., VCMS-2026-0010 → id=10

    # ----------------------------------------------------------
    # Status Logs  (complaint_db_id, old, new, changed_by, note, changed_at)
    # ----------------------------------------------------------
    status_logs = [
        # VCMS-2026-0001: Pending → In Progress → Resolved
        (1, None,          'Pending',     ADMIN, 'Complaint received.',                                    ts(20)),
        (1, 'Pending',     'In Progress', ADMIN, 'Assigned to Ramesh Naik. Work to begin this week.',      ts(17)),
        (1, 'In Progress', 'Resolved',   ADMIN, 'Pothole filled and road surface repaired.',              ts(12)),

        # VCMS-2026-0002: Pending → In Progress
        (2, None,          'Pending',     ADMIN, 'Complaint received.',                                    ts(15)),
        (2, 'Pending',     'In Progress', ADMIN, 'Assigned to Suresh Jadhav. Pipeline inspection scheduled.', ts(13)),

        # VCMS-2026-0003: Pending only
        (3, None,          'Pending',     ADMIN, 'Complaint received.',                                    ts(10)),

        # VCMS-2026-0004: Pending only
        (4, None,          'Pending',     ADMIN, 'Complaint received.',                                    ts(8)),

        # VCMS-2026-0005: Pending → Rejected
        (5, None,          'Pending',     ADMIN, 'Complaint received.',                                    ts(18)),
        (5, 'Pending',     'Rejected',    ADMIN, 'Duplicate — already covered under ward drainage work order #DW-22.', ts(16)),

        # VCMS-2026-0006: Pending → In Progress → Resolved
        (6, None,          'Pending',     ADMIN, 'Complaint received. Marked High priority.',              ts(25)),
        (6, 'Pending',     'In Progress', ADMIN, 'Assigned to Vijay More. Wire to be secured today.',     ts(23)),
        (6, 'In Progress', 'Resolved',   ADMIN, 'Low-hanging wire secured and tied to the pole.',        ts(18)),

        # VCMS-2026-0007: Pending → In Progress
        (7, None,          'Pending',     ADMIN, 'Complaint received.',                                    ts(6)),
        (7, 'Pending',     'In Progress', ADMIN, 'Assigned to Prakash Sawant. Animal control visiting Thursday.', ts(5)),

        # VCMS-2026-0008: Pending only
        (8, None,          'Pending',     ADMIN, 'Complaint received.',                                    ts(3)),

        # VCMS-2026-0009: Pending only
        (9, None,          'Pending',     ADMIN, 'Complaint received.',                                    ts(2)),

        # VCMS-2026-0010: Pending → In Progress
        (10, None,         'Pending',     ADMIN, 'Complaint received.',                                    ts(5)),
        (10, 'Pending',    'In Progress', ADMIN, 'Assigned to Suresh Jadhav. Route covered tomorrow.',    ts(4)),
    ]

    cur.executemany(
        """INSERT INTO status_logs (complaint_id, old_status, new_status, changed_by, note, changed_at)
           VALUES (?,?,?,?,?,?)""",
        status_logs
    )

    # ----------------------------------------------------------
    # Feedback  (only for Resolved: complaint ids 1 and 6)
    # ----------------------------------------------------------
    feedback_rows = [
        (1, 2, 5, 'Very happy with the quick resolution! The road is much better now.',               ts(11)),
        (6, 3, 4, 'Glad the wire is fixed — it was a real hazard. Took a bit long but good work.',   ts(17)),
    ]

    cur.executemany(
        """INSERT INTO feedback (complaint_id, user_id, rating, comment, submitted_at)
           VALUES (?,?,?,?,?)""",
        feedback_rows
    )

    # ----------------------------------------------------------
    # Notifications  (user_id, complaint_db_id, message, is_read, created_at)
    # ----------------------------------------------------------
    notifications = [
        (2, 1,  'Your complaint VCMS-2026-0001 status updated to In Progress.',  1, ts(17)),
        (2, 1,  'Your complaint VCMS-2026-0001 has been Resolved.',              1, ts(12)),
        (3, 2,  'Your complaint VCMS-2026-0002 status updated to In Progress.',  1, ts(13)),
        (2, 5,  'Your complaint VCMS-2026-0005 has been Rejected.',              1, ts(16)),
        (3, 6,  'Your complaint VCMS-2026-0006 status updated to In Progress.',  1, ts(23)),
        (3, 6,  'Your complaint VCMS-2026-0006 has been Resolved.',              0, ts(18)),  # unread
        (4, 7,  'Your complaint VCMS-2026-0007 status updated to In Progress.',  0, ts(5)),   # unread
        (3, 10, 'Your complaint VCMS-2026-0010 status updated to In Progress.',  0, ts(4)),   # unread
    ]

    cur.executemany(
        """INSERT INTO notifications (user_id, complaint_id, message, is_read, created_at)
           VALUES (?,?,?,?,?)""",
        notifications
    )

    # ----------------------------------------------------------
    # Properties (one per villager)
    # ----------------------------------------------------------
    # owner_id: Rajesh=2, Sunita=3, Mohan=4, Priya=5
    properties = [
        ('EGS-PROP-2026-0001', 2, 'Ward 3', 'RESIDENTIAL', 800,
         'House No. 45, Phule Nagar, Ward 3', 450000.0, ts(25), 'ACTIVE'),
        ('EGS-PROP-2026-0002', 3, 'Ward 1', 'RESIDENTIAL', 650,
         'Plot No. 12, Ambedkar Chowk, Ward 1', 380000.0, ts(25), 'ACTIVE'),
        ('EGS-PROP-2026-0003', 4, 'Ward 7', 'COMMERCIAL',  1200,
         'Shop No. 7, Ganesh Mandir Road, Ward 7', 750000.0, ts(25), 'ACTIVE'),
        ('EGS-PROP-2026-0004', 5, 'Ward 5', 'AGRICULTURAL', 5000,
         'Survey No. 118, Tilak Road, Ward 5', 200000.0, ts(25), 'ACTIVE'),
    ]
    cur.executemany(
        """INSERT INTO properties
           (property_no, owner_id, ward, property_type, area_sqft,
            address, assessed_value, registered_at, status)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        properties
    )
    # DB ids: EGS-PROP-2026-0001 → id=1, ..., id=4

    # ----------------------------------------------------------
    # Tax Records
    # ----------------------------------------------------------
    # 2025-26 records: due_date already past → will become OVERDUE
    # 2026-27 records: due_date in future → stay UNPAID
    tax_records = [
        # prop_id, tax_type,      fy,       amount,   due_date,     status
        (1, 'PROPERTY_TAX', '2025-26', 2250.0,  '2026-03-31', 'PAID'),
        (1, 'WATER_TAX',    '2025-26',  600.0,  '2026-03-31', 'PAID'),
        (1, 'PROPERTY_TAX', '2026-27', 2400.0,  '2027-03-31', 'UNPAID'),
        (1, 'WATER_TAX',    '2026-27',  650.0,  '2027-03-31', 'UNPAID'),
        (2, 'PROPERTY_TAX', '2025-26', 1900.0,  '2026-03-31', 'UNPAID'),   # past due → OVERDUE on load
        (2, 'PROPERTY_TAX', '2026-27', 2000.0,  '2027-03-31', 'UNPAID'),
        (3, 'PROPERTY_TAX', '2026-27', 3750.0,  '2027-03-31', 'UNPAID'),
        (4, 'PROPERTY_TAX', '2026-27', 1000.0,  '2027-03-31', 'UNPAID'),
    ]
    cur.executemany(
        """INSERT INTO tax_records
           (property_id, tax_type, financial_year, amount_due, due_date, status)
           VALUES (?,?,?,?,?,?)""",
        tax_records
    )
    # DB ids: tax_records 1..8

    # ----------------------------------------------------------
    # Payments (for the two PAID tax records of property 1)
    # ----------------------------------------------------------
    payments = [
        # tax_record_id, payer_id, amount, method, rz_order, rz_pay, status, paid_at, receipt
        (1, 2, 2250.0, 'CASH', None, None, 'SUCCESS', ts(10), 'EGS-RCPT-2026-0001'),
        (2, 2,  600.0, 'CASH', None, None, 'SUCCESS', ts(10), 'EGS-RCPT-2026-0002'),
    ]
    cur.executemany(
        """INSERT INTO payments
           (tax_record_id, payer_id, amount_paid, payment_method,
            razorpay_order_id, razorpay_payment_id, payment_status, paid_at, receipt_no)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        payments
    )

    conn.commit()
    conn.close()

    print(f"\nDatabase seeded: {os.path.abspath(DB_PATH)}")
    print("\n--- Demo Credentials ---")
    print("  Admin    mobile: 9999900000   password: admin123")
    print("  Villager mobile: 9876543210   password: village123  (Rajesh Patil, Ward 3)")
    print("  Villager mobile: 9876543211   password: village123  (Sunita Kamble, Ward 1)")
    print("  Villager mobile: 9876543212   password: village123  (Mohan Shinde, Ward 7)")
    print("  Villager mobile: 9876543213   password: village123  (Priya Deshpande, Ward 5)")
    print()


if __name__ == '__main__':
    run()
