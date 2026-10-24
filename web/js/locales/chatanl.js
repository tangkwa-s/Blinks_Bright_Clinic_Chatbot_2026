/* i18n catalog fragment — chat-analysis.js (Chat Analysis dashboard) */
export default {
  'chatanl.title': { th: 'วิเคราะห์แชทลูกค้า', en: 'Chat Analysis' },
  'chatanl.subtitle': {
    th: 'ลูกค้าพิมพ์อะไรเข้ามา รู้สึกอย่างไร และทักช่วงไหน',
    en: 'What customers write, how they feel, and when they reach out',
  },
  'chatanl.loadFailed': { th: 'โหลดข้อมูลไม่สำเร็จ', en: 'Could not load chat analysis' },
  'chatanl.noData': { th: 'ยังไม่มีข้อความจากลูกค้าในช่วงเวลานี้', en: 'No customer messages in this period yet' },
  'chatanl.viewAllTime': { th: 'ดูข้อมูลทั้งหมดที่เคยมี', en: 'View all-time data' },

  /* KPI tiles */
  'chatanl.statMessages': { th: 'ข้อความจากลูกค้า', en: 'Customer messages' },
  'chatanl.statCustomers': { th: 'ลูกค้าที่ทักเข้ามา', en: 'Customers chatting' },
  'chatanl.statAiReplies': { th: 'ตอบโดย AI', en: 'AI replies' },
  'chatanl.statTakeovers': { th: 'แอดมินรับช่วง', en: 'Human takeovers' },
  'chatanl.statReplyTime': { th: 'เวลาตอบกลับ (มัธยฐาน)', en: 'Median reply time' },
  'chatanl.seconds': { th: '{n} วินาที', en: '{n} sec' },
  'chatanl.minutes': { th: '{n} นาที', en: '{n} min' },
  'chatanl.hoursUnit': { th: '{n} ชม.', en: '{n} hr' },

  /* word cloud */
  'chatanl.wordcloud': { th: 'คำที่ลูกค้าพูดถึงบ่อย', en: 'What customers talk about' },
  'chatanl.wcTreatment': { th: 'ทรีตเมนต์ในคลินิก', en: 'Clinic treatments' },
  'chatanl.wcGeneral': { th: 'คำทั่วไป', en: 'General terms' },
  'chatanl.mentions': { th: '{n} ครั้ง', en: '{n} mentions' },

  /* sentiment */
  'chatanl.sentiment': { th: 'ความรู้สึกของลูกค้า', en: 'Customer sentiment' },
  'chatanl.sentimentTrend': { th: 'แนวโน้มความรู้สึก', en: 'Sentiment trend' },
  'chatanl.positive': { th: 'เชิงบวก', en: 'Positive' },
  'chatanl.neutral': { th: 'กลาง ๆ', en: 'Neutral' },
  'chatanl.negative': { th: 'เชิงลบ', en: 'Negative' },
  'chatanl.positiveShare': { th: 'ของข้อความทั้งหมดเป็นเชิงบวก', en: 'of messages are positive' },
  'chatanl.trendHint': {
    th: 'แท่งขึ้น = ข้อความเชิงบวก · แท่งลง = เชิงลบ',
    en: 'Bars up = positive messages · bars down = negative',
  },

  /* channels + topics */
  'chatanl.byChannel': { th: 'ข้อความตามช่องทาง', en: 'Messages by channel' },
  'chatanl.topTopics': { th: 'ทรีตเมนต์ที่ถูกถามถึง', en: 'Treatments customers ask about' },
  'chatanl.msgsUnit': { th: 'ข้อความ', en: 'messages' },

  /* busy hours heatmap */
  'chatanl.busyHours': { th: 'ช่วงเวลาที่ลูกค้าทัก', en: 'When customers reach out' },
  'chatanl.busyHint': { th: 'สีเข้ม = ข้อความเยอะ (เวลาไทย)', en: 'Darker = more messages (Bangkok time)' },

  /* attention list */
  'chatanl.attention': { th: 'ข้อความเชิงลบล่าสุด', en: 'Recent negative messages' },
  'chatanl.attentionHint': { th: 'คลิกเพื่อเปิดแชท', en: 'Click to open the conversation' },
  'chatanl.noNegative': { th: 'ไม่มีข้อความเชิงลบในช่วงนี้ 🎉', en: 'No negative messages in this period 🎉' },
};
