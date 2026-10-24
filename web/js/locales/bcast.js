/* i18n catalog fragment — broadcast.js */
export default {
  /* page chrome */
  'bcast.title': { th: 'บรอดแคสต์', en: 'Broadcast' },
  'bcast.subtitle': { th: 'แคมเปญดึงลูกค้ากลับมาแบบเจาะกลุ่มเป้าหมาย', en: 'Targeted re-engagement campaigns for customer segments.' },
  'bcast.newCampaign': { th: 'สร้างแคมเปญ', en: 'New campaign' },
  'bcast.loadFailed': { th: 'โหลดแคมเปญไม่สำเร็จ', en: 'Could not load campaigns' },
  'bcast.emptyTitle': { th: 'ยังไม่มีแคมเปญ', en: 'No campaigns yet' },
  'bcast.emptySub': { th: 'สร้างแคมเปญเพื่อดึงกลุ่มลูกค้ากลับมา', en: 'Create a campaign to re-engage a customer segment.' },
  'bcast.searchCampaigns': { th: 'ค้นหาแคมเปญ…', en: 'Search campaigns…' },
  'bcast.noMatches': { th: 'ไม่พบรายการที่ตรงกัน', en: 'No matches' },
  'bcast.tryAnotherSearch': { th: 'ลองค้นหาด้วยคำอื่น', en: 'Try another search.' },

  /* campaign card */
  'bcast.autoSendAt': { th: 'จะส่งอัตโนมัติ {when}', en: 'Auto-sends {when}' },
  'bcast.noMessage': { th: '(ไม่มีข้อความ)', en: '(no message)' },
  'bcast.audience': { th: 'กลุ่มเป้าหมาย', en: 'Audience' },
  'bcast.metricSent': { th: 'ส่งแล้ว', en: 'Sent' },
  'bcast.metricOpened': { th: 'เปิดอ่าน', en: 'Opened' },
  'bcast.metricResponded': { th: 'ตอบกลับ', en: 'Replied' },
  'bcast.repliedYes': { th: 'ตอบแล้ว', en: 'Replied' },
  'bcast.logResponded': { th: 'ตอบกลับ {n} คน', en: '{n} replied' },
  'bcast.logs': { th: 'บันทึกการส่ง', en: 'Logs' },
  'bcast.reuse': { th: 'ใช้ซ้ำ', en: 'Reuse' },
  'bcast.reuseTip': { th: 'สร้างแคมเปญใหม่จากแคมเปญนี้', en: 'Create a new campaign from this one' },
  'bcast.send': { th: 'ส่ง', en: 'Send' },
  'bcast.sendNow': { th: 'ส่งเลย', en: 'Send now' },
  'bcast.sentToast': { th: 'ส่งสำเร็จ {n} คน', en: 'Sent to {n} recipient(s)' },
  'bcast.failedCount': { th: '{n} ส่งไม่ได้', en: '{n} failed' },
  'bcast.sendFailed': { th: 'ส่งไม่สำเร็จ', en: 'Send failed' },

  /* status badge labels */
  'bcast.statusDraft': { th: 'ฉบับร่าง', en: 'Draft' },
  'bcast.statusScheduled': { th: 'ตั้งเวลา', en: 'Scheduled' },
  'bcast.statusSent': { th: 'ส่งแล้ว', en: 'Sent' },

  /* delivery log modal */
  'bcast.deliveryLog': { th: 'บันทึกการส่ง', en: 'Delivery log' },
  'bcast.noLog': { th: 'ยังไม่มีบันทึกการส่ง', en: 'No delivery log yet' },
  'bcast.logSummary': { th: 'ส่งสำเร็จ {sent} / {audience} คน', en: 'Sent {sent} / {audience}' },
  'bcast.colCustomer': { th: 'ลูกค้า', en: 'Customer' },
  'bcast.channel': { th: 'ช่องทาง', en: 'Channel' },
  'bcast.colTime': { th: 'เวลา', en: 'Time' },
  'bcast.logLoadFailed': { th: 'โหลดบันทึกการส่งไม่สำเร็จ', en: 'Could not load the log' },
  'bcast.dlvDelivered': { th: 'ส่งสำเร็จ', en: 'Delivered' },
  'bcast.dlvFailed': { th: 'ส่งไม่ได้', en: 'Failed' },
  'bcast.dlvUnreachable': { th: 'ติดต่อไม่ได้', en: 'Unreachable' },

  /* audience modal + rows */
  'bcast.unreachable': { th: 'ติดต่อไม่ได้', en: 'unreachable' },
  'bcast.unreachableTip': { th: 'ไม่มี id {channel} จึงติดต่อไม่ได้', en: "No {channel} id — can't be reached" },
  'bcast.unknown': { th: 'ไม่ทราบชื่อ', en: 'Unknown' },
  'bcast.noMatch': { th: 'ไม่มีลูกค้าที่ตรงเงื่อนไข', en: 'No customers match' },
  'bcast.noMatchSub': { th: 'กลุ่มเป้าหมายนี้ยังว่างอยู่', en: 'This segment is currently empty.' },
  'bcast.noMatchSegment': { th: 'ไม่มีลูกค้าที่ตรงกับกลุ่มนี้', en: 'No customers match this segment.' },
  'bcast.audienceSummary': { th: 'ลูกค้า {count} ราย · ติดต่อได้ตอนนี้ {reachable} ราย', en: '{count} customer(s) · {reachable} reachable now' },
  'bcast.audienceLoadFailed': { th: 'โหลดกลุ่มเป้าหมายไม่สำเร็จ', en: 'Could not load audience' },

  /* new / reuse campaign modal */
  'bcast.copySuffix': { th: '(สำเนา)', en: '(copy)' },
  'bcast.reuseCampaign': { th: 'ใช้แคมเปญซ้ำ', en: 'Reuse campaign' },
  'bcast.editCampaign': { th: 'แก้ไขแคมเปญ', en: 'Edit campaign' },
  'bcast.campaignName': { th: 'ชื่อแคมเปญ', en: 'Campaign name' },
  'bcast.campaignNamePh': { th: 'เช่น โปรดึงลูกค้ากลับเดือนพฤษภาคม', en: 'e.g. May win-back offer' },
  'bcast.fieldStage': { th: 'สถานะลูกค้า', en: 'Stage' },
  'bcast.fieldTemp': { th: 'ระดับความสนใจ', en: 'Temperature' },
  'bcast.fieldInactive': { th: 'ไม่มีการเคลื่อนไหว (วัน)', en: 'Inactive (days)' },
  'bcast.scheduleSend': { th: 'ตั้งเวลาส่ง', en: 'Schedule send' },
  'bcast.scheduleHint': { th: '(เว้นว่าง = กดส่งเอง)', en: '(leave blank = send manually)' },
  'bcast.message': { th: 'ข้อความ', en: 'Message' },
  'bcast.messagePh': { th: 'ตอนนี้มีโปรพิเศษสำหรับลูกค้า…', en: 'We have a special offer for you right now…' },
  'bcast.viewList': { th: 'ดูรายชื่อ', en: 'View list' },
  'bcast.hideList': { th: 'ซ่อนรายชื่อ', en: 'Hide list' },
  'bcast.createFromThis': { th: 'สร้างจากแคมเปญนี้', en: 'Create from this' },
  'bcast.createCampaign': { th: 'สร้างแคมเปญ', en: 'Create campaign' },
  'bcast.nameRequired': { th: 'กรุณาระบุชื่อแคมเปญ', en: 'Campaign name is required' },
  'bcast.created': { th: 'สร้างแคมเปญแล้ว', en: 'Campaign created' },
  'bcast.failed': { th: 'ไม่สำเร็จ', en: 'Failed' },
  'bcast.deleteConfirmTitle': { th: 'ลบแคมเปญ?', en: 'Delete campaign?' },
  'bcast.deleteConfirmMsg': {
    th: '"{name}" จะถูกลบออกอย่างถาวร',
    en: '"{name}" will be permanently deleted.' },
  'bcast.deleted': { th: 'ลบแคมเปญแล้ว', en: 'Campaign deleted' },
  'bcast.previewSummary': { th: 'กลุ่มเป้าหมาย: {count} ราย · ติดต่อได้ {reachable} ราย', en: 'Audience: {count} customer(s) · {reachable} reachable' },

  /* stage filter / labels */
  'bcast.stageAny': { th: 'ทุกสถานะ', en: 'Any stage' },
  'bcast.stageNewLead': { th: 'ลีดใหม่', en: 'New Lead' },
  'bcast.stageInterested': { th: 'สนใจ', en: 'Interested' },
  'bcast.stageBooked': { th: 'จองแล้ว', en: 'Booked' },
  'bcast.stagePaid': { th: 'ชำระแล้ว', en: 'Paid' },
  'bcast.stageFollowup': { th: 'ติดตามผล', en: 'Follow-up' },

  /* temperature filter */
  'bcast.tempAny': { th: 'ทุกระดับความสนใจ', en: 'Any temperature' },
  'bcast.tempHot': { th: 'ร้อน', en: 'Hot' },
  'bcast.tempWarm': { th: 'อุ่น', en: 'Warm' },
  'bcast.tempCold': { th: 'เย็น', en: 'Cold' },

  /* channel filter */
  'bcast.chAll': { th: 'ทุกช่องทาง', en: 'All channels' },
  'bcast.chWeb': { th: 'แชทเว็บ', en: 'Web Chat' },
};
