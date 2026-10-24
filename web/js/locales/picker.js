/* i18n catalog fragment — clinics.js (workspace picker / lobby) */
export default {
  // top bar + greeting
  'picker.guestName': { th: 'คุณ', en: 'there' },
  'picker.logout': { th: 'ออกจากระบบ', en: 'Log out' },
  'picker.eyebrow': { th: 'พื้นที่ทำงานของคุณ', en: 'Your workspace' },
  'picker.chooseTitle': { th: 'เลือก<em>คลินิก</em>', en: 'Choose a <em>clinic</em>' },
  'picker.chooseSub': {
    th: '{name} เลือกธุรกิจคลินิกที่ต้องการเข้าไปจัดการ',
    en: '{name}, select which clinic business to step into and manage.',
  },

  // grid states
  'picker.loadFail': { th: 'โหลดรายการคลินิกไม่สำเร็จ', en: 'Could not load clinics' },
  'picker.newClinic': { th: 'คลินิกใหม่', en: 'New clinic' },
  'picker.newClinicSub': { th: 'เพิ่มคลินิกเพื่อจัดการ', en: 'Add a clinic to manage' },
  'picker.noClinicTitle': { th: 'ยังไม่ได้กำหนดคลินิก', en: 'No clinic assigned' },
  'picker.noClinicSub': {
    th: 'โปรดติดต่อผู้ดูแลระบบเพื่อเพิ่มคุณเข้าคลินิก',
    en: 'Ask an administrator to add you to a clinic.',
  },

  // enter / remove a clinic
  'picker.openFail': { th: 'เปิดคลินิกไม่สำเร็จ', en: 'Could not open clinic' },
  'picker.enterClinic': { th: 'เข้าสู่คลินิก', en: 'Enter clinic' },
  'picker.removeTitle': { th: 'นำคลินิกออก', en: 'Remove clinic' },
  'picker.removeMsg': {
    th: 'นำ "{name}" ออกจากพื้นที่ทำงาน? ข้อมูลจะยังถูกเก็บไว้ แต่คลินิกจะไม่แสดงที่นี่อีก',
    en: 'Remove "{name}" from the workspace? Its data is kept but the clinic will no longer appear here.',
  },
  'picker.clinicRemoved': { th: 'นำคลินิกออกแล้ว', en: 'Clinic removed' },
  'picker.removeFail': { th: 'นำคลินิกออกไม่สำเร็จ', en: 'Could not remove clinic' },

  // card image controls
  'picker.changeLogo': { th: 'เปลี่ยนโลโก้', en: 'Change logo' },
  'picker.changeCover': { th: 'เปลี่ยนภาพหน้าปก', en: 'Change cover image' },
  'picker.changeCoverShort': { th: 'เปลี่ยนหน้าปก', en: 'Change cover' },
  'picker.editClinic': { th: 'แก้ไขคลินิก', en: 'Edit clinic' },
  'picker.aestheticClinic': { th: 'คลินิกความงาม', en: 'Aesthetic clinic' },
  'picker.branch': { th: 'สาขา', en: 'branch' },
  'picker.branches': { th: 'สาขา', en: 'branches' },
  'picker.coverUpdated': { th: 'อัปเดตภาพหน้าปกแล้ว', en: 'Cover image updated' },
  'picker.logoUpdated': { th: 'อัปเดตโลโก้แล้ว', en: 'Logo updated' },
  'picker.uploadFail': { th: 'อัปโหลดรูปภาพไม่สำเร็จ', en: 'Could not upload image' },

  // edit / create dialog
  'picker.clinicName': { th: 'ชื่อคลินิก', en: 'Clinic name' },
  'picker.tagline': { th: 'แท็กไลน์', en: 'Tagline' },
  'picker.taglinePh': {
    th: 'เช่น ดูแลผิวและเลเซอร์ระดับพรีเมียม',
    en: 'e.g. Premium skin &amp; laser care',
  },
  'picker.brandAccent': { th: 'สีประจำแบรนด์', en: 'Brand accent' },
  'picker.customColour': { th: 'สีกำหนดเอง', en: 'Custom colour' },
  'picker.editHint': {
    th: 'เคล็ดลับ: เปลี่ยนภาพธุรกิจได้ทุกเมื่อโดยคลิกที่โลโก้บนการ์ดคลินิก ที่อยู่เว็บ (slug) จะยังคงเดิม',
    en: 'Tip: change the business image any time by clicking the logo on the clinic card. The web address (slug) stays the same.',
  },
  'picker.saveChanges': { th: 'บันทึกการเปลี่ยนแปลง', en: 'Save changes' },
  'picker.enterName': { th: 'กรุณากรอกชื่อคลินิก', en: 'Enter a clinic name' },
  'picker.clinicUpdated': { th: 'อัปเดตคลินิกแล้ว', en: 'Clinic updated' },
  'picker.saveChangesFail': { th: 'บันทึกการเปลี่ยนแปลงไม่สำเร็จ', en: 'Could not save changes' },
  'picker.namePh': { th: 'เช่น Aura Aesthetic Clinic', en: 'e.g. Aura Aesthetic Clinic' },
  'picker.businessImage': { th: 'ภาพธุรกิจ', en: 'Business image' },
  'picker.uploadHint': { th: 'คลิกเพื่ออัปโหลดโลโก้หรือรูปภาพ', en: 'Click to upload a logo or photo' },
  'picker.newClinicHint': {
    th: 'ระบบจะตั้งค่าแคตตาล็อกทรีตเมนต์เริ่มต้น คลังความรู้ ระบบอัตโนมัติ และสาขาเริ่มต้นให้โดยอัตโนมัติ — คลินิกพร้อมใช้งานได้ทันที',
    en: 'A starter treatment catalog, knowledge base, automations and a default branch are set up automatically — the clinic is ready to use right away.',
  },
  'picker.createClinic': { th: 'สร้างคลินิก', en: 'Create clinic' },
  'picker.createdImageFail': {
    th: 'สร้างคลินิกแล้ว แต่อัปโหลดรูปภาพไม่สำเร็จ',
    en: 'Clinic made, but the image upload failed',
  },
  'picker.clinicCreated': { th: 'สร้างคลินิกแล้ว', en: 'Clinic created' },
  'picker.createFail': { th: 'สร้างคลินิกไม่สำเร็จ', en: 'Could not create clinic' },
};
