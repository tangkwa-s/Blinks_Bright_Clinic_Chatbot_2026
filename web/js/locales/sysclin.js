/* i18n catalog fragment — system-clinics.js */
export default {
  // header
  'sysclin.title': { th: 'คลินิก', en: 'Clinics' },
  'sysclin.subtitle': { th: 'สร้าง ตั้งค่า และเก็บถาวรธุรกิจคลินิกบนแพลตฟอร์ม', en: 'Create, configure and archive the clinic businesses on the platform.' },
  'sysclin.newClinic': { th: 'คลินิกใหม่', en: 'New clinic' },

  // list states
  'sysclin.loadFailed': { th: 'โหลดข้อมูลคลินิกไม่สำเร็จ', en: 'Could not load clinics' },
  'sysclin.emptyTitle': { th: 'ยังไม่มีคลินิก', en: 'No clinics yet' },
  'sysclin.emptySub': { th: 'สร้างคลินิกแรกเพื่อเริ่มต้นใช้งาน', en: 'Create the first clinic to get started.' },

  // table headers
  'sysclin.colClinic': { th: 'คลินิก', en: 'Clinic' },
  'sysclin.colBranches': { th: 'สาขา', en: 'Branches' },
  'sysclin.colStaff': { th: 'ทีมงาน', en: 'Staff' },
  'sysclin.colCustomers': { th: 'ลูกค้า', en: 'Customers' },
  'sysclin.colDepositPaid': { th: 'ชำระค่ามัดจำ', en: 'Deposit paid' },
  'sysclin.colPaid': { th: 'ชำระแล้ว', en: 'Paid' },
  'sysclin.colRevenue': { th: 'รายได้', en: 'Revenue' },

  // status + row actions
  'sysclin.statusArchived': { th: 'เก็บถาวรแล้ว', en: 'Archived' },
  'sysclin.open': { th: 'เปิด', en: 'Open' },
  'sysclin.restore': { th: 'กู้คืน', en: 'Restore' },
  'sysclin.archive': { th: 'เก็บถาวร', en: 'Archive' },
  'sysclin.deletePermanently': { th: 'ลบถาวร', en: 'Delete permanently' },

  // row action toasts
  'sysclin.openFailed': { th: 'เปิดคลินิกไม่สำเร็จ', en: 'Could not open clinic' },
  'sysclin.restored': { th: 'กู้คืนคลินิกแล้ว', en: 'Clinic restored' },
  'sysclin.restoreFailed': { th: 'กู้คืนไม่สำเร็จ', en: 'Could not restore' },
  'sysclin.archived': { th: 'เก็บถาวรคลินิกแล้ว', en: 'Clinic archived' },
  'sysclin.archiveFailed': { th: 'เก็บถาวรไม่สำเร็จ', en: 'Could not archive' },
  'sysclin.deletedPermanently': { th: 'ลบคลินิกถาวรแล้ว', en: 'Clinic permanently deleted' },

  // archive confirm dialog
  'sysclin.archiveTitle': { th: 'เก็บถาวรคลินิก', en: 'Archive clinic' },
  'sysclin.archiveMsg': { th: 'เก็บถาวร "{name}" หรือไม่? ข้อมูลจะยังคงอยู่ แต่จะออกจากพื้นที่ทำงานที่ใช้งานอยู่', en: 'Archive "{name}"? Its data is kept, but it leaves the active workspace.' },

  // delete confirm dialog
  'sysclin.deleteTitle': { th: 'ลบคลินิกถาวร', en: 'Delete clinic permanently' },
  'sysclin.deleteMsg': { th: 'ลบ "{name}" และข้อมูลทั้งหมด (ลูกค้า การสนทนา การจอง การชำระเงิน แคตตาล็อก) อย่างถาวรหรือไม่? การกระทำนี้ไม่สามารถย้อนกลับได้', en: 'Permanently delete "{name}" and ALL of its data (customers, conversations, bookings, payments, catalog)? This cannot be undone.' },
  'sysclin.deleteForever': { th: 'ลบถาวร', en: 'Delete forever' },

  // clinic modal
  'sysclin.editClinic': { th: 'แก้ไขคลินิก', en: 'Edit clinic' },
  'sysclin.clinicFallback': { th: 'คลินิก', en: 'Clinic' },
  'sysclin.clinicImage': { th: 'รูปคลินิก', en: 'Clinic image' },
  'sysclin.clinicName': { th: 'ชื่อคลินิก', en: 'Clinic name' },
  'sysclin.namePlaceholder': { th: 'เช่น Aura Aesthetic Clinic', en: 'e.g. Aura Aesthetic Clinic' },
  'sysclin.tagline': { th: 'สโลแกน', en: 'Tagline' },
  'sysclin.taglinePlaceholder': { th: 'เช่น ดูแลผิวและเลเซอร์ระดับพรีเมียม', en: 'e.g. Premium skin & laser care' },
  'sysclin.brandAccent': { th: 'สีประจำแบรนด์', en: 'Brand accent' },
  'sysclin.customColour': { th: 'สีกำหนดเอง', en: 'Custom colour' },
  'sysclin.starterHint': { th: 'ระบบจะจัดเตรียมแคตตาล็อกเริ่มต้น คลังความรู้ ระบบอัตโนมัติ และสาขาเริ่มต้นให้โดยอัตโนมัติ คลินิกพร้อมใช้งานได้ทันที', en: 'A starter catalog, knowledge base, automations and a default branch are provisioned automatically — the clinic is ready to use right away.' },
  'sysclin.createClinic': { th: 'สร้างคลินิก', en: 'Create clinic' },
  'sysclin.saveChanges': { th: 'บันทึกการเปลี่ยนแปลง', en: 'Save changes' },
  'sysclin.enterName': { th: 'กรุณากรอกชื่อคลินิก', en: 'Enter a clinic name' },
  'sysclin.imageUploadFailed': { th: 'บันทึกคลินิกแล้ว แต่อัปโหลดรูปไม่สำเร็จ', en: 'Clinic saved, but the image upload failed' },
  'sysclin.created': { th: 'สร้างคลินิกแล้ว', en: 'Clinic created' },
};
