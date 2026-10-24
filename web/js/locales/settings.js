/* i18n catalog fragment — settings.js */
export default {
  /* header + tabs */
  'settings.title': { th: 'ตั้งค่า', en: 'Settings' },
  'settings.subtitle': { th: 'สาขา ทีมงาน ผู้ช่วย AI และปฏิทินของคลินิก', en: 'Clinic branches, team, AI assistant and calendar.' },
  'settings.tabBranches': { th: 'สาขา', en: 'Branches' },
  'settings.tabTeam': { th: 'ทีมงาน', en: 'Team' },
  'settings.tabAI': { th: 'ผู้ช่วย AI', en: 'AI Assistant' },
  'settings.tabCalendar': { th: 'ปฏิทิน', en: 'Calendar' },

  /* day names (full) */
  'settings.dayMon': { th: 'จันทร์', en: 'Monday' },
  'settings.dayTue': { th: 'อังคาร', en: 'Tuesday' },
  'settings.dayWed': { th: 'พุธ', en: 'Wednesday' },
  'settings.dayThu': { th: 'พฤหัสบดี', en: 'Thursday' },
  'settings.dayFri': { th: 'ศุกร์', en: 'Friday' },
  'settings.daySat': { th: 'เสาร์', en: 'Saturday' },
  'settings.daySun': { th: 'อาทิตย์', en: 'Sunday' },

  /* day names (short, for the hours summary chips) */
  'settings.dayMonShort': { th: 'จ.', en: 'Mon' },
  'settings.dayTueShort': { th: 'อ.', en: 'Tue' },
  'settings.dayWedShort': { th: 'พ.', en: 'Wed' },
  'settings.dayThuShort': { th: 'พฤ.', en: 'Thu' },
  'settings.dayFriShort': { th: 'ศ.', en: 'Fri' },
  'settings.daySatShort': { th: 'ส.', en: 'Sat' },
  'settings.daySunShort': { th: 'อา.', en: 'Sun' },
  'settings.closed': { th: 'ปิด', en: 'Closed' },

  /* branches tab + branch card */
  'settings.addBranch': { th: 'เพิ่มสาขา', en: 'Add branch' },
  'settings.editBranch': { th: 'แก้ไขสาขา', en: 'Edit branch' },
  'settings.address': { th: 'ที่อยู่', en: 'Address' },
  'settings.hours': { th: 'เวลาทำการ', en: 'Hours' },

  /* branch modal */
  'settings.branchNamePh': { th: 'เช่น คลินิกอโศก', en: 'e.g. Asoke Clinic' },
  'settings.code': { th: 'รหัสสาขา', en: 'Code' },
  'settings.codePh': { th: 'เช่น ASK', en: 'e.g. ASK' },
  'settings.phone': { th: 'เบอร์โทร', en: 'Phone' },
  'settings.openingHours': { th: 'เวลาทำการ', en: 'Opening hours' },
  'settings.openingHoursHint': { th: '— AI จะแจ้งข้อมูลนี้ให้ลูกค้าทราบ', en: '— the AI shares these with customers' },
  'settings.openClosed': { th: 'เปิด / ปิด', en: 'Open / closed' },
  'settings.applyMonday': { th: 'ใช้เวลาของวันจันทร์กับทุกวัน', en: 'Apply Monday to every day' },
  'settings.createBranch': { th: 'สร้างสาขา', en: 'Create branch' },
  'settings.branchNameRequired': { th: 'กรุณากรอกชื่อสาขา', en: 'Branch name is required' },
  'settings.closeAfterOpen': { th: 'เวลาปิดต้องอยู่หลังเวลาเปิด', en: 'Closing time must be after opening time' },
  'settings.branchAdded': { th: 'เพิ่มสาขาแล้ว · AI กำลังซิงค์', en: 'Branch added · AI syncing' },
  'settings.branchUpdated': { th: 'อัปเดตสาขาแล้ว · AI กำลังซิงค์', en: 'Branch updated · AI syncing' },
  'settings.appliedMonday': { th: 'ใช้เวลาของวันจันทร์กับทุกวันแล้ว', en: 'Applied Monday to all days' },

  /* team tab */
  'settings.addTeamMember': { th: 'เพิ่มทีมงาน', en: 'Add team member' },
  'settings.role': { th: 'บทบาท', en: 'Role' },
  'settings.colTitle': { th: 'ตำแหน่ง', en: 'Title' },
  'settings.deleteAccount': { th: 'ลบบัญชี', en: 'Delete account' },
  'settings.delTeamTitle': { th: 'ลบทีมงาน', en: 'Delete team member' },
  'settings.delTeamMsg': { th: 'ลบบัญชีของ "{name}" อย่างถาวร? การล็อกอินจะถูกลบและไม่สามารถย้อนกลับได้', en: "Permanently delete {name}'s account? This removes their login and cannot be undone." },
  'settings.teamMemberDeleted': { th: 'ลบทีมงานแล้ว', en: 'Team member deleted' },

  /* staff modal */
  'settings.editTeamMember': { th: 'แก้ไขทีมงาน', en: 'Edit team member' },
  'settings.staffNamePh': { th: 'เช่น คุณพลอย', en: 'e.g. Khun Ploy' },
  'settings.email': { th: 'อีเมล', en: 'Email' },
  'settings.loginSuffix': { th: '(ล็อกอิน)', en: '(login)' },
  'settings.titlePh': { th: 'เช่น ที่ปรึกษาอาวุโส', en: 'e.g. Senior Consultant' },
  'settings.tempPassword': { th: 'รหัสผ่านชั่วคราว', en: 'Temporary password' },
  'settings.resetPassword': { th: 'รีเซ็ตรหัสผ่าน', en: 'Reset password' },
  'settings.setInitialPass': { th: 'ตั้งรหัสผ่านเริ่มต้น', en: 'Set an initial password' },
  'settings.leaveBlank': { th: 'เว้นว่างไว้เพื่อใช้รหัสผ่านเดิม', en: 'Leave blank to keep current' },
  'settings.createMember': { th: 'สร้างสมาชิก', en: 'Create member' },
  'settings.nameEmailPassRequired': { th: 'กรุณากรอกชื่อ อีเมล และรหัสผ่าน', en: 'Name, email and a password are required' },
  'settings.emailRequired': { th: 'กรุณากรอกอีเมล', en: 'Email is required' },
  'settings.savedPhotoFailed': { th: 'บันทึกแล้ว แต่อัปโหลดรูปไม่สำเร็จ', en: 'Saved, but the photo upload failed' },
  'settings.teamMemberAdded': { th: 'เพิ่มทีมงานแล้ว', en: 'Team member added' },
  'settings.teamMemberUpdated': { th: 'อัปเดตทีมงานแล้ว', en: 'Team member updated' },

  /* channels tab + channel cards */

  /* channel modal */

  /* AI assistant tab */
  'settings.aiTitle': { th: 'ผู้ช่วย AI ของคลินิก', en: 'Clinic AI assistant' },
  'settings.aiDesc': { th: 'ตั้งชื่อผู้ช่วย AI และเพิ่มแนวทางเฉพาะของคลินิก เช่น โทนการพูดหรือนโยบายเพิ่มเติม', en: "Name your AI assistant and add clinic-specific guidance, e.g. tone of voice or extra policy." },
  'settings.aiNameLabel': { th: 'ชื่อผู้ช่วย', en: 'Assistant name' },
  'settings.aiNamePh': { th: 'เช่น น้องฟ้า', en: 'e.g. น้องฟ้า' },
  'settings.aiInstrLabel': { th: 'คำแนะนำเพิ่มเติม', en: 'Custom instructions' },
  'settings.aiInstrPh': { th: 'เช่น พูดสุภาพ ลงท้ายด้วย "ค่ะ" และแนะนำให้ลูกค้าปรึกษาแพทย์ก่อนทำหัตถการทุกครั้ง', en: 'e.g. Speak politely, end sentences with "ka", and always suggest a doctor consult before any procedure' },
  'settings.aiSafetyHint': { th: 'คำแนะนำนี้ปรับโทนการพูดและนโยบายเพิ่มเติมเท่านั้น — ไม่สามารถยกเลิกกฎความปลอดภัย ความถูกต้องของราคา หรือการอ้างอิงข้อมูลจริงของระบบได้', en: 'These adjust tone and extra policy only — they can never override the safety, pricing-honesty, or grounding rules.' },
  'settings.aiSaved': { th: 'บันทึกการตั้งค่าผู้ช่วย AI แล้ว', en: 'AI assistant settings saved' },
  'settings.holdMinutesLabel': { th: 'เวลาถือคิว (นาที)', en: 'Booking hold timeout (minutes)' },
  'settings.holdMinutesPh': { th: 'ค่าเริ่มต้นของระบบ', en: 'System default' },
  'settings.holdMinutesHint': { th: 'เมื่อ AI จองคิวและรอชำระเงิน ระบบจะถือคิวไว้เท่านี้ก่อนปล่อยให้ลูกค้าท่านอื่น — เว้นว่างหรือใส่ 0 เพื่อใช้ค่าเริ่มต้นของระบบ แต่ละทรีตเมนต์สามารถตั้งค่าของตัวเองแทนได้ในหน้าทรีตเมนต์', en: "How long an unpaid AI booking holds its slot before it's released to other customers. Leave blank or 0 to use the system default — an individual treatment can set its own value on the Treatments page." },

  /* calendar tab */
  'settings.calTitle': { th: 'ซิงก์การนัดหมายไปยังปฏิทินของคุณ', en: 'Sync bookings to your calendar' },
  'settings.calDesc': { th: 'สมัครรับลิงก์นี้ใน Google Calendar (เพิ่มปฏิทิน → จาก URL) หรือ Apple Calendar (File → New Calendar Subscription) — การนัดหมายจะอัปเดตอัตโนมัติเมื่อปฏิทินรีเฟรช', en: 'Subscribe to this link in Google Calendar (Add calendar → From URL) or Apple Calendar (File → New Calendar Subscription) — bookings update automatically whenever the calendar refreshes.' },
  'settings.calUrlLabel': { th: 'ลิงก์สมัครรับปฏิทิน (ICS)', en: 'Calendar subscribe URL (ICS)' },
  'settings.calSecretHint': { th: 'เก็บลิงก์นี้ไว้เป็นความลับเหมือนรหัสผ่าน — ผู้ที่มีลิงก์สามารถเห็นการนัดหมายของคลินิกได้', en: 'Treat this link like a password — anyone holding it can see the clinic’s bookings.' },
  'settings.calCopy': { th: 'คัดลอกลิงก์', en: 'Copy link' },
  'settings.calCopied': { th: 'คัดลอกลิงก์แล้ว', en: 'Link copied' },
  'settings.calCopyFailed': { th: 'คัดลอกไม่สำเร็จ — เลือกข้อความแล้วคัดลอกเอง', en: 'Copy failed — select the text and copy it manually' },
  'settings.calBranchAll': { th: 'ทุกสาขา', en: 'All branches' },
};
