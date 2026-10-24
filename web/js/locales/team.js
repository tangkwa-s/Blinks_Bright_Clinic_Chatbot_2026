/* i18n catalog fragment — team.js */
export default {
  /* header */
  'team.title': { th: 'แพทย์และทีมงาน', en: 'Doctors & Staff' },
  'team.subtitle': { th: 'จัดการทีมงานและแพทย์ในแต่ละสาขา และดูตารางการจองรายสาขา', en: 'Manage staff and doctors per branch, and view the per-branch booking schedule' },
  'team.tabTeam': { th: 'ทีมงาน', en: 'Team' },
  'team.tabSchedule': { th: 'ตารางการจอง', en: 'Booking schedule' },

  /* clinical roster roles (doctor reuses role.doctor) */
  'team.roleNurse': { th: 'พยาบาล', en: 'Nurse' },
  'team.roleTherapist': { th: 'นักบำบัด', en: 'Therapist' },
  'team.roleStaff': { th: 'พนักงาน', en: 'Staff' },

  /* booking statuses */
  'team.bkPending': { th: 'รอดำเนินการ', en: 'Pending' },
  'team.bkConfirmed': { th: 'ยืนยันแล้ว', en: 'Confirmed' },
  'team.bkCompleted': { th: 'เสร็จสิ้น', en: 'Completed' },
  'team.bkCancelled': { th: 'ยกเลิก', en: 'Cancelled' },
  'team.bkNoShow': { th: 'ไม่มาตามนัด', en: 'No-show' },
  'team.bkExpired': { th: 'หมดเวลาถือคิว', en: 'Hold expired' },

  /* team tab — branch sections */
  'team.noBranch': { th: 'ไม่ระบุสาขา', en: 'No branch' },
  'team.peopleCount': { th: '{count} คน', en: '{count} people' },
  'team.doctorCount': { th: '{count} แพทย์', en: '{count} doctors' },
  'team.noStaffInBranch': { th: 'ยังไม่มีทีมงานในสาขานี้', en: 'No staff in this branch yet' },
  'team.noMatches': { th: 'ไม่พบรายการที่ตรงกัน', en: 'No matches' },
  'team.noMatchesSub': { th: 'ลองเปลี่ยนบทบาทหรือคำค้นหา', en: 'Try a different role or search.' },
  'team.addStaff': { th: 'เพิ่มทีมงาน / แพทย์', en: 'Add staff / doctor' },
  'team.searchPlaceholder': { th: 'ค้นหาทีมงาน/แพทย์…', en: 'Search staff/doctors…' },

  /* staff modal */
  'team.editStaff': { th: 'แก้ไขข้อมูลทีมงาน', en: 'Edit staff member' },
  'team.noBranchOpt': { th: '— ไม่ระบุสาขา —', en: '— No branch —' },
  'team.fullName': { th: 'ชื่อ-นามสกุล', en: 'Full name' },
  'team.position': { th: 'ตำแหน่ง', en: 'Position' },
  'team.positionPh': { th: 'เช่น แพทย์ผิวหนัง', en: 'e.g. Dermatologist' },
  'team.role': { th: 'บทบาท', en: 'Role' },
  'team.phone': { th: 'เบอร์โทร', en: 'Phone' },
  'team.phoneHint': { th: '(ไม่เกิน 10 หลัก)', en: '(max 10 digits)' },
  'team.icsUrl': { th: 'ลิงก์ปฏิทินภายนอก (iCal/ICS)', en: 'External calendar link (iCal/ICS)' },
  'team.icsUrlPh': { th: 'https://calendar.google.com/calendar/ical/...', en: 'https://calendar.google.com/calendar/ical/...' },
  'team.icsSyncNow': { th: 'ซิงก์ตอนนี้', en: 'Sync now' },
  'team.icsSyncFailed': { th: 'ซิงก์ล้มเหลว', en: 'Sync failed' },
  'team.icsLastSynced': { th: 'ซิงก์ล่าสุด {when}', en: 'Last synced {when}' },
  'team.icsNeverSynced': { th: 'ยังไม่เคยซิงก์', en: 'Never synced yet' },
  'team.icsBusyLabel': { th: 'ไม่ว่าง (ปฏิทินส่วนตัว) — ไม่ใช่การจองในระบบ', en: 'Busy (personal calendar) — not a booking in this system' },
  'team.icsBusyBadge': { th: 'ปฏิทินภายนอก', en: 'External calendar' },
  'team.activeInSystem': { th: 'เปิดใช้งานในระบบ', en: 'Active in the system' },
  'team.rosterHint': { th: 'ทีมงานคลินิก (แพทย์ / นักบำบัด) สำหรับจัดตารางการจอง แยกจากบัญชีล็อกอินที่จัดการในหน้า ตั้งค่า → ทีมงาน', en: 'Clinic roster (doctors / therapists) for booking schedules. Separate from the login accounts managed in Settings → Team.' },
  'team.addStaffBtn': { th: 'เพิ่มทีมงาน', en: 'Add staff' },
  'team.enterName': { th: 'กรุณากรอกชื่อ-นามสกุล', en: 'Enter a full name' },
  'team.savedPhotoFailed': { th: 'บันทึกแล้ว แต่อัปโหลดรูปไม่สำเร็จ', en: 'Saved, but the photo upload failed' },
  'team.staffAdded': { th: 'เพิ่มทีมงานแล้ว', en: 'Staff member added' },

  /* delete staff */
  'team.delStaffTitle': { th: 'ลบทีมงาน', en: 'Delete staff member' },
  'team.delStaffMsg': { th: 'ลบ "{name}" ออกจากทีมงานถาวร? การจองที่มอบหมายไว้จะถูกปลดแพทย์ออก (ไม่สามารถย้อนกลับได้)', en: 'Permanently remove "{name}" from the roster? Any assigned bookings will have the doctor unassigned. This cannot be undone.' },
  'team.delPermanent': { th: 'ลบถาวร', en: 'Delete permanently' },
  'team.staffDeleted': { th: 'ลบทีมงานแล้ว', en: 'Staff member deleted' },

  /* schedule tab */
  'team.noBranchesTitle': { th: 'ยังไม่มีสาขา', en: 'No branches yet' },
  'team.noBranchesSub': { th: 'เพิ่มสาขาก่อนในหน้า ตั้งค่า', en: 'Add a branch first in Settings' },
  'team.prevDay': { th: 'วันก่อนหน้า', en: 'Previous day' },
  'team.nextDay': { th: 'วันถัดไป', en: 'Next day' },
  'team.scheduleLoadFailed': { th: 'โหลดตารางไม่สำเร็จ', en: 'Could not load the schedule' },
  'team.bookingCount': { th: '{count} การจอง', en: '{count} bookings' },
  'team.noBookingsTitle': { th: 'ไม่มีการจองในวันนี้', en: 'No bookings on this day' },
  'team.noBookingsSub': { th: 'เลือกวันอื่น หรือสร้างการจองในหน้า การจอง', en: 'Pick another day, or create a booking in Bookings' },
  'team.noDoctorOpt': { th: '— ไม่ระบุแพทย์ —', en: '— No doctor —' },
  'team.doctorUpdated': { th: 'อัปเดตแพทย์แล้ว', en: 'Doctor updated' },

  /* booking detail modal */
  'team.bookingDetails': { th: 'รายละเอียดการจอง', en: 'Booking details' },
  'team.customer': { th: 'ลูกค้า', en: 'Customer' },
  'team.service': { th: 'บริการ', en: 'Service' },
  'team.time': { th: 'เวลา', en: 'Time' },
};
