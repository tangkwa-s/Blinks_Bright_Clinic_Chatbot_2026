/* i18n catalog fragment — knowledge.js */
export default {
  /* article type enum labels */
  'kb.typeFaq': { th: 'คำถามที่พบบ่อย', en: 'FAQ' },
  'kb.typePolicy': { th: 'นโยบาย', en: 'Policy' },
  'kb.typePrep': { th: 'การเตรียมตัว', en: 'Preparation' },
  'kb.typeAftercare': { th: 'การดูแลหลังทำ', en: 'Aftercare' },
  'kb.typeGeneral': { th: 'ทั่วไป', en: 'General' },

  /* page header + tabs */
  'kb.title': { th: 'คลังความรู้', en: 'Knowledge Base' },
  'kb.subtitle': {
    th: 'ข้อมูลคลินิกที่ผู้ช่วย AI ใช้ตอบลูกค้า ดูแลให้ถูกต้องเสมอเพื่อให้คำตอบอ้างอิงได้จริง',
    en: 'The clinic facts your AI assistant answers from — kept accurate so replies stay grounded.',
  },
  'kb.reindexAi': { th: 'รีอินเด็กซ์ AI', en: 'Reindex AI' },
  'kb.tabArticles': { th: 'บทความและคำถามที่พบบ่อย', en: 'Articles & FAQ' },
  'kb.tabPromotions': { th: 'โปรโมชัน', en: 'Promotions' },

  /* stat cards */
  'kb.statArticles': { th: 'บทความ', en: 'Articles' },
  'kb.statTreatments': { th: 'ทรีตเมนต์', en: 'Treatments' },
  'kb.statPromotions': { th: 'โปรโมชัน', en: 'Promotions' },
  'kb.statIndexed': { th: 'จัดทำดัชนีแล้ว', en: 'Indexed' },

  /* reindex toasts */
  'kb.reindexed': {
    th: 'จัดทำดัชนีใหม่ {chunks} รายการ · ฝังเวกเตอร์ {embedded} รายการ',
    en: 'Reindexed {chunks} items · {embedded} embedded',
  },
  'kb.reindexFailed': { th: 'รีอินเด็กซ์ไม่สำเร็จ', en: 'Reindex failed' },

  /* articles tab */
  'kb.searchArticles': { th: 'ค้นหาบทความ…', en: 'Search articles…' },
  'kb.addArticle': { th: 'เพิ่มบทความ', en: 'Add article' },
  'kb.noMatches': { th: 'ไม่พบรายการที่ตรงกัน', en: 'No matches' },
  'kb.noArticles': { th: 'ยังไม่มีบทความ', en: 'No articles yet' },
  'kb.tryAnotherSearch': { th: 'ลองค้นหาด้วยคำอื่น', en: 'Try another search.' },
  'kb.uploadDoc': { th: 'อัปโหลดเอกสาร', en: 'Upload document' },
  'kb.uploaded': { th: 'เพิ่ม "{title}" เข้าคลังความรู้แล้ว', en: 'Added "{title}" to the knowledge base' },
  'kb.uploadFailed': { th: 'อัปโหลดไม่สำเร็จ', en: 'Upload failed' },
  'kb.fileTooLarge': { th: 'ไฟล์ใหญ่เกินไป (สูงสุด 10 MB)', en: 'File is too large (max 10 MB)' },
  'kb.fileUnsupported': { th: 'รองรับเฉพาะไฟล์ PDF, DOCX และ TXT', en: 'Only PDF, DOCX and TXT files are supported' },
  'kb.noArticlesHint': {
    th: 'เพิ่มคำถามที่พบบ่อย นโยบาย และคำแนะนำการดูแลให้ AI',
    en: 'Add FAQ, policy and care notes for the AI.',
  },

  /* article modal */
  'kb.editArticle': { th: 'แก้ไขบทความ', en: 'Edit article' },
  'kb.newArticle': { th: 'บทความใหม่', en: 'New article' },
  'kb.fieldType': { th: 'ประเภท', en: 'Type' },
  'kb.fieldTitle': { th: 'หัวข้อ', en: 'Title' },
  'kb.titlePlaceholder': { th: 'เช่น จองนัดหมายได้อย่างไร?', en: 'e.g. How do I book an appointment?' },
  'kb.fieldContent': { th: 'เนื้อหา', en: 'Content' },
  'kb.contentPlaceholder': { th: 'คำตอบที่ต้องการให้ AI ตอบ…', en: 'The answer the AI should give…' },
  'kb.deleteArticleConfirm': { th: 'ลบบทความนี้?', en: 'Delete article?' },
  'kb.articleDeleted': { th: 'ลบบทความแล้ว', en: 'Article deleted' },
  'kb.titleRequired': { th: 'กรุณากรอกหัวข้อ', en: 'Title is required' },

  /* promotions tab */
  'kb.searchPromotions': { th: 'ค้นหาโปรโมชัน…', en: 'Search promotions…' },
  'kb.addPromotion': { th: 'เพิ่มโปรโมชัน', en: 'Add promotion' },
  'kb.offer': { th: 'ข้อเสนอ', en: 'Offer' },
  'kb.noPromotions': { th: 'ยังไม่มีโปรโมชัน', en: 'No promotions' },
  'kb.noPromotionsHint': { th: 'เพิ่มข้อเสนอตามฤดูกาลและแพ็กเกจ', en: 'Add seasonal offers and bundles.' },

  /* promotion modal */
  'kb.editPromotion': { th: 'แก้ไขโปรโมชัน', en: 'Edit promotion' },
  'kb.newPromotion': { th: 'โปรโมชันใหม่', en: 'New promotion' },
  'kb.fieldDetail': { th: 'รายละเอียด', en: 'Detail' },
  'kb.fieldDiscountLabel': { th: 'ป้ายส่วนลด', en: 'Discount label' },
  'kb.discountPlaceholder': { th: 'เช่น ลด 20%', en: 'e.g. 20% off' },
  'kb.fieldPromoPrice': { th: 'ราคาโปรโมชัน (฿, ไม่บังคับ)', en: 'Promo price (฿, optional)' },
  'kb.fieldTreatment': { th: 'ทรีตเมนต์', en: 'Treatment' },
  'kb.anyTreatment': { th: 'ทรีตเมนต์ใดก็ได้', en: 'Any treatment' },
  'kb.promoBranchHint': { th: 'เลือกได้หลายสาขา — ติ๊กครบทุกสาขาจะกลับเป็น "ทุกสาขา"', en: 'Select any number of branches — checking every one collapses back to "All branches"' },
  'kb.fieldValidFrom': { th: 'เริ่มใช้ได้', en: 'Valid from' },
  'kb.fieldValidTo': { th: 'ใช้ได้ถึง', en: 'Valid to' },

  /* effective period + quota */
  'kb.expired': { th: 'หมดเขตแล้ว', en: 'Expired' },
  'kb.validRange': { th: 'ใช้ได้ {from} – {to}', en: 'Valid {from} – {to}' },
  'kb.fieldQuota': { th: 'จำนวนสิทธิ์ (โควตา)', en: 'Quota (slots)' },
  'kb.quotaHint': { th: '0 = ไม่จำกัดสิทธิ์', en: '0 = unlimited' },
  'kb.quotaUsed': { th: 'ใช้ไป {used}/{quota} สิทธิ์', en: 'Used {used}/{quota}' },
  'kb.quotaFull': { th: 'สิทธิ์เต็มแล้ว', en: 'Fully redeemed' },
  'kb.quotaUnlimited': { th: 'ไม่จำกัดสิทธิ์', en: 'Unlimited slots' },
  'kb.deletePromoTitle': { th: 'ลบโปรโมชัน?', en: 'Delete promotion?' },
  'kb.deletePromoMsg': { th: '"{title}" จะถูกลบออกจากระบบและ AI จะไม่เสนออีก หากมีการจองที่ใช้โปรนี้แล้วระบบจะปิดการใช้งานแทนการลบ (เก็บประวัติไว้)', en: '"{title}" will be removed from the system and the AI. If bookings already used it, it is deactivated instead (history kept).' },
  'kb.promoArchived': { th: 'ปิดการใช้งานโปรแล้ว (มีประวัติการจอง จึงเก็บไว้)', en: 'Promotion deactivated (kept — bookings reference it)' },
  'kb.promoDeleted': { th: 'ลบโปรโมชันแล้ว', en: 'Promotion deleted' },
};