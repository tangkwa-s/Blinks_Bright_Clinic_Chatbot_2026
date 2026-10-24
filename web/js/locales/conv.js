/* i18n catalog fragment — conversations.js */
export default {
  /* ---- filter segments ---- */
  'conv.filterNew': { th: 'ใหม่', en: 'New' },

  /* ---- pipeline stages (badges + stage buttons) ---- */
  'conv.stageNewLead': { th: 'ลีดใหม่', en: 'New Lead' },
  'conv.stageInterested': { th: 'สนใจ', en: 'Interested' },
  'conv.stageBooked': { th: 'จองแล้ว', en: 'Booked' },
  'conv.stagePaid': { th: 'ชำระแล้ว', en: 'Paid' },
  'conv.stageFollowup': { th: 'ติดตามผล', en: 'Follow-up' },

  /* ---- list column ---- */
  'conv.searchPlaceholder': { th: 'ค้นหาการสนทนา…', en: 'Search conversations…' },
  'conv.human': { th: 'ทีมงาน', en: 'Human' },
  'conv.requestAdmin': { th: 'ขอแอดมิน', en: 'Needs admin' },
  'conv.noConvTitle': { th: 'ยังไม่มีการสนทนา', en: 'No conversations' },
  'conv.noConvSub': { th: 'ลองเปลี่ยนตัวกรองดู', en: 'Try another filter.' },
  'conv.couldNotLoad': { th: 'โหลดการสนทนาไม่สำเร็จ', en: 'Could not load conversation' },

  /* ---- chat bubbles ---- */
  'conv.sources': { th: 'แหล่งข้อมูล', en: 'Sources' },
  'conv.aiAssistant': { th: 'ผู้ช่วย AI', en: 'AI ASSISTANT' },
  'conv.automationTag': { th: 'ข้อความอัตโนมัติ', en: 'Automated message' },
  'conv.deliveryFailed': { th: 'ส่งไม่สำเร็จ', en: 'Not delivered' },
  'conv.needsReview': { th: 'ควรตรวจสอบ', en: 'Needs review' },
  'conv.flagOffer': { th: 'อ้างสิทธิพิเศษที่ไม่มีข้อมูลรองรับ', en: 'Unverified offer mentioned' },
  'conv.flagDiscount': { th: 'ราคาต่ำกว่ามาตรฐานที่ไม่มีข้อมูลรองรับ', en: 'Unverified discount' },
  'conv.flagPayment': { th: 'อ้างว่าชำระเงินแล้วแต่ยังไม่ยืนยัน', en: 'Unverified payment claim' },
  'conv.viewGrounding': { th: 'ดูข้อมูลอ้างอิง', en: 'View reference data' },

  /* ---- thread header ---- */
  'conv.backToList': { th: 'กลับไปที่รายการ', en: 'Back to list' },
  'conv.toggleListTitle': { th: 'ซ่อน / แสดงรายการแชท', en: 'Hide / show chat list' },
  'conv.togglePanelTitle': { th: 'ซ่อน / แสดงรายละเอียดลูกค้า', en: 'Hide / show customer details' },
  'conv.noBranch': { th: 'ไม่มีสาขา', en: 'No branch' },
  'conv.aiActive': { th: 'AI ทำงานอยู่', en: 'AI active' },

  /* ---- composer ---- */
  'conv.aiReplyingBanner': { th: 'ผู้ช่วย AI กำลังตอบลูกค้าให้โดยอัตโนมัติ', en: 'The AI assistant is replying automatically.' },
  'conv.takenOverBanner': { th: 'คุณกำลังดูแลการสนทนานี้เอง — AI หยุดทำงานชั่วคราว', en: 'You have taken over — the AI is paused.' },
  'conv.takeOver': { th: 'รับช่วงดูแลเอง', en: 'Take over' },
  'conv.returnToAi': { th: 'ส่งกลับให้ AI', en: 'Return to AI' },
  'conv.replyPlaceholder': { th: 'เขียนข้อความตอบกลับ…', en: 'Write a reply…' },
  'conv.sendFailed': { th: 'ส่งข้อความไม่สำเร็จ', en: 'Send failed' },
  'conv.takeoverToReply': { th: 'กด “รับช่วงดูแลเอง” ก่อนจึงจะพิมพ์ตอบลูกค้าได้', en: 'Take over the conversation before replying…' },
  'conv.takeoverRequired': { th: 'ต้องกด “รับช่วงดูแลเอง” ก่อนจึงจะส่งข้อความได้', en: 'Take over the conversation before sending a message' },
  'conv.takeoverDone': { th: 'คุณกำลังดูแลการสนทนานี้แล้ว', en: 'You are now handling this conversation' },
  'conv.returnedReplying': { th: 'ส่งต่อให้ AI — กำลังตอบลูกค้าให้…', en: 'Handed to the AI — replying now…' },
  'conv.returnedToAi': { th: 'ส่งกลับให้ผู้ช่วย AI แล้ว', en: 'Handed back to the AI assistant' },

  /* ---- thread empty state ---- */
  'conv.selectConvTitle': { th: 'เลือกการสนทนา', en: 'Select a conversation' },
  'conv.selectConvSub': { th: 'เลือกลีดจากรายการเพื่อเริ่มต้น', en: 'Pick a lead from the list to start.' },

  /* ---- customer panel ---- */
  'conv.leadScore': { th: 'คะแนนลีด', en: 'Lead score' },
  'conv.pipelineStage': { th: 'ขั้นตอนในไปป์ไลน์', en: 'Pipeline stage' },
  'conv.details': { th: 'รายละเอียด', en: 'Details' },
  'conv.phone': { th: 'เบอร์โทร', en: 'Phone' },
  'conv.email': { th: 'อีเมล', en: 'Email' },
  'conv.budget': { th: 'งบประมาณ', en: 'Budget' },
  'conv.kvInterested': { th: 'สนใจ', en: 'Interested' },
  'conv.concern': { th: 'ความกังวล', en: 'Concern' },
  'conv.aiSummary': { th: 'สรุปบทสนทนา', en: 'Conversation summary' },
  'conv.noSummaryYet': { th: 'ยังไม่มีสรุป — ระบบจะสรุปให้อัตโนมัติหลังจาก AI ตอบลูกค้า', en: 'No summary yet — generated automatically after the AI replies.' },
  'conv.chargeCustom': { th: 'เรียกเก็บเงิน (กำหนดราคาเอง)', en: 'Charge (custom amount)' },
  'conv.viewFullProfile': { th: 'ดูโปรไฟล์เต็ม', en: 'View full profile' },
  'conv.stageUpdated': { th: 'อัปเดตขั้นตอนแล้ว', en: 'Stage updated' },

  /* ---- charge modal ---- */
  'conv.openPhoto': { th: 'เปิดรูปขนาดเต็ม', en: 'Open full-size photo' },
  'conv.chargeTitle': { th: 'เรียกเก็บเงิน', en: 'Charge customer' },
  'conv.chargeHint': { th: 'ส่ง QR ชำระเงินพร้อมยอดที่กำหนดเองให้ {name} ในแชตทันที (เช่น ราคาที่ตกลงกันหลังต่อรอง) แล้วยืนยันรับเงินที่หน้าการชำระเงินเมื่อได้รับสลิป', en: 'Send {name} the payment QR with a custom amount in chat (e.g. a price agreed after negotiation), then confirm it on Payments once the slip arrives.' },
  'conv.amountBaht': { th: 'จำนวนเงิน (บาท)', en: 'Amount (THB)' },
  'conv.amountPlaceholder': { th: 'เช่น 3000', en: 'e.g. 3000' },
  'conv.labelField': { th: 'ป้ายกำกับ', en: 'Label' },
  'conv.servicePayment': { th: 'ชำระค่าบริการ', en: 'Service payment' },
  'conv.createSendLink': { th: 'สร้างลิงก์และส่ง', en: 'Create & send link' },
  'conv.enterValidAmount': { th: 'กรอกจำนวนเงินให้ถูกต้อง', en: 'Enter a valid amount' },
  'conv.linkSent': { th: 'ส่งลิงก์ชำระเงินให้ลูกค้าแล้ว', en: 'Payment link sent to the customer' },
  'conv.createLinkFailed': { th: 'สร้างลิงก์ไม่สำเร็จ', en: 'Could not create link' },
};
