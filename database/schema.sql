-- ============================================================
-- e-gramSeva (इ-ग्रामसेवा) — Citizen Services Portal
-- MySQL 8.0+ Schema
-- Apply once on your production MySQL instance.
-- For local dev, run database/seed.py instead (uses SQLite).
-- ============================================================

SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS notifications;
DROP TABLE IF EXISTS feedback;
DROP TABLE IF EXISTS status_logs;
DROP TABLE IF EXISTS complaints;
DROP TABLE IF EXISTS users;

SET FOREIGN_KEY_CHECKS = 1;


-- ------------------------------------------------------------
-- 1. users
--    Stores both villagers and the admin account.
--    Admin is seeded manually — no public signup for that role.
-- ------------------------------------------------------------
CREATE TABLE users (
    id            INT            AUTO_INCREMENT PRIMARY KEY,
    full_name     VARCHAR(100)   NOT NULL,
    mobile        VARCHAR(15)    NOT NULL,
    ward          ENUM(
                    'Ward 1','Ward 2','Ward 3','Ward 4','Ward 5',
                    'Ward 6','Ward 7','Ward 8','Ward 9','Ward 10'
                  )              NULL,            -- NULL for admin
    password_hash VARCHAR(255)   NOT NULL,
    role          ENUM('villager','admin') NOT NULL DEFAULT 'villager',
    created_at    DATETIME       DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_users_mobile UNIQUE (mobile)
);


-- ------------------------------------------------------------
-- 2. complaints
--    Core table. One row per filed complaint.
--    ward is copied from the user at submission time so that
--    reports remain accurate even if a user's ward changes later.
--    resolved_at is a dedicated column (not derived from
--    status_logs) to keep AVG resolution-time queries simple.
-- ------------------------------------------------------------
CREATE TABLE complaints (
    id             INT           AUTO_INCREMENT PRIMARY KEY,
    complaint_id   VARCHAR(20)   NOT NULL,           -- e.g. VCMS-2026-0001
    user_id        INT           NOT NULL,
    category       ENUM(
                     'Road','Water','Street Lights',
                     'Garbage','Drainage','Electricity','Other'
                   )             NOT NULL,
    description    TEXT          NOT NULL,
    ward           ENUM(
                     'Ward 1','Ward 2','Ward 3','Ward 4','Ward 5',
                     'Ward 6','Ward 7','Ward 8','Ward 9','Ward 10'
                   )             NOT NULL,
    address_detail VARCHAR(255)  NULL,
    latitude       DECIMAL(9,6)  NULL,
    longitude      DECIMAL(9,6)  NULL,
    photo_path     VARCHAR(255)  NULL,
    status         ENUM('Pending','In Progress','Resolved','Rejected')
                                 NOT NULL DEFAULT 'Pending',
    priority       ENUM('Normal','High')
                                 NOT NULL DEFAULT 'Normal',
    assigned_to    VARCHAR(100)  NULL,               -- worker name, plain text
    created_at     DATETIME      DEFAULT CURRENT_TIMESTAMP,
    resolved_at    DATETIME      NULL,

    CONSTRAINT uq_complaints_cid  UNIQUE (complaint_id),
    CONSTRAINT fk_complaints_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE RESTRICT
);


-- ------------------------------------------------------------
-- 3. status_logs
--    Append-only audit trail. One row per status transition.
--    old_status is NULL for the very first "Pending" entry
--    (i.e., when the complaint is first created).
-- ------------------------------------------------------------
CREATE TABLE status_logs (
    id            INT   AUTO_INCREMENT PRIMARY KEY,
    complaint_id  INT   NOT NULL,
    old_status    ENUM('Pending','In Progress','Resolved','Rejected') NULL,
    new_status    ENUM('Pending','In Progress','Resolved','Rejected') NOT NULL,
    changed_by    INT   NOT NULL,                    -- admin user id
    note          TEXT  NULL,
    changed_at    DATETIME DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_sl_complaint FOREIGN KEY (complaint_id)
        REFERENCES complaints(id) ON DELETE CASCADE,
    CONSTRAINT fk_sl_user FOREIGN KEY (changed_by)
        REFERENCES users(id) ON DELETE RESTRICT
);


-- ------------------------------------------------------------
-- 4. feedback
--    One rating per resolved complaint. UNIQUE on complaint_id
--    enforces the 1-per-complaint rule at the DB level.
-- ------------------------------------------------------------
CREATE TABLE feedback (
    id            INT       AUTO_INCREMENT PRIMARY KEY,
    complaint_id  INT       NOT NULL,
    user_id       INT       NOT NULL,
    rating        TINYINT   NOT NULL,
    comment       TEXT      NULL,
    submitted_at  DATETIME  DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_feedback_complaint UNIQUE (complaint_id),
    CONSTRAINT chk_rating      CHECK (rating BETWEEN 1 AND 5),
    CONSTRAINT fk_fb_complaint FOREIGN KEY (complaint_id)
        REFERENCES complaints(id) ON DELETE CASCADE,
    CONSTRAINT fk_fb_user      FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE RESTRICT
);


-- ------------------------------------------------------------
-- 5. notifications
--    Per-user inbox. A row is inserted on every status change.
--    Unread count: SELECT COUNT(*) WHERE user_id=? AND is_read=0
-- ------------------------------------------------------------
CREATE TABLE notifications (
    id            INT          AUTO_INCREMENT PRIMARY KEY,
    user_id       INT          NOT NULL,
    complaint_id  INT          NOT NULL,
    message       VARCHAR(255) NOT NULL,
    is_read       TINYINT(1)   NOT NULL DEFAULT 0,
    created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_notif_user      FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_notif_complaint FOREIGN KEY (complaint_id)
        REFERENCES complaints(id) ON DELETE CASCADE
);


-- ------------------------------------------------------------
-- 6. notices
--    Public notice board posted by admin. is_active controls
--    visibility on the home page.
-- ------------------------------------------------------------
CREATE TABLE notices (
    id         INT          AUTO_INCREMENT PRIMARY KEY,
    title      VARCHAR(150) NOT NULL,
    body       TEXT         NOT NULL,
    posted_by  INT          NOT NULL,
    is_active  TINYINT(1)   NOT NULL DEFAULT 1,
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_notices_user FOREIGN KEY (posted_by)
        REFERENCES users(id) ON DELETE RESTRICT
);


-- ------------------------------------------------------------
-- 7. service_requests
--    Unified table for Certificate (Birth/Death/Residence),
--    Permission, and Tax service applications.
--    form_data_json stores sub-type–specific key-value pairs
--    as a JSON string (parsed in app.py with Python's json module).
-- ------------------------------------------------------------
CREATE TABLE service_requests (
    id              INT           AUTO_INCREMENT PRIMARY KEY,
    request_no      VARCHAR(50)   NOT NULL,              -- REQ-2026-XXXX
    user_id         INT           NOT NULL,
    service_type    VARCHAR(50)   NOT NULL,              -- CERTIFICATE, PERMISSION, TAX
    sub_type        VARCHAR(50)   NOT NULL,              -- BIRTH, DEATH, RESIDENCE
    applicant_name  VARCHAR(100)  NOT NULL,
    ward            VARCHAR(20)   NOT NULL,
    form_data_json  TEXT          NULL,                  -- JSON blob of form fields
    document_path   VARCHAR(255)  NULL,                  -- uploaded identity/proof file
    status          VARCHAR(20)   NOT NULL DEFAULT 'PENDING', -- PENDING, VERIFIED, APPROVED, REJECTED
    remarks         TEXT          NULL,
    created_at      DATETIME      DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME      DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_service_requests_reqno UNIQUE (request_no),
    CONSTRAINT fk_sr_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE RESTRICT
);


-- ------------------------------------------------------------
-- 8. properties
--    One row per registered property in the Gram Panchayat.
--    Linked to an owner (user). assessed_value is the admin-
--    assigned market value used for tax calculation.
-- ------------------------------------------------------------
CREATE TABLE properties (
    id              INT           AUTO_INCREMENT PRIMARY KEY,
    property_no     VARCHAR(50)   NOT NULL,              -- EGS-PROP-2026-XXXX
    owner_id        INT           NOT NULL,
    ward            VARCHAR(20)   NOT NULL,
    property_type   VARCHAR(50)   NOT NULL,              -- RESIDENTIAL, COMMERCIAL, AGRICULTURAL
    area_sqft       REAL          NOT NULL,
    address         TEXT          NOT NULL,
    assessed_value  REAL          NOT NULL,
    registered_at   DATETIME      DEFAULT CURRENT_TIMESTAMP,
    status          VARCHAR(20)   NOT NULL DEFAULT 'ACTIVE', -- ACTIVE, DISPUTED, TRANSFERRED

    CONSTRAINT uq_properties_propno UNIQUE (property_no),
    CONSTRAINT fk_prop_owner FOREIGN KEY (owner_id)
        REFERENCES users(id) ON DELETE RESTRICT
);


-- ------------------------------------------------------------
-- 9. tax_records
--    One row per tax demand (property tax or water tax) for a
--    specific financial year. UNIQUE on (property, type, year)
--    prevents duplicate demands.
--    Status moves UNPAID → OVERDUE lazily on page load when
--    due_date has passed (no cron needed).
-- ------------------------------------------------------------
CREATE TABLE tax_records (
    id              INT           AUTO_INCREMENT PRIMARY KEY,
    property_id     INT           NOT NULL,
    tax_type        VARCHAR(30)   NOT NULL,              -- PROPERTY_TAX, WATER_TAX
    financial_year  VARCHAR(10)   NOT NULL,              -- e.g. 2026-27
    amount_due      REAL          NOT NULL,
    due_date        DATE          NOT NULL,
    status          VARCHAR(20)   NOT NULL DEFAULT 'UNPAID', -- UNPAID, PAID, OVERDUE, WAIVED
    created_at      DATETIME      DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_taxrec_prop_type_fy UNIQUE (property_id, tax_type, financial_year),
    CONSTRAINT fk_taxrec_property FOREIGN KEY (property_id)
        REFERENCES properties(id) ON DELETE CASCADE
);


-- ------------------------------------------------------------
-- 10. payments
--     One row per payment attempt against a tax_record.
--     receipt_no is generated only on SUCCESS.
--     Razorpay fields are nullable — filled only for online
--     payments (Phase 6.3).
-- ------------------------------------------------------------
CREATE TABLE payments (
    id                  INT           AUTO_INCREMENT PRIMARY KEY,
    tax_record_id       INT           NOT NULL,
    payer_id            INT           NOT NULL,
    amount_paid         REAL          NOT NULL,
    payment_method      VARCHAR(30)   NULL,              -- RAZORPAY_TEST, CASH, UPI
    razorpay_order_id   VARCHAR(100)  NULL,
    razorpay_payment_id VARCHAR(100)  NULL,
    payment_status      VARCHAR(20)   NOT NULL DEFAULT 'CREATED', -- CREATED, SUCCESS, FAILED
    paid_at             DATETIME      NULL,
    receipt_no          VARCHAR(50)   NULL,               -- EGS-RCPT-2026-XXXX

    CONSTRAINT uq_payments_receipt UNIQUE (receipt_no),
    CONSTRAINT fk_pay_taxrec FOREIGN KEY (tax_record_id)
        REFERENCES tax_records(id) ON DELETE CASCADE,
    CONSTRAINT fk_pay_payer FOREIGN KEY (payer_id)
        REFERENCES users(id) ON DELETE RESTRICT
);


-- ------------------------------------------------------------
-- Indexes
-- ------------------------------------------------------------
CREATE INDEX idx_complaints_user     ON complaints(user_id);
CREATE INDEX idx_complaints_status   ON complaints(status);
CREATE INDEX idx_complaints_category ON complaints(category);
CREATE INDEX idx_complaints_ward     ON complaints(ward);
CREATE INDEX idx_notif_user_read     ON notifications(user_id, is_read);
CREATE INDEX idx_statuslog_complaint ON status_logs(complaint_id);
CREATE INDEX idx_sr_user             ON service_requests(user_id);
CREATE INDEX idx_sr_status           ON service_requests(status);
CREATE INDEX idx_prop_owner          ON properties(owner_id);
CREATE INDEX idx_prop_ward           ON properties(ward);
CREATE INDEX idx_taxrec_property     ON tax_records(property_id);
CREATE INDEX idx_taxrec_status       ON tax_records(status);
CREATE INDEX idx_pay_taxrec          ON payments(tax_record_id);
CREATE INDEX idx_pay_payer           ON payments(payer_id);

