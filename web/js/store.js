/* Blinks Bright — lightweight client state with a tiny pub/sub */

import { t } from './i18n.js';

const listeners = {};

export const store = {
  user: null,
  clinic: null,        // the active clinic (workspace)
  tier: 'clinic',      // 'system' (platform console) | 'clinic' (a workspace)
  canManageClinics: false,
  branches: [],
  branchId: 'all',     // active branch filter ('all' or branch id)
  dateRange: '30d',    // active date-range filter

  set(key, value) {
    this[key] = value;
    (listeners[key] || []).forEach((fn) => fn(value));
  },
  on(key, fn) {
    (listeners[key] = listeners[key] || []).push(fn);
    return () => { listeners[key] = listeners[key].filter((f) => f !== fn); };
  },
  branchName(id) {
    if (id === 'all' || id == null) return t('menu.allBranches');
    const b = this.branches.find((x) => x.id === Number(id));
    return b ? b.name : t('menu.branch');
  },
  isRole(...roles) { return this.user && roles.includes(this.user.role); },
  canManage() { return this.isRole('owner', 'super_admin', 'branch_manager'); },
  isSystem() { return this.tier === 'system'; },
};
