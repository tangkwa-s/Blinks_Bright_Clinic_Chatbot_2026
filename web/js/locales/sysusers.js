/* i18n catalog fragment — system-users.js */
export default {
  /* header */
  'sysusers.title': { th: 'ผู้ใช้และบทบาท', en: 'Users & Roles' },
  'sysusers.subtitle': { th: 'สร้างบัญชีเข้าสู่ระบบ และกำหนดบทบาท คลินิก และสาขาให้แต่ละบัญชี', en: 'Create logins and assign each one a role, clinic and branch.' },
  'sysusers.addUser': { th: 'เพิ่มผู้ใช้', en: 'Add user' },

  /* filters */
  'sysusers.allRoles': { th: 'ทุกบทบาท', en: 'All roles' },
  'sysusers.allClinics': { th: 'ทุกคลินิก', en: 'All clinics' },
  'sysusers.searchPh': { th: 'ค้นหาชื่อหรืออีเมล', en: 'Search name or email' },

  /* role labels (view-specific; the rest reuse role.*) */
  'sysusers.roleSystemAdmin': { th: 'ผู้ดูแลระบบ', en: 'System Admin' },
  'sysusers.roleSalesAdmin': { th: 'ฝ่ายขาย / แอดมิน', en: 'Sales / Admin' },

  /* list states + table */
  'sysusers.loadUsersFailed': { th: 'โหลดข้อมูลผู้ใช้ไม่สำเร็จ', en: 'Could not load users' },
  'sysusers.emptyTitle': { th: 'ไม่พบผู้ใช้ที่ตรงกัน', en: 'No users match' },
  'sysusers.emptySub': { th: 'ปรับตัวกรอง หรือเพิ่มผู้ใช้', en: 'Adjust the filters or add a user.' },
  'sysusers.role': { th: 'บทบาท', en: 'Role' },
  'sysusers.clinic': { th: 'คลินิก', en: 'Clinic' },
  'sysusers.platformDash': { th: '— แพลตฟอร์ม —', en: '— Platform —' },
  'sysusers.disabled': { th: 'ปิดใช้งาน', en: 'Disabled' },

  /* user modal */
  'sysusers.editUser': { th: 'แก้ไขผู้ใช้', en: 'Edit user' },
  'sysusers.platformNoClinic': { th: '— แพลตฟอร์ม (ไม่ระบุคลินิก) —', en: '— Platform (no clinic) —' },
  'sysusers.fullName': { th: 'ชื่อ-นามสกุล', en: 'Full name' },
  'sysusers.email': { th: 'อีเมล', en: 'Email' },
  'sysusers.loginSuffix': { th: ' (สำหรับเข้าสู่ระบบ)', en: ' (login)' },
  'sysusers.password': { th: 'รหัสผ่าน', en: 'Password' },
  'sysusers.resetPassword': { th: 'รีเซ็ตรหัสผ่าน', en: 'Reset password' },
  'sysusers.passMin': { th: 'อย่างน้อย 6 ตัวอักษร', en: 'At least 6 characters' },
  'sysusers.passKeep': { th: 'เว้นว่างเพื่อใช้รหัสผ่านเดิม', en: 'Leave blank to keep current' },
  'sysusers.clinicHint': { th: 'มีเพียง <strong>ผู้ดูแลระบบ</strong> เท่านั้นที่ทำงานได้โดยไม่ต้องระบุคลินิก บทบาทอื่นทุกบทบาทต้องสังกัดคลินิก ส่วนสาขาไม่บังคับ (เว้นว่าง = ทุกสาขา)', en: 'Only a <strong>System Admin</strong> can run without a clinic. Every other role must belong to a clinic; a branch is optional (blank = all branches).' },

  /* modal actions + toasts */
  'sysusers.createUser': { th: 'สร้างผู้ใช้', en: 'Create user' },
  'sysusers.saveChanges': { th: 'บันทึกการเปลี่ยนแปลง', en: 'Save changes' },
  'sysusers.enterName': { th: 'กรุณากรอกชื่อ', en: 'Enter a name' },
  'sysusers.chooseClinic': { th: 'เลือกคลินิกสำหรับบทบาทนี้', en: 'Choose a clinic for this role' },
  'sysusers.emailPassRequired': { th: 'ต้องระบุอีเมลและรหัสผ่าน', en: 'Email and a password are required' },
  'sysusers.savedPhotoFailed': { th: 'บันทึกผู้ใช้แล้ว แต่อัปโหลดรูปไม่สำเร็จ', en: 'User saved, but the photo upload failed' },
  'sysusers.userCreated': { th: 'สร้างผู้ใช้แล้ว', en: 'User created' },
  'sysusers.userUpdated': { th: 'อัปเดตผู้ใช้แล้ว', en: 'User updated' },
  'sysusers.saveFailed': { th: 'บันทึกไม่สำเร็จ', en: 'Could not save' },
};
