/* Blinks Bright — translation catalog (Thai / English).

   One flat object keyed by a dot-string; each value is `{en, th}`. Read through
   `t(key, vars)` in i18n.js. Keys are grouped by namespace only for readability —
   the object is flat. Generic words live under `common.*`; reuse them rather than
   minting near-duplicates. Data values (customer names, treatment names, chat
   text) are NOT translated — only UI chrome is. */

import dash from './locales/dash.js';
import conv from './locales/conv.js';
import cust from './locales/cust.js';
import book from './locales/book.js';
import team from './locales/team.js';
import payments from './locales/payments.js';
import treat from './locales/treat.js';
import kb from './locales/kb.js';
import retn from './locales/retn.js';
import anl from './locales/anl.js';
import chatanl from './locales/chatanl.js';
import bcast from './locales/bcast.js';
import settings from './locales/settings.js';
import test from './locales/test.js';
import sysdash from './locales/sysdash.js';
import sysclin from './locales/sysclin.js';
import sysusers from './locales/sysusers.js';
import auth from './locales/auth.js';
import picker from './locales/picker.js';

/* Shared/common seed — generic words, navigation, shell, menus, roles, pay, time. */
const SEED = {
  /* ---------------- common (generic, reused everywhere) ---------------- */
  'common.save': { th: 'บันทึก', en: 'Save' },
  'common.cancel': { th: 'ยกเลิก', en: 'Cancel' },
  'common.close': { th: 'ปิด', en: 'Close' },
  'common.delete': { th: 'ลบ', en: 'Delete' },
  'common.edit': { th: 'แก้ไข', en: 'Edit' },
  'common.add': { th: 'เพิ่ม', en: 'Add' },
  'common.confirm': { th: 'ยืนยัน', en: 'Confirm' },
  'common.remove': { th: 'นำออก', en: 'Remove' },
  'common.upload': { th: 'อัปโหลด', en: 'Upload' },
  'common.loading': { th: 'กำลังโหลด…', en: 'Loading…' },
  'common.loadFailed': { th: 'โหลดข้อมูลไม่สำเร็จ', en: 'Could not load data' },
  'common.saved': { th: 'บันทึกแล้ว', en: 'Saved' },
  'common.saveFailed': { th: 'บันทึกไม่สำเร็จ', en: 'Save failed' },
  'common.deleted': { th: 'ลบแล้ว', en: 'Deleted' },
  'common.deleteFailed': { th: 'ลบไม่สำเร็จ', en: 'Delete failed' },
  'common.updated': { th: 'อัปเดตแล้ว', en: 'Updated' },
  'common.updateFailed': { th: 'อัปเดตไม่สำเร็จ', en: 'Update failed' },
  'common.noData': { th: 'ไม่มีข้อมูล', en: 'No data' },
  'common.optional': { th: '(ไม่บังคับ)', en: '(optional)' },
  'common.projectNote': {
    th: 'เว็บไซต์นี้เป็นส่วนหนึ่งของโครงงานวิชา 06048308 Intelligent Chatbot Development ข้อมูลคลินิก แพทย์ ราคา และโปรโมชันทั้งหมดเป็น<strong>ข้อมูลจำลอง</strong> เพื่อการเรียนการสอน ไม่ใช่ธุรกิจจริง',
    en: 'This website is part of a project for course 06048308 Intelligent Chatbot Development. All clinic, doctor, price and promotion information is <strong>simulated data</strong> for teaching purposes, not a real business.',
  },
  'common.projectCredit': {
    th: 'จัดทำโดย นางสาวชาลิสา น้อยบุญเติม (68076015) นางสาวศุภิสรา ศิริเสรี (68076063)',
    en: 'Created by Chalisa Noibunterm (68076015) and Supisara Siriseree (68076063)',
  },
  'common.showPassword': { th: 'แสดงรหัสผ่าน', en: 'Show password' },
  'common.hidePassword': { th: 'ซ่อนรหัสผ่าน', en: 'Hide password' },
  'common.all': { th: 'ทั้งหมด', en: 'All' },
  'common.search': { th: 'ค้นหา', en: 'Search' },
  'common.clear': { th: 'ล้าง', en: 'Clear' },
  'common.viewAll': { th: 'ดูทั้งหมด', en: 'View all' },
  'common.today': { th: 'วันนี้', en: 'Today' },
  'common.areYouSure': { th: 'แน่ใจหรือไม่?', en: 'Are you sure?' },
  'common.active': { th: 'เปิดใช้งาน', en: 'Active' },
  'common.inactive': { th: 'ปิดใช้งาน', en: 'Inactive' },
  'common.name': { th: 'ชื่อ', en: 'Name' },
  'common.status': { th: 'สถานะ', en: 'Status' },
  'common.actions': { th: 'จัดการ', en: 'Actions' },
  'common.viewFailTitle': { th: 'กำลังจัดเตรียม', en: 'Coming together' },
  'common.viewFailSub': { th: 'ส่วนนี้กำลังพัฒนา ระบบหลักและเมนูพร้อมใช้งานแล้ว', en: 'This section is being built. The app shell and navigation are live.' },
  'common.requestFailed': { th: 'คำขอไม่สำเร็จ', en: 'Request failed' },
  'common.networkError': { th: 'เชื่อมต่อไม่สำเร็จ เซิร์ฟเวอร์ทำงานอยู่หรือไม่?', en: 'Network error - is the server running?' },
  'common.sessionExpired': { th: 'เซสชันหมดอายุ', en: 'Session expired' },

  /* ---------------- clinic workspace navigation ---------------- */
  'nav.dashboard': { th: 'ภาพรวม', en: 'Overview' },
  'nav.conversations': { th: 'การสนทนา', en: 'Conversations' },
  'nav.bookings': { th: 'การจอง', en: 'Bookings' },
  'nav.team': { th: 'แพทย์และทีมงาน', en: 'Doctors & Staff' },
  'nav.customers': { th: 'ลูกค้า', en: 'Customers' },
  'nav.payments': { th: 'การชำระเงิน', en: 'Payments' },
  'nav.treatments': { th: 'ทรีตเมนต์', en: 'Treatments' },
  'nav.knowledge': { th: 'คลังความรู้', en: 'Knowledge Base' },
  'nav.retention': { th: 'การดูแลลูกค้า', en: 'Retention' },
  'nav.analytics': { th: 'การวิเคราะห์', en: 'Analytics' },
  'nav.chatAnalysis': { th: 'วิเคราะห์แชท', en: 'Chat Analysis' },
  'nav.broadcast': { th: 'บรอดแคสต์', en: 'Broadcast' },
  'nav.settings': { th: 'ตั้งค่า', en: 'Settings' },
  'nav.test': { th: 'ทดสอบระบบ', en: 'Test Console' },
  'nav.systemDashboard': { th: 'ภาพรวม', en: 'Overview' },
  'nav.systemClinics': { th: 'คลินิก', en: 'Clinics' },
  'nav.systemUsers': { th: 'ผู้ใช้และสิทธิ์', en: 'Users & Roles' },

  /* ---------------- app shell / topbar ---------------- */
  'shell.systemConsole': { th: 'คอนโซลระบบ', en: 'System console' },
  'shell.switchClinic': { th: 'สลับคลินิก', en: 'Switch clinic' },
  'shell.account': { th: 'บัญชีและออกจากระบบ', en: 'Account & sign out' },
  'shell.sysadmin': { th: 'ผู้ดูแลระบบ', en: 'System Administrator' },
  'shell.managingAll': { th: 'กำลังดูแลทุกคลินิก', en: 'managing all clinics' },
  'shell.platform': { th: 'แพลตฟอร์ม', en: 'Platform' },
  'shell.notifications': { th: 'การแจ้งเตือน', en: 'Notifications' },
  'shell.myBranch': { th: 'สาขาของฉัน', en: 'My branch' },
  'shell.logout': { th: 'ออกจากระบบ', en: 'Log out' },
  'shell.greetMorning': { th: 'สวัสดีตอนเช้า', en: 'Good morning' },
  'shell.greetAfternoon': { th: 'สวัสดีตอนบ่าย', en: 'Good afternoon' },
  'shell.greetEvening': { th: 'สวัสดีตอนเย็น', en: 'Good evening' },

  /* ---------------- account menu key/value labels ---------------- */
  'menu.role': { th: 'บทบาท', en: 'Role' },
  'menu.email': { th: 'อีเมล', en: 'Email' },
  'menu.scope': { th: 'ขอบเขต', en: 'Scope' },
  'menu.allClinics': { th: 'ทุกคลินิก (แพลตฟอร์ม)', en: 'All clinics (platform)' },
  'menu.title': { th: 'ตำแหน่ง', en: 'Title' },
  'menu.clinic': { th: 'คลินิก', en: 'Clinic' },
  'menu.branch': { th: 'สาขา', en: 'Branch' },
  'menu.allBranches': { th: 'ทุกสาขา', en: 'All branches' },

  /* ---------------- role display names ---------------- */
  'role.owner': { th: 'เจ้าของ', en: 'Owner' },
  'role.super_admin': { th: 'ผู้ดูแลระบบ', en: 'Super admin' },
  'role.branch_manager': { th: 'ผู้จัดการสาขา', en: 'Branch manager' },
  'role.sales': { th: 'ฝ่ายขาย', en: 'Sales' },
  'role.doctor': { th: 'แพทย์', en: 'Doctor' },
  'role.marketing': { th: 'การตลาด', en: 'Marketing' },

  /* ---------------- shared ui.js helpers ---------------- */
  'ui.profilePhoto': { th: 'รูปโปรไฟล์', en: 'Profile photo' },
  'ui.uploadPhoto': { th: 'อัปโหลดรูป', en: 'Upload photo' },
  'ui.uploadPhotoTitle': { th: 'อัปโหลดรูปภาพ', en: 'Upload a photo' },
  'ui.photoHint': { th: 'PNG, JPG หรือ WebP · ไม่เกิน 4 MB', en: 'PNG, JPG or WebP · up to 4 MB' },

  /* ---------------- payment card (ui.js + chat widget) ---------------- */
  'pay.label': { th: 'ชำระเงิน', en: 'Pay' },
  'pay.paidNote': { th: 'ชำระเงินเรียบร้อยแล้ว', en: 'Payment received' },
  'pay.paidCta': { th: 'ชำระแล้ว', en: 'Paid' },
  'pay.method': { th: 'ชำระเงินออนไลน์', en: 'Online payment' },
  'pay.slipChecking': { th: 'ได้รับสลิปแล้ว รอตรวจ (หยุดเวลาถือคิว)', en: 'Slip received, waiting for review (hold paused)' },
  'pay.qrSent': { th: 'ส่ง QR โอนเงินแล้ว รอสลิป แล้วยืนยันที่หน้าการชำระเงิน', en: 'Transfer QR sent; check the slip, then confirm on Payments' },
  'pay.cta': { th: 'จ่ายเงิน', en: 'Pay now' },
  'pay.holdCountdown': { th: 'ระบบสำรองคิวนี้ให้อีก {mm}:{ss} นาที', en: 'Holding this slot for {mm}:{ss} more' },
  'pay.holdExpired': { th: 'หมดเวลาถือคิวแล้ว', en: 'Hold has expired' },

  /* ---------------- relative time (timeAgo) ---------------- */
  'time.justNow': { th: 'เมื่อสักครู่', en: 'just now' },
  'time.mAgo': { th: '{n} นาทีที่แล้ว', en: '{n}m ago' },
  'time.hAgo': { th: '{n} ชม.ที่แล้ว', en: '{n}h ago' },
  'time.dAgo': { th: '{n} วันที่แล้ว', en: '{n}d ago' },

  /* ---------------- month, full (calendar heading) ---------------- */
  'time.month0': { th: 'มกราคม', en: 'January' },
  'time.month1': { th: 'กุมภาพันธ์', en: 'February' },
  'time.month2': { th: 'มีนาคม', en: 'March' },
  'time.month3': { th: 'เมษายน', en: 'April' },
  'time.month4': { th: 'พฤษภาคม', en: 'May' },
  'time.month5': { th: 'มิถุนายน', en: 'June' },
  'time.month6': { th: 'กรกฎาคม', en: 'July' },
  'time.month7': { th: 'สิงหาคม', en: 'August' },
  'time.month8': { th: 'กันยายน', en: 'September' },
  'time.month9': { th: 'ตุลาคม', en: 'October' },
  'time.month10': { th: 'พฤศจิกายน', en: 'November' },
  'time.month11': { th: 'ธันวาคม', en: 'December' },

  /* ---------------- weekday, short (dayNameRaw) ---------------- */
  'time.dow0': { th: 'อา.', en: 'Sun' },
  'time.dow1': { th: 'จ.', en: 'Mon' },
  'time.dow2': { th: 'อ.', en: 'Tue' },
  'time.dow3': { th: 'พ.', en: 'Wed' },
  'time.dow4': { th: 'พฤ.', en: 'Thu' },
  'time.dow5': { th: 'ศ.', en: 'Fri' },
  'time.dow6': { th: 'ส.', en: 'Sat' },
};

/* Merge the seed with every per-view fragment into one flat catalog. Namespaces
   are disjoint (common.* / nav.* / … vs dash.* / conv.* / …) so there are no
   collisions; Object.assign keeps it a single lookup table for t(). */
export const CATALOG = Object.assign(
  {}, SEED,
  dash, conv, cust, book, team, payments, treat, kb, retn, anl, chatanl, bcast,
  settings, test, sysdash, sysclin, sysusers, auth, picker,
);
