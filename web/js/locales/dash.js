/* i18n catalog fragment — dashboard.js */
export default {
  // hero / range selector
  'dash.subtitle': { th: 'ดูภาพรวมผลการดำเนินงานของคลินิกคุณ', en: "Here's how your clinic is performing." },
  'dash.guestName': { th: 'คุณ', en: 'there' },
  'dash.goodMorning': { th: 'สวัสดีตอนเช้า', en: 'Good morning' },
  'dash.goodAfternoon': { th: 'สวัสดีตอนบ่าย', en: 'Good afternoon' },
  'dash.goodEvening': { th: 'สวัสดีตอนเย็น', en: 'Good evening' },
  'dash.days7': { th: '7 วัน', en: '7 days' },
  'dash.days30': { th: '30 วัน', en: '30 days' },
  'dash.days90': { th: '90 วัน', en: '90 days' },
  'dash.days365': { th: '1 ปี', en: '1 year' },
  'dash.loadFailed': { th: 'โหลดภาพรวมไม่สำเร็จ', en: 'Could not load dashboard' },

  // channels (fixed enum — brand names kept verbatim)
  'dash.chWeb': { th: 'เว็บแชท', en: 'Web Chat' },

  // pipeline stages (fixed enum)
  'dash.stageNewLead': { th: 'ลีดใหม่', en: 'New Lead' },
  'dash.stageInterested': { th: 'สนใจ', en: 'Interested' },
  'dash.stageBooked': { th: 'จองแล้ว', en: 'Booked' },
  'dash.stagePaid': { th: 'ชำระแล้ว', en: 'Paid' },
  'dash.stageFollowup': { th: 'ติดตามผล', en: 'Follow-up' },

  // stat cards
  'dash.statRevenue': { th: 'รายได้', en: 'Revenue' },
  'dash.statLeads': { th: 'ลีดใหม่', en: 'New leads' },
  'dash.statBookings': { th: 'การจอง', en: 'Bookings' },
  'dash.statDepositPaid': { th: 'ชำระค่ามัดจำ', en: 'Deposit paid' },
  'dash.statPaid': { th: 'ชำระแล้ว', en: 'Paid' },
  'dash.statPending': { th: 'รอชำระ', en: 'Pending' },
  'dash.statFollowups': { th: 'การติดตามผล', en: 'Follow-ups' },
  'dash.statConversion': { th: 'อัตราการปิดการขาย', en: 'Conversion' },

  // cards / charts
  'dash.revenueTrend': { th: 'แนวโน้มรายได้', en: 'Revenue trend' },
  'dash.collected': { th: 'เก็บได้ {amount}', en: '{amount} collected' },
  'dash.leadsByChannel': { th: 'ลีดแยกตามช่องทาง', en: 'Leads by channel' },
  'dash.leads': { th: 'ลีด', en: 'leads' },
  'dash.leadFunnel': { th: 'กรวยลีด', en: 'Lead funnel' },
  'dash.topTreatments': { th: 'ทรีตเมนต์ยอดนิยม', en: 'Top treatments' },
  'dash.branchPerformance': { th: 'ผลการดำเนินงานตามสาขา', en: 'Branch performance' },
  'dash.branchStat': { th: '{revenue} · {count} การจอง', en: '{revenue} · {count} bookings' },
  'dash.recentConversations': { th: 'การสนทนาล่าสุด', en: 'Recent conversations' },
  'dash.noConversations': { th: 'ยังไม่มีการสนทนา', en: 'No conversations' },
  'dash.topClosers': { th: 'ทีมปิดการขายยอดเยี่ยม', en: 'Top closers' },
  'dash.closerStat': { th: 'ปิดได้ {closed} จาก {total} ลีด', en: '{closed} closed of {total} leads' },
};
