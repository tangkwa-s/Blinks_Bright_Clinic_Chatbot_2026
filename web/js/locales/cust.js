/* i18n catalog fragment — customers.js */
export default {
  /* ---- page chrome ---- */
  'cust.title': { th: 'ลูกค้า', en: 'Customers' },
  'cust.subtitle': { th: 'ไปป์ไลน์ลีดและข้อมูลลูกค้าของคุณ', en: 'Your lead pipeline and customer records.' },
  'cust.tabPipeline': { th: 'ไปป์ไลน์', en: 'Pipeline' },
  'cust.tabList': { th: 'รายการ', en: 'List' },
  'cust.searchPlaceholder': { th: 'ค้นหาชื่อลูกค้าหรือเบอร์โทร…', en: 'Search by name or phone…' },
  'cust.loadFailed': { th: 'โหลดข้อมูลลูกค้าไม่สำเร็จ', en: 'Could not load customers' },

  /* ---- list filters ---- */
  'cust.filterAllStages': { th: 'ทุกสถานะ', en: 'All stages' },
  'cust.filterAllTemps': { th: 'ทุกระดับ', en: 'All temperatures' },

  /* ---- pipeline stage labels ---- */
  'cust.stageNewLead': { th: 'ลีดใหม่', en: 'New Lead' },
  'cust.stageInterested': { th: 'สนใจ', en: 'Interested' },
  'cust.stageBooked': { th: 'จองแล้ว', en: 'Booked' },
  'cust.stagePaid': { th: 'ชำระแล้ว', en: 'Paid' },
  'cust.stageFollowup': { th: 'ติดตามผล', en: 'Follow-up' },
  'cust.stageLost': { th: 'หลุดดีล', en: 'Lost' },

  /* ---- lead temperature labels ---- */
  'cust.tempHot': { th: 'ร้อน', en: 'Hot' },
  'cust.tempWarm': { th: 'อุ่น', en: 'Warm' },
  'cust.tempCold': { th: 'เย็น', en: 'Cold' },

  /* ---- booking status labels ---- */
  'cust.bkPending': { th: 'รอยืนยัน', en: 'Pending' },
  'cust.bkConfirmed': { th: 'ยืนยันแล้ว', en: 'Confirmed' },
  'cust.bkCompleted': { th: 'เสร็จสิ้น', en: 'Completed' },
  'cust.bkCancelled': { th: 'ยกเลิก', en: 'Cancelled' },
  'cust.bkNoShow': { th: 'ไม่มาตามนัด', en: 'No-show' },
  'cust.bkExpired': { th: 'หมดเวลาถือคิว', en: 'Hold expired' },

  /* ---- payment status / type labels ---- */
  'cust.payPending': { th: 'รอชำระ', en: 'Pending' },
  'cust.payPaid': { th: 'ชำระแล้ว', en: 'Paid' },
  'cust.payFailed': { th: 'ไม่สำเร็จ', en: 'Failed' },
  'cust.payRefunded': { th: 'คืนเงินแล้ว', en: 'Refunded' },
  'cust.payTypeDeposit': { th: 'มัดจำ', en: 'Deposit' },
  'cust.payTypeFull': { th: 'เต็มจำนวน', en: 'Full' },
  'cust.paymentRow': { th: 'ชำระ{type}', en: '{type} payment' },

  /* ---- golden records / duplicates ---- */
  'cust.dupFound': { th: 'พบ {n} กลุ่มที่อาจเป็นลูกค้าคนเดียวกัน', en: 'Found {n} possible duplicate group(s)' },
  'cust.dupHint': { th: 'มีลูกค้าที่ใช้เบอร์โทรหรืออีเมลเดียวกัน รวมเป็น golden record เดียวเพื่อเห็นประวัติครบ', en: 'Some customers share a phone or email. Merge them into one golden record to see the full history.' },
  'cust.dupReview': { th: 'ตรวจสอบและรวม', en: 'Review & merge' },
  'cust.dupReasonBoth': { th: 'เบอร์โทร + อีเมลเหมือนกัน', en: 'Same phone + email' },
  'cust.dupReasonEmail': { th: 'อีเมลเหมือนกัน', en: 'Same email' },
  'cust.dupReasonPhone': { th: 'เบอร์โทรเหมือนกัน', en: 'Same phone' },
  'cust.dupPickHint': { th: 'ติ๊กเฉพาะคนที่เป็นคนเดียวกัน คนแรกที่ติ๊กจะเป็นข้อมูลหลัก (golden)', en: 'Tick only the records that are the same person; the first one you tick becomes the primary (golden).' },
  'cust.dupSelectAll': { th: 'เลือกทั้งหมด', en: 'Select all' },
  'cust.dupPrimaryTag': { th: 'ตัวหลัก', en: 'primary' },
  'cust.dupPickTwo': { th: 'ติ๊กอย่างน้อย 2 คนที่จะรวมกัน', en: 'Tick at least two records to merge' },
  'cust.mergeBtn': { th: 'รวมเป็นคนเดียว', en: 'Merge into one' },
  'cust.mergeBtnN': { th: 'รวม {n} คน', en: 'Merge {n}' },
  'cust.dupModalTitle': { th: 'ลูกค้าที่อาจซ้ำกัน ({n} กลุ่ม)', en: 'Possible duplicate customers ({n} group(s))' },
  'cust.mergeConfirm': { th: 'รวม {n} รายการเข้ากับ “{name}”? ประวัติทั้งหมด (แชต / การจอง / การชำระเงิน) จะถูกย้ายมารวมกัน และรายการที่ซ้ำจะถูกซ่อน', en: 'Merge {n} record(s) into “{name}”? All history (chats / bookings / payments) will be moved together and the duplicates hidden.' },
  'cust.mergeNow': { th: 'รวมเลย', en: 'Merge now' },
  'cust.mergeSuccess': { th: 'รวมเป็น golden record แล้ว', en: 'Merged into a golden record' },
  'cust.mergeFailed': { th: 'รวมไม่สำเร็จ', en: 'Merge failed' },
  'cust.unitBookings': { th: 'การจอง', en: 'bookings' },
  'cust.unitChats': { th: 'แชต', en: 'chats' },

  /* ---- kanban / list ---- */
  'cust.noInterest': { th: 'ยังไม่มีข้อมูลความสนใจ', en: 'No interest noted' },
  'cust.score': { th: 'คะแนน', en: 'score' },
  'cust.noCustomers': { th: 'ยังไม่มีลูกค้า', en: 'No customers' },
  'cust.colCustomer': { th: 'ลูกค้า', en: 'Customer' },
  'cust.colChannel': { th: 'ช่องทาง', en: 'Channel' },
  'cust.colStage': { th: 'สถานะ', en: 'Stage' },
  'cust.colTemp': { th: 'ระดับ', en: 'Temp' },
  'cust.colScore': { th: 'คะแนน', en: 'Score' },
  'cust.colLtv': { th: 'มูลค่ารวม', en: 'Lifetime value' },
  'cust.colLastActive': { th: 'ใช้งานล่าสุด', en: 'Last active' },

  /* ---- profile header ---- */
  'cust.notFound': { th: 'ไม่พบลูกค้า', en: 'Customer not found' },
  'cust.allCustomers': { th: 'ลูกค้าทั้งหมด', en: 'All customers' },
  'cust.noBranch': { th: 'ไม่มีสาขา', en: 'No branch' },
  'cust.openChat': { th: 'เปิดแชต', en: 'Open chat' },

  /* ---- profile cards ---- */
  'cust.activityTimeline': { th: 'ไทม์ไลน์กิจกรรม', en: 'Activity timeline' },
  'cust.bookingsPayments': { th: 'การจองและการชำระเงิน', en: 'Bookings & payments' },
  'cust.notes': { th: 'โน้ต', en: 'Notes' },
  'cust.notePlaceholder': { th: 'เพิ่มโน้ตภายใน…', en: 'Add an internal note…' },
  'cust.leadScore': { th: 'คะแนนลีด', en: 'Lead score' },
  'cust.pipelineStage': { th: 'สถานะไปป์ไลน์', en: 'Pipeline stage' },
  'cust.productsOfInterest': { th: 'บริการที่สนใจ', en: 'Products of interest' },
  'cust.serviceFallback': { th: 'บริการ', en: 'Service' },
  'cust.details': { th: 'รายละเอียด', en: 'Details' },
  'cust.nickname': { th: 'ชื่อเล่น', en: 'Nickname' },
  'cust.interested': { th: 'สนใจ', en: 'Interested' },
  'cust.budget': { th: 'งบประมาณ', en: 'Budget' },
  'cust.concern': { th: 'สิ่งที่กังวล', en: 'Concern' },
  'cust.lifetimeValue': { th: 'มูลค่ารวม', en: 'Lifetime value' },
  'cust.owner': { th: 'ผู้ดูแล', en: 'Owner' },
  'cust.membership': { th: 'สมาชิก', en: 'Membership' },
  'cust.pointsUnit': { th: 'แต้ม', en: 'pts' },
  'cust.packages': { th: 'แพ็กเกจ', en: 'Packages' },
  'cust.sessionsLeft': { th: 'เหลือ {remaining} จาก {total} ครั้ง', en: '{remaining} of {total} sessions left' },

  /* ---- empty states ---- */
  'cust.noActivity': { th: 'ยังไม่มีกิจกรรม', en: 'No activity yet' },
  'cust.noBookingsPayments': { th: 'ยังไม่มีการจองหรือการชำระเงิน', en: 'No bookings or payments' },
  'cust.noNotes': { th: 'ยังไม่มีโน้ต', en: 'No notes yet.' },

  /* ---- notes / stage / copy toasts ---- */
  'cust.noteAdded': { th: 'เพิ่มโน้ตแล้ว', en: 'Note added' },
  'cust.actionFailed': { th: 'ไม่สำเร็จ', en: 'Failed' },
  'cust.stageUpdated': { th: 'อัปเดตสถานะแล้ว', en: 'Stage updated' },

  /* ---- delete customer ---- */
  'cust.deleteTitle': { th: 'ลบ {name}?', en: 'Delete {name}?' },
  'cust.deleteMsg': { th: 'การลบนี้จะนำลูกค้าและข้อมูลที่เกี่ยวข้องทั้งหมดออกอย่างถาวร — การสนทนา ข้อความ การจอง การชำระเงิน การแจ้งเตือน และโน้ต และไม่สามารถย้อนกลับได้', en: 'This permanently removes the customer and ALL related data — conversations, messages, bookings, payments, reminders and notes. This cannot be undone.' },
  'cust.deleteEverything': { th: 'ลบทั้งหมด', en: 'Delete everything' },
  'cust.deleteSuccess': { th: 'ลบลูกค้าและข้อมูลที่เกี่ยวข้องทั้งหมดแล้ว', en: 'Customer and all related data deleted' },

  /* ---- edit customer modal ---- */
  'cust.editTitle': { th: 'แก้ไขลูกค้า', en: 'Edit customer' },
  'cust.phone': { th: 'เบอร์โทร', en: 'Phone' },
  'cust.email': { th: 'อีเมล', en: 'Email' },
  'cust.nickPlaceholder': { th: 'เช่น แบงค์', en: 'e.g. Bank' },
  'cust.interestedIn': { th: 'สนใจ', en: 'Interested in' },
  'cust.interestedPlaceholder': { th: 'เช่น HIFU Lifting', en: 'e.g. HIFU Lifting' },
  'cust.budgetPlaceholder': { th: 'เช่น ฿20,000', en: 'e.g. ฿20,000' },
  'cust.concernPlaceholder': { th: 'สิ่งที่ลูกค้าต้องการปรับปรุง', en: 'What the customer wants to improve' },
  'cust.saveChanges': { th: 'บันทึกการเปลี่ยนแปลง', en: 'Save changes' },
  'cust.enterName': { th: 'กรุณากรอกชื่อ', en: 'Enter a name' },
  'cust.customerUpdated': { th: 'อัปเดตลูกค้าแล้ว', en: 'Customer updated' },
  'cust.saveChangesFailed': { th: 'บันทึกการเปลี่ยนแปลงไม่สำเร็จ', en: 'Could not save changes' },
};
