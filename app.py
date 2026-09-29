import os
import json
import uuid
import hmac
import hashlib
import sqlite3
from datetime import datetime
from functools import wraps
from io import BytesIO
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, g, send_file, make_response, jsonify
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
import razorpay
from config import Config

app = Flask(__name__)
app.config.from_object(Config)

# ── Razorpay client (test mode) ───────────────────────────────────
rzp_client = None
if app.config.get('RAZORPAY_KEY_ID') and app.config.get('RAZORPAY_KEY_SECRET'):
    rzp_client = razorpay.Client(
        auth=(app.config['RAZORPAY_KEY_ID'], app.config['RAZORPAY_KEY_SECRET'])
    )

ALLOWED_EXTENSIONS  = {'jpg', 'jpeg', 'png', 'webp'}
DOC_EXTENSIONS      = {'jpg', 'jpeg', 'png', 'webp', 'pdf'}
CATEGORIES          = ['Road', 'Water', 'Street Lights', 'Garbage', 'Drainage', 'Electricity', 'Other']
WARDS               = [f'Ward {i}' for i in range(1, 11)]
STATUSES            = ['Pending', 'In Progress', 'Resolved', 'Rejected']
SERVICE_STATUSES    = ['PENDING', 'VERIFIED', 'APPROVED', 'REJECTED']
CERTIFICATE_TYPES   = ['BIRTH', 'DEATH', 'RESIDENCE']
PERMISSION_TYPES    = ['BUILDING', 'WATER']
SCHEME_TYPES        = ['pmay', 'ujjwala', 'kisan_samman']
PROPERTY_TYPES      = ['RESIDENTIAL', 'COMMERCIAL', 'AGRICULTURAL']
PROPERTY_STATUSES   = ['ACTIVE', 'DISPUTED', 'TRANSFERRED']
TAX_TYPES           = ['PROPERTY_TAX', 'WATER_TAX']
TAX_STATUSES        = ['UNPAID', 'PAID', 'OVERDUE', 'WAIVED']
PAYMENT_STATUSES    = ['CREATED', 'SUCCESS', 'FAILED']

# ── Government Schemes catalog (static reference data) ───────────
# Keyed by sub_type slug; consumed by scheme_services() and scheme_apply().
SCHEMES = {
    'pmay': {
        'label':       'PM Awas Yojana',
        'subtitle':    'Housing Assistance Scheme',
        'icon':        'home',
        'icon_color':  '#022448',
        'eligibility': (
            'Below Poverty Line (BPL) families or those without a pucca house. '
            'Annual household income below \u20b93 lakh for rural beneficiaries.'
        ),
        'doc_hint':    'Income certificate, Aadhaar card, bank passbook copy.',
    },
    'ujjwala': {
        'label':       'Ujjwala Yojana',
        'subtitle':    'LPG Connection Scheme',
        'icon':        'propane',
        'icon_color':  '#92400e',
        'eligibility': (
            'Women from BPL households who do not already hold an LPG connection. '
            'Identification via Aadhaar and ration card.'
        ),
        'doc_hint':    'Aadhaar card, ration card, BPL certificate (if available).',
    },
    'kisan_samman': {
        'label':       'Kisan Samman Nidhi',
        'subtitle':    'Farmer Income Support Scheme',
        'icon':        'agriculture',
        'icon_color':  '#065f46',
        'eligibility': (
            'Small and marginal farmers owning cultivable land up to 2 hectares. '
            'Must be linked to Aadhaar and hold an active bank account.'
        ),
        'doc_hint':    'Land record / 7-12 extract, Aadhaar card, bank passbook copy.',
    },
}

# ── i18n translation table ────────────────────────────────────────
TRANSLATIONS = {
    'mr': {
        # Navigation
        'Home':                       '\u092e\u0941\u0916\u094d\u092f\u092a\u0943\u0937\u094d\u0920',
        'My Complaints':              '\u092e\u093e\u091d\u094d\u092f\u093e \u0924\u0915\u094d\u0930\u093e\u0930\u0940',
        'File a Complaint':           '\u0924\u0915\u094d\u0930\u093e\u0930 \u0928\u094b\u0902\u0926\u0935\u093e',
        'Login':                      '\u092a\u094d\u0930\u0935\u0947\u0936 \u0915\u0930\u093e',
        'Logout':                     '\u092c\u093e\u0939\u0947\u0930 \u092a\u0921\u093e',
        'Register':                   '\u0928\u094b\u0902\u0926\u0923\u0940 \u0915\u0930\u093e',
        'Notice Board':               '\u0938\u0942\u091a\u0928\u093e \u092b\u0932\u0915',
        'Certificates':               '\u092a\u094d\u0930\u092e\u093e\u0923\u092a\u0924\u094d\u0930\u0947',
        'Services':                   '\u0938\u0947\u0935\u093e',
        # Status labels
        'Pending':                    '\u092a\u094d\u0930\u0932\u0902\u092c\u093f\u0924',
        'In Progress':                '\u092a\u094d\u0930\u0915\u094d\u0930\u093f\u092f\u0947\u0924',
        'Resolved':                   '\u0928\u093f\u0930\u093e\u0915\u0930\u0923',
        'Rejected':                   '\u0928\u093e\u0915\u093e\u0930\u0932\u0947',
        'PENDING':                    '\u092a\u094d\u0930\u0932\u0902\u092c\u093f\u0924',
        'VERIFIED':                   '\u0938\u0924\u094d\u092f\u093e\u092a\u093f\u0924',
        'APPROVED':                   '\u092e\u0902\u091c\u0942\u0930',
        'REJECTED':                   '\u0928\u093e\u0915\u093e\u0930\u0932\u0947',
        # Categories
        'Road':                       '\u0930\u0938\u094d\u0924\u093e',
        'Water':                      '\u092a\u093e\u0923\u0940',
        'Street Lights':              '\u0926\u093f\u0935\u093e\u092c\u0924\u094d\u0924\u0940',
        'Garbage':                    '\u0915\u091a\u0930\u093e',
        'Drainage':                   '\u0917\u091f\u093e\u0930',
        'Electricity':                '\u0935\u0940\u091c',
        'Other':                      '\u0907\u0924\u0930',
        # Dashboard
        'Total':                      '\u090f\u0915\u0942\u0923',
        'In Progress Count':          '\u092a\u094d\u0930\u0915\u094d\u0930\u093f\u092f\u0947\u0924',
        'Complaint ID':               '\u0924\u0915\u094d\u0930\u093e\u0930 \u0915\u094d\u0930\u092e\u093e\u0902\u0915',
        'Category':                   '\u0936\u094d\u0930\u0947\u0923\u0940',
        'Ward':                       '\u0935\u093e\u0930\u094d\u0921',
        'Status':                     '\u0938\u094d\u0925\u093f\u0924\u0940',
        'Filed On':                   '\u0928\u094b\u0902\u0926\u0923\u0940 \u0924\u093e\u0930\u0940\u0916',
        'View':                       '\u092a\u0939\u093e',
        'File New Complaint':         '\u0928\u0935\u0940\u0928 \u0924\u0915\u094d\u0930\u093e\u0930',
        # New complaint form
        'File a New Complaint':       '\u0928\u0935\u0940\u0928 \u0924\u0915\u094d\u0930\u093e\u0930 \u0928\u094b\u0902\u0926\u0935\u093e',
        'Complaint Details':          '\u0924\u0915\u094d\u0930\u093e\u0930\u0940\u091a\u0947 \u0924\u092a\u0936\u0940\u0932',
        'Description':                '\u0935\u0930\u094d\u0923\u0928',
        'Address':                    '\u092a\u0924\u094d\u0924\u093e',
        'Location':                   '\u0938\u094d\u0925\u093e\u0928',
        'Use My Location':            '\u092e\u093e\u091d\u0947 \u0938\u094d\u0925\u093e\u0928 \u0935\u093e\u092a\u0930\u093e',
        'Location Captured':          '\u0938\u094d\u0925\u093e\u0928 \u092e\u093f\u0933\u093e\u0932\u0947',
        'Photo':                      '\u092b\u094b\u091f\u094b',
        'Submit Complaint':           '\u0924\u0915\u094d\u0930\u093e\u0930 \u0938\u093e\u0926\u0930 \u0915\u0930\u093e',
        'Cancel':                     '\u0930\u0926\u094d\u0926 \u0915\u0930\u093e',
        # Detail page
        'Back to My Complaints':      '\u092e\u093e\u091d\u094d\u092f\u093e \u0924\u0915\u094d\u0930\u093e\u0930\u0940\u0902\u0915\u0921\u0947 \u092a\u0930\u0924',
        'Complaint Information':      '\u0924\u0915\u094d\u0930\u093e\u0930 \u092e\u093e\u0939\u093f\u0924\u0940',
        'Status Timeline':            '\u0938\u094d\u0925\u093f\u0924\u0940 \u0935\u0947\u0933\u093e\u092a\u0924\u094d\u0930\u0915',
        'Scan to Track':              '\u0924\u0915\u094d\u0930\u093e\u0930 \u0924\u092a\u093e\u0938\u093e\u0938\u093e\u0920\u0940 \u0938\u094d\u0915\u0945\u0928 \u0915\u0930\u093e',
        'Rate This Resolution':       '\u092e\u0942\u0932\u094d\u092f\u093e\u0902\u0915\u0928 \u0915\u0930\u093e',
        'Submit Rating':              '\u092e\u0942\u0932\u094d\u092f\u093e\u0902\u0915\u0928 \u0938\u093e\u0926\u0930 \u0915\u0930\u093e',
        'Your Rating':                '\u0924\u0941\u092e\u091a\u0947 \u092e\u0942\u0932\u094d\u092f\u093e\u0902\u0915\u0928',
        # Auth
        'Full Name':                  '\u092a\u0942\u0930\u094d\u0923 \u0928\u093e\u0935',
        'Mobile Number':              '\u092e\u094b\u092c\u093e\u0907\u0932 \u0928\u0902\u092c\u0930',
        'Password':                   '\u092a\u093e\u0938\u0935\u0930\u094d\u0921',
        'Confirm Password':           '\u092a\u0941\u0928\u094d\u0939\u093e \u092a\u093e\u0938\u0935\u0930\u094d\u0921',
        # Notice board
        'Panchayat Notices':          '\u092a\u0902\u091a\u093e\u092f\u0924 \u0938\u0942\u091a\u0928\u093e',
        'No notices posted yet':      '\u0905\u0926\u094d\u092f\u093e\u092a \u0915\u094b\u0923\u0924\u0940\u0939\u0940 \u0938\u0942\u091a\u0928\u093e \u0928\u093e\u0939\u0940',
        'How It Works':               '\u0939\u0947 \u0915\u0938\u0947 \u0915\u093e\u0930\u094d\u092f \u0915\u0930\u0924\u0947',
        # Certificate services
        'Certificate Services':       '\u092a\u094d\u0930\u092e\u093e\u0923\u092a\u0924\u094d\u0930 \u0938\u0947\u0935\u093e',
        'My Applications':            '\u092e\u093e\u091d\u0947 \u0905\u0930\u094d\u091c',
        'Birth Certificate':          '\u091c\u0928\u094d\u092e \u092a\u094d\u0930\u092e\u093e\u0923\u092a\u0924\u094d\u0930',
        'Death Certificate':          '\u092e\u0943\u0924\u094d\u092f\u0942 \u092a\u094d\u0930\u092e\u093e\u0923\u092a\u0924\u094d\u0930',
        'Residence Certificate':      '\u0930\u0939\u093f\u0935\u093e\u0938\u0940 \u092a\u094d\u0930\u092e\u093e\u0923\u092a\u0924\u094d\u0930',
        'Apply Now':                  '\u0905\u0930\u094d\u091c \u0915\u0930\u093e',
        'Download Certificate':       '\u092a\u094d\u0930\u092e\u093e\u0923\u092a\u0924\u094d\u0930 \u0921\u093e\u0909\u0928\u0932\u094b\u0921 \u0915\u0930\u093e',
        '(Admin)': '(प्रशासक)',
        '(Resident)': '(रहिवासी)',
        '10-digit registered mobile number': '१०-अंकी नोंदणीकृत मोबाईल क्रमांक',
        'Back to My Complaints': 'माझ्या तक्रारींकडे परत जा',
        'Describe the action taken, reason for update, or instructions to the worker': 'घेतलेली कारवाई, अपडेटचे कारण किंवा कामगाराला सूचनांचे वर्णन करा',
        'Full notice text. Include dates, timings, contact info as needed.&#10;Example:&#10;Water supply will be available 6–8 AM on Tuesday, 12 August 2026 for Ward 3 and Ward 5.&#10;For queries: Gram Panchayat office — 9876500000': 'संपूर्ण सूचनेचा मजकूर. आवश्यकता असल्यास तारखा, वेळा, संपर्क माहिती समाविष्ट करा.&#10;उदाहरण:&#10;मंगळवार, 12 ऑगस्ट 2026 रोजी प्रभाग 3 आणि प्रभाग 5 साठी सकाळी 6-8 पाणीपुरवठा उपलब्ध असेल.&#10;चौकशीसाठी: ग्रामपंचायत कार्यालय — 9876500000',
        'House/Plot No., Street, Locality, Ward': 'घर/प्लॉट क्र., रस्ता, परिसर, प्रभाग',
        'My Dashboard': 'माझा डॅशबोर्ड',
        'Reports': 'अहवाल',
        'Verification notes, reason for rejection, etc.': 'पडताळणीच्या नोंदी, नाकारण्याचे कारण, इ.',
        'Worker\'s full name': 'कामगाराचे पूर्ण नाव',
        'e.g. 2026-27': 'उदा. 2026-27',
        'e.g. Water Supply Schedule — Ward 3 & 5': 'उदा. पाणी पुरवठा वेळापत्रक — प्रभाग 3 आणि 5',
        'ग्राम पंचायत &mdash; इ-ग्रामसेवा': 'ग्रामपंचायत &mdash; इ-ग्रामसेवा',
        'जन्म नोंद — Janma Nondi': 'जन्म नोंद — Janma Nondi',
        'मालमत्ता नोंद — Malmatta Nondi': 'मालमत्ता नोंद — Malmatta Nondi',
        'मृत्यू नोंद — Mrutyu Nondi': 'मृत्यू नोंद — Mrutyu Nondi',
        '— Select —': '— निवडा —',
        'Panchayat Helpline: 1800-XXX-XXXX': 'पंचायत हेल्पलाइन: १८००-XXX-XXXX',
        'Mon&ndash;Sat, 9 am &ndash; 6 pm': 'सोम-शनि, स. 9 ते सायं. 6',
        'Citizen Services Portal &mdash; Gram Panchayat': 'नागरिक सेवा पोर्टल &mdash; ग्रामपंचायत',
        'Citizen &bull; Sarpanch &bull; Sachiv': 'नागरिक &bull; सरपंच &bull; सचिव',
        'Empowering Rural Governance Through Digital Access': 'डिजिटल ऍक्सेसद्वारे ग्रामीण प्रशासनाचे सक्षमीकरण',
        'Direct, transparent, and expedited access to Gram Panchayat civil certificates, land and property assessments, localized welfare benefits, and citizen grievance tracking.': 'ग्रामपंचायत नागरी प्रमाणपत्रे, जमीन आणि मालमत्तेचे मूल्यांकन, स्थानिक कल्याणकारी फायदे आणि नागरिक तक्रार ट्रॅकिंगमध्ये थेट, पारदर्शक आणि जलद प्रवेश.',
        'Statutory Validity': 'वैधानिक वैधता',
        'e-Sign Certified': 'ई-साइन प्रमाणित',
        'Zero-Leakage DBT': 'झिरो-लीकेज डीबीटी',
        'Direct Benefit': 'थेट लाभ',
        '100% Paperless': '१००% पेपरलेस',
        'Instant e-Records': 'त्वरित ई-रेकॉर्ड',
        'Welcome Back': 'परत स्वागत आहे',
        'Sign In to Portal': 'पोर्टलमध्ये साइन इन करा',
        'Login with your registered mobile number and password.': 'तुमचा नोंदणीकृत मोबाईल क्रमांक आणि पासवर्ड वापरून लॉग इन करा.',
        'Mobile Number': 'मोबाईल क्रमांक',
        'Password': 'पासवर्ड',
        'Login': 'लॉगिन करा',
        "Don't have an account?": 'खाते नाही का?',
        'Register as New Villager': 'नवीन ग्रामस्थ म्हणून नोंदणी करा',
        'Or continue as': 'किंवा या रूपात सुरू ठेवा',
        'Gram Panchayat staff?': 'ग्रामपंचायत कर्मचारी आहात का?',
        'Use your official credentials above — there is no separate admin login page.': 'तुमची अधिकृत क्रेडेन्शियल्स वर वापरा - प्रशासकांसाठी वेगळे लॉगिन पेज नाही.',
        'Protected by National Informatics Infrastructure &bull; 256-bit SSL': 'राष्ट्रीय माहिती पायाभूत सुविधा &bull; 256-bit SSL द्वारे संरक्षित',
        'Government of India &bull; MoPR Initiative': 'भारत सरकार &bull; MoPR पुढाकार',
        'Citizen Services Portal &copy; 2026. Gram Panchayat.': 'नागरिक सेवा पोर्टल &copy; 2026. ग्रामपंचायत.',
        'Gram Panchayat Architectural Node': 'ग्रामपंचायत आर्किटेक्चरल नोड',
        'Live Node': 'लाइव्ह नोड',
        'National e-Governance Programme': 'राष्ट्रीय ई-गव्हर्नन्स कार्यक्रम',
        'NIC': 'एनआयसी',
        'New Resident Registration': 'नवीन रहिवासी नोंदणी',
        'Register': 'नोंदणी करा',
        'Fill in your details below. Your mobile number will be your login username.': 'खाली तुमचे तपशील भरा. तुमचा मोबाईल नंबर तुमचा लॉगिन युजरनेम असेल.',
        'Full Name': 'पूर्ण नाव',
        'Confirm Password': 'पासवर्डची पुष्टी करा',
        'Already registered?': 'आधीच नोंदणीकृत आहात का?',
        'Login here': 'येथे लॉगिन करा',
        '10-digit number': '१०-अंकी क्रमांक',
        '10-digit mobile number': '१०-अंकी मोबाईल क्रमांक',
        'Minimum 6 characters': 'किमान ६ अक्षरे',
        'Repeat password': 'पासवर्ड पुन्हा टाका',
        'Enter your password': 'तुमचा पासवर्ड टाका',
        'This will be used to log in.': 'याचा वापर लॉग इन करण्यासाठी केला जाईल.',
        'As per Aadhaar or official record': 'आधार किंवा अधिकृत रेकॉर्डनुसार',
        'A unique property number (EGS-PROP-XXXX) will be auto-generated on submission.': 'सबमिशनवर एक अद्वितीय मालमत्ता क्रमांक (EGS-PROP-XXXX) स्वयं-व्युत्पन्न केला जाईल.',
        'APPROVED': 'मंजूर',
        'Activate': 'सक्रिय करा',
        'Active': 'सक्रिय',
        'Active notices appear on the public home page.': 'सक्रिय सूचना सार्वजनिक होम पेजवर दिसतात.',
        'Add Tax Record': 'कर रेकॉर्ड जोडा',
        'Address': 'पत्ता',
        'Admin Remarks': 'प्रशासक शेरा',
        'Administration': 'प्रशासन',
        'All Categories': 'सर्व श्रेणी',
        'All Complaints': 'सर्व तक्रारी',
        'All Notices': 'सर्व सूचना',
        'All Statuses': 'सर्व स्थिती',
        'All Types': 'सर्व प्रकार',
        'All Wards': 'सर्व प्रभाग',
        'Amount': 'रक्कम',
        'Amount Due': 'थकबाकीची रक्कम',
        'Amount Due (₹)': 'थकबाकीची रक्कम (₹)',
        'Applicant & Ward': 'अर्जदार आणि प्रभाग',
        'Applicant Name': 'अर्जदाराचे नाव',
        'Application Approved': 'अर्ज मंजूर',
        'Application Details': 'अर्जाचा तपशील',
        'Application Type': 'अर्जाचा प्रकार',
        'Applied On': 'अर्ज केल्याची तारीख',
        'Apply': 'अर्ज करा',
        'Approved': 'मंजूर',
        'Approved From': 'मंजूर तारीख (पासून)',
        'Approved On': 'मंजूर केल्याची तारीख',
        'Area': 'क्षेत्रफळ',
        'Area (sq ft)': 'क्षेत्रफळ (चौ. फूट)',
        'Assessed Value': 'मूल्यांकित किंमत',
        'Assessed Value (₹)': 'मूल्यांकित किंमत (₹)',
        'Assign Worker': 'कामगार नियुक्त करा',
        'Assigned To': 'नियुक्त केले',
        'Audit Trail — Complete History': 'ऑडिट ट्रेल - संपूर्ण इतिहास',
        'Avg Resolution Time': 'सरासरी निराकरण वेळ',
        'Back to All Complaints': 'सर्व तक्रारींकडे परत जा',
        'Back to Dashboard': 'डॅशबोर्डवर परत जा',
        'Back to Properties': 'मालमत्तांकडे परत जा',
        'Back to Service Requests': 'सेवा विनंत्यांकडे परत जा',
        'Birth Register • Gram Panchayat • Official Record (Read-only)': 'जन्म नोंदवही • ग्रामपंचायत • अधिकृत रेकॉर्ड (फक्त-वाचनीय)',
        'Cancel': 'रद्द करा',
        'Category': 'श्रेणी',
        'Category & Priority': 'श्रेणी आणि प्राधान्य',
        'Category Breakdown': 'श्रेणीनुसार वर्गीकरण',
        'Certificate Approved': 'प्रमाणपत्र मंजूर',
        'Certificate, permission, and scheme applications from residents': 'रहिवाशांकडून प्रमाणपत्र, परवानगी आणि योजनांचे अर्ज',
        'Citizen Services Portal &bull; Official Register': 'नागरिक सेवा पोर्टल &bull; अधिकृत नोंदवही',
        'Clear': 'साफ करा',
        'Close': 'बंद करा',
        'Collected': 'गोळा केलेले',
        'Complaint ID': 'तक्रार क्र.',
        'Complaint Information': 'तक्रार माहिती',
        'Complaint data summary for all wards': 'सर्व प्रभागांसाठी तक्रार डेटा सारांश',
        'Complaints Dashboard': 'तक्रारी डॅशबोर्ड',
        'Complaints by Category': 'श्रेणीनुसार तक्रारी',
        'Count': 'संख्या',
        'Current resolution photo:': 'वर्तमान निराकरण फोटो:',
        'Currently Pending': 'सध्या प्रलंबित',
        'Dashboard': 'डॅशबोर्ड',
        'Date of Birth': 'जन्मतारीख',
        'Date of Death': 'मृत्यूची तारीख',
        'Deactivate': 'निष्क्रिय करा',
        'Deactivated': 'निष्क्रिय',
        'Death Register • Gram Panchayat • Official Record (Read-only)': 'मृत्यू नोंदवही • ग्रामपंचायत • अधिकृत रेकॉर्ड (फक्त-वाचनीय)',
        'Description': 'वर्णन',
        'Due Date': 'नियत तारीख',
        'F.Y.': 'आर्थिक वर्ष',
        'Filed By': 'दाखल करणारे',
        'Filed On': 'दाखल केल्याची तारीख',
        'Filed by': 'दाखल करणारे',
        'Filter Status': 'स्थिती फिल्टर करा',
        'Filter Ward': 'प्रभाग फिल्टर करा',
        'Financial Year': 'आर्थिक वर्ष',
        'Full Address': 'पूर्ण पत्ता',
        'Governance Menu': 'प्रशासन मेनू',
        'Gram Panchayat': 'ग्रामपंचायत',
        'Gram Panchayat &mdash; e-gramSeva': 'ग्रामपंचायत &mdash; इ-ग्रामसेवा',
        'Gram Panchayat — Administration View': 'ग्रामपंचायत — प्रशासन दृश्य',
        'Gram Sevak': 'ग्रामसेवक',
        'High': 'उच्च',
        'High Priority': 'उच्च प्राधान्य',
        'Janma Nondi': 'जन्म नोंद',
        'Last Updated': 'शेवटचे अपडेट',
        'Logout': 'लॉग आउट',
        'Malmatta Nondi': 'मालमत्ता नोंद',
        'Manage': 'व्यवस्थापित करा',
        'Manage citizen complaints submitted via the portal.': 'पोर्टलद्वारे सबमिट केलेल्या नागरिक तक्रारी व्यवस्थापित करा.',
        'Market value for tax calculation.': 'कर मोजणीसाठी बाजार मूल्य.',
        'Method': 'पद्धत',
        'Monthly Complaints Filed (Last 6 Months)': 'दाखल केलेल्या मासिक तक्रारी (गेले ६ महिने)',
        'Mrutyu Nondi': 'मृत्यू नोंद',
        'Must be a registered villager account.': 'नोंदणीकृत ग्रामस्थ खाते असणे आवश्यक आहे.',
        'No complaints found for the selected filters.': 'निवडलेल्या फिल्टरसाठी कोणत्याही तक्रारी आढळल्या नाहीत.',
        'No notices posted yet.': 'अद्याप कोणत्याही सूचना पोस्ट केल्या नाहीत.',
        'No properties found.': 'कोणत्याही मालमत्ता आढळल्या नाहीत.',
        'No records found for the selected filters.': 'निवडलेल्या फिल्टरसाठी कोणतेही रेकॉर्ड आढळले नाही.',
        'No service requests found.': 'कोणत्याही सेवा विनंत्या आढळल्या नाहीत.',
        'No tax records found.': 'कोणतेही कर रेकॉर्ड आढळले नाही.',
        'No tax records yet.': 'अद्याप कोणतेही कर रेकॉर्ड नाही.',
        'Normal': 'सामान्य',
        'Notice Board Management': 'सूचना फलक व्यवस्थापन',
        'Notice Details': 'सूचनेचा तपशील',
        'Notice Title': 'सूचनेचे शीर्षक',
        'Notices': 'सूचना',
        'Officer Control Center': 'अधिकारी नियंत्रण केंद्र',
        'Outstanding': 'थकबाकी',
        'Overdue': 'मुदत संपलेली',
        'Owner': 'मालक',
        'Owner Name': 'मालकाचे नाव',
        'Owner\'s Mobile Number': 'मालकाचा मोबाईल क्रमांक',
        'Owner:': 'मालक:',
        'Paid': 'भरले',
        'Paid On': 'भरल्याची तारीख',
        'Panchayat Admin': 'पंचायत प्रशासक',
        'Payment History': 'पेमेंट इतिहास',
        'Pending Review': 'पुनरावलोकन प्रलंबित',
        'Post New Notice': 'नवीन सूचना पोस्ट करा',
        'Post Notice': 'सूचना पोस्ट करा',
        'Print / Save as PDF': 'प्रिंट करा / पीडीएफ म्हणून जतन करा',
        'Print Register': 'नोंदवही प्रिंट करा',
        'Priority': 'प्राधान्य',
        'Progress Note': 'प्रगती नोंद',
        'Properties': 'मालमत्ता',
        'Property': 'मालमत्ता',
        'Property & Tax': 'मालमत्ता आणि कर',
        'Property Details': 'मालमत्ता तपशील',
        'Property No.': 'मालमत्ता क्र.',
        'Property Owner': 'मालमत्ता मालक',
        'Property Register • Gram Panchayat • Official Record (Read-only)': 'मालमत्ता नोंदवही • ग्रामपंचायत • अधिकृत रेकॉर्ड (फक्त-वाचनीय)',
        'QR Code — Scan to Track': 'QR कोड — ट्रॅक करण्यासाठी स्कॅन करा',
        'Receipt No.': 'पावती क्र.',
        'Recent Complaints': 'अलीकडील तक्रारी',
        'Register New Property': 'नवीन मालमत्तेची नोंदणी करा',
        'Register Property': 'मालमत्तेची नोंदणी करा',
        'Registered': 'नोंदणीकृत',
        'Registered From': 'नोंदणी तारीख (पासून)',
        'Registered On': 'नोंदणी केल्याची तारीख',
        'Registered properties in the Gram Panchayat': 'ग्रामपंचायतीमध्ये नोंदणीकृत मालमत्ता',
        'Registers': 'नोंदवह्या',
        'Reports & Analytics': 'अहवाल आणि विश्लेषण',
        'Request No.': 'विनंती क्र.',
        'Resident Feedback': 'रहिवाशांचा अभिप्राय',
        'Resident\'s Complaint Photo': 'रहिवाशाचा तक्रार फोटो',
        'Resolution Photo': 'निराकरण फोटो',
        'Resolution Rate': 'निराकरण दर',
        'Resolved': 'सुटलेला',
        'Resolved On': 'निराकरण झालेली तारीख',
        'Review': 'पुनरावलोकन',
        'Sarpanch': 'सरपंच',
        'Save Changes': 'बदल जतन करा',
        'Service Requests': 'सेवा विनंत्या',
        'Share': 'शेअर करा',
        'Sr.': 'अ.क्र.',
        'Status': 'स्थिती',
        'Status Breakdown': 'स्थितीनुसार वर्गीकरण',
        'Status Distribution': 'स्थितीचे वितरण',
        'Tax': 'कर',
        'Tax Overview': 'कराचा आढावा',
        'Tax Records': 'कर रेकॉर्ड',
        'Tax Type': 'कराचा प्रकार',
        'Tax collection status across all properties': 'सर्व मालमत्तांवरील कर संकलन स्थिती',
        'The certificate has been generated and is available for download.': 'प्रमाणपत्र तयार केले गेले आहे आणि डाउनलोडसाठी उपलब्ध आहे.',
        'This application has been approved. The applicant will be notified.': 'हा अर्ज मंजूर झाला आहे. अर्जदाराला सूचित केले जाईल.',
        'To': 'ते',
        'Total': 'एकूण',
        'Total Complaints': 'एकूण तक्रारी',
        'Total Records': 'एकूण नोंदी',
        'Total Requests': 'एकूण विनंत्या',
        'Type': 'प्रकार',
        'Unpaid': 'न भरलेले',
        'Update Property': 'मालमत्ता अपडेट करा',
        'Update Status': 'स्थिती अपडेट करा',
        'Update This Complaint': 'ही तक्रार अपडेट करा',
        'Uploaded Document': 'अपलोड केलेला दस्तऐवज',
        'View': 'पहा',
        'View / Download Certificate': 'प्रमाणपत्र पहा / डाउनलोड करा',
        'View PDF Document': 'PDF दस्तऐवज पहा',
        'View Reports': 'अहवाल पहा',
        'Village Level Worker': 'ग्रामस्तरीय कार्यकर्ता',
        'Ward': 'प्रभाग',
        'Year': 'वर्ष',
        'Admin — All Complaints': 'प्रशासक — सर्व तक्रारी',
        'Gram Panchayat administration — manage all citizen complaints.': 'ग्रामपंचायत प्रशासन — सर्व नागरिक तक्रारींचे व्यवस्थापन करा.',
        'Admin — Dashboard': 'प्रशासक — डॅशबोर्ड',
        '(optional — for Resolved status)': '(ऐच्छिक — निराकरण झालेल्या स्थितीसाठी)',
        'e.g. Ram Patil': 'उदा. राम पाटील',
        '9876543210': '९८७६५४३२१०',
        'Namaste, ': 'नमस्ते, ',
        'Active Citizen': 'सक्रिय नागरिक',
        'Gram Panchayat': 'ग्रामपंचायत',
        'Aadhaar Verified': 'आधार प्रमाणित',
        'One-Click Citizen Portal': 'वन-क्लिक नागरिक पोर्टल',
        'Quick Civic Services': 'जलद नागरी सेवा',
        'Access instant village administration services and online governance tools': 'त्वरित गाव प्रशासन सेवा आणि ऑनलाइन प्रशासन साधने मिळवा',
        'End-to-End Digitized &amp; Paperless': 'पूर्णपणे डिजिटाइज्ड आणि पेपरलेस',
        '3 Types': '3 प्रकार',
        'Apply Certificate': 'प्रमाणपत्रासाठी अर्ज करा',
        'Birth, Death &amp; Residence certificates': 'जन्म, मृत्यू आणि रहिवासी प्रमाणपत्रे',
        'Instant ACK': 'त्वरित पावती',
        'Apply Permission': 'परवानगीसाठी अर्ज करा',
        'Building construction, water connection': 'इमारत बांधकाम, पाणी कनेक्शन',
        'Submit Request': 'विनंती सबमिट करा',
        'View Schemes': 'योजना पहा',
        'Welfare &amp; Subsidies': 'कल्याण आणि अनुदान',
        'Check eligibility and apply for schemes': 'पात्रता तपासा आणि योजनांसाठी अर्ज करा',
        'Explore': 'अन्वेषण करा',
        'Property Tax': 'मालमत्ता कर',
        'Property & Tax': 'मालमत्ता आणि कर',
        'Check Dues': 'थकबाकी तपासा',
        'Pay your pending property &amp; water tax': 'तुमचा प्रलंबित मालमत्ता आणि पाणी कर भरा',
        'Check Status': 'स्थिती तपासा',
        'Raise an issue with the local administration': 'स्थानिक प्रशासनाकडे समस्या मांडा',
        'Application ID': 'अर्ज क्रमांक',
        'Service': 'सेवा',
        'Action': 'कृती',
        'File civic complaints and track their resolution online &mdash; anytime, from any device.': 'नागरी तक्रारी नोंदवा आणि ऑनलाइन ट्रॅक करा &mdash; कधीही, कोणत्याही उपकरणावरून.',
        'Notice Board': 'सूचना फलक',
        'No notices posted yet.': 'अद्याप कोणत्याही सूचना पोस्ट केल्या नाहीत.',
        'Register with your mobile number and ward number.': 'तुमचा मोबाईल क्रमांक आणि प्रभाग क्रमांक वापरून नोंदणी करा.',
        'File a complaint with a description and optional photo.': 'तपशील आणि ऐच्छिक फोटोसह तक्रार नोंदवा.',
        'Track the status as Gram Panchayat assigns a worker.': 'ग्रामपंचायतीने कामगार नेमल्यावर स्थितीचा मागोवा घ्या.',
        'Get notified when your complaint is resolved.': 'तुमची तक्रार सुटल्यावर सूचना मिळवा.',
        'Rate the resolution to help improve services.': 'सेवा सुधारण्यात मदत करण्यासाठी निराकरणाला रेट करा.',
        'Citizen Service Portal &bull; Gram Panchayat Digital Window': 'नागरिक सेवा पोर्टल &bull; ग्रामपंचायत डिजिटल विंडो',
        'Apply for official Gram Panchayat certificates online. Upload your documents and track your application status without visiting the Panchayat office.': 'अधिकृत ग्रामपंचायत प्रमाणपत्रांसाठी ऑनलाइन अर्ज करा. पंचायत कार्यालयाला भेट न देता कागदपत्रे अपलोड करा आणि स्थितीचा मागोवा घ्या.',
        'Avg. Fulfillment': 'सरासरी पूर्तता वेळ',
        '2-3 Days': '2-3 दिवस',
        'Outstanding Tax Dues — Certificate Applications Blocked': 'थकबाकी कर — प्रमाणपत्र अर्ज ब्लॉक केले आहेत',
        'You have unpaid property-tax dues. All certificate applications are on hold until every due below is settled.': 'तुमची मालमत्ता-कराची थकबाकी आहे. खालील प्रत्येक थकबाकी पूर्ण होईपर्यंत सर्व प्रमाणपत्र अर्ज होल्डवर आहेत.',
        'Property&nbsp;No.': 'मालमत्ता&nbsp;क्र.',
        'Tax Type': 'कर प्रकार',
        'Financial Year': 'आर्थिक वर्ष',
        'Amount Due': 'थकबाकीची रक्कम',
        'Pay Dues Now': 'आता थकबाकी भरा',
        'Public Registry Services': 'सार्वजनिक नोंदणी सेवा',
        '3 Services': '3 सेवा',
        'Official birth registration certificate issued by the Gram Panchayat. Required for school admission, Aadhaar enrollment, and other government services.': 'ग्रामपंचायतीने जारी केलेले अधिकृत जन्म नोंदणी प्रमाणपत्र. शालेय प्रवेश, आधार नोंदणी आणि इतर सरकारी सेवांसाठी आवश्यक.',
        'Parent\'s identity proof (Aadhaar / Voter ID)': 'पालकांचा ओळख पुरावा (आधार / मतदार ओळखपत्र)',
        'Hospital discharge certificate (if available)': 'रुग्णालय डिस्चार्ज प्रमाणपत्र (उपलब्ध असल्यास)',
        'Official death registration certificate. Required for insurance claims, property transfer, and legal proceedings.': 'अधिकृत मृत्यू नोंदणी प्रमाणपत्र. विमा दावे, मालमत्ता हस्तांतरण आणि कायदेशीर प्रक्रियेसाठी आवश्यक.',
        'Deceased\'s identity proof': 'मृताचा ओळख पुरावा',
        'Medical certificate of cause of death': 'मृत्यूच्या कारणाचे वैद्यकीय प्रमाणपत्र',
        'Proof of residence issued by the Gram Panchayat. Required for school admission, employment, and government scheme applications.': 'ग्रामपंचायतीने दिलेला रहिवासी पुरावा. शालेय प्रवेश, रोजगार आणि सरकारी योजनांच्या अर्जांसाठी आवश्यक.',
        'Aadhaar card or ration card copy': 'आधार कार्ड किंवा शिधापत्रिका प्रत',
        'Electricity bill / property tax receipt': 'वीज बिल / मालमत्ता कर पावती',
        'Apply for Birth, Death, or Residence certificates from the Gram Panchayat.': 'ग्रामपंचायतीकडून जन्म, मृत्यू किंवा रहिवासी प्रमाणपत्रासाठी अर्ज करा.',
        'Permission Services': 'परवानगी सेवा',
        'Apply for Building or Water Connection permissions from the Gram Panchayat.': 'ग्रामपंचायतीकडून इमारत किंवा पाणी कनेक्शन परवानगीसाठी अर्ज करा.',
        'Apply for official Gram Panchayat permissions online. Upload your documents and track your application status.': 'अधिकृत ग्रामपंचायत परवानगीसाठी ऑनलाइन अर्ज करा. कागदपत्रे अपलोड करा आणि स्थितीचा मागोवा घ्या.',
        '5-7 Days': '5-7 दिवस',
        '2 Services': '2 सेवा',
        'Permissions': 'परवानग्या',
        'Building Permission': 'इमारत परवानगी',
        'Official Gram Panchayat construction permission for new buildings, extensions, or renovations. Required before commencing any construction work on residential or commercial plots.': 'नवीन इमारती, विस्तार किंवा नूतनीकरणासाठी अधिकृत ग्रामपंचायत बांधकाम परवानगी. निवासी किंवा व्यावसायिक भूखंडांवर कोणतेही बांधकाम सुरू करण्यापूर्वी आवश्यक.',
        'Site plan / architectural drawing (PDF or image)': 'साइट योजना / वास्तुशिल्प चित्र (PDF किंवा प्रतिमा)',
        'Applicant\'s identity proof (Aadhaar / Voter ID)': 'अर्जदाराचा ओळख पुरावा (आधार / मतदार ओळखपत्र)',
        'Proof of plot ownership': 'भूखंड मालकीचा पुरावा',
        'Water Connection Permission': 'पाणी कनेक्शन परवानगी',
        'New domestic or commercial water connection from the Gram Panchayat supply network. Required for first-time connections and pipe-size upgrades.': 'ग्रामपंचायत पुरवठा नेटवर्कवरून नवीन घरगुती किंवा व्यावसायिक पाणी कनेक्शन. पहिल्यांदा कनेक्शन आणि पाईप आकाराच्या अपग्रेडसाठी आवश्यक.',
        'Property ownership proof / rent agreement': 'मालमत्ता मालकीचा पुरावा / भाडे करार',
        'Government Schemes': 'सरकारी योजना',
        'Apply for government welfare schemes through the Gram Panchayat — PM Awas Yojana, Ujjwala Yojana, Kisan Samman Nidhi, and more.': 'ग्रामपंचायतीमार्फत सरकारी कल्याणकारी योजनांसाठी अर्ज करा — पीएम आवास योजना, उज्ज्वला योजना, किसान सन्मान निधी आणि बरेच काही.',
        'Apply for central and state government welfare schemes through the Gram Panchayat. Upload your documents and track your application status online.': 'ग्रामपंचायतीमार्फत केंद्र आणि राज्य सरकारच्या कल्याणकारी योजनांसाठी अर्ज करा. कागदपत्रे अपलोड करा आणि ऑनलाइन स्थितीचा मागोवा घ्या.',
        'Avg. Enrollment': 'सरासरी नावनोंदणी वेळ',
        '10-15 Days': '10-15 दिवस',
        'Welfare Programs': 'कल्याणकारी कार्यक्रम',
        'Schemes': 'योजना',
        'Welfare Schemes': 'कल्याणकारी योजना',
        'Back to Certificate Services': 'प्रमाणपत्र सेवांकडे परत',
        'Statutory Civic Service': 'वैधानिक नागरी सेवा',
        'Application': 'अर्ज',
        'Fields marked': 'ज्या फील्डवर',
        'are required. A unique request number will be generated on submission.': 'खूण आहे ते आवश्यक आहेत. सबमिशन केल्यावर एक अद्वितीय विनंती क्रमांक व्युत्पन्न केला जाईल.',
        'Statutory SLA': 'वैधानिक SLA',
        '15 Working Days': '15 कामकाजाचे दिवस',
        'Applicant Details': 'अर्जदाराचे तपशील',
        'Applicant Name': 'अर्जदाराचे नाव',
        'Select': 'निवडा',
        'Date of Birth': 'जन्मतारीख',
        'Place of Birth': 'जन्मस्थान',
        'e.g. Shivaji Hospital': 'उदा. शिवाजी हॉस्पिटल',
        'Gender': 'लिंग',
        'Male': 'पुरुष',
        'Female': 'स्त्री',
        'Father\'s Name': 'वडिलांचे नाव',
        'Mother\'s Name': 'आईचे नाव',
        'Deceased\'s Full Name': 'मृताचे पूर्ण नाव',
        'Date of Death': 'मृत्यूची तारीख',
        'Relation to Deceased': 'मृताशी नाते',
        'e.g. Son, Daughter': 'उदा. मुलगा, मुलगी',
        'Place of Death': 'मृत्यूचे ठिकाण',
        'Cause of Death': 'मृत्यूचे कारण',
        'Full Residential Address': 'पूर्ण रहिवासी पत्ता',
        'House No., Street, Village, Taluka, District': 'घर क्र., रस्ता, गाव, तालुका, जिल्हा',
        'Resident Since': 'रहिवासी कधीपासून',
        'e.g. 2005 or Birth': 'उदा. 2005 किंवा जन्म',
        'Purpose of Certificate': 'प्रमाणपत्राचा उद्देश',
        'e.g. School admission, Employment': 'उदा. शालेय प्रवेश, रोजगार',
        'Aadhaar Last 4 Digits': 'आधार शेवटचे 4 अंक',
        'e.g. 5678': 'उदा. 5678',
        'Supporting Document': 'सहाय्यक दस्तऐवज',
        '(optional)': '(ऐच्छिक)',
        'Upload a scanned copy of your identity proof (Aadhaar, Voter ID) or supporting document. Accepted formats: JPG, PNG, WebP, PDF. Max 5 MB.': 'तुमच्या ओळख पुराव्याची (आधार, मतदार ओळखपत्र) किंवा सहाय्यक दस्तऐवजाची स्कॅन केलेली प्रत अपलोड करा. स्वीकृत स्वरूप: JPG, PNG, WebP, PDF. कमाल 5 MB.',
        'Blocked — Clear Dues First': 'अवरोधित — प्रथम थकबाकी भरा',
        'Submit Application': 'अर्ज सादर करा',
        'Gram Panchayat Helpdesk': 'ग्रामपंचायत मदत कक्ष',
        'Timings:': 'वेळा:',
        '10 AM to 5 PM': 'सकाळी 10 ते संध्याकाळी 5',
        'Contact:': 'संपर्क:',
        'Before You Submit': 'सबमिट करण्यापूर्वी',
        'Verify all spellings precisely match your Aadhaar card.': 'सर्व स्पेलिंग्ज तुमच्या आधार कार्डशी तंतोतंत जुळत असल्याचे पडताळून पहा.',
        'A valid phone number is required for SMS updates.': 'SMS अपडेटसाठी वैध फोन नंबर आवश्यक आहे.',
        'Ensure supporting documents are legible and under 5 MB.': 'सहाय्यक कागदपत्रे वाचण्यायोग्य आणि 5 MB पेक्षा कमी असल्याची खात्री करा.',
        'Back to Permission Services': 'परवानगी सेवांकडे परत',
        'Application form for': 'यासाठी अर्ज',
        'from the Gram Panchayat.': 'ग्रामपंचायतीकडून.',
        'Location &amp; Plot Details': 'स्थान आणि प्लॉट तपशील',
        'Survey / Gut Number': 'सर्वे / गट क्रमांक',
        'e.g. Gut No. 45': 'उदा. गट क्र. ४५',
        'Plot Area (sq. ft)': 'प्लॉट क्षेत्र (चौ. फूट)',
        'e.g. 1500': 'उदा. १५००',
        'Proposed Construction Details': 'प्रस्तावित बांधकाम तपशील',
        'e.g. G+1 Residential House': 'उदा. G+1 निवासी घर',
        'Property No. (if existing)': 'मालमत्ता क्र. (असल्यास)',
        'e.g. 1045': 'उदा. १०४5',
        'Required Pipe Size': 'आवश्यक पाईप आकार',
        '0.5 inch (Domestic)': '०.५ इंच (घरगुती)',
        '1.0 inch (Commercial)': '१.० इंच (व्यावसायिक)',
        'Back to Government Schemes': 'सरकारी योजनांकडे परत',
        'Upload a scanned copy of the required eligibility document (e.g., Ration card, 7/12 extract). Accepted formats: JPG, PNG, WebP, PDF. Max 5 MB.': 'पात्रता दस्तऐवजाची (उदा., शिधापत्रिका, 7/12 उतारा) स्कॅन केलेली प्रत अपलोड करा. स्वीकृत स्वरूप: JPG, PNG, WebP, PDF. कमाल 5 MB.',
        'Bank Account details must match the applicant\'s name.': 'बँक खात्याचा तपशील अर्जदाराच्या नावाशी जुळला पाहिजे.',
        'Tax Records': 'कर रेकॉर्ड',
        'Due Date': 'नियत तारीख',
        'Pay Now': 'आता भरा',
        'Paid': 'भरले',
        'Payment History': 'पेमेंट इतिहास',
        'Receipt No.': 'पावती क्र.',
        'Year': 'वर्ष',
        'Amount Paid': 'भरलेली रक्कम',
        'Method': 'पद्धत',
        'Paid On': 'भरल्याची तारीख',
        'Receipt': 'पावती',
        'No tax records yet.': 'अद्याप कोणतेही कर रेकॉर्ड नाही.',
        'No properties registered': 'कोणत्याही मालमत्ता नोंदणीकृत नाहीत',
        'Contact the Gram Panchayat office to link a property to your account.': 'तुमच्या खात्याशी मालमत्ता लिंक करण्यासाठी ग्रामपंचायत कार्यालयाशी संपर्क साधा.',
        'Payment gateway not configured': 'पेमेंट गेटवे कॉन्फिगर केलेला नाही',
    }
}


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(
            app.config['DATABASE'],
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def ensure_schema():
    """Idempotent schema migrations applied on every startup."""
    db_path = app.config['DATABASE']
    if not os.path.exists(db_path):
        return
    conn = sqlite3.connect(db_path)
    # 1. resolution_photo_path on complaints
    existing_cols = {row[1] for row in conn.execute('PRAGMA table_info(complaints)').fetchall()}
    if 'resolution_photo_path' not in existing_cols:
        conn.execute('ALTER TABLE complaints ADD COLUMN resolution_photo_path TEXT')
    # 2. notices table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS notices (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title      TEXT NOT NULL,
            body       TEXT NOT NULL,
            posted_by  INTEGER NOT NULL,
            is_active  INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # 3. service_requests table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS service_requests (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            request_no      VARCHAR(50) UNIQUE NOT NULL,
            user_id         INTEGER NOT NULL,
            service_type    VARCHAR(50) NOT NULL,
            sub_type        VARCHAR(50) NOT NULL,
            applicant_name  VARCHAR(100) NOT NULL,
            ward            VARCHAR(20) NOT NULL,
            form_data_json  TEXT,
            document_path   VARCHAR(255),
            status          VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            remarks         TEXT,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT
        )
    ''')
    # 4. properties table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS properties (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            property_no     VARCHAR(50) UNIQUE NOT NULL,
            owner_id        INTEGER NOT NULL,
            ward            VARCHAR(20) NOT NULL,
            property_type   VARCHAR(50) NOT NULL,
            area_sqft       REAL NOT NULL,
            address         TEXT NOT NULL,
            assessed_value  REAL NOT NULL,
            registered_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            status          VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
            FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE RESTRICT
        )
    ''')
    # 5. tax_records table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS tax_records (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            property_id     INTEGER NOT NULL,
            tax_type        VARCHAR(30) NOT NULL,
            financial_year  VARCHAR(10) NOT NULL,
            amount_due      REAL NOT NULL,
            due_date        DATE NOT NULL,
            status          VARCHAR(20) NOT NULL DEFAULT 'UNPAID',
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (property_id, tax_type, financial_year),
            FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE CASCADE
        )
    ''')
    # 6. payments table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            tax_record_id       INTEGER NOT NULL,
            payer_id            INTEGER NOT NULL,
            amount_paid         REAL NOT NULL,
            payment_method      VARCHAR(30),
            razorpay_order_id   VARCHAR(100),
            razorpay_payment_id VARCHAR(100),
            payment_status      VARCHAR(20) NOT NULL DEFAULT 'CREATED',
            paid_at             DATETIME,
            receipt_no          VARCHAR(50) UNIQUE,
            FOREIGN KEY (tax_record_id) REFERENCES tax_records(id) ON DELETE CASCADE,
            FOREIGN KEY (payer_id) REFERENCES users(id) ON DELETE RESTRICT
        )
    ''')
    conn.commit()
    conn.close()


# Apply schema migrations on module load.
ensure_schema()

# Ensure docs upload directory exists.
DOCS_UPLOAD_DIR = os.path.join(app.config['UPLOAD_FOLDER'], 'docs')
os.makedirs(DOCS_UPLOAD_DIR, exist_ok=True)


@app.context_processor
def inject_globals():
    unread = 0
    if 'user_id' in session and session.get('role') == 'villager':
        db = get_db()
        row = db.execute(
            'SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0',
            (session['user_id'],)
        ).fetchone()
        unread = row[0]
    lang  = session.get('lang', 'en')
    trans = TRANSLATIONS.get(lang, {})
    def _(text):
        return trans.get(text, text)
    return {'unread_count': unread, '_': _, 'lang': lang}


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            flash('This page is restricted to administrators.', 'danger')
            return redirect(url_for('villager_dashboard'))
        return f(*args, **kwargs)
    return decorated


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def allowed_doc(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in DOC_EXTENSIONS


def save_photo(file):
    ext = secure_filename(file.filename).rsplit('.', 1)[1].lower()
    filename = f'{uuid.uuid4().hex}.{ext}'
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    return filename


def save_document(file):
    """Save uploaded proof document to static/uploads/docs/."""
    ext = secure_filename(file.filename).rsplit('.', 1)[1].lower()
    filename = f'{uuid.uuid4().hex}.{ext}'
    file.save(os.path.join(DOCS_UPLOAD_DIR, filename))
    return filename


def generate_complaint_id(db):
    year   = datetime.now().year
    prefix = f'VCMS-{year}-'
    last   = db.execute(
        'SELECT complaint_id FROM complaints WHERE complaint_id LIKE ? ORDER BY id DESC LIMIT 1',
        (prefix + '%',)
    ).fetchone()
    num = 1 if last is None else int(last['complaint_id'].split('-')[-1]) + 1
    return f'{prefix}{num:04d}'


def generate_request_no(db):
    """Auto-generate service request numbers as REQ-2026-XXXX."""
    year   = datetime.now().year
    prefix = f'REQ-{year}-'
    last   = db.execute(
        'SELECT request_no FROM service_requests WHERE request_no LIKE ? ORDER BY id DESC LIMIT 1',
        (prefix + '%',)
    ).fetchone()
    num = 1 if last is None else int(last['request_no'].split('-')[-1]) + 1
    return f'{prefix}{num:04d}'


def generate_property_no(db):
    """Auto-generate property numbers as EGS-PROP-2026-XXXX."""
    year   = datetime.now().year
    prefix = f'EGS-PROP-{year}-'
    last   = db.execute(
        'SELECT property_no FROM properties WHERE property_no LIKE ? ORDER BY id DESC LIMIT 1',
        (prefix + '%',)
    ).fetchone()
    num = 1 if last is None else int(last['property_no'].split('-')[-1]) + 1
    return f'{prefix}{num:04d}'


def generate_receipt_no(db):
    """Auto-generate payment receipt numbers as EGS-RCPT-2026-XXXX."""
    year   = datetime.now().year
    prefix = f'EGS-RCPT-{year}-'
    last   = db.execute(
        'SELECT receipt_no FROM payments WHERE receipt_no LIKE ? ORDER BY id DESC LIMIT 1',
        (prefix + '%',)
    ).fetchone()
    num = 1 if last is None else int(last['receipt_no'].split('-')[-1]) + 1
    return f'{prefix}{num:04d}'


def refresh_overdue_statuses(db):
    """Lazy OVERDUE detection: flip UNPAID → OVERDUE when due_date has passed.
    Call this at the start of any route that displays tax records."""
    db.execute('''
        UPDATE tax_records SET status = 'OVERDUE'
        WHERE status = 'UNPAID' AND due_date < date('now')
    ''')
    db.commit()


def get_unpaid_dues(db, user_id):
    """Return list of UNPAID/OVERDUE tax records for properties owned by user_id.
    Calls refresh_overdue_statuses() first so the check is current.
    Returns empty list if the user owns no properties or all dues are clear."""
    refresh_overdue_statuses(db)
    rows = db.execute('''
        SELECT p.property_no, tr.tax_type, tr.financial_year, tr.amount_due
        FROM tax_records tr
        JOIN properties p ON tr.property_id = p.id
        WHERE p.owner_id = ? AND tr.status IN ('UNPAID', 'OVERDUE')
        ORDER BY tr.financial_year, tr.tax_type
    ''', (user_id,)).fetchall()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════
# Index / Home
# ══════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    if session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))
    db = get_db()
    rows = db.execute(
        'SELECT * FROM notices WHERE is_active = 1 ORDER BY created_at DESC LIMIT 10'
    ).fetchall()
    notices = [{**dict(r), 'created_at': str(r['created_at'])} for r in rows]
    return render_template('index.html', notices=notices)


# ── Language toggle ────────────────────────────────────────────────

@app.route('/set-lang/<lang>')
def set_lang(lang):
    if lang in ('en', 'mr'):
        session['lang'] = lang
    return redirect(request.referrer or url_for('index'))


# ══════════════════════════════════════════════════════════════════
# Authentication
# ══════════════════════════════════════════════════════════════════

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))
    if request.method == 'POST':
        mobile   = request.form['mobile'].strip()
        password = request.form['password']
        db       = get_db()
        user     = db.execute(
            'SELECT * FROM users WHERE mobile = ?', (mobile,)
        ).fetchone()
        if user is None or not check_password_hash(user['password_hash'], password):
            flash('Incorrect mobile number or password.', 'danger')
            return render_template('auth/login.html')
        session.clear()
        session['user_id']   = user['id']
        session['role']      = user['role']
        session['full_name'] = user['full_name']
        session['ward']      = user['ward']
        dest = 'admin_dashboard' if user['role'] == 'admin' else 'villager_dashboard'
        return redirect(url_for(dest))
    return render_template('auth/login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('index'))
    if request.method == 'POST':
        full_name = request.form['full_name'].strip()
        mobile    = request.form['mobile'].strip()
        ward      = request.form['ward']
        password  = request.form['password']
        confirm   = request.form['confirm_password']
        error = None
        if not full_name:
            error = 'Full name is required.'
        elif not mobile.isdigit() or len(mobile) != 10:
            error = 'Enter a valid 10-digit mobile number.'
        elif ward not in WARDS:
            error = 'Please select a valid ward.'
        elif len(password) < 6:
            error = 'Password must be at least 6 characters long.'
        elif password != confirm:
            error = 'Passwords do not match.'
        if error is None:
            db = get_db()
            if db.execute('SELECT id FROM users WHERE mobile = ?', (mobile,)).fetchone():
                error = 'This mobile number is already registered.'
        if error:
            flash(error, 'danger')
            return render_template('auth/register.html', wards=WARDS, form=request.form)
        db.execute(
            "INSERT INTO users (full_name, mobile, ward, password_hash, role) VALUES (?, ?, ?, ?, 'villager')",
            (full_name, mobile, ward, generate_password_hash(password))
        )
        db.commit()
        flash('Registration successful. You can now log in.', 'success')
        return redirect(url_for('login'))
    return render_template('auth/register.html', wards=WARDS, form={})


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# ══════════════════════════════════════════════════════════════════
# QR Code: dynamic PNG for any complaint or certificate
# ══════════════════════════════════════════════════════════════════

def _generate_qr_png(data_url, fill='#1a3a5c'):
    """Return a BytesIO PNG buffer containing a QR code for data_url."""
    try:
        import qrcode as qrlib
    except ImportError:
        return None
    qr = qrlib.QRCode(version=1, box_size=7, border=3,
                      error_correction=qrlib.constants.ERROR_CORRECT_M)
    qr.add_data(data_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color=fill, back_color='white')
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


@app.route('/complaint/<complaint_id>/qr.png')
def complaint_qr(complaint_id):
    url = url_for('complaint_detail', complaint_id=complaint_id, _external=True)
    buf = _generate_qr_png(url)
    if buf is None:
        return 'qrcode library not installed', 503
    return send_file(buf, mimetype='image/png', max_age=300)


@app.route('/certificate/<request_no>/qr.png')
def certificate_qr(request_no):
    url = url_for('certificate_download', request_no=request_no, _external=True)
    buf = _generate_qr_png(url, fill='#065f46')
    if buf is None:
        return 'qrcode library not installed', 503
    return send_file(buf, mimetype='image/png', max_age=300)


# ══════════════════════════════════════════════════════════════════
# Villager: Dashboard (complaints + service requests)
# ══════════════════════════════════════════════════════════════════

@app.route('/villager/dashboard')
@login_required
def villager_dashboard():
    db = get_db()
    complaints = db.execute('''
        SELECT id, complaint_id, category, ward, address_detail,
               status, priority, created_at, resolved_at
        FROM complaints WHERE user_id = ?
        ORDER BY created_at DESC
    ''', (session['user_id'],)).fetchall()
    counts = {
        'total':       len(complaints),
        'pending':     sum(1 for c in complaints if c['status'] == 'Pending'),
        'in_progress': sum(1 for c in complaints if c['status'] == 'In Progress'),
        'resolved':    sum(1 for c in complaints if c['status'] == 'Resolved'),
    }
    # Service requests for "My Applications" tab
    svc_rows = db.execute('''
        SELECT * FROM service_requests WHERE user_id = ? ORDER BY created_at DESC
    ''', (session['user_id'],)).fetchall()
    svc_requests = [{**dict(r), 'created_at': str(r['created_at'])} for r in svc_rows]
    return render_template('villager/dashboard.html',
                           complaints=complaints, counts=counts,
                           svc_requests=svc_requests)


# ══════════════════════════════════════════════════════════════════
# Villager: File New Complaint
# ══════════════════════════════════════════════════════════════════

@app.route('/complaint/new', methods=['GET', 'POST'])
@login_required
def new_complaint():
    if request.method == 'POST':
        category       = request.form['category']
        ward           = request.form['ward']
        description    = request.form['description'].strip()
        address_detail = request.form.get('address_detail', '').strip() or None
        latitude       = request.form.get('latitude') or None
        longitude      = request.form.get('longitude') or None
        error = None
        if category not in CATEGORIES:
            error = 'Please select a valid category.'
        elif ward not in WARDS:
            error = 'Please select a valid ward.'
        elif len(description) < 20:
            error = 'Please describe the issue in at least 20 characters.'
        photo_filename = None
        if error is None:
            photo = request.files.get('photo')
            if photo and photo.filename:
                if allowed_file(photo.filename):
                    photo_filename = save_photo(photo)
                else:
                    error = 'Only JPG, PNG, or WebP images are accepted.'
        if error:
            flash(error, 'danger')
            return render_template('villager/new_complaint.html', form=request.form)
        db  = get_db()
        cid = generate_complaint_id(db)
        db.execute('''
            INSERT INTO complaints
              (complaint_id, user_id, category, description, ward,
               address_detail, latitude, longitude, photo_path, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending')
        ''', (cid, session['user_id'], category, description, ward,
              address_detail, latitude, longitude, photo_filename))
        new_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.execute(
            'INSERT INTO status_logs (complaint_id, old_status, new_status, changed_by, note) VALUES (?, NULL, ?, ?, ?)',
            (new_id, 'Pending', session['user_id'], 'Complaint registered by resident.')
        )
        db.execute(
            'INSERT INTO notifications (user_id, complaint_id, message) VALUES (?, ?, ?)',
            (session['user_id'], new_id, f'Your complaint {cid} has been submitted and is Pending review.')
        )
        db.commit()
        flash(f'Complaint {cid} submitted successfully.', 'success')
        return redirect(url_for('complaint_detail', complaint_id=cid))
    return render_template('villager/new_complaint.html',
                           form={'ward': session.get('ward', ''),
                                 'category': '', 'description': ''})


# ══════════════════════════════════════════════════════════════════
# Villager: Complaint Detail + Timeline
# ══════════════════════════════════════════════════════════════════

@app.route('/complaint/<complaint_id>')
@login_required
def complaint_detail(complaint_id):
    db = get_db()
    complaint = db.execute('''
        SELECT c.*, u.full_name AS filer_name
        FROM complaints c JOIN users u ON c.user_id = u.id
        WHERE c.complaint_id = ? AND c.user_id = ?
    ''', (complaint_id, session['user_id'])).fetchone()
    if complaint is None:
        flash('Complaint not found or you do not have access to it.', 'danger')
        return redirect(url_for('villager_dashboard'))
    logs = db.execute('''
        SELECT sl.old_status, sl.new_status, sl.note, sl.changed_at,
               u.full_name AS changed_by_name
        FROM status_logs sl JOIN users u ON sl.changed_by = u.id
        WHERE sl.complaint_id = ? ORDER BY sl.changed_at ASC
    ''', (complaint['id'],)).fetchall()
    feedback_row = db.execute(
        'SELECT * FROM feedback WHERE complaint_id = ?', (complaint['id'],)
    ).fetchone()
    return render_template('villager/complaint_detail.html',
                           complaint=complaint, logs=logs, feedback_row=feedback_row)


# ── Villager: Submit Feedback ──────────────────────────────────────

@app.route('/complaint/<complaint_id>/feedback', methods=['POST'])
@login_required
def submit_feedback(complaint_id):
    db = get_db()
    complaint = db.execute(
        'SELECT id, status FROM complaints WHERE complaint_id = ? AND user_id = ?',
        (complaint_id, session['user_id'])
    ).fetchone()
    if complaint is None or complaint['status'] != 'Resolved':
        flash('Feedback can only be submitted for your resolved complaints.', 'warning')
        return redirect(url_for('complaint_detail', complaint_id=complaint_id))
    if db.execute('SELECT id FROM feedback WHERE complaint_id = ?', (complaint['id'],)).fetchone():
        flash('You have already submitted feedback for this complaint.', 'info')
        return redirect(url_for('complaint_detail', complaint_id=complaint_id))
    rating = request.form.get('rating', '')
    if not rating.isdigit() or not (1 <= int(rating) <= 5):
        flash('Please select a rating between 1 and 5.', 'danger')
        return redirect(url_for('complaint_detail', complaint_id=complaint_id))
    comment = request.form.get('comment', '').strip() or None
    db.execute(
        'INSERT INTO feedback (complaint_id, user_id, rating, comment) VALUES (?, ?, ?, ?)',
        (complaint['id'], session['user_id'], int(rating), comment)
    )
    db.commit()
    flash('Thank you for your feedback!', 'success')
    return redirect(url_for('complaint_detail', complaint_id=complaint_id))


# ══════════════════════════════════════════════════════════════════
# Villager: Certificate Services
# ══════════════════════════════════════════════════════════════════

@app.route('/services/certificates')
@login_required
def certificate_services():
    db = get_db()
    unpaid_dues = get_unpaid_dues(db, session['user_id'])
    return render_template('villager/certificates.html', unpaid_dues=unpaid_dues)


@app.route('/services/certificates/apply/<sub_type>', methods=['GET', 'POST'])
@login_required
def certificate_apply(sub_type):
    sub_type = sub_type.upper()
    if sub_type not in CERTIFICATE_TYPES:
        flash('Invalid certificate type.', 'danger')
        return redirect(url_for('certificate_services'))

    if request.method == 'POST':
        applicant_name = request.form.get('applicant_name', '').strip()
        ward           = request.form.get('ward', '')
        error = None
        if not applicant_name:
            error = 'Applicant name is required.'
        elif ward not in WARDS:
            error = 'Please select a valid ward.'

        # Build form_data_json from sub-type–specific fields
        form_data = {}
        if sub_type == 'BIRTH':
            form_data['date_of_birth']   = request.form.get('date_of_birth', '')
            form_data['place_of_birth']  = request.form.get('place_of_birth', '')
            form_data['father_name']     = request.form.get('father_name', '')
            form_data['mother_name']     = request.form.get('mother_name', '')
            form_data['gender']          = request.form.get('gender', '')
            if not form_data['date_of_birth']:
                error = error or 'Date of birth is required.'
        elif sub_type == 'DEATH':
            form_data['deceased_name']   = request.form.get('deceased_name', '')
            form_data['date_of_death']   = request.form.get('date_of_death', '')
            form_data['place_of_death']  = request.form.get('place_of_death', '')
            form_data['cause_of_death']  = request.form.get('cause_of_death', '')
            form_data['relation']        = request.form.get('relation', '')
            if not form_data['date_of_death']:
                error = error or 'Date of death is required.'
        elif sub_type == 'RESIDENCE':
            form_data['resident_since']  = request.form.get('resident_since', '')
            form_data['full_address']    = request.form.get('full_address', '')
            form_data['purpose']         = request.form.get('purpose', '')
            form_data['aadhaar_last4']   = request.form.get('aadhaar_last4', '')
            if not form_data['full_address']:
                error = error or 'Full address is required.'

        # Document upload
        doc_filename = None
        doc_file = request.files.get('document')
        if doc_file and doc_file.filename:
            if allowed_doc(doc_file.filename):
                doc_filename = save_document(doc_file)
            else:
                error = error or 'Only JPG, PNG, WebP, or PDF documents are accepted.'

        if error:
            flash(error, 'danger')
            return render_template('villager/certificate_form.html',
                                   sub_type=sub_type, form=request.form)

        # ── Tax Clearance Gate ────────────────────────────────────
        db = get_db()
        unpaid = get_unpaid_dues(db, session['user_id'])
        if unpaid:
            dues_detail = '; '.join(
                f"{d['property_no']} — {d['tax_type'].replace('_', ' ').title()} "
                f"{d['financial_year']} (₹{d['amount_due']:,.0f})"
                for d in unpaid
            )
            flash(
                f'Certificate application blocked: you have outstanding tax dues. '
                f'Please clear all dues before applying. Pending: {dues_detail}',
                'danger'
            )
            return render_template('villager/certificate_form.html',
                                   sub_type=sub_type, form=request.form)
        # ──────────────────────────────────────────────────────────

        rno = generate_request_no(db)
        db.execute('''
            INSERT INTO service_requests
              (request_no, user_id, service_type, sub_type, applicant_name,
               ward, form_data_json, document_path, status)
            VALUES (?, ?, 'CERTIFICATE', ?, ?, ?, ?, ?, 'PENDING')
        ''', (rno, session['user_id'], sub_type, applicant_name, ward,
              json.dumps(form_data), doc_filename))
        db.commit()
        flash(f'Application {rno} submitted successfully.', 'success')
        return redirect(url_for('villager_dashboard'))

    # Phase 7.2 — pass dues to template so the UX banner/submit-block renders
    db = get_db()
    unpaid_dues = get_unpaid_dues(db, session['user_id'])
    return render_template('villager/certificate_form.html',
                           sub_type=sub_type,
                           unpaid_dues=unpaid_dues,
                           form={'ward': session.get('ward', ''), 'applicant_name': session.get('full_name', '')})


# ══════════════════════════════════════════════════════════════════
# Certificate Download (HTML page styled as official certificate)
# ══════════════════════════════════════════════════════════════════

@app.route('/certificate/download/<request_no>')
@login_required
def certificate_download(request_no):
    db = get_db()
    sr = db.execute('''
        SELECT sr.*, u.full_name AS filer_name, u.mobile AS filer_mobile
        FROM service_requests sr JOIN users u ON sr.user_id = u.id
        WHERE sr.request_no = ?
    ''', (request_no,)).fetchone()
    if sr is None:
        flash('Certificate not found.', 'danger')
        return redirect(url_for('villager_dashboard'))
    if sr['status'] != 'APPROVED':
        flash('Certificate is not yet approved.', 'warning')
        return redirect(url_for('villager_dashboard'))
    form_data = json.loads(sr['form_data_json']) if sr['form_data_json'] else {}
    return render_template('certificate.html', sr=sr, form_data=form_data)



# ══════════════════════════════════════════════════════════════════
# Villager: Permission Services (Phase 9.1)
# ══════════════════════════════════════════════════════════════════


@app.route('/permissions')
@login_required
def permission_services():
    """Landing page — choose Building or Water Connection permission."""
    return render_template('villager/permissions.html')


@app.route('/permissions/apply/<sub_type>', methods=['GET', 'POST'])
@login_required
def permission_apply(sub_type):
    """Apply for a Building or Water Connection permission."""
    sub_type = sub_type.upper()
    if sub_type not in PERMISSION_TYPES:
        flash('Invalid permission type.', 'danger')
        return redirect(url_for('permission_services'))

    if request.method == 'POST':
        applicant_name = request.form.get('applicant_name', '').strip()
        ward           = request.form.get('ward', '')
        error = None
        if not applicant_name:
            error = 'Applicant name is required.'
        elif ward not in WARDS:
            error = 'Please select a valid ward.'

        # Build form_data_json from sub-type–specific fields
        form_data = {}
        if sub_type == 'BUILDING':
            form_data['plot_no']           = request.form.get('plot_no', '').strip()
            form_data['plot_area_sqft']    = request.form.get('plot_area_sqft', '').strip()
            form_data['construction_type'] = request.form.get('construction_type', '')
            form_data['building_height_m'] = request.form.get('building_height_m', '').strip()
            form_data['architect_name']    = request.form.get('architect_name', '').strip()
            form_data['estimated_cost']    = request.form.get('estimated_cost', '').strip()
            if not form_data['plot_no']:
                error = error or 'Plot number is required.'
            if form_data['construction_type'] not in ('Residential', 'Commercial'):
                error = error or 'Please select a valid construction type.'
        elif sub_type == 'WATER':
            form_data['property_no']        = request.form.get('property_no', '').strip()
            form_data['connection_type']    = request.form.get('connection_type', '')
            form_data['pipe_size_inch']     = request.form.get('pipe_size_inch', '')
            form_data['purpose_description'] = request.form.get('purpose_description', '').strip()
            if form_data['connection_type'] not in ('Domestic', 'Commercial'):
                error = error or 'Please select a valid connection type.'

        # Document upload — reuse existing handler identically
        doc_filename = None
        doc_file = request.files.get('document')
        if doc_file and doc_file.filename:
            if allowed_doc(doc_file.filename):
                doc_filename = save_document(doc_file)
            else:
                error = error or 'Only JPG, PNG, WebP, or PDF documents are accepted.'

        if error:
            flash(error, 'danger')
            return render_template('villager/permission_form.html',
                                   sub_type=sub_type, form=request.form)

        db = get_db()

        # ── Tax Clearance Gate (Phase 9.2) ──────────────────────────────
        unpaid = get_unpaid_dues(db, session['user_id'])
        if unpaid:
            dues_detail = '; '.join(
                f"{d['property_no']} — {d['tax_type'].replace('_', ' ').title()} "
                f"{d['financial_year']} (₹{d['amount_due']:,.0f})"
                for d in unpaid
            )
            flash(
                f'Permission application blocked: you have outstanding tax dues. '
                f'Please clear all dues before applying. Pending: {dues_detail}',
                'danger'
            )
            return render_template('villager/permission_form.html',
                                   sub_type=sub_type, form=request.form,
                                   unpaid_dues=unpaid)
        # ────────────────────────────────────────────────────────

        rno = generate_request_no(db)
        db.execute('''
            INSERT INTO service_requests
              (request_no, user_id, service_type, sub_type, applicant_name,
               ward, form_data_json, document_path, status)
            VALUES (?, ?, 'PERMISSION', ?, ?, ?, ?, ?, 'PENDING')
        ''', (rno, session['user_id'], sub_type, applicant_name, ward,
              json.dumps(form_data), doc_filename))
        db.commit()
        flash(f'Permission application {rno} submitted successfully.', 'success')
        return redirect(url_for('villager_dashboard'))

    # GET: pass unpaid_dues to template so banner and disabled button render.
    db = get_db()
    unpaid_dues = get_unpaid_dues(db, session['user_id'])
    return render_template('villager/permission_form.html',
                           sub_type=sub_type,
                           unpaid_dues=unpaid_dues,
                           form={'ward': session.get('ward', ''),
                                 'applicant_name': session.get('full_name', '')})



# ══════════════════════════════════════════════════════════════════
# Villager: Government Schemes (Phase 10.1 / 10.2)
# ══════════════════════════════════════════════════════════════════


@app.route('/schemes')
@login_required
def scheme_services():
    """Catalog landing page — list all available government schemes."""
    return render_template('villager/schemes.html', schemes=SCHEMES)


@app.route('/schemes/apply/<sub_type>', methods=['GET', 'POST'])
@login_required
def scheme_apply(sub_type):
    """Apply for a government scheme (pmay / ujjwala / kisan_samman)."""
    sub_type = sub_type.lower()
    if sub_type not in SCHEME_TYPES:
        flash('Invalid scheme type.', 'danger')
        return redirect(url_for('scheme_services'))

    scheme = SCHEMES[sub_type]

    if request.method == 'POST':
        applicant_name = request.form.get('applicant_name', '').strip()
        ward           = request.form.get('ward', '')
        error = None
        if not applicant_name:
            error = 'Applicant name is required.'
        elif ward not in WARDS:
            error = 'Please select a valid ward.'

        # Build form_data_json from scheme-specific fields
        form_data = {}
        if sub_type == 'pmay':
            form_data['family_income_annual'] = request.form.get('family_income_annual', '').strip()
            form_data['house_status']         = request.form.get('house_status', '')
            form_data['aadhaar_last4']        = request.form.get('aadhaar_last4', '').strip()
            form_data['bank_account_no']      = request.form.get('bank_account_no', '').strip()
            if form_data['house_status'] not in ('Kachha', 'Pucca', 'None'):
                error = error or 'Please select a valid house status.'
        elif sub_type == 'ujjwala':
            form_data['family_income_annual']    = request.form.get('family_income_annual', '').strip()
            form_data['existing_lpg_connection'] = request.form.get('existing_lpg_connection', '')
            form_data['aadhaar_last4']           = request.form.get('aadhaar_last4', '').strip()
            if form_data['existing_lpg_connection'] not in ('Yes', 'No'):
                error = error or 'Please indicate whether an LPG connection already exists.'
        elif sub_type == 'kisan_samman':
            form_data['land_area_acres'] = request.form.get('land_area_acres', '').strip()
            form_data['land_survey_no']  = request.form.get('land_survey_no', '').strip()
            form_data['aadhaar_last4']   = request.form.get('aadhaar_last4', '').strip()
            form_data['bank_account_no'] = request.form.get('bank_account_no', '').strip()
            if not form_data['land_survey_no']:
                error = error or 'Land survey number is required.'

        # Document upload — reuse existing handler identically
        doc_filename = None
        doc_file = request.files.get('document')
        if doc_file and doc_file.filename:
            if allowed_doc(doc_file.filename):
                doc_filename = save_document(doc_file)
            else:
                error = error or 'Only JPG, PNG, WebP, or PDF documents are accepted.'

        if error:
            flash(error, 'danger')
            return render_template('villager/scheme_form.html',
                                   sub_type=sub_type, scheme=scheme, form=request.form)

        db = get_db()

        # ── Tax Clearance Gate (Phase 10.2) ──────────────────────────────
        unpaid = get_unpaid_dues(db, session['user_id'])
        if unpaid:
            dues_detail = '; '.join(
                f"{d['property_no']} — {d['tax_type'].replace('_', ' ').title()} "
                f"{d['financial_year']} (₹{d['amount_due']:,.0f})"
                for d in unpaid
            )
            flash(
                f'Scheme application blocked: you have outstanding tax dues. '
                f'Please clear all dues before applying. Pending: {dues_detail}',
                'danger'
            )
            return render_template('villager/scheme_form.html',
                                   sub_type=sub_type, scheme=scheme,
                                   form=request.form, unpaid_dues=unpaid)
        # ────────────────────────────────────────────────────────────────

        rno = generate_request_no(db)
        db.execute('''
            INSERT INTO service_requests
              (request_no, user_id, service_type, sub_type, applicant_name,
               ward, form_data_json, document_path, status)
            VALUES (?, ?, 'SCHEME', ?, ?, ?, ?, ?, 'PENDING')
        ''', (rno, session['user_id'], sub_type, applicant_name, ward,
              json.dumps(form_data), doc_filename))
        db.commit()
        flash(f'Scheme application {rno} submitted successfully.', 'success')
        return redirect(url_for('villager_dashboard'))

    # GET: pass unpaid_dues to template so banner and disabled button render.
    db = get_db()
    unpaid_dues = get_unpaid_dues(db, session['user_id'])
    return render_template('villager/scheme_form.html',
                           sub_type=sub_type,
                           scheme=scheme,
                           unpaid_dues=unpaid_dues,
                           form={'ward': session.get('ward', ''),
                                 'applicant_name': session.get('full_name', '')})


# ══════════════════════════════════════════════════════════════════

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    db = get_db()
    cat_f    = request.args.get('category', '').strip()
    status_f = request.args.get('status',   '').strip()
    ward_f   = request.args.get('ward',     '').strip()
    query  = '''SELECT c.id, c.complaint_id, c.category, c.ward, c.status,
                       c.priority, c.assigned_to, c.created_at, c.resolved_at,
                       u.full_name AS filer_name
                FROM complaints c JOIN users u ON c.user_id = u.id WHERE 1=1'''
    params = []
    if cat_f:
        query += ' AND c.category = ?'; params.append(cat_f)
    if status_f:
        query += ' AND c.status = ?';   params.append(status_f)
    if ward_f:
        query += ' AND c.ward = ?';     params.append(ward_f)
    query += " ORDER BY CASE WHEN c.priority = 'High' THEN 0 ELSE 1 END, c.created_at DESC"
    complaints = db.execute(query, params).fetchall()
    stats = {
        'total':         db.execute('SELECT COUNT(*) FROM complaints').fetchone()[0],
        'pending':       db.execute("SELECT COUNT(*) FROM complaints WHERE status='Pending'").fetchone()[0],
        'high_priority': db.execute("SELECT COUNT(*) FROM complaints WHERE priority='High'").fetchone()[0],
        'resolved':      db.execute("SELECT COUNT(*) FROM complaints WHERE status='Resolved'").fetchone()[0],
    }
    return render_template('admin/dashboard.html',
                           complaints=complaints, stats=stats,
                           categories=CATEGORIES, wards=WARDS, statuses=STATUSES,
                           filters={'category': cat_f, 'status': status_f, 'ward': ward_f})


# ── Admin: Complaint Detail ────────────────────────────────────────

@app.route('/admin/complaint/<complaint_id>')
@admin_required
def admin_complaint_detail(complaint_id):
    db = get_db()
    complaint = db.execute('''
        SELECT c.*, u.full_name AS filer_name, u.mobile AS filer_mobile
        FROM complaints c JOIN users u ON c.user_id = u.id
        WHERE c.complaint_id = ?
    ''', (complaint_id,)).fetchone()
    if complaint is None:
        flash('Complaint not found.', 'danger')
        return redirect(url_for('admin_dashboard'))
    logs = db.execute('''
        SELECT sl.old_status, sl.new_status, sl.note, sl.changed_at,
               u.full_name AS changed_by_name, u.role AS changed_by_role
        FROM status_logs sl JOIN users u ON sl.changed_by = u.id
        WHERE sl.complaint_id = ? ORDER BY sl.changed_at ASC
    ''', (complaint['id'],)).fetchall()
    feedback_row = db.execute(
        'SELECT * FROM feedback WHERE complaint_id = ?', (complaint['id'],)
    ).fetchone()
    return render_template('admin/complaint_detail.html',
                           complaint=complaint, logs=logs,
                           feedback_row=feedback_row, statuses=STATUSES)


# ── Admin: Update Complaint ────────────────────────────────────────

@app.route('/admin/complaint/<complaint_id>/update', methods=['POST'])
@admin_required
def admin_update_complaint(complaint_id):
    db = get_db()
    complaint = db.execute(
        'SELECT * FROM complaints WHERE complaint_id = ?', (complaint_id,)
    ).fetchone()
    if complaint is None:
        flash('Complaint not found.', 'danger')
        return redirect(url_for('admin_dashboard'))
    new_status  = request.form.get('status', '').strip()
    assigned_to = request.form.get('assigned_to', '').strip() or None
    note        = request.form.get('note', '').strip() or None
    if new_status not in STATUSES:
        flash('Invalid status.', 'danger')
        return redirect(url_for('admin_complaint_detail', complaint_id=complaint_id))
    old_status = complaint['status']
    resolution_photo = complaint['resolution_photo_path']
    photo = request.files.get('resolution_photo')
    if photo and photo.filename and allowed_file(photo.filename):
        resolution_photo = save_photo(photo)
    resolved_at = complaint['resolved_at']
    if new_status == 'Resolved' and old_status != 'Resolved':
        resolved_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    db.execute('''
        UPDATE complaints
        SET status = ?, assigned_to = ?, resolved_at = ?, resolution_photo_path = ?
        WHERE complaint_id = ?
    ''', (new_status, assigned_to, resolved_at, resolution_photo, complaint_id))
    db.execute(
        'INSERT INTO status_logs (complaint_id, old_status, new_status, changed_by, note) VALUES (?, ?, ?, ?, ?)',
        (complaint['id'], old_status, new_status, session['user_id'], note)
    )
    if new_status != old_status:
        db.execute(
            'INSERT INTO notifications (user_id, complaint_id, message) VALUES (?, ?, ?)',
            (complaint['user_id'], complaint['id'],
             f'Your complaint {complaint_id} has been updated to {new_status}.')
        )
    db.commit()
    flash(f'Complaint {complaint_id} updated.', 'success')
    return redirect(url_for('admin_complaint_detail', complaint_id=complaint_id))


# ══════════════════════════════════════════════════════════════════
# Admin: Reports & Analytics
# ══════════════════════════════════════════════════════════════════

@app.route('/admin/reports')
@admin_required
def admin_reports():
    db = get_db()
    by_category = [{'category': r['category'], 'cnt': r['cnt']} for r in
                   db.execute('SELECT category, COUNT(*) AS cnt FROM complaints GROUP BY category ORDER BY cnt DESC').fetchall()]
    by_status   = [{'status': r['status'], 'cnt': r['cnt']} for r in
                   db.execute('SELECT status, COUNT(*) AS cnt FROM complaints GROUP BY status').fetchall()]
    monthly_rows = db.execute(
        "SELECT strftime('%Y-%m', created_at) AS month, COUNT(*) AS cnt FROM complaints GROUP BY month ORDER BY month DESC LIMIT 6"
    ).fetchall()
    monthly_filed = list(reversed([{'month': r['month'], 'cnt': r['cnt']} for r in monthly_rows]))
    avg_row = db.execute(
        "SELECT AVG(julianday(resolved_at) - julianday(created_at)) AS avg_days FROM complaints WHERE status='Resolved' AND resolved_at IS NOT NULL"
    ).fetchone()
    avg_days = round(float(avg_row['avg_days']), 1) if avg_row['avg_days'] else 0
    total    = db.execute('SELECT COUNT(*) FROM complaints').fetchone()[0]
    resolved = db.execute("SELECT COUNT(*) FROM complaints WHERE status='Resolved'").fetchone()[0]
    pending  = db.execute("SELECT COUNT(*) FROM complaints WHERE status='Pending'").fetchone()[0]
    return render_template('admin/reports.html',
                           by_category=by_category, by_status=by_status,
                           monthly_filed=monthly_filed, avg_days=avg_days,
                           total=total, resolved=resolved, pending=pending,
                           resolution_rate=round(resolved / total * 100, 1) if total else 0)


# ══════════════════════════════════════════════════════════════════
# Admin: Notice Board Management
# ══════════════════════════════════════════════════════════════════

@app.route('/admin/notices')
@admin_required
def admin_notices():
    db = get_db()
    rows = db.execute(
        'SELECT n.*, u.full_name AS poster_name FROM notices n JOIN users u ON n.posted_by = u.id ORDER BY n.created_at DESC'
    ).fetchall()
    notices = [{**dict(r), 'created_at': str(r['created_at'])} for r in rows]
    return render_template('admin/notices.html', notices=notices)


@app.route('/admin/notices/new', methods=['POST'])
@admin_required
def admin_post_notice():
    title = request.form.get('title', '').strip()
    body  = request.form.get('body',  '').strip()
    if not title or not body:
        flash('Title and notice text are required.', 'danger')
        return redirect(url_for('admin_notices'))
    db = get_db()
    db.execute(
        'INSERT INTO notices (title, body, posted_by) VALUES (?, ?, ?)',
        (title, body, session['user_id'])
    )
    db.commit()
    flash(f'Notice posted: {title}', 'success')
    return redirect(url_for('admin_notices'))


@app.route('/admin/notice/<int:notice_id>/toggle', methods=['POST'])
@admin_required
def admin_toggle_notice(notice_id):
    db = get_db()
    notice = db.execute('SELECT is_active FROM notices WHERE id = ?', (notice_id,)).fetchone()
    if notice is None:
        flash('Notice not found.', 'danger')
        return redirect(url_for('admin_notices'))
    new_state = 0 if notice['is_active'] else 1
    db.execute('UPDATE notices SET is_active = ? WHERE id = ?', (new_state, notice_id))
    db.commit()
    flash('Notice ' + ('activated.' if new_state else 'deactivated.'), 'success')
    return redirect(url_for('admin_notices'))


# ══════════════════════════════════════════════════════════════════
# Admin: Service Requests Management
# ══════════════════════════════════════════════════════════════════

@app.route('/admin/service-requests')
@admin_required
def admin_service_requests():
    db = get_db()
    status_f = request.args.get('status', '').strip()
    type_f   = request.args.get('sub_type', '').strip()
    query  = '''SELECT sr.*, u.full_name AS filer_name, u.mobile AS filer_mobile
                FROM service_requests sr JOIN users u ON sr.user_id = u.id WHERE 1=1'''
    params = []
    if status_f:
        query += ' AND sr.status = ?'; params.append(status_f)
    if type_f:
        query += ' AND sr.sub_type = ?'; params.append(type_f)
    query += ' ORDER BY sr.created_at DESC'
    rows = db.execute(query, params).fetchall()
    requests_list = [{**dict(r), 'created_at': str(r['created_at']),
                      'updated_at': str(r['updated_at'])} for r in rows]
    stats = {
        'total':    db.execute('SELECT COUNT(*) FROM service_requests').fetchone()[0],
        'pending':  db.execute("SELECT COUNT(*) FROM service_requests WHERE status='PENDING'").fetchone()[0],
        'approved': db.execute("SELECT COUNT(*) FROM service_requests WHERE status='APPROVED'").fetchone()[0],
    }
    return render_template('admin/service_requests.html',
                           requests=requests_list, stats=stats,
                           service_statuses=SERVICE_STATUSES,
                           all_sub_types=CERTIFICATE_TYPES + PERMISSION_TYPES + SCHEME_TYPES,
                           filters={'status': status_f, 'sub_type': type_f})


@app.route('/admin/service-request/<request_no>')
@admin_required
def admin_service_request_detail(request_no):
    db = get_db()
    sr = db.execute('''
        SELECT sr.*, u.full_name AS filer_name, u.mobile AS filer_mobile
        FROM service_requests sr JOIN users u ON sr.user_id = u.id
        WHERE sr.request_no = ?
    ''', (request_no,)).fetchone()
    if sr is None:
        flash('Service request not found.', 'danger')
        return redirect(url_for('admin_service_requests'))
    form_data = json.loads(sr['form_data_json']) if sr['form_data_json'] else {}
    return render_template('admin/service_request_detail.html',
                           sr=sr, form_data=form_data,
                           service_statuses=SERVICE_STATUSES)


@app.route('/admin/service-request/<request_no>/update', methods=['POST'])
@admin_required
def admin_update_service_request(request_no):
    db = get_db()
    sr = db.execute('SELECT * FROM service_requests WHERE request_no = ?', (request_no,)).fetchone()
    if sr is None:
        flash('Service request not found.', 'danger')
        return redirect(url_for('admin_service_requests'))
    new_status = request.form.get('status', '').strip()
    remarks    = request.form.get('remarks', '').strip() or None
    if new_status not in SERVICE_STATUSES:
        flash('Invalid status.', 'danger')
        return redirect(url_for('admin_service_request_detail', request_no=request_no))
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    db.execute('''
        UPDATE service_requests SET status = ?, remarks = ?, updated_at = ? WHERE request_no = ?
    ''', (new_status, remarks, now, request_no))
    db.commit()
    flash(f'Service request {request_no} updated to {new_status}.', 'success')
    return redirect(url_for('admin_service_request_detail', request_no=request_no))


# ══════════════════════════════════════════════════════════════════
# Villager: Property & Tax
# ══════════════════════════════════════════════════════════════════

@app.route('/services/property-tax')
@login_required
def villager_property_tax():
    db = get_db()
    refresh_overdue_statuses(db)
    props = db.execute('''
        SELECT * FROM properties WHERE owner_id = ? ORDER BY registered_at DESC
    ''', (session['user_id'],)).fetchall()
    # For each property, get tax records and payments
    properties_data = []
    for p in props:
        tax_rows = db.execute('''
            SELECT * FROM tax_records WHERE property_id = ? ORDER BY financial_year DESC, tax_type
        ''', (p['id'],)).fetchall()
        pay_rows = db.execute('''
            SELECT py.*, tr.tax_type, tr.financial_year
            FROM payments py JOIN tax_records tr ON py.tax_record_id = tr.id
            WHERE tr.property_id = ? AND py.payment_status = 'SUCCESS'
            ORDER BY py.paid_at DESC
        ''', (p['id'],)).fetchall()
        properties_data.append({
            'property': dict(p),
            'tax_records': [dict(t) for t in tax_rows],
            'payments': [{**dict(py), 'paid_at': str(py['paid_at'])} for py in pay_rows],
        })
    return render_template('villager/property_tax.html',
                           properties_data=properties_data,
                           razorpay_key_id=app.config.get('RAZORPAY_KEY_ID', ''),
                           razorpay_enabled=rzp_client is not None)


# ── Razorpay: Create Order ─────────────────────────────────────────

@app.route('/pay/create-order', methods=['POST'])
@login_required
def pay_create_order():
    """Create a Razorpay order for a tax_record and return order details."""
    if rzp_client is None:
        return jsonify({'error': 'Payment gateway not configured.'}), 503

    tax_record_id = request.form.get('tax_record_id', '')
    if not tax_record_id:
        return jsonify({'error': 'Missing tax_record_id.'}), 400

    db = get_db()
    tr = db.execute('''
        SELECT tr.*, p.owner_id, p.property_no
        FROM tax_records tr JOIN properties p ON tr.property_id = p.id
        WHERE tr.id = ?
    ''', (tax_record_id,)).fetchone()
    if tr is None:
        return jsonify({'error': 'Tax record not found.'}), 404

    # Only the property owner can pay
    if tr['owner_id'] != session['user_id']:
        return jsonify({'error': 'You are not the owner of this property.'}), 403

    # Block duplicate payment
    if tr['status'] == 'PAID':
        return jsonify({'error': 'This tax record has already been paid.'}), 409

    if tr['status'] not in ('UNPAID', 'OVERDUE'):
        return jsonify({'error': f'Cannot pay a record with status {tr["status"]}.'}), 400

    # Create Razorpay order (amount in paise)
    amount_paise = int(round(tr['amount_due'] * 100))
    try:
        rz_order = rzp_client.order.create({
            'amount': amount_paise,
            'currency': 'INR',
            'receipt': f'tax-{tr["id"]}',
            'notes': {
                'property_no': tr['property_no'],
                'tax_type': tr['tax_type'],
                'financial_year': tr['financial_year'],
            }
        })
    except Exception as e:
        return jsonify({'error': f'Razorpay error: {str(e)}'}), 502

    # Insert CREATED payment row
    db.execute('''
        INSERT INTO payments (tax_record_id, payer_id, amount_paid,
                              payment_method, razorpay_order_id, payment_status)
        VALUES (?, ?, ?, 'RAZORPAY_TEST', ?, 'CREATED')
    ''', (tr['id'], session['user_id'], tr['amount_due'], rz_order['id']))
    db.commit()

    return jsonify({
        'order_id': rz_order['id'],
        'amount': amount_paise,
        'currency': 'INR',
        'key_id': app.config['RAZORPAY_KEY_ID'],
        'tax_record_id': tr['id'],
        'description': f'{tr["tax_type"].replace("_"," ").title()} — {tr["financial_year"]} — {tr["property_no"]}',
    })


# ── Razorpay: Verify Payment ───────────────────────────────────────

@app.route('/pay/verify', methods=['POST'])
@login_required
def pay_verify():
    """Verify Razorpay payment signature and finalize."""
    if rzp_client is None:
        flash('Payment gateway not configured.', 'danger')
        return redirect(url_for('villager_property_tax'))

    rz_order_id   = request.form.get('razorpay_order_id', '')
    rz_payment_id = request.form.get('razorpay_payment_id', '')
    rz_signature  = request.form.get('razorpay_signature', '')
    tax_record_id = request.form.get('tax_record_id', '')

    if not all([rz_order_id, rz_payment_id, rz_signature, tax_record_id]):
        flash('Incomplete payment data received.', 'danger')
        return redirect(url_for('villager_property_tax'))

    db = get_db()

    # Find the CREATED payment row
    pay = db.execute('''
        SELECT * FROM payments
        WHERE razorpay_order_id = ? AND payer_id = ? AND payment_status = 'CREATED'
    ''', (rz_order_id, session['user_id'])).fetchone()
    if pay is None:
        flash('Payment record not found or already processed.', 'danger')
        return redirect(url_for('villager_property_tax'))

    # Verify signature server-side (HMAC-SHA256)
    msg = f'{rz_order_id}|{rz_payment_id}'
    expected_sig = hmac.new(
        app.config['RAZORPAY_KEY_SECRET'].encode(),
        msg.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, rz_signature):
        # Signature mismatch → mark FAILED
        db.execute('''
            UPDATE payments SET payment_status = 'FAILED', razorpay_payment_id = ?
            WHERE id = ?
        ''', (rz_payment_id, pay['id']))
        db.commit()
        flash('Payment verification failed. Your payment could not be confirmed. '
              'If money was deducted, it will be refunded automatically.', 'danger')
        return redirect(url_for('villager_property_tax'))

    # ✅ Signature verified — finalize payment
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    receipt_no = generate_receipt_no(db)
    db.execute('''
        UPDATE payments
        SET payment_status = 'SUCCESS', razorpay_payment_id = ?,
            amount_paid = ?, paid_at = ?, receipt_no = ?, payment_method = 'RAZORPAY_TEST'
        WHERE id = ?
    ''', (rz_payment_id, pay['amount_paid'], now, receipt_no, pay['id']))

    # Mark tax record as PAID
    db.execute('UPDATE tax_records SET status = ? WHERE id = ?', ('PAID', pay['tax_record_id']))
    db.commit()

    flash(f'Payment successful! Receipt {receipt_no} generated.', 'success')
    return redirect(url_for('receipt_download', receipt_no=receipt_no))


# ── Receipt download (reuses certificate letterhead pattern) ───────

@app.route('/receipt/download/<receipt_no>')
@login_required
def receipt_download(receipt_no):
    db = get_db()
    pay = db.execute('''
        SELECT py.*, tr.tax_type, tr.financial_year, tr.amount_due,
               p.property_no, p.address, p.ward AS prop_ward, p.property_type,
               u.full_name AS payer_name, u.mobile AS payer_mobile
        FROM payments py
        JOIN tax_records tr ON py.tax_record_id = tr.id
        JOIN properties p ON tr.property_id = p.id
        JOIN users u ON py.payer_id = u.id
        WHERE py.receipt_no = ?
    ''', (receipt_no,)).fetchone()
    if pay is None:
        flash('Receipt not found.', 'danger')
        return redirect(url_for('villager_property_tax'))
    if pay['payment_status'] != 'SUCCESS':
        flash('Receipt is only available for successful payments.', 'warning')
        return redirect(url_for('villager_property_tax'))
    return render_template('receipt.html', pay=pay)


@app.route('/receipt/<receipt_no>/qr.png')
def receipt_qr(receipt_no):
    url = url_for('receipt_download', receipt_no=receipt_no, _external=True)
    buf = _generate_qr_png(url, fill='#1a3a5c')
    if buf is None:
        return 'qrcode library not installed', 503
    return send_file(buf, mimetype='image/png', max_age=300)


# ══════════════════════════════════════════════════════════════════
# Admin: Property Management
# ══════════════════════════════════════════════════════════════════

@app.route('/admin/properties')
@admin_required
def admin_properties():
    db = get_db()
    refresh_overdue_statuses(db)
    ward_f   = request.args.get('ward', '').strip()
    status_f = request.args.get('status', '').strip()
    query = '''SELECT p.*, u.full_name AS owner_name, u.mobile AS owner_mobile
               FROM properties p JOIN users u ON p.owner_id = u.id WHERE 1=1'''
    params = []
    if ward_f:
        query += ' AND p.ward = ?'; params.append(ward_f)
    if status_f:
        query += ' AND p.status = ?'; params.append(status_f)
    query += ' ORDER BY p.registered_at DESC'
    props = db.execute(query, params).fetchall()
    stats = {
        'total':  db.execute('SELECT COUNT(*) FROM properties').fetchone()[0],
        'active': db.execute("SELECT COUNT(*) FROM properties WHERE status='ACTIVE'").fetchone()[0],
    }
    return render_template('admin/properties.html',
                           properties=props, stats=stats, wards=WARDS,
                           property_statuses=PROPERTY_STATUSES,
                           filters={'ward': ward_f, 'status': status_f})


@app.route('/admin/properties/register', methods=['GET', 'POST'])
@admin_required
def admin_register_property():
    db = get_db()
    if request.method == 'POST':
        owner_mobile = request.form.get('owner_mobile', '').strip()
        ward         = request.form.get('ward', '')
        prop_type    = request.form.get('property_type', '')
        area_sqft    = request.form.get('area_sqft', '')
        address      = request.form.get('address', '').strip()
        assessed_val = request.form.get('assessed_value', '')
        error = None
        # Validate owner
        owner = db.execute('SELECT id, full_name FROM users WHERE mobile = ?', (owner_mobile,)).fetchone()
        if owner is None:
            error = f'No user found with mobile number {owner_mobile}.'
        elif ward not in WARDS:
            error = 'Please select a valid ward.'
        elif prop_type not in PROPERTY_TYPES:
            error = 'Please select a valid property type.'
        elif not area_sqft:
            error = 'Area (sq ft) is required.'
        elif not address:
            error = 'Address is required.'
        elif not assessed_val:
            error = 'Assessed value is required.'
        try:
            area_sqft_f  = float(area_sqft) if area_sqft else 0
            assessed_f   = float(assessed_val) if assessed_val else 0
        except ValueError:
            error = error or 'Area and assessed value must be numbers.'
            area_sqft_f = 0
            assessed_f  = 0
        if error:
            flash(error, 'danger')
            return render_template('admin/property_register.html',
                                   form=request.form, wards=WARDS,
                                   property_types=PROPERTY_TYPES)
        pno = generate_property_no(db)
        db.execute('''
            INSERT INTO properties (property_no, owner_id, ward, property_type,
                                    area_sqft, address, assessed_value)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (pno, owner['id'], ward, prop_type, area_sqft_f, address, assessed_f))
        db.commit()
        flash(f'Property {pno} registered to {owner["full_name"]}.', 'success')
        return redirect(url_for('admin_property_detail', property_no=pno))
    return render_template('admin/property_register.html',
                           form={}, wards=WARDS, property_types=PROPERTY_TYPES)


@app.route('/admin/property/<property_no>')
@admin_required
def admin_property_detail(property_no):
    db = get_db()
    refresh_overdue_statuses(db)
    prop = db.execute('''
        SELECT p.*, u.full_name AS owner_name, u.mobile AS owner_mobile
        FROM properties p JOIN users u ON p.owner_id = u.id
        WHERE p.property_no = ?
    ''', (property_no,)).fetchone()
    if prop is None:
        flash('Property not found.', 'danger')
        return redirect(url_for('admin_properties'))
    tax_rows = db.execute('''
        SELECT * FROM tax_records WHERE property_id = ? ORDER BY financial_year DESC, tax_type
    ''', (prop['id'],)).fetchall()
    pay_rows = db.execute('''
        SELECT py.*, tr.tax_type, tr.financial_year
        FROM payments py JOIN tax_records tr ON py.tax_record_id = tr.id
        WHERE tr.property_id = ? ORDER BY py.paid_at DESC
    ''', (prop['id'],)).fetchall()
    return render_template('admin/property_detail.html',
                           prop=prop, tax_records=tax_rows, payments=pay_rows,
                           property_statuses=PROPERTY_STATUSES,
                           tax_types=TAX_TYPES)


@app.route('/admin/property/<property_no>/update', methods=['POST'])
@admin_required
def admin_update_property(property_no):
    db = get_db()
    prop = db.execute('SELECT * FROM properties WHERE property_no = ?', (property_no,)).fetchone()
    if prop is None:
        flash('Property not found.', 'danger')
        return redirect(url_for('admin_properties'))
    new_status = request.form.get('status', '').strip()
    if new_status and new_status in PROPERTY_STATUSES:
        db.execute('UPDATE properties SET status = ? WHERE property_no = ?', (new_status, property_no))
    assessed_val = request.form.get('assessed_value', '').strip()
    if assessed_val:
        try:
            db.execute('UPDATE properties SET assessed_value = ? WHERE property_no = ?',
                       (float(assessed_val), property_no))
        except ValueError:
            flash('Assessed value must be a number.', 'danger')
            return redirect(url_for('admin_property_detail', property_no=property_no))
    db.commit()
    flash(f'Property {property_no} updated.', 'success')
    return redirect(url_for('admin_property_detail', property_no=property_no))


@app.route('/admin/property/<property_no>/add-tax', methods=['POST'])
@admin_required
def admin_add_tax_record(property_no):
    db = get_db()
    prop = db.execute('SELECT id FROM properties WHERE property_no = ?', (property_no,)).fetchone()
    if prop is None:
        flash('Property not found.', 'danger')
        return redirect(url_for('admin_properties'))
    tax_type = request.form.get('tax_type', '').strip()
    fy       = request.form.get('financial_year', '').strip()
    amount   = request.form.get('amount_due', '').strip()
    due_date = request.form.get('due_date', '').strip()
    error = None
    if tax_type not in TAX_TYPES:
        error = 'Please select a valid tax type.'
    elif not fy:
        error = 'Financial year is required (e.g. 2026-27).'
    elif not amount:
        error = 'Amount due is required.'
    elif not due_date:
        error = 'Due date is required.'
    if error:
        flash(error, 'danger')
        return redirect(url_for('admin_property_detail', property_no=property_no))
    try:
        amount_f = float(amount)
    except ValueError:
        flash('Amount must be a number.', 'danger')
        return redirect(url_for('admin_property_detail', property_no=property_no))
    # Respect UNIQUE constraint
    existing = db.execute('''
        SELECT id FROM tax_records WHERE property_id = ? AND tax_type = ? AND financial_year = ?
    ''', (prop['id'], tax_type, fy)).fetchone()
    if existing:
        flash(f'A {tax_type.replace("_", " ").title()} record for {fy} already exists on this property.', 'danger')
        return redirect(url_for('admin_property_detail', property_no=property_no))
    db.execute('''
        INSERT INTO tax_records (property_id, tax_type, financial_year, amount_due, due_date)
        VALUES (?, ?, ?, ?, ?)
    ''', (prop['id'], tax_type, fy, amount_f, due_date))
    db.commit()
    flash(f'{tax_type.replace("_", " ").title()} for {fy} added (₹{amount_f:,.0f}).', 'success')
    return redirect(url_for('admin_property_detail', property_no=property_no))


@app.route('/admin/tax-overview')
@admin_required
def admin_tax_overview():
    db = get_db()
    refresh_overdue_statuses(db)
    status_f = request.args.get('status', '').strip()
    query = '''SELECT tr.*, p.property_no, p.ward, p.address,
                      u.full_name AS owner_name
               FROM tax_records tr
               JOIN properties p ON tr.property_id = p.id
               JOIN users u ON p.owner_id = u.id
               WHERE 1=1'''
    params = []
    if status_f:
        query += ' AND tr.status = ?'; params.append(status_f)
    query += ' ORDER BY tr.due_date DESC'
    rows = db.execute(query, params).fetchall()
    stats = {
        'total':   db.execute('SELECT COUNT(*) FROM tax_records').fetchone()[0],
        'unpaid':  db.execute("SELECT COUNT(*) FROM tax_records WHERE status='UNPAID'").fetchone()[0],
        'overdue': db.execute("SELECT COUNT(*) FROM tax_records WHERE status='OVERDUE'").fetchone()[0],
        'paid':    db.execute("SELECT COUNT(*) FROM tax_records WHERE status='PAID'").fetchone()[0],
        'total_due': db.execute("SELECT COALESCE(SUM(amount_due),0) FROM tax_records WHERE status IN ('UNPAID','OVERDUE')").fetchone()[0],
        'total_collected': db.execute("SELECT COALESCE(SUM(amount_due),0) FROM tax_records WHERE status='PAID'").fetchone()[0],
    }
    return render_template('admin/tax_overview.html',
                           records=rows, stats=stats,
                           tax_statuses=TAX_STATUSES,
                           filters={'status': status_f})



# ══════════════════════════════════════════════════════════════════
# Phase 8 — Nondi (Register) Views  [READ-ONLY, admin only]
# ══════════════════════════════════════════════════════════════════

def _parse_register_filters():
    """Extract ward, date_from, date_to from query params. Returns a dict."""
    return {
        'ward':      request.args.get('ward', '').strip(),
        'date_from': request.args.get('date_from', '').strip(),
        'date_to':   request.args.get('date_to',   '').strip(),
    }


def _build_cert_register_query(sub_type, filters):
    """Return (query_str, params) for birth/death certificate registers."""
    query = '''
        SELECT sr.*, u.full_name AS filer_name
        FROM service_requests sr
        JOIN users u ON sr.user_id = u.id
        WHERE sr.service_type = 'CERTIFICATE'
          AND sr.sub_type = ?
          AND sr.status = 'APPROVED'
    '''
    params = [sub_type]
    if filters['ward']:
        query += ' AND sr.ward = ?'
        params.append(filters['ward'])
    if filters['date_from']:
        query += " AND DATE(sr.updated_at) >= ?"
        params.append(filters['date_from'])
    if filters['date_to']:
        query += " AND DATE(sr.updated_at) <= ?"
        params.append(filters['date_to'])
    query += ' ORDER BY sr.created_at DESC'
    return query, params


def _build_property_register_query(filters):
    """Return (query_str, params) for the property (Malmatta) register."""
    query = '''
        SELECT p.*, u.full_name AS owner_name
        FROM properties p
        JOIN users u ON p.owner_id = u.id
        WHERE 1=1
    '''
    params = []
    if filters['ward']:
        query += ' AND p.ward = ?'
        params.append(filters['ward'])
    if filters['date_from']:
        query += " AND DATE(p.registered_at) >= ?"
        params.append(filters['date_from'])
    if filters['date_to']:
        query += " AND DATE(p.registered_at) <= ?"
        params.append(filters['date_to'])
    query += ' ORDER BY p.property_no ASC'
    return query, params


@app.route('/admin/registers/birth')
@admin_required
def admin_register_birth():
    """Birth Register (Janma Nondi) — APPROVED birth certificate requests."""
    db      = get_db()
    filters = _parse_register_filters()
    query, params = _build_cert_register_query('BIRTH', filters)
    rows = db.execute(query, params).fetchall()
    # Parse form_data_json per row to surface date_of_birth for display
    records = []
    for r in rows:
        fd = json.loads(r['form_data_json']) if r['form_data_json'] else {}
        records.append({**dict(r), 'form_data': fd})
    return render_template('admin/register_birth.html',
                           records=records, filters=filters, wards=WARDS)


@app.route('/admin/registers/death')
@admin_required
def admin_register_death():
    """Death Register (Mrutyu Nondi) — APPROVED death certificate requests."""
    db      = get_db()
    filters = _parse_register_filters()
    query, params = _build_cert_register_query('DEATH', filters)
    rows = db.execute(query, params).fetchall()
    records = []
    for r in rows:
        fd = json.loads(r['form_data_json']) if r['form_data_json'] else {}
        records.append({**dict(r), 'form_data': fd})
    return render_template('admin/register_death.html',
                           records=records, filters=filters, wards=WARDS)


@app.route('/admin/registers/property')
@admin_required
def admin_register_property_nondi():
    """Property Register (Malmatta Nondi) — all registered properties."""
    db      = get_db()
    filters = _parse_register_filters()
    query, params = _build_property_register_query(filters)
    rows    = db.execute(query, params).fetchall()
    records = [dict(r) for r in rows]
    return render_template('admin/register_property.html',
                           records=records, filters=filters, wards=WARDS)


@app.route('/admin/registers/<register_type>/print')
@admin_required
def admin_register_print(register_type):
    """Print view for all three registers — standalone page, no base.html."""
    if register_type not in ('birth', 'death', 'property'):
        flash('Invalid register type.', 'danger')
        return redirect(url_for('admin_register_birth'))
    db      = get_db()
    filters = _parse_register_filters()
    records = []
    if register_type in ('birth', 'death'):
        sub_type = register_type.upper()
        query, params = _build_cert_register_query(sub_type, filters)
        rows = db.execute(query, params).fetchall()
        for r in rows:
            fd = json.loads(r['form_data_json']) if r['form_data_json'] else {}
            records.append({**dict(r), 'form_data': fd})
    else:
        query, params = _build_property_register_query(filters)
        rows = db.execute(query, params).fetchall()
        records = [dict(r) for r in rows]
    type_labels = {
        'birth':    ('Janma Nondi', 'Birth Register'),
        'death':    ('Mrutyu Nondi', 'Death Register'),
        'property': ('Malmatta Nondi', 'Property Register'),
    }
    label_mr, label_en = type_labels[register_type]
    printed_on = datetime.now().strftime('%d %B %Y')
    return render_template('admin/register_print.html',
                           records=records, filters=filters,
                           register_type=register_type,
                           label_mr=label_mr, label_en=label_en,
                           printed_on=printed_on)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5050)
