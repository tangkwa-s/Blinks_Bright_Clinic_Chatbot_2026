/* i18n catalog fragment — bookings.js */
export default {
  'book.title': { th: 'การจอง', en: 'Bookings' },
  'book.subtitle': { th: 'การจองทั้งหมดจากทุกสาขา — จองโดย AI หรือทีมงานของคุณ', en: 'Appointments across every branch — booked by the AI or your team.' },
  'book.newBooking': { th: 'การจองใหม่', en: 'New booking' },
  'book.loadFailed': { th: 'โหลดการจองไม่สำเร็จ', en: 'Could not load bookings' },
  'book.emptyTitle': { th: 'ยังไม่มีการจอง', en: 'No bookings' },
  'book.emptySub': { th: 'การจองใหม่จะแสดงที่นี่', en: 'New appointments will appear here.' },

  /* booking status (fixed enum) */
  'book.statusPending': { th: 'รอดำเนินการ', en: 'Pending' },
  'book.statusConfirmed': { th: 'ยืนยันแล้ว', en: 'Confirmed' },
  'book.statusCompleted': { th: 'เสร็จสิ้น', en: 'Completed' },
  'book.statusCancelled': { th: 'ยกเลิก', en: 'Cancelled' },
  'book.statusNoShow': { th: 'ไม่มาตามนัด', en: 'No-show' },
  'book.statusExpired': { th: 'หมดเวลาถือคิว', en: 'Hold expired' },
  'book.heldUntil': { th: 'ถือคิวถึง', en: 'Held until' },
  'book.holdNote': { th: 'ปล่อยคิวอัตโนมัติถ้ายังไม่ชำระ', en: 'released automatically if unpaid' },
  'book.filterUpcoming': { th: 'ที่กำลังจะถึง', en: 'Upcoming' },

  /* booking details */
  'book.detailsTitle': { th: 'รายละเอียดการจอง', en: 'Booking details' },
  'book.customer': { th: 'ลูกค้า', en: 'Customer' },
  'book.treatment': { th: 'ทรีตเมนต์', en: 'Treatment' },
  'book.doctor': { th: 'แพทย์', en: 'Doctor' },
  'book.when': { th: 'วันและเวลา', en: 'When' },
  'book.price': { th: 'ราคา', en: 'Price' },
  'book.deposit': { th: 'เงินมัดจำ', en: 'Deposit' },
  'book.paid': { th: 'ชำระแล้ว', en: 'paid' },
  'book.unpaid': { th: 'ยังไม่ชำระ', en: 'unpaid' },

  /* delete flow */
  'book.delConfirmTitle': { th: 'ลบการจองนี้?', en: 'Delete booking?' },
  'book.delConfirmMsg': {
    th: 'ลบการจอง {service} ของ {name} วันที่ {when}? การกระทำนี้ไม่สามารถย้อนกลับได้',
    en: "Remove {name}'s {service} booking on {when}? This cannot be undone.",
  },
  'book.cancelledKept': { th: 'ยกเลิกการจองแล้ว (เก็บการชำระเงินไว้)', en: 'Booking cancelled (payment kept)' },
  'book.deletedMsg': { th: 'ลบการจองแล้ว', en: 'Booking deleted' },

  /* payment link */
  'book.sendPayLink': { th: 'เปิด QR ชำระเงิน', en: 'Open payment QR' },
  'book.payLinkOpened': { th: 'เปิด QR ชำระเงินแล้ว ยืนยันรับเงินได้ที่หน้าการชำระเงินเมื่อได้รับสลิป', en: 'Payment QR opened; confirm it on Payments once the slip arrives' },
  'book.linkFailed': { th: 'เปิด QR ชำระเงินไม่สำเร็จ', en: 'Could not open the payment QR' },

  /* update */
  'book.updatedMsg': { th: 'อัปเดตการจองแล้ว', en: 'Booking updated' },

  /* new booking modal */
  'book.loadFormFailed': { th: 'โหลดข้อมูลฟอร์มไม่สำเร็จ', en: 'Could not load form data' },
  'book.date': { th: 'วันที่', en: 'Date' },
  'book.time': { th: 'เวลา', en: 'Time' },
  'book.createBooking': { th: 'สร้างการจอง', en: 'Create booking' },
  'book.createdMsg': { th: 'สร้างการจองแล้ว', en: 'Booking created' },
  'book.createFailed': { th: 'สร้างการจองไม่สำเร็จ', en: 'Could not create booking' },

  /* doctor + availability */
  'book.doctorSelect': { th: 'แพทย์ (ไม่บังคับ)', en: 'Doctor (optional)' },
  'book.anyDoctor': { th: 'ไม่ระบุแพทย์', en: 'Any doctor' },
  'book.noSlots': { th: 'ไม่มีเวลาว่างในวันที่เลือก', en: 'No free slots on that date' },

  /* course / bundle series */
  'book.bundleToggle': { th: 'จองเป็นคอร์สหลายครั้ง', en: 'Book as a multi-session course' },
  'book.bundleSessions': { th: 'จำนวนครั้ง', en: 'Sessions' },
  'book.bundleInterval': { th: 'เว้นระยะทุก (เดือน)', en: 'Every (months)' },
  'book.seriesCreated': { th: 'สร้างการจองคอร์ส {n} ครั้งแล้ว', en: 'Course booked — {n} sessions created' },
  'book.seriesCreatedAdjusted': { th: 'สร้างการจองคอร์ส {n} ครั้งแล้ว — เลื่อน {m} ครั้งไปช่วงเวลาว่างที่ใกล้ที่สุด โปรดตรวจสอบตารางนัด', en: 'Course booked — {n} sessions created; {m} moved to the nearest free slot, please review the schedule' },

  /* date-range filter */
  'book.rangeFrom': { th: 'ตั้งแต่', en: 'From' },
  'book.rangeTo': { th: 'ถึง', en: 'To' },
  'book.rangeFromLabel': { th: 'ตั้งแต่วันที่', en: 'From date' },
  'book.rangeToLabel': { th: 'ถึงวันที่', en: 'To date' },
  'book.rangeClear': { th: 'ล้างข้อมูล', en: 'Clear' },
  'book.rangeApply': { th: 'ยืนยัน', en: 'Apply' },
  'book.rangeThisWeek': { th: 'สัปดาห์นี้', en: 'This week' },
  'book.rangeToday': { th: 'วันนี้', en: 'Today' },
  'book.rangeThisMonth': { th: 'เดือนนี้', en: 'This month' },
  'book.range3m': { th: '3 เดือน', en: '3 months' },
  'book.range6m': { th: '6 เดือน', en: '6 months' },
  'book.rangePrevMonth': { th: 'เดือนก่อนหน้า', en: 'Previous month' },
  'book.rangeNextMonth': { th: 'เดือนถัดไป', en: 'Next month' },
  'book.rangeAll': { th: 'ทุกวันที่', en: 'All dates' },
  'book.rangeInvalid': { th: 'วันเริ่มต้นต้องไม่เกินวันสิ้นสุด', en: 'The start date cannot be after the end date' },
  'book.rangeCount': { th: 'พบ {n} รายการ', en: '{n} bookings' },
  'book.emptyRangeSub': { th: 'ไม่มีการจองในช่วงวันที่ที่เลือก ลองเปลี่ยนช่วงวันที่ดูนะคะ', en: 'Nothing booked in the selected dates. Try a different range.' },
};
