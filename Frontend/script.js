/**
 * SmartGym Vision — Frontend Dashboard Controller (Person 3 Deliverable)
 * Complete integration with Person 1 (CV Detection) & Person 2 (FastAPI Backend, Rules, LLM)
 *
 * UPDATED: ZONE_METADATA / EQUIPMENT_METADATA / initial appState.zones /
 * appState.equipment now match the REAL gym layout confirmed from your
 * camera stills (Squat Rack & Bench Area, Free Weights Aisle, Cable /
 * Functional Trainer Zone, Machine Row — 11 pieces of equipment total),
 * matching backend/data/zones_config.json exactly. Previously this file
 * still had placeholder treadmill/pull-up-station metadata from before
 * the real equipment list was confirmed.
 */

// ============================================================================
// 1. Global State & Configuration
// ============================================================================
const CONFIG = {
  BACKEND_BASE_URL: 'http://127.0.0.1:8001',
  POLLING_INTERVAL_SEC: 5,
  GYM_CAPACITY: 50,
  AUTH: {
    USERNAME: 'admin',
    PASSWORD: 'password'
  },
  ENDPOINTS: {
    HEALTH: '/',
    SUMMARY: '/stats/summary',
    CURRENT: '/stats/current',
    PEAK_TIMES: '/stats/peak-times',
    HOURLY: '/stats/hourly',
    HEATMAP: '/stats/heatmap',
    EQUIPMENT: '/equipment/status',
    RECOMMENDATION: '/recommendations/latest',
    GENERATE_REC: '/recommendations/generate',
    MONTHLY_REPORT: '/recommendations/monthly-report',
    GENERATE_MONTHLY_REPORT: '/recommendations/monthly-report/generate'
  }
};

// Real gym zone metadata — matches backend/data/zones_config.json exactly.
// x/y/w/h are in the 350x300 virtual canvas space used by drawFloorHeatmap()
// and the video overlay (NOT the same pixel space as zones_config.json's
// real-video bboxes, which are calibrated separately via draw_zones.py).
const ZONE_METADATA = {
  zone_squat_bench: { name: 'Squat Rack & Bench Area', capacity: 15, x: 10, y: 20, w: 98, h: 220, color: '#f43f5e' },
  zone_freeweights_aisle: { name: 'Free Weights Aisle', capacity: 10, x: 116, y: 20, w: 61, h: 220, color: '#06b6d4' },
  zone_cable_stations: { name: 'Cable / Functional Trainer Zone', capacity: 12, x: 185, y: 20, w: 86, h: 220, color: '#10b981' },
  zone_machine_row: { name: 'Machine Row', capacity: 10, x: 279, y: 20, w: 61, h: 220, color: '#8b5cf6' },
};

// Real equipment catalog — matches backend/data/zones_config.json exactly.
const EQUIPMENT_METADATA = {
  squat_rack_1: { name: 'Squat Rack #1', zone: 'Squat Rack & Bench Area', usageRate: 90, roi: [15, 30, 35, 50] },
  squat_rack_2: { name: 'Squat Rack #2', zone: 'Squat Rack & Bench Area', usageRate: 80, roi: [55, 30, 35, 50] },
  adjustable_bench_1: { name: 'Adjustable Bench #1', zone: 'Squat Rack & Bench Area', usageRate: 65, roi: [15, 90, 35, 40] },
  adjustable_bench_2: { name: 'Adjustable Bench #2', zone: 'Squat Rack & Bench Area', usageRate: 55, roi: [55, 90, 35, 40] },
  dumbbell_rack_1: { name: 'Dumbbell Rack', zone: 'Free Weights Aisle', usageRate: 85, roi: [125, 40, 40, 160] },
  cable_station_1: { name: 'Cable Crossover #1', zone: 'Cable / Functional Trainer Zone', usageRate: 70, roi: [190, 35, 25, 60] },
  cable_station_2: { name: 'Cable Crossover #2', zone: 'Cable / Functional Trainer Zone', usageRate: 65, roi: [220, 35, 25, 60] },
  cable_station_3: { name: 'Cable Crossover #3', zone: 'Cable / Functional Trainer Zone', usageRate: 50, roi: [248, 35, 20, 60] },
  leg_press_sled_1: { name: 'Leg Press / Hack Squat #1', zone: 'Machine Row', usageRate: 60, roi: [283, 35, 25, 55] },
  leg_press_sled_2: { name: 'Leg Press / Hack Squat #2', zone: 'Machine Row', usageRate: 50, roi: [283, 100, 25, 55] },
  chest_press_machine_1: { name: 'Chest / Shoulder Press Machine', zone: 'Machine Row', usageRate: 55, roi: [283, 165, 25, 55] },
};

// Configured surveillance cameras metadata
const CAMERA_CONFIGS = {
  cam1: {
    id: 'cam1',
    name: 'CAM 01 — Squat Rack & Bench Area',
    zoneId: 'zone_squat_bench',
    zoneName: 'Squat Rack & Bench Area',
    videoFile: 'assets/cam1.mp4',
    fps: 58.6,
    frameWidth: 832,
    frameHeight: 384
  },
  cam2: {
    id: 'cam2',
    name: 'CAM 02 — Free Weights Aisle',
    zoneId: 'zone_freeweights_aisle',
    zoneName: 'Free Weights Aisle',
    videoFile: 'assets/cam2.mp4',
    fps: 59.3,
    frameWidth: 816,
    frameHeight: 464
  },
  cam3: {
    id: 'cam3',
    name: 'CAM 03 — Cable & Functional Zone',
    zoneId: 'zone_cable_stations',
    zoneName: 'Cable / Functional Trainer Zone',
    videoFile: 'assets/cam3.mp4',
    fps: 59.2,
    frameWidth: 832,
    frameHeight: 464
  },
  cam4: {
    id: 'cam4',
    name: 'CAM 04 — Machine Row',
    zoneId: 'zone_machine_row',
    zoneName: 'Machine Row',
    videoFile: 'assets/cam4.mp4',
    fps: 58.2,
    frameWidth: 816,
    frameHeight: 464
  },
  demo: {
    id: 'demo',
    name: 'CAM Overview — Main Floor (Wide Angle)',
    zoneId: 'zone_overview',
    zoneName: 'Main Gym Floor Overview',
    videoFile: 'assets/demo_video.mp4',
    fps: 25.0,
    frameWidth: 1920,
    frameHeight: 1080
  }
};

let appState = {
  isAuthenticated: false,
  is12HourFormat: true,
  activePage: 'pageLiveFeed',
  activeCamera: 'cam1',
  cameraTracks: {},
  mode: 'DEMO_SIMULATION', // 'LIVE_BACKEND' | 'DEMO_SIMULATION'
  backendAvailable: false,
  countdown: CONFIG.POLLING_INTERVAL_SEC,
  pollingTimer: null,
  activeFilter: 'all',
  activeChartRange: 'today',
  selectedZone: null,
  aiDetectionsEnabled: true,
  roiOverlayEnabled: true,
  isVideoPlaying: true,

  // Real-time telemetry
  headcount: 24,
  capacity: CONFIG.GYM_CAPACITY,
  peakForecast: {
    peakHours: '18:00 - 20:00',
    predictedHeadcount: 44,
    mismatchHours: '+1.5 hrs'
  },

  // Floor zones — real layout (4 zones), initial placeholder counts until
  // the first live/seeded fetch overwrites them.
  zones: [
    { id: 'zone_squat_bench', name: 'Squat Rack & Bench Area', count: 9, capacity: 15, x: 10, y: 20, w: 98, h: 220, color: '#f43f5e', heat: 0.60 },
    { id: 'zone_freeweights_aisle', name: 'Free Weights Aisle', count: 6, capacity: 10, x: 116, y: 20, w: 61, h: 220, color: '#06b6d4', heat: 0.60 },
    { id: 'zone_cable_stations', name: 'Cable / Functional Trainer Zone', count: 7, capacity: 12, x: 185, y: 20, w: 86, h: 220, color: '#10b981', heat: 0.58 },
    { id: 'zone_machine_row', name: 'Machine Row', count: 4, capacity: 10, x: 279, y: 20, w: 61, h: 220, color: '#8b5cf6', heat: 0.40 },
  ],

  // Equipment list — real layout (11 items)
  equipment: [
    { id: 'squat_rack_1', name: 'Squat Rack #1', zone: 'Squat Rack & Bench Area', status: 'in_use', idleMinutes: 0, usageRate: 90, roi: [15, 30, 35, 50] },
    { id: 'squat_rack_2', name: 'Squat Rack #2', zone: 'Squat Rack & Bench Area', status: 'in_use', idleMinutes: 0, usageRate: 80, roi: [55, 30, 35, 50] },
    { id: 'adjustable_bench_1', name: 'Adjustable Bench #1', zone: 'Squat Rack & Bench Area', status: 'available', idleMinutes: 6, usageRate: 65, roi: [15, 90, 35, 40] },
    { id: 'adjustable_bench_2', name: 'Adjustable Bench #2', zone: 'Squat Rack & Bench Area', status: 'available', idleMinutes: 10, usageRate: 55, roi: [55, 90, 35, 40] },
    { id: 'dumbbell_rack_1', name: 'Dumbbell Rack', zone: 'Free Weights Aisle', status: 'in_use', idleMinutes: 0, usageRate: 85, roi: [125, 40, 40, 160] },
    { id: 'cable_station_1', name: 'Cable Crossover #1', zone: 'Cable / Functional Trainer Zone', status: 'in_use', idleMinutes: 0, usageRate: 70, roi: [190, 35, 25, 60] },
    { id: 'cable_station_2', name: 'Cable Crossover #2', zone: 'Cable / Functional Trainer Zone', status: 'available', idleMinutes: 4, usageRate: 65, roi: [220, 35, 25, 60] },
    { id: 'cable_station_3', name: 'Cable Crossover #3', zone: 'Cable / Functional Trainer Zone', status: 'available', idleMinutes: 12, usageRate: 50, roi: [248, 35, 20, 60] },
    { id: 'leg_press_sled_1', name: 'Leg Press / Hack Squat #1', zone: 'Machine Row', status: 'in_use', idleMinutes: 0, usageRate: 60, roi: [283, 35, 25, 55] },
    { id: 'leg_press_sled_2', name: 'Leg Press / Hack Squat #2', zone: 'Machine Row', status: 'available', idleMinutes: 8, usageRate: 50, roi: [283, 100, 25, 55] },
    { id: 'chest_press_machine_1', name: 'Chest / Shoulder Press Machine', zone: 'Machine Row', status: 'available', idleMinutes: 3, usageRate: 55, roi: [283, 165, 25, 55] },
  ],

  // Recommendations
  recommendation: {
    severity: 'HIGH',
    ruleId: 'Rule #1: Zone Imbalance & Rule #2: Idle Equipment',
    narrative: 'High traffic imbalance detected in the Squat Rack & Bench Area relative to the gym average. Watch Machine Row equipment for extended idle periods during peak hours.',
    metrics: {
      freeWeightsLoad: '73%',
      functionalLoad: '20%',
      peakMismatch: '+1.5 hrs',
      idleAlert: 'Nominal'
    },
    timestamp: 'Just now'
  },

  // Hourly Peak Trend for Chart.js
  hourlyTrend: {
    hours: ['06:00', '08:00', '10:00', '12:00', '14:00', '16:00', '18:00', '20:00', '22:00'],
    today: [8, 22, 18, 26, 20, 32, 46, 41, 14],
    historicalAvg: [10, 20, 15, 22, 18, 28, 42, 38, 12]
  },

  weeklyPeakMatrix: {
    days: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
    peakCounts: [48, 46, 47, 44, 38, 35, 29]
  },

  monthlyReport: null
};

// Chart.js instance reference
let peakChartInstance = null;

// Synthetic Video & AI overlay animation variables
let visionPersons = [];
let animFrameId = null;

// ============================================================================
// 2. Initialization & Authentication
// ============================================================================
document.addEventListener('DOMContentLoaded', () => {
  if (window.lucide) {
    lucide.createIcons();
  }

  initClock();
  bindAuthEvents();
  bindNavigationEvents();
  bindControls();

  if (sessionStorage.getItem('smartgym_auth') === 'true') {
    unlockDashboard();
  }
});

function bindAuthEvents() {
  const loginForm = document.getElementById('loginForm');
  const usernameInput = document.getElementById('usernameInput');
  const passwordInput = document.getElementById('passwordInput');
  const errorMsg = document.getElementById('loginErrorMsg');

  loginForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const user = usernameInput.value.trim();
    const pass = passwordInput.value.trim();

    if (user === CONFIG.AUTH.USERNAME && pass === CONFIG.AUTH.PASSWORD) {
      errorMsg.style.display = 'none';
      sessionStorage.setItem('smartgym_auth', 'true');
      unlockDashboard();
      showToast('Signed in successfully as Administrator', 'success');
    } else {
      errorMsg.style.display = 'flex';
    }
  });

  document.getElementById('logoutBtn').addEventListener('click', () => {
    sessionStorage.removeItem('smartgym_auth');
    appState.isAuthenticated = false;
    if (appState.pollingTimer) clearInterval(appState.pollingTimer);
    document.getElementById('appShell').style.display = 'none';
    document.getElementById('loginView').style.display = 'flex';
    showToast('Signed out of dashboard', 'success');
  });
}

function unlockDashboard() {
  appState.isAuthenticated = true;
  document.getElementById('loginView').style.display = 'none';
  document.getElementById('appShell').style.display = 'flex';

  initSyntheticPersons();
  initPeakChart();
  initFloorHeatmap();
  initVideoFeedOverlay();
  switchCamera('cam1');

  // Test backend and start polling
  detectBackendServer();
  startPollingLoop();
  renderDashboard();

  if (window.lucide) {
    lucide.createIcons();
  }
}

// ============================================================================
// 3. Tab Navigation
// ============================================================================
function bindNavigationEvents() {
  const navTabs = document.querySelectorAll('.nav-tab');
  navTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const targetPageId = tab.getAttribute('data-page');
      switchPage(targetPageId);
    });
  });
}

function switchPage(pageId) {
  appState.activePage = pageId;

  document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.classList.toggle('active', tab.getAttribute('data-page') === pageId);
  });

  document.querySelectorAll('.app-page').forEach(page => {
    page.classList.toggle('active', page.id === pageId);
  });

  if (pageId === 'pageHeatmap') {
    setTimeout(resizeAndDrawHeatmap, 60);
  } else if (pageId === 'pageAnalytics') {
    setTimeout(updateChartData, 60);
  }

  if (window.lucide) {
    lucide.createIcons();
  }
}

// ============================================================================
// 4. Live Clock & Time Switcher
// ============================================================================
function initClock() {
  const clockEl = document.getElementById('liveClock');
  const toggleBtn = document.getElementById('timeFormatToggleBtn');
  const badgeEl = document.getElementById('timeFormatBadge');

  function updateClockDisplay() {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('en-US', {
      hour12: appState.is12HourFormat,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });

    const dateStr = now.toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric'
    });

    if (clockEl) clockEl.textContent = `${timeStr} | ${dateStr}`;
  }

  if (toggleBtn) {
    toggleBtn.addEventListener('click', () => {
      appState.is12HourFormat = !appState.is12HourFormat;
      if (badgeEl) badgeEl.textContent = appState.is12HourFormat ? '12H (AM/PM)' : '24H';
      updateClockDisplay();
      showToast(`Clock format: ${appState.is12HourFormat ? '12-Hour (AM/PM)' : '24-Hour'}`, 'success');
    });
  }

  updateClockDisplay();
  setInterval(updateClockDisplay, 1000);
}

// ============================================================================
// 5. Backend Polling & API Integration (Person 3 Deliverable)
// ============================================================================
async function detectBackendServer() {
  const statusDot = document.getElementById('statusDot');
  const statusText = document.getElementById('backendStatusText');

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 1800);

    const res = await fetch(`${CONFIG.BACKEND_BASE_URL}${CONFIG.ENDPOINTS.HEALTH}`, {
      signal: controller.signal
    });
    clearTimeout(timeoutId);

    if (res.ok) {
      appState.mode = 'LIVE_BACKEND';
      appState.backendAvailable = true;
      if (statusDot) statusDot.className = 'status-dot online';
      if (statusText) statusText.textContent = 'Backend: Online (Live API)';
      await fetchAllBackendData();
      return;
    }
  } catch (err) {
    // Graceful offline simulation mode
    appState.mode = 'DEMO_SIMULATION';
    appState.backendAvailable = false;
    if (statusDot) statusDot.className = 'status-dot online';
    if (statusText) statusText.textContent = 'Backend: Offline (Demo Mode)';
  }

  renderDashboard();
}

function startPollingLoop() {
  appState.countdown = CONFIG.POLLING_INTERVAL_SEC;

  if (appState.pollingTimer) clearInterval(appState.pollingTimer);

  appState.pollingTimer = setInterval(async () => {
    appState.countdown--;

    if (appState.countdown <= 0) {
      appState.countdown = CONFIG.POLLING_INTERVAL_SEC;
      await performDataFetch();
    }
  }, 1000);
}

async function performDataFetch() {
  if (appState.mode === 'LIVE_BACKEND') {
    try {
      await fetchAllBackendData();
    } catch (e) {
      console.warn('Backend fetch failed, falling back to simulated tick:', e);
      simulateDynamicDataUpdate();
    }
  } else {
    simulateDynamicDataUpdate();
  }

  renderDashboard();
}

async function fetchAllBackendData() {
  const baseUrl = CONFIG.BACKEND_BASE_URL;

  try {
    const [currentRes, equipRes, recRes, hourlyRes, peakRes] = await Promise.all([
      fetch(`${baseUrl}${CONFIG.ENDPOINTS.CURRENT}`).then(r => r.ok ? r.json() : null).catch(() => null),
      fetch(`${baseUrl}${CONFIG.ENDPOINTS.EQUIPMENT}`).then(r => r.ok ? r.json() : null).catch(() => null),
      fetch(`${baseUrl}${CONFIG.ENDPOINTS.RECOMMENDATION}`).then(r => r.ok ? r.json() : null).catch(() => null),
      fetch(`${baseUrl}${CONFIG.ENDPOINTS.HOURLY}?hours=24`).then(r => r.ok ? r.json() : null).catch(() => null),
      fetch(`${baseUrl}${CONFIG.ENDPOINTS.PEAK_TIMES}?top_n=5`).then(r => r.ok ? r.json() : null).catch(() => null)
    ]);

    // 1. Process Live Headcount & Zones
    if (currentRes && currentRes.zones) {
      appState.headcount = currentRes.total_count || 0;

      // Deduplicate zones: keep only the latest record per zone_id
      // (backend may return multiple rows for the same zone from different time slices)
      const seenZoneIds = new Map();
      currentRes.zones.forEach(z => {
        // Keep the entry with the highest person_count (most recent/relevant)
        const existing = seenZoneIds.get(z.zone_id);
        if (!existing || (z.person_count || 0) >= (existing.person_count || 0)) {
          seenZoneIds.set(z.zone_id, z);
        }
      });

      const uniqueZones = Array.from(seenZoneIds.values());
      const updatedZones = uniqueZones.map((z, idx) => {
        const meta = ZONE_METADATA[z.zone_id] || {
          name: z.zone_id.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
          capacity: 15,
          // Spread unknown zones in a safe grid so they never overlap
          x: 20 + (idx % 3) * 110,
          y: 20 + Math.floor(idx / 3) * 130,
          w: 100,
          h: 120,
          color: ['#f43f5e', '#06b6d4', '#10b981', '#8b5cf6', '#3b82f6'][idx % 5]
        };

        const count = z.person_count || 0;
        const heat = Math.min(1.0, +(count / meta.capacity).toFixed(2));

        return {
          id: z.zone_id,
          name: meta.name,
          count: count,
          capacity: meta.capacity,
          x: meta.x,
          y: meta.y,
          w: meta.w,
          h: meta.h,
          color: meta.color,
          heat: heat
        };
      });

      if (updatedZones.length > 0) {
        appState.zones = updatedZones;
        appState.capacity = updatedZones.reduce((sum, z) => sum + (z.capacity || 0), 0);
      }
    }

    // 2. Process Equipment Status
    if (equipRes && equipRes.equipment && equipRes.equipment.length > 0) {
      appState.equipment = equipRes.equipment.map((eq, idx) => {
        const meta = EQUIPMENT_METADATA[eq.equipment_id] || {
          name: eq.equipment_id.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
          zone: (eq.zone_id || 'Main Zone').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
          usageRate: Math.max(20, Math.min(95, 85 - idx * 8)),
          roi: [30 + (idx % 3) * 105, 45 + Math.floor(idx / 3) * 90, 70, 50]
        };

        let status = eq.status === 'in_use' ? 'in_use' : 'available';
        const idleMins = Math.round(eq.idle_minutes || 0);

        if (status === 'available' && idleMins >= 45) {
          status = 'malfunction';
        }

        return {
          id: eq.equipment_id,
          name: meta.name,
          zone: meta.zone,
          status: status,
          idleMinutes: idleMins,
          usageRate: meta.usageRate,
          roi: meta.roi
        };
      });
    }

    // 3. Process Live Recommendation
    if (recRes && recRes.recommendation) {
      appState.recommendation = {
        severity: 'HIGH',
        ruleId: recRes.based_on_triggers && recRes.based_on_triggers.length > 0
          ? `Rule Triggers (${recRes.based_on_triggers.length} Active)`
          : 'Rule #1: Zone Imbalance & Telemetry Checks',
        narrative: recRes.recommendation,
        metrics: {
          freeWeightsLoad: `${Math.round((appState.zones[0]?.heat || 0.7) * 100)}%`,
          functionalLoad: `${Math.round((appState.zones[appState.zones.length - 1]?.heat || 0.2) * 100)}%`,
          peakMismatch: '+1.5 hrs',
          idleAlert: appState.equipment.find(e => e.status === 'malfunction')?.name.split(' ')[0] || 'Nominal'
        },
        timestamp: recRes.timestamp ? new Date(recRes.timestamp).toLocaleTimeString('en-US', {
          hour12: appState.is12HourFormat, hour: '2-digit', minute: '2-digit'
        }) : 'Just now'
      };
    }

    // 4. Process Hourly Stats for Charts
    if (hourlyRes && hourlyRes.data && hourlyRes.data.length > 0) {
      const hourMap = new Map();
      hourlyRes.data.forEach(row => {
        const hourStr = row.hour_start ? new Date(row.hour_start).getHours() + ':00' : '12:00';
        const currentAvg = hourMap.get(hourStr) || 0;
        hourMap.set(hourStr, currentAvg + (row.avg_person_count || 0));
      });

      if (hourMap.size > 0) {
        appState.hourlyTrend.hours = Array.from(hourMap.keys());
        appState.hourlyTrend.today = Array.from(hourMap.values()).map(v => Math.round(v));
      }
    }

    // 5. Process Peak Times
    if (peakRes && peakRes.peak_times && peakRes.peak_times.length > 0) {
      const busiest = peakRes.peak_times[0];
      if (busiest) {
        // Format hour as "06:00 PM – 08:00 PM" style range
        const startHour = parseInt(busiest.hour) || 18;
        const endHour = startHour + 2;
        const fmt = (h) => {
          const period = h >= 12 ? 'PM' : 'AM';
          const h12 = h % 12 === 0 ? 12 : h % 12;
          return `${String(h12).padStart(2, '0')}:00 ${period}`;
        };
        document.getElementById('peakHourVal').textContent = `${fmt(startHour)} – ${fmt(endHour)}`;
        const estLoad = Math.round(busiest.avg_total_person_count || busiest.avg_person_count || 42);
        document.getElementById('peakStatusBadge').textContent = `Est. Load: ${estLoad} People`;
      }
    }

  } catch (e) {
    console.error('Error parsing backend payload:', e);
  }
}

// Fallback dynamic simulator for seamless offline demos
function simulateDynamicDataUpdate() {
  const delta = Math.floor(Math.random() * 5) - 2;
  appState.headcount = Math.max(8, Math.min(CONFIG.GYM_CAPACITY, appState.headcount + delta));

  let remaining = appState.headcount;
  if (appState.zones.length >= 3) {
    appState.zones[0].count = Math.min(appState.zones[0].capacity, Math.floor(remaining * 0.45) + (Math.random() > 0.5 ? 1 : 0));
    remaining -= appState.zones[0].count;

    appState.zones[1].count = Math.min(appState.zones[1].capacity, Math.floor(remaining * 0.65));
    remaining -= appState.zones[1].count;

    appState.zones[2].count = Math.max(1, remaining);

    appState.zones.forEach(z => {
      z.heat = Math.min(1.0, +(z.count / z.capacity).toFixed(2));
    });
  }

  if (Math.random() > 0.7 && appState.equipment.length > 0) {
    const eq = appState.equipment[Math.floor(Math.random() * appState.equipment.length)];
    if (eq.id !== 'chest_press_machine_1') {
      eq.status = eq.status === 'in_use' ? 'available' : 'in_use';
      eq.idleMinutes = eq.status === 'available' ? Math.floor(Math.random() * 12) : 0;
    }
  }

  // Keep one item drifting toward "possible malfunction" for demo clarity
  const watchItem = appState.equipment.find(e => e.id === 'chest_press_machine_1');
  if (watchItem && watchItem.status !== 'in_use') {
    watchItem.idleMinutes += 1;
    if (watchItem.idleMinutes >= 45) watchItem.status = 'malfunction';
  }
}

// ============================================================================
// 6. View Rendering
// ============================================================================
function renderDashboard() {
  renderKpiBar();
  renderZonesSummary();
  renderEquipmentTable();
  renderRecommendations();
  drawFloorHeatmap();

  if (window.lucide) {
    lucide.createIcons();
  }
}

function renderKpiBar() {
  // Dynamically compute total facility capacity from all active physical zones in real-time
  const dynamicCapacity = appState.zones.reduce((sum, z) => sum + (z.capacity || 0), 0);
  appState.capacity = dynamicCapacity > 0 ? dynamicCapacity : CONFIG.GYM_CAPACITY;

  const hcEl = document.getElementById('headcountVal');
  const capEl = document.getElementById('capacityVal');
  if (hcEl) hcEl.textContent = appState.headcount;
  if (capEl) capEl.textContent = appState.capacity;

  const occupancyRate = Math.round((appState.headcount / appState.capacity) * 100);
  const badgeEl = document.getElementById('occupancyBadge');
  if (badgeEl) {
    badgeEl.textContent = `${occupancyRate}% Capacity`;
    if (occupancyRate >= 80) badgeEl.className = 'qk-badge alert';
    else if (occupancyRate >= 50) badgeEl.className = 'qk-badge violet';
    else badgeEl.className = 'qk-badge normal';
  }

  // Equipment: show how many are available, not % active
  const inUseCount = appState.equipment.filter(e => e.status === 'in_use').length;
  const availableCount = appState.equipment.filter(e => e.status === 'available').length;
  const eqRatioEl = document.getElementById('equipmentActiveRatio');
  if (eqRatioEl) eqRatioEl.textContent = `${inUseCount} / ${appState.equipment.length}`;

  const eqActiveBadge = document.getElementById('eqActiveBadge');
  if (eqActiveBadge && appState.equipment.length > 0) {
    if (availableCount === 0) {
      eqActiveBadge.textContent = 'All Units Occupied';
      eqActiveBadge.className = 'qk-badge alert';
    } else {
      eqActiveBadge.textContent = `${availableCount} Unit${availableCount > 1 ? 's' : ''} Available`;
      eqActiveBadge.className = 'qk-badge violet';
    }
  }

  // Update the "All Units (N)" filter tab to match the real equipment count
  const allTab = document.querySelector('.filter-tab[data-filter="all"]');
  if (allTab) allTab.textContent = `All Units (${appState.equipment.length})`;

  // Disparity: % of total people concentrated in the busiest zone vs even distribution
  if (appState.zones.length > 0) {
    const totalPeople = appState.headcount || 1; // avoid divide by zero
    // Use actual people counts if available, else fall back to heat * capacity
    const zoneCounts = appState.zones.map(z =>
      (z.count !== undefined) ? z.count : Math.round(z.heat * (z.capacity || 20))
    );
    const totalZonePeople = zoneCounts.reduce((a, b) => a + b, 0) || 1;
    const maxZoneCount = Math.max(...zoneCounts);
    const minZoneCount = Math.min(...zoneCounts);

    // What % of gym people are in the busiest zone vs what's expected if even
    const busiestShare = Math.round((maxZoneCount / totalZonePeople) * 100);
    const evenShare = Math.round(100 / appState.zones.length);   // e.g. 25% for 4 zones
    const disparity = Math.max(0, busiestShare - evenShare);     // how many % above fair share

    const imbalanceEl = document.getElementById('zoneImbalanceVal');
    if (imbalanceEl) imbalanceEl.textContent = `${busiestShare}%`;  // busiest zone's share

    // Rebalance when busiest zone holds 30%+ more people than fair share
    const zoneAlertBadge = document.getElementById('zoneAlertBadge');
    if (zoneAlertBadge) {
      if (disparity >= 30) {
        zoneAlertBadge.textContent = 'Rebalance Suggested';
        zoneAlertBadge.className = 'qk-badge alert';
      } else if (disparity >= 15) {
        zoneAlertBadge.textContent = 'Moderate Imbalance';
        zoneAlertBadge.className = 'qk-badge violet';
      } else {
        zoneAlertBadge.textContent = 'Well Distributed';
        zoneAlertBadge.className = 'qk-badge normal';
      }
    }
  }
}

function renderZonesSummary() {
  const container = document.getElementById('zonesSummaryGrid');
  if (!container) return;

  container.innerHTML = appState.zones.map(zone => {
    const isSelected = appState.selectedZone === zone.id;
    let badgeColor = 'low';
    if (zone.heat > 0.8) badgeColor = 'alert';
    else if (zone.heat > 0.5) badgeColor = 'high';
    else if (zone.heat > 0.25) badgeColor = 'med';

    return `
      <div class="zone-chip ${isSelected ? 'selected' : ''}" data-zone-id="${zone.id}">
        <span class="zone-chip-title">${zone.name}</span>
        <div class="zone-chip-data">
          <span><span class="color-dot ${badgeColor}"></span> ${zone.count} / ${zone.capacity} People</span>
          <span style="color: var(--text-muted); font-size: 0.75rem; font-family: var(--font-mono);">${Math.round(zone.heat * 100)}%</span>
        </div>
      </div>
    `;
  }).join('');

  container.querySelectorAll('.zone-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const zoneId = chip.getAttribute('data-zone-id');
      appState.selectedZone = appState.selectedZone === zoneId ? null : zoneId;
      renderDashboard();
    });
  });
}

function renderEquipmentTable() {
  const tbody = document.getElementById('equipmentTableBody');
  if (!tbody) return;

  const filtered = appState.equipment.filter(eq => {
    if (appState.activeFilter === 'all') return true;
    if (appState.activeFilter === 'in_use') return eq.status === 'in_use';
    if (appState.activeFilter === 'available') return eq.status === 'available';
    if (appState.activeFilter === 'malfunction') return eq.status === 'malfunction';
    return true;
  });

  tbody.innerHTML = filtered.map(eq => {
    let statusBadge = '';
    if (eq.status === 'in_use') {
      statusBadge = `<span class="eq-status-badge in_use"><i data-lucide="check"></i> In Use</span>`;
    } else if (eq.status === 'available') {
      statusBadge = `<span class="eq-status-badge available"><i data-lucide="circle"></i> Available</span>`;
    } else {
      statusBadge = `<span class="eq-status-badge malfunction"><i data-lucide="alert-triangle"></i> Maintenance Alert</span>`;
    }

    const idleDisplay = eq.status === 'in_use' ? '0m' : `${eq.idleMinutes} mins`;
    const isHighIdle = eq.idleMinutes >= 45;

    return `
      <tr>
        <td style="font-family: var(--font-mono); font-weight: 700; color: var(--accent-cyan);">${eq.id}</td>
        <td><strong>${eq.name}</strong></td>
        <td style="color: var(--text-muted);">${eq.zone}</td>
        <td>${statusBadge}</td>
        <td class="idle-time-tag ${isHighIdle ? 'high' : ''}">${idleDisplay}</td>
        <td>
          <div style="display: flex; align-items: center; gap: 0.6rem;">
            <div style="flex: 1; max-width: 100px; height: 5px; background: rgba(255,255,255,0.08); border-radius: 3px;">
              <div style="width: ${eq.usageRate}%; height: 100%; background: ${eq.usageRate > 85 ? 'var(--accent-rose)' : 'var(--accent-emerald)'}; border-radius: 3px;"></div>
            </div>
            <span style="font-size: 0.78rem; font-family: var(--font-mono);">${eq.usageRate}%</span>
          </div>
        </td>
        <td>
          <button class="icon-btn-small" onclick="inspectEquipment('${eq.id}')" title="Inspect Telemetry">
            <i data-lucide="search"></i>
          </button>
        </td>
      </tr>
    `;
  }).join('');
}

function renderRecommendations() {
  const rec = appState.recommendation;
  const narrativeEl = document.getElementById('recNarrativeText');
  const ruleRefEl = document.getElementById('recRuleRef');
  const timestampEl = document.getElementById('llmTimestamp');

  if (narrativeEl) narrativeEl.innerHTML = `"${rec.narrative}"`;
  if (ruleRefEl) ruleRefEl.textContent = `Triggered by ${rec.ruleId}`;
  if (timestampEl) timestampEl.textContent = `Generated: ${rec.timestamp}`;

  const gw = document.getElementById('gmFreeWeights');
  const gf = document.getElementById('gmFunctional');
  const gm = document.getElementById('gmPeakMismatch');
  const gi = document.getElementById('gmIdleAlert');

  if (gw) gw.textContent = rec.metrics.freeWeightsLoad;
  if (gf) gf.textContent = rec.metrics.functionalLoad;
  if (gm) gm.textContent = rec.metrics.peakMismatch;
  if (gi) gi.textContent = rec.metrics.idleAlert;
}

// ============================================================================
// 7. Interactive Floor Plan Heatmap
// ============================================================================
function resizeAndDrawHeatmap() {
  const canvas = document.getElementById('gymFloorCanvas');
  const container = document.getElementById('heatmapContainer');
  if (!canvas || !container || !container.clientWidth) return;
  canvas.width = container.clientWidth * window.devicePixelRatio;
  canvas.height = container.clientHeight * window.devicePixelRatio;
  drawFloorHeatmap();
}

function initFloorHeatmap() {
  const canvas = document.getElementById('gymFloorCanvas');
  const container = document.getElementById('heatmapContainer');
  if (!canvas || !container) return;

  window.addEventListener('resize', resizeAndDrawHeatmap);
  setTimeout(resizeAndDrawHeatmap, 60);

  const tooltip = document.getElementById('zoneTooltip');
  canvas.addEventListener('mousemove', (e) => {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / (rect.width * window.devicePixelRatio);
    const scaleY = canvas.height / (rect.height * window.devicePixelRatio);
    const mouseX = (e.clientX - rect.left) * scaleX;
    const mouseY = (e.clientY - rect.top) * scaleY;

    const normX = (mouseX / canvas.width) * 350;
    const normY = (mouseY / canvas.height) * 300;

    let hoveredZone = null;
    for (const z of appState.zones) {
      if (normX >= z.x && normX <= z.x + z.w && normY >= z.y && normY <= z.y + z.h) {
        hoveredZone = z;
        break;
      }
    }

    if (hoveredZone && tooltip) {
      tooltip.style.display = 'block';
      tooltip.style.left = `${e.clientX - rect.left + 12}px`;
      tooltip.style.top = `${e.clientY - rect.top + 12}px`;
      tooltip.innerHTML = `
        <div style="font-weight: 700; color: #fff;">${hoveredZone.name}</div>
        <div style="color: var(--accent-cyan); font-size: 0.78rem;">Occupancy: <strong>${hoveredZone.count} / ${hoveredZone.capacity}</strong> (${Math.round(hoveredZone.heat * 100)}%)</div>
      `;
    } else if (tooltip) {
      tooltip.style.display = 'none';
    }
  });

  canvas.addEventListener('mouseleave', () => {
    if (tooltip) tooltip.style.display = 'none';
  });

  canvas.addEventListener('click', (e) => {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / (rect.width * window.devicePixelRatio);
    const scaleY = canvas.height / (rect.height * window.devicePixelRatio);
    const mouseX = (e.clientX - rect.left) * scaleX;
    const mouseY = (e.clientY - rect.top) * scaleY;

    const normX = (mouseX / canvas.width) * 350;
    const normY = (mouseY / canvas.height) * 300;

    for (const z of appState.zones) {
      if (normX >= z.x && normX <= z.x + z.w && normY >= z.y && normY <= z.y + z.h) {
        appState.selectedZone = appState.selectedZone === z.id ? null : z.id;
        renderDashboard();
        break;
      }
    }
  });
}

function drawFloorHeatmap() {
  const canvas = document.getElementById('gymFloorCanvas');
  if (!canvas || !canvas.width) return;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const w = canvas.width;
  const h = canvas.height;

  ctx.clearRect(0, 0, w, h);
  ctx.save();
  ctx.scale(w / 350, h / 300);

  // Background gym floor blueprint
  ctx.fillStyle = '#0a101f';
  ctx.fillRect(0, 0, 350, 300);

  // Floor grid
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.04)';
  ctx.lineWidth = 1;
  for (let x = 0; x < 350; x += 20) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, 300); ctx.stroke();
  }
  for (let y = 0; y < 300; y += 20) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(350, y); ctx.stroke();
  }

  // Truncate to a box's actual pixel width (measured, not guessed) — used
  // by both zone and equipment labels below so long names never overflow
  // past their own box into a neighbor's.
  function fitText(text, maxWidth) {
    if (ctx.measureText(text).width <= maxWidth) return text;
    let truncated = text;
    while (truncated.length > 1 && ctx.measureText(truncated + '…').width > maxWidth) {
      truncated = truncated.slice(0, -1);
    }
    return truncated + '…';
  }

  // Draw Heatmap Zones
  appState.zones.forEach(zone => {
    const isSelected = appState.selectedZone === zone.id;
    const centerX = zone.x + zone.w / 2;
    const centerY = zone.y + zone.h / 2;
    const radius = Math.max(zone.w, zone.h) * 0.65;

    const heatGrad = ctx.createRadialGradient(centerX, centerY, 5, centerX, centerY, radius);
    if (zone.heat > 0.8) {
      heatGrad.addColorStop(0, 'rgba(244, 63, 94, 0.45)');
      heatGrad.addColorStop(0.6, 'rgba(245, 158, 11, 0.25)');
      heatGrad.addColorStop(1, 'rgba(244, 63, 94, 0.0)');
    } else if (zone.heat > 0.5) {
      heatGrad.addColorStop(0, 'rgba(245, 158, 11, 0.35)');
      heatGrad.addColorStop(0.6, 'rgba(16, 185, 129, 0.15)');
      heatGrad.addColorStop(1, 'rgba(245, 158, 11, 0.0)');
    } else {
      heatGrad.addColorStop(0, 'rgba(6, 182, 212, 0.25)');
      heatGrad.addColorStop(0.7, 'rgba(59, 130, 246, 0.1)');
      heatGrad.addColorStop(1, 'rgba(6, 182, 212, 0.0)');
    }

    ctx.fillStyle = heatGrad;
    ctx.fillRect(zone.x - 10, zone.y - 10, zone.w + 20, zone.h + 20);

    ctx.strokeStyle = isSelected ? '#ffffff' : (zone.heat > 0.8 ? '#f43f5e' : 'rgba(255, 255, 255, 0.18)');
    ctx.lineWidth = isSelected ? 2.5 : 1.5;
    ctx.strokeRect(zone.x, zone.y, zone.w, zone.h);

    const labelMaxWidth = zone.w - 10;

    ctx.fillStyle = isSelected ? '#ffffff' : 'rgba(255, 255, 255, 0.9)';
    ctx.font = 'bold 8px Outfit, sans-serif';
    ctx.fillText(fitText(zone.name, labelMaxWidth), zone.x + 6, zone.y + 14);

    ctx.fillStyle = zone.heat > 0.8 ? '#f43f5e' : '#10b981';
    ctx.font = '7px JetBrains Mono, monospace';
    ctx.fillText(fitText(`${zone.count} ppl (${Math.round(zone.heat * 100)}%)`, labelMaxWidth), zone.x + 6, zone.y + 26);
  });

  // Draw Equipment as soft glowing "heat blobs" instead of hard boxes —
  // this is what actually gives the panel a heatmap look.
  const eqCenters = appState.equipment
    .filter(e => e.roi)
    .map(e => ({ id: e.id, cx: e.roi[0] + e.roi[2] / 2, cy: e.roi[1] + e.roi[3] / 2 }));

  appState.equipment.forEach(eq => {
    if (!eq.roi) return;
    const [rx, ry, rw, rh] = eq.roi;
    const cx = rx + rw / 2;
    const cy = ry + rh / 2;
    const radius = Math.max(rw, rh) * 0.75;

    // Cap the label width at half the distance to the nearest OTHER
    // equipment marker — without this, tightly packed equipment (e.g. two
    // squat racks side by side) get labels that run into each other, even
    // though each individually "fits" its own box width.
    let nearestDist = Infinity;
    eqCenters.forEach(other => {
      if (other.id === eq.id) return;
      const d = Math.hypot(other.cx - cx, other.cy - cy);
      if (d < nearestDist) nearestDist = d;
    });
    const eqMaxWidth = Math.max(24, Math.min(rw + 14, nearestDist - 6));

    let core, mid;
    if (eq.status === 'malfunction') {
      core = 'rgba(244, 63, 94, 0.55)';
      mid = 'rgba(244, 63, 94, 0.18)';
    } else if (eq.status === 'in_use') {
      core = 'rgba(16, 185, 129, 0.55)';
      mid = 'rgba(16, 185, 129, 0.18)';
    } else {
      core = 'rgba(148, 163, 184, 0.22)';
      mid = 'rgba(148, 163, 184, 0.08)';
    }

    const blobGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius);
    blobGrad.addColorStop(0, core);
    blobGrad.addColorStop(0.55, mid);
    blobGrad.addColorStop(1, 'rgba(0,0,0,0)');

    ctx.save();
    ctx.shadowColor = eq.status === 'malfunction' ? 'rgba(244,63,94,0.6)' : (eq.status === 'in_use' ? 'rgba(16,185,129,0.6)' : 'rgba(148,163,184,0.3)');
    ctx.shadowBlur = 10;
    ctx.fillStyle = blobGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    ctx.fillStyle = eq.status === 'malfunction' ? '#f43f5e' : (eq.status === 'in_use' ? '#10b981' : 'rgba(226,232,240,0.5)');
    ctx.beginPath();
    ctx.arc(cx, cy, 2, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = 'rgba(226, 232, 240, 0.85)';
    ctx.font = '6.5px Outfit, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(fitText(eq.name, eqMaxWidth), cx, cy + radius * 0.6 + 8);
    ctx.textAlign = 'left';
  });

  ctx.restore();
}

// ============================================================================
// 8. Video Feed & Real YOLO Detection Overlay (CAM 1 - 4 & Overview)
// ============================================================================
async function loadCameraTrack(camId) {
  if (appState.cameraTracks[camId]) {
    return appState.cameraTracks[camId];
  }

  try {
    // Try fetching from local static assets first, or fallback to backend API
    const res = await fetch(`assets/detections/${camId}_detections.json`);
    if (res.ok) {
      const data = await res.json();
      appState.cameraTracks[camId] = data;
      return data;
    }
  } catch (e) {
    // try API endpoint
    try {
      const resApi = await fetch(`${CONFIG.BACKEND_BASE_URL}/live/detections/${camId}`);
      if (resApi.ok) {
        const data = await resApi.json();
        appState.cameraTracks[camId] = data;
        return data;
      }
    } catch (err) {
      console.warn(`Could not load detection track for ${camId}:`, err);
    }
  }
  return null;
}

function switchCamera(camId) {
  const config = CAMERA_CONFIGS[camId] || CAMERA_CONFIGS['cam1'];
  appState.activeCamera = camId;

  // 1. Update Video Element
  const video = document.getElementById('gymVideoFeed');
  if (video) {
    video.src = config.videoFile;
    if (appState.isVideoPlaying) {
      video.play().catch(e => console.warn('Autoplay error:', e));
    }
  }

  // 2. Update Camera Switcher UI Buttons
  document.querySelectorAll('.cam-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-cam-id') === camId);
  });

  // 3. Update Dropdown Selector
  const videoSelect = document.getElementById('videoSelect');
  if (videoSelect && videoSelect.value !== camId) {
    videoSelect.value = camId;
  }

  // 4. Update Header and HUD Elements
  const titleEl = document.getElementById('cameraFeedTitle');
  if (titleEl) titleEl.textContent = `Surveillance Stream — ${config.name}`;

  const hudCam = document.getElementById('hudCameraName');
  if (hudCam) hudCam.textContent = config.name;

  const hudFps = document.getElementById('hudFps');
  if (hudFps) hudFps.textContent = config.fps.toFixed(1);

  const hudMode = document.getElementById('hudDetectionMode');
  if (hudMode) hudMode.textContent = 'YOLOv8 + Equipment ROIs';

  // Load track metadata
  loadCameraTrack(camId).then(trackData => {
    if (trackData) {
      const trackedPersons = trackData.tracks && trackData.tracks[0] ? trackData.tracks[0].count : 0;
      const hudTracked = document.getElementById('hudTrackedCount');
      if (hudTracked) hudTracked.textContent = `${trackedPersons} Persons`;
    }
  });

  showToast(`Switched to ${config.name}`, 'info');
}

function initSyntheticPersons() {
  visionPersons = [];
  for (let i = 0; i < 24; i++) {
    visionPersons.push({
      id: `P-${100 + i}`,
      x: 30 + Math.random() * 560,
      y: 50 + Math.random() * 260,
      vx: (Math.random() - 0.5) * 0.9,
      vy: (Math.random() - 0.5) * 0.9,
      w: 28 + Math.random() * 10,
      h: 55 + Math.random() * 15,
      confidence: (0.89 + Math.random() * 0.09).toFixed(2)
    });
  }
}

function initVideoFeedOverlay() {
  const canvas = document.getElementById('aiOverlayCanvas');
  const video = document.getElementById('gymVideoFeed');
  const container = document.getElementById('videoContainer');
  if (!canvas || !container) return;

  // Pre-load active camera track
  loadCameraTrack(appState.activeCamera || 'cam1');

  function renderLoop() {
    canvas.width = container.clientWidth;
    canvas.height = container.clientHeight;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const activeCam = appState.activeCamera || 'cam1';
    const config = CAMERA_CONFIGS[activeCam] || CAMERA_CONFIGS['cam1'];
    const trackData = appState.cameraTracks[activeCam];

    if (!video || video.paused || video.readyState < 2) {
      drawSynthesizedCameraFeed(ctx, canvas.width, canvas.height);
    }

    const frameW = (trackData && trackData.frame_width) || config.frameWidth || 832;
    const frameH = (trackData && trackData.frame_height) || config.frameHeight || 384;
    const scaleX = canvas.width / frameW;
    const scaleY = canvas.height / frameH;

    let currentDetections = [];
    let currentEquipment = (trackData && trackData.equipment_rois) || [];

    if (trackData && trackData.tracks && trackData.tracks.length > 0 && video && video.duration) {
      const curTime = (video.currentTime || 0) % (trackData.duration || video.duration);
      // Find nearest timestamp entry
      let closest = trackData.tracks[0];
      let minDiff = Math.abs(closest.time - curTime);
      for (let i = 1; i < trackData.tracks.length; i++) {
        const diff = Math.abs(trackData.tracks[i].time - curTime);
        if (diff < minDiff) {
          minDiff = diff;
          closest = trackData.tracks[i];
        } else if (trackData.tracks[i].time > curTime + 1.5) {
          break;
        }
      }
      if (closest) {
        currentDetections = closest.persons || [];
        if (closest.equipment && closest.equipment.length > 0) {
          currentEquipment = closest.equipment;
        }
      }
    }

    // Update HUD Live Count with real detection count
    const hudTracked = document.getElementById('hudTrackedCount');
    if (hudTracked) {
      const activeCount = currentDetections.length > 0 ? currentDetections.length : (trackData ? 0 : appState.headcount);
      hudTracked.textContent = `${activeCount} Persons`;
    }

    // 1. Draw Real YOLO Person Bounding Boxes (Green High-Tech Boxes)
    if (appState.aiDetectionsEnabled) {
      if (currentDetections.length > 0) {
        currentDetections.forEach(p => {
          const [x1, y1, x2, y2] = p.bbox;
          const sx = x1 * scaleX;
          const sy = y1 * scaleY;
          const sw = (x2 - x1) * scaleX;
          const sh = (y2 - y1) * scaleY;

          // Main green box
          ctx.strokeStyle = '#10b981';
          ctx.lineWidth = 2.0;
          ctx.strokeRect(sx, sy, sw, sh);

          // Glowing corner accents
          const cornerLen = Math.min(12, Math.max(6, sw * 0.2));
          ctx.fillStyle = '#10b981';
          ctx.fillRect(sx, sy, cornerLen, 3);
          ctx.fillRect(sx, sy, 3, cornerLen);
          ctx.fillRect(sx + sw - cornerLen, sy, cornerLen, 3);
          ctx.fillRect(sx + sw - 3, sy, 3, cornerLen);
          ctx.fillRect(sx, sy + sh - 3, cornerLen, 3);
          ctx.fillRect(sx, sy + sh - cornerLen, 3, cornerLen);
          ctx.fillRect(sx + sw - cornerLen, sy + sh - 3, cornerLen, 3);
          ctx.fillRect(sx + sw - 3, sy + sh - cornerLen, 3, cornerLen);

          // Label Banner
          const labelText = `person ${Math.round((p.confidence || 0.88) * 100)}%`;
          ctx.font = 'bold 9px JetBrains Mono, monospace';
          const textWidth = ctx.measureText(labelText).width;

          ctx.fillStyle = 'rgba(16, 185, 129, 0.9)';
          ctx.fillRect(sx, Math.max(0, sy - 15), textWidth + 8, 15);

          ctx.fillStyle = '#022c22';
          ctx.fillText(labelText, sx + 4, Math.max(10, sy - 4));

          // Centroid Dot
          if (p.centroid) {
            const [cx, cy] = p.centroid;
            ctx.beginPath();
            ctx.arc(cx * scaleX, cy * scaleY, 3, 0, Math.PI * 2);
            ctx.fillStyle = '#10b981';
            ctx.fill();
          }
        });
      } else if (!trackData) {
        // Fallback synthetic animation if video tracks not loaded
        visionPersons.slice(0, Math.min(6, appState.headcount)).forEach(p => {
          if (appState.isVideoPlaying) {
            p.x += p.vx;
            p.y += p.vy;
            if (p.x < 20 || p.x > canvas.width - 50) p.vx *= -1;
            if (p.y < 30 || p.y > canvas.height - 75) p.vy *= -1;
          }

          ctx.strokeStyle = '#10b981';
          ctx.lineWidth = 1.8;
          ctx.strokeRect(p.x, p.y, p.w, p.h);

          const cornerLen = 6;
          ctx.fillStyle = '#10b981';
          ctx.fillRect(p.x, p.y, cornerLen, 2.5);
          ctx.fillRect(p.x, p.y, 2.5, cornerLen);
          ctx.fillRect(p.x + p.w - cornerLen, p.y, cornerLen, 2.5);
          ctx.fillRect(p.x + p.w - 2.5, p.y, 2.5, cornerLen);

          ctx.fillStyle = 'rgba(16, 185, 129, 0.85)';
          ctx.fillRect(p.x, p.y - 14, p.w + 14, 13);
          ctx.fillStyle = '#062b1e';
          ctx.font = 'bold 8.5px JetBrains Mono, monospace';
          ctx.fillText(`person ${p.confidence}`, p.x + 3, p.y - 4);
        });
      }
    }

    // 2. Draw Equipment ROI Zones (Dynamically colored by occupancy)
    if (appState.roiOverlayEnabled && currentEquipment.length > 0) {
      currentEquipment.forEach(eq => {
        if (!eq.bbox) return;
        const [x1, y1, x2, y2] = eq.bbox;
        const sx = x1 * scaleX;
        const sy = y1 * scaleY;
        const sw = (x2 - x1) * scaleX;
        const sh = (y2 - y1) * scaleY;

        const isInUse = eq.status === 'in_use';
        const isMalfunction = eq.status === 'malfunction';

        let strokeColor = 'rgba(6, 182, 212, 0.75)'; // cyan: available
        let fillColor = 'rgba(6, 182, 212, 0.06)';
        let badgeBg = 'rgba(6, 182, 212, 0.85)';
        let statusTag = 'AVAILABLE';

        if (isInUse) {
          strokeColor = 'rgba(16, 185, 129, 0.9)'; // emerald: in use
          fillColor = 'rgba(16, 185, 129, 0.16)';
          badgeBg = 'rgba(16, 185, 129, 0.9)';
          statusTag = 'IN USE';
        } else if (isMalfunction) {
          strokeColor = 'rgba(244, 63, 94, 0.95)'; // rose: maintenance
          fillColor = 'rgba(244, 63, 94, 0.25)';
          badgeBg = 'rgba(244, 63, 94, 0.95)';
          statusTag = 'ALERT';
        }

        ctx.strokeStyle = strokeColor;
        ctx.lineWidth = isInUse ? 2.0 : 1.5;
        ctx.setLineDash(isInUse ? [] : [5, 3]);
        ctx.strokeRect(sx, sy, sw, sh);
        ctx.setLineDash([]);

        ctx.fillStyle = fillColor;
        ctx.fillRect(sx, sy, sw, sh);

        // Equipment Label Badge
        const eqLabel = `${eq.name} • ${statusTag}`;
        ctx.font = 'bold 8.5px Outfit, sans-serif';
        const labelW = ctx.measureText(eqLabel).width;

        ctx.fillStyle = badgeBg;
        ctx.fillRect(sx, Math.max(0, sy - 14), labelW + 8, 14);

        ctx.fillStyle = isInUse ? '#022c22' : '#ffffff';
        ctx.fillText(eqLabel, sx + 4, Math.max(10, sy - 4));
      });
    }

    animFrameId = requestAnimationFrame(renderLoop);
  }

  renderLoop();
}

function drawSynthesizedCameraFeed(ctx, width, height) {
  const grad = ctx.createLinearGradient(0, 0, 0, height);
  grad.addColorStop(0, '#0a101f');
  grad.addColorStop(0.5, '#111b30');
  grad.addColorStop(1, '#080d19');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
  ctx.lineWidth = 1;
  const horizon = height * 0.25;
  for (let i = -width; i < width * 2; i += 60) {
    ctx.beginPath();
    ctx.moveTo(width / 2 + i * 0.2, horizon);
    ctx.lineTo(i, height);
    ctx.stroke();
  }
  for (let y = horizon; y < height; y += (y - horizon) * 0.35 + 15) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }
}

// ============================================================================
// 9. Peak Time & Trend Visualizations (Chart.js)
// ============================================================================
function initPeakChart() {
  const ctx = document.getElementById('peakTimeChart');
  if (!ctx) return;

  const gradientToday = ctx.getContext('2d').createLinearGradient(0, 0, 0, 300);
  gradientToday.addColorStop(0, 'rgba(6, 182, 212, 0.45)');
  gradientToday.addColorStop(1, 'rgba(6, 182, 212, 0.0)');

  const gradientHistorical = ctx.getContext('2d').createLinearGradient(0, 0, 0, 300);
  gradientHistorical.addColorStop(0, 'rgba(139, 92, 246, 0.25)');
  gradientHistorical.addColorStop(1, 'rgba(139, 92, 246, 0.0)');

  peakChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: appState.hourlyTrend.hours,
      datasets: [
        {
          label: "Today's Headcount",
          data: appState.hourlyTrend.today,
          borderColor: '#06b6d4',
          backgroundColor: gradientToday,
          fill: true,
          tension: 0.35,
          borderWidth: 3,
          pointBackgroundColor: '#06b6d4',
          pointRadius: 4
        },
        {
          label: '30-Day Historical Baseline',
          data: appState.hourlyTrend.historicalAvg,
          borderColor: 'rgba(139, 92, 246, 0.8)',
          backgroundColor: gradientHistorical,
          borderDash: [5, 5],
          fill: false,
          tension: 0.35,
          borderWidth: 2,
          pointRadius: 2
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          position: 'top',
          labels: { color: '#94a3b8', font: { family: 'Outfit', size: 11 }, usePointStyle: true }
        }
      },
      scales: {
        x: {
          grid: { color: 'rgba(255, 255, 255, 0.05)' },
          ticks: { color: '#64748b', font: { family: 'Outfit', size: 10 } }
        },
        y: {
          min: 0,
          max: 55,
          grid: { color: 'rgba(255, 255, 255, 0.05)' },
          ticks: { color: '#64748b', font: { family: 'JetBrains Mono', size: 10 }, stepSize: 10 }
        }
      }
    }
  });
}

function updateChartData() {
  if (!peakChartInstance) return;

  if (appState.activeChartRange === 'today') {
    peakChartInstance.config.type = 'line';
    peakChartInstance.data.labels = appState.hourlyTrend.hours;
    peakChartInstance.data.datasets[0].label = "Today's Headcount";
    peakChartInstance.data.datasets[0].data = appState.hourlyTrend.today;
    if (peakChartInstance.data.datasets[1]) peakChartInstance.data.datasets[1].hidden = false;
  } else {
    peakChartInstance.config.type = 'bar';
    peakChartInstance.data.labels = appState.weeklyPeakMatrix.days;
    peakChartInstance.data.datasets[0].label = 'Average Daily Peak Headcount';
    peakChartInstance.data.datasets[0].data = appState.weeklyPeakMatrix.peakCounts;
    if (peakChartInstance.data.datasets[1]) peakChartInstance.data.datasets[1].hidden = true;
  }

  peakChartInstance.update();
}

// ============================================================================
// 10. User Actions & Controls
// ============================================================================
function bindControls() {
  const toggleAi = document.getElementById('toggleAiDetections');
  if (toggleAi) {
    toggleAi.addEventListener('change', (e) => {
      appState.aiDetectionsEnabled = e.target.checked;
    });
  }

  const toggleRoi = document.getElementById('toggleRoiOverlay');
  if (toggleRoi) {
    toggleRoi.addEventListener('change', (e) => {
      appState.roiOverlayEnabled = e.target.checked;
      drawFloorHeatmap();
    });
  }

  const playPauseBtn = document.getElementById('videoPlayPauseBtn');
  const video = document.getElementById('gymVideoFeed');
  if (playPauseBtn && video) {
    playPauseBtn.addEventListener('click', () => {
      appState.isVideoPlaying = !appState.isVideoPlaying;
      if (appState.isVideoPlaying) video.play();
      else video.pause();
      playPauseBtn.innerHTML = `<i data-lucide="${appState.isVideoPlaying ? 'pause' : 'play'}"></i>`;
      if (window.lucide) lucide.createIcons();
    });
  }

  // Camera Switcher Buttons
  document.querySelectorAll('.cam-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const camId = btn.getAttribute('data-cam-id');
      if (camId) switchCamera(camId);
    });
  });

  const videoSelect = document.getElementById('videoSelect');
  if (videoSelect) {
    videoSelect.addEventListener('change', (e) => {
      const camId = e.target.value;
      if (CAMERA_CONFIGS[camId]) {
        switchCamera(camId);
      } else if (camId === 'simulated') {
        const video = document.getElementById('gymVideoFeed');
        if (video) video.src = '';
        showToast('Switched to Synthesized Vision Simulator', 'info');
      }
    });
  }

  document.querySelectorAll('.filter-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.filter-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      appState.activeFilter = tab.getAttribute('data-filter');
      renderEquipmentTable();
    });
  });

  document.querySelectorAll('.chart-time-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.chart-time-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      appState.activeChartRange = btn.getAttribute('data-chart-range');
      updateChartData();
    });
  });

  // Generate / Re-evaluate AI Recommendation Button
  const recBtn = document.getElementById('generateNewRecBtn');
  if (recBtn) {
    recBtn.addEventListener('click', async () => {
      showToast('Re-evaluating gym threshold rules against live telemetry...', 'success');

      if (appState.mode === 'LIVE_BACKEND') {
        try {
          const res = await fetch(`${CONFIG.BACKEND_BASE_URL}${CONFIG.ENDPOINTS.GENERATE_REC}`, {
            method: 'POST'
          });
          const data = await res.json();
          if (data.recommendation) {
            appState.recommendation.narrative = data.recommendation;
            appState.recommendation.timestamp = new Date().toLocaleTimeString('en-US', {
              hour12: appState.is12HourFormat, hour: '2-digit', minute: '2-digit'
            });
            renderRecommendations();
            showToast('AI operational recommendations generated successfully!', 'success');
            return;
          }
        } catch (e) {
          console.warn('API generate call fallback:', e);
        }
      }

      // Simulation fallback
      setTimeout(() => {
        appState.recommendation.timestamp = new Date().toLocaleTimeString('en-US', {
          hour12: appState.is12HourFormat, hour: '2-digit', minute: '2-digit'
        });
        renderRecommendations();
        showToast('Operational recommendations refreshed with latest numbers', 'success');
      }, 500);
    });
  }

  // Rule Config Modal Button
  const ruleBtn = document.getElementById('viewRuleConfigBtn');
  if (ruleBtn) {
    ruleBtn.addEventListener('click', () => {
      alert("Smart Gym Active Operational Rules (data/rules_config.json):\n\n1. Zone Imbalance: ratio >= 2.0x gym average (min 5 people)\n2. Idle Equipment: idle >= 2 min (lowered for demo visibility; 45 min in production)\n3. Underused Zone: max <= 2 people over 24h\n4. Peak Time Mismatch: deviation >= 1.5x from expected hours (6-8am, 5-8pm)");
    });
  }

  // Monthly Report Modal Handling
  const reportModal = document.getElementById('reportModal');
  const openReportBtn = document.getElementById('openReportBtn');
  const closeReportBtn = document.getElementById('closeReportModalBtn');

  if (openReportBtn && reportModal) {
    openReportBtn.addEventListener('click', async () => {
      reportModal.style.display = 'flex';
      await loadMonthlyReport();
    });
  }
  if (closeReportBtn && reportModal) {
    closeReportBtn.addEventListener('click', () => {
      reportModal.style.display = 'none';
    });
  }
  if (reportModal) {
    reportModal.addEventListener('click', (e) => {
      if (e.target === reportModal) reportModal.style.display = 'none';
    });
  }

  const printBtn = document.getElementById('printReportBtn');
  if (printBtn) {
    printBtn.addEventListener('click', () => {
      window.print();
    });
  }

  const emailBtn = document.getElementById('emailReportBtn');
  if (emailBtn) {
    emailBtn.addEventListener('click', async () => {
      emailBtn.disabled = true;
      emailBtn.style.opacity = '0.5';
      showToast('Sending report via email…', 'info');
      try {
        const res = await fetch(`${CONFIG.BACKEND_BASE_URL}/recommendations/send-monthly-email`, {
          method: 'POST'
        });
        if (res.ok) {
          const result = await res.json();
          const sentTo = result?.result?.sent_to || 'the configured staff address';
          showToast(`Monthly report sent to ${sentTo}!`, 'success');
          setTimeout(() => { if (reportModal) reportModal.style.display = 'none'; }, 1500);
        } else {
          const err = await res.json();
          showToast(`Failed: ${err.detail || 'Unknown error'}`, 'error');
        }
      } catch (e) {
        showToast('Could not reach backend', 'error');
      } finally {
        emailBtn.disabled = false;
        emailBtn.style.opacity = '1';
      }
    });
  }
}

async function loadMonthlyReport() {
  const narrativeEl = document.getElementById('monthlyNarrative');
  if (!narrativeEl) return;

  if (appState.mode === 'LIVE_BACKEND') {
    try {
      let res = await fetch(`${CONFIG.BACKEND_BASE_URL}${CONFIG.ENDPOINTS.MONTHLY_REPORT}`);
      let data = await res.json();

      if (!data.report) {
        // Trigger generation if not present
        res = await fetch(`${CONFIG.BACKEND_BASE_URL}${CONFIG.ENDPOINTS.GENERATE_MONTHLY_REPORT}`, { method: 'POST' });
        data = await res.json();
      }

      if (data.narrative || (data.report && data.report.narrative)) {
        narrativeEl.textContent = data.narrative || data.report.narrative;
        return;
      }
    } catch (e) {
      console.warn('Error loading monthly report:', e);
    }
  }

  narrativeEl.textContent = `No monthly report available yet — connect to the live backend and click "Generate this month's report" to produce one from recorded data.`;
}

function showToast(message, type = 'success') {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <i data-lucide="${type === 'alert' ? 'alert-triangle' : 'check-circle'}" style="color: ${type === 'alert' ? 'var(--accent-rose)' : 'var(--accent-emerald)'}"></i>
    <span>${message}</span>
  `;

  container.appendChild(toast);
  if (window.lucide) lucide.createIcons();

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(100%)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

window.inspectEquipment = function (id) {
  const item = appState.equipment.find(e => e.id === id);
  if (!item) return;

  alert(`Equipment Inspection: [${item.id}] ${item.name}\n\n• Zone Location: ${item.zone}\n• Telemetry Status: ${item.status.toUpperCase()}\n• Inactivity Duration: ${item.idleMinutes} minutes\n• Monthly Utilization: ${item.usageRate}%`);
};