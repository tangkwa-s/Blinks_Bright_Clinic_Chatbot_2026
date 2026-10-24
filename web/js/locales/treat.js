/* i18n catalog fragment — treatments.js */
export default {
  'treat.title': { th: 'ทรีตเมนต์', en: 'Treatments' },
  'treat.subtitle': {
    th: 'เมนูบริการที่ใช้งานจริงของคุณ ทุกการเปลี่ยนแปลงที่นี่คือสิ่งที่ผู้ช่วย AI นำเสนอ ตั้งราคา และจองให้ลูกค้า',
    en: 'Your live service menu — every change here is what the AI assistant offers, prices and books.' },
  'treat.syncAI': { th: 'ซิงค์ AI', en: 'Sync AI' },
  'treat.addTreatment': { th: 'เพิ่มทรีตเมนต์', en: 'Add treatment' },
  'treat.searchPlaceholder': { th: 'ค้นหาทรีตเมนต์…', en: 'Search treatments…' },

  /* stat cards */
  'treat.statCategories': { th: 'หมวดหมู่', en: 'Categories' },
  'treat.statAiKnowledge': { th: 'คลังความรู้ AI', en: 'AI knowledge' },
  'treat.aiKnowledgeTip': {
    th: 'คลังความรู้ที่ AI จัดทำดัชนีทั้งหมด (ฝังแล้ว/ทั้งหมด): ทรีตเมนต์ + โปรโมชัน + บทความ + สาขา + แพทย์ ไม่ใช่แค่ทรีตเมนต์',
    en: 'All AI-indexed knowledge (embedded/total): treatments + promotions + articles + branches + doctors, not just treatments' },

  /* cards */
  'treat.hidden': { th: 'ซ่อนอยู่', en: 'Hidden' },
  'treat.general': { th: 'ทั่วไป', en: 'General' },
  'treat.noDescription': { th: 'ยังไม่มีคำอธิบาย', en: 'No description yet.' },
  'treat.minUnit': { th: 'นาที', en: 'min' },
  'treat.repeatEvery': { th: 'ทำซ้ำทุก {n} วัน', en: 'repeat every {n}d' },

  /* sync toasts */
  'treat.aiSynced': {
    th: 'ซิงค์ AI แล้ว · จัดทำดัชนีคลังความรู้ {n} รายการ (ทรีตเมนต์ โปรโมชัน บทความ สาขา และแพทย์)',
    en: 'AI synced · {n} knowledge items indexed (treatments, promos, articles, branches, doctors)' },
  'treat.syncFailed': { th: 'ซิงค์ไม่สำเร็จ', en: 'Sync failed' },

  /* empty states */
  'treat.noMatches': { th: 'ไม่พบรายการที่ตรงกัน', en: 'No matches' },
  'treat.noMatchesSub': { th: 'ลองเปลี่ยนหมวดหมู่หรือคำค้นหา', en: 'Try a different category or search.' },
  'treat.noTreatmentsYet': { th: 'ยังไม่มีทรีตเมนต์', en: 'No treatments yet' },
  'treat.emptyEditSub': { th: 'เพิ่มทรีตเมนต์แรกเพื่อสร้างเมนูของคุณ', en: 'Add your first treatment to build the menu.' },
  'treat.emptyViewSub': { th: 'เมนูยังว่างอยู่', en: 'The menu is empty.' },

  /* modal */
  'treat.newTreatment': { th: 'ทรีตเมนต์ใหม่', en: 'New treatment' },
  'treat.editTreatment': { th: 'แก้ไขทรีตเมนต์', en: 'Edit treatment' },
  'treat.uploadPhoto': { th: 'อัปโหลดรูป', en: 'Upload photo' },
  'treat.photoHint': {
    th: 'PNG, JPG หรือ WebP · ไม่เกิน 4 MB แสดงบนเมนูและให้ลูกค้าเห็น',
    en: 'PNG, JPG or WebP · up to 4 MB. Shown on the menu and to customers.' },
  'treat.category': { th: 'หมวดหมู่', en: 'Category' },
  'treat.categoryPick': { th: 'เลือกจากหมวดที่มีอยู่', en: 'Pick an existing category' },
  'treat.categoryPlaceholder': { th: 'เช่น เฟเชียล', en: 'e.g. Facial' },
  'treat.basePrice': { th: 'ราคาฐาน (฿)', en: 'Base price (฿)' },
  'treat.duration': { th: 'ระยะเวลา (นาที)', en: 'Duration (min)' },
  'treat.recommendedInterval': { th: 'ระยะห่างที่แนะนำ (วัน)', en: 'Recommended interval (days)' },
  'treat.deposit': { th: 'เงินมัดจำ (฿)', en: 'Deposit (฿)' },
  'treat.depositHint': { th: '— เว้นว่าง = อัตโนมัติ 20% ของราคาแต่ละสาขา, ถ้ากำหนดจะใช้จำนวนเท่ากันทุกสาขา (สูงสุด = ราคาฐาน)', en: '— blank = auto 20% of each branch\'s own price; if set, the same flat amount applies at every branch (max = base price)' },
  'treat.auto': { th: 'อัตโนมัติ', en: 'auto' },
  'treat.holdMinutes': { th: 'เวลาถือคิว (นาที)', en: 'Hold timeout (minutes)' },
  'treat.holdMinutesHint': { th: '— เว้นว่าง = ใช้ค่าของคลินิก', en: '— blank = use the clinic\'s setting' },
  'treat.inheritClinic': { th: 'ค่าของคลินิก', en: 'Clinic setting' },
  'treat.description': { th: 'คำอธิบาย', en: 'Description' },
  'treat.prepNotes': { th: 'หมายเหตุการเตรียมตัว', en: 'Preparation notes' },
  'treat.aftercareNotes': { th: 'หมายเหตุการดูแลหลังทำ', en: 'Aftercare notes' },
  'treat.contraindications': { th: 'ข้อห้าม', en: 'Contraindications' },
  'treat.visibleOnMenu': { th: 'แสดงบนเมนูและให้ AI นำเสนอ', en: 'Visible on the menu & offered by the AI' },
  'treat.perBranchPrice': { th: 'ราคาแยกตามสาขา', en: 'Per-branch price' },
  'treat.perBranchHint': { th: '(ไม่บังคับ — เว้นว่างจะใช้ราคาฐาน)', en: '(optional — blank uses base price)' },
  'treat.branchAutoAll': { th: 'ทุกสาขา', en: 'All branches' },
  'treat.branchMultiHint': {
    th: 'เลือกได้หลายสาขา — ถ้าเลือกครบทุกสาขาจะถือเป็น "ทุกสาขา" โดยอัตโนมัติ',
    en: 'Select any number of branches — checking every one collapses back to "All branches"',
  },

  /* delete + validation toasts */
  'treat.deleteConfirmTitle': { th: 'ลบทรีตเมนต์?', en: 'Delete treatment?' },
  'treat.deleteConfirmMsg': {
    th: '"{name}" จะถูกลบออกจากเมนูและ AI หากมีการจองที่ผ่านมาแล้ว ระบบจะซ่อนไว้แทนการลบ',
    en: '"{name}" will be removed from the menu and the AI. If it has past bookings it is hidden instead of deleted.' },
  'treat.deleteConfirmBranches': { th: 'สาขาที่ถูกลบ: {branches}', en: 'Branches affected: {branches}' },
  'treat.treatmentHidden': { th: 'ซ่อนทรีตเมนต์แล้ว (เก็บไว้เป็นประวัติ)', en: 'Treatment hidden (kept for history)' },
  'treat.treatmentDeleted': { th: 'ลบทรีตเมนต์แล้ว', en: 'Treatment deleted' },
  'treat.nameRequired': { th: 'กรุณากรอกชื่อ', en: 'Name is required' },
  'treat.nameDuplicate': { th: 'มีทรีตเมนต์ชื่อ "{name}" อยู่แล้ว กรุณาใช้ชื่ออื่น', en: 'A treatment named "{name}" already exists' },
  'treat.basePriceRange': { th: 'ราคาฐานต้องอยู่ระหว่าง 0 ถึง ฿{max}', en: 'Base price must be between 0 and ฿{max}' },
  'treat.durationRange': { th: 'ระยะเวลาต้องอยู่ระหว่าง 0 ถึง {max} นาที', en: 'Duration must be between 0 and {max} minutes' },
  'treat.intervalRange': { th: 'ระยะห่างที่แนะนำต้องอยู่ระหว่าง 0 ถึง {max} วัน', en: 'Recommended interval must be between 0 and {max} days' },
  'treat.depositNegative': { th: 'เงินมัดจำต้องไม่ติดลบ', en: 'Deposit cannot be negative' },
  'treat.depositExceeds': { th: 'เงินมัดจำต้องไม่เกินราคาฐาน', en: 'Deposit cannot exceed the base price' },
  'treat.holdMinutesRange': { th: 'เวลาถือคิวต้องอยู่ระหว่าง 0 ถึง {max} นาที', en: 'Hold timeout must be between 0 and {max} minutes' },
  'treat.branchPriceRange': { th: 'ราคาแยกตามสาขาต้องมากกว่า 0 และไม่เกิน ฿{max} (เว้นว่างถ้าจะใช้ราคาฐาน)', en: 'Per-branch price must be greater than 0 and at most ฿{max} (leave it blank to use the base price)' },
  'treat.savedPhotoFailed': { th: 'บันทึกแล้ว แต่การอัปโหลดรูปไม่สำเร็จ', en: 'Saved, but the photo upload failed' },
  'treat.savedSyncing': { th: 'บันทึกแล้ว · AI กำลังซิงค์', en: 'Saved · the AI is syncing' },
  'treat.imageTooLarge': { th: 'รูปภาพมีขนาดใหญ่เกินไป (สูงสุด 4 MB)', en: 'Image is too large (max 4 MB)' },
};
