/* i18n catalog fragment — analytics.js */
export default {
  // page header
  'anl.title': { th: 'การวิเคราะห์ด้วย AI', en: 'AI Analytics' },
  'anl.subtitle': {
    th: 'ข้อมูลเชิงลึกจากการสนทนา เพื่อปรับสคริปต์การขายและผู้ช่วย AI ให้คมขึ้น',
    en: 'Conversation insights to sharpen your sales script and the AI assistant.',
  },
  'anl.loadFailed': { th: 'โหลดข้อมูลการวิเคราะห์ไม่สำเร็จ', en: 'Could not load analytics' },

  // pipeline stages (fixed enum)
  'anl.stageNewLead': { th: 'ลีดใหม่', en: 'New Lead' },
  'anl.stageInterested': { th: 'สนใจ', en: 'Interested' },
  'anl.stageBooked': { th: 'จองแล้ว', en: 'Booked' },
  'anl.stagePaid': { th: 'ชำระแล้ว', en: 'Paid' },

  // stat cards
  'anl.statReplies': { th: 'AI ตอบไปแล้ว', en: 'AI replies sent' },
  'anl.statGrounded': { th: 'อ้างอิงคลังความรู้', en: 'Grounded in KB' },
  'anl.statEscalations': { th: 'การส่งต่อให้ทีมงาน', en: 'Escalations' },
  'anl.statTakeovers': { th: 'ทีมงานรับช่วงต่อ', en: 'Human takeovers' },
  'anl.statCost': { th: 'ค่าใช้จ่าย AI', en: 'AI cost' },
  'anl.costSub': {
    th: '{tokens} โทเคน · {calls} การตอบของ AI',
    en: '{tokens} tokens · {calls} AI replies',
  },

  // intent / conversion cards
  'anl.whatCustomersAsk': { th: 'สิ่งที่ลูกค้าถามบ่อย', en: 'What customers ask about' },
  'anl.noIntentData': { th: 'ยังไม่มีข้อมูลความต้องการ', en: 'No intent data yet' },
  'anl.topConverting': { th: 'ทรีตเมนต์ที่ปิดการขายได้ดีที่สุด', en: 'Highest-converting treatments' },

  // funnel drop-off
  'anl.funnelDropoff': { th: 'จุดที่ลีดหลุดในกรวย', en: 'Funnel drop-off' },
  'anl.funnelDropoffSub': { th: 'จุดที่สูญเสียลีด', en: 'where leads are lost' },
  'anl.kept': { th: 'คงอยู่', en: 'kept' },

  // unknown questions
  'anl.unknownQuestions': { th: 'คำถามที่ยังไม่รู้จัก', en: 'Unknown questions' },
  'anl.unknownQuestionsSub': { th: 'ฝึก AI และคลังความรู้', en: 'train the AI &amp; KB' },
  'anl.predictedLine': {
    th: 'คาดการณ์: {intent} · ความมั่นใจ {confidence}',
    en: 'predicted: {intent} · confidence {confidence}',
  },
  'anl.noUnclassified': { th: 'ไม่มีคำถามที่จัดหมวดไม่ได้', en: 'No unclassified questions' },
  'anl.noUnclassifiedSub': {
    th: 'AI จัดการทุกอย่างที่พบได้อย่างครบถ้วน',
    en: 'The AI is handling everything it sees.',
  },

  // common objections
  'anl.commonObjections': { th: 'ข้อโต้แย้งที่พบบ่อย', en: 'Common objections' },
  'anl.commonObjectionsSub': {
    th: 'สิ่งที่ทำให้ลูกค้าลังเลที่จะจอง',
    en: 'what holds customers back from booking',
  },
  'anl.noObjections': { th: 'ยังไม่มีบันทึกข้อโต้แย้ง', en: 'No objections logged' },
  'anl.noObjectionsSub': {
    th: 'ลูกค้าไม่มีข้อกังวลเกี่ยวกับการจอง',
    en: 'Customers are not raising concerns about booking.',
  },
};
