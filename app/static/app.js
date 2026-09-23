/**
 * THERMOGRAPH — Client Dashboard Application (Task T11 + T12)
 * Plain JavaScript consuming the Flask REST API.
 * Conforms to TECH_SPEC §9 and PRD §7.9, §10, §11.
 */

// PRD FR-16 Human-readable Rule-based Class Labels
const SITE_CLASS_LABELS = {
  "PERSISTENT_INDUSTRIAL": "Persistent source at mapped industrial facility",
  "PERSISTENT_UNMAPPED": "Persistent source, no mapped facility — needs verification",
  "EPISODIC_NEAR_FACILITY": "Occasional activity near mapped facility",
  "EPISODIC_OTHER": "Occasional activity, no industrial evidence found"
};

// Status Colors conforming to TECH_SPEC §9
const STATUS_COLORS = {
  "HIGH": "#d62728",
  "MEDIUM": "#ff7f0e",
  "LOW": "#ca8a04",
  "NORMAL": "#16a34a",
  "INSUFFICIENT_HISTORY": "#94a3b8",
  "NEW_SITE_NO_ANOMALY": "#94a3b8"
};

// Global State
let map = null;
let sitesLayer = null;
let facilitiesLayer = null;
let isolatedLayer = null;
let isolatedDataLoaded = false;
let currentChart = null;
let activeSiteMarker = null;
let activeSiteId = null;
let isSimulated = false; // Simulation state: default is real data (False)
let riskData = []; // Cached ranked anomalous sites
let markersBySiteId = {}; // Fast lookup for map markers

// Helper: Escape HTML strings to prevent XSS
function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// Helper: Format numbers with commas
function formatNumber(num) {
  if (num === null || num === undefined) return "—";
  return Number(num).toLocaleString();
}

// -----------------------------------------------------------------------------
// 1. Initialize Map
// -----------------------------------------------------------------------------
function initMap() {
  // Centred on Gujarat (approx. 22.5°N, 71.5°E, zoom 7)
  // preferCanvas: true ensures high rendering performance on low-resource hardware
  map = L.map("map", {
    center: [22.5, 71.5],
    zoom: 7,
    preferCanvas: true
  });

  // Base map: OpenStreetMap tiles
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);

  // Layer groups
  sitesLayer = L.layerGroup().addTo(map);
  facilitiesLayer = L.layerGroup().addTo(map);
  isolatedLayer = L.layerGroup(); // Off by default

  // Layer control
  const overlays = {
    "Thermal Sites (568)": sitesLayer,
    "OSM Facilities (710)": facilitiesLayer,
    "Isolated Detections (10,974)": isolatedLayer
  };
  L.control.layers(null, overlays, { position: "topright", collapsed: false }).addTo(map);

  // Lazy-load isolated detections on demand when user checks the overlay
  map.on("overlayadd", function (e) {
    if (e.layer === isolatedLayer && !isolatedDataLoaded) {
      loadIsolatedDetections();
    }
  });

  // Map Legend Control
  const legend = L.control({ position: "bottomright" });
  legend.onAdd = function () {
    const div = L.DomUtil.create("div", "leaflet-legend");
    div.innerHTML = `
      <div class="legend-title">Legend</div>
      <div class="legend-row">
        <span class="legend-circle" style="background:#d62728;"></span>
        <span>HIGH Anomaly</span>
      </div>
      <div class="legend-row">
        <span class="legend-circle" style="background:#ff7f0e;"></span>
        <span>MEDIUM Anomaly</span>
      </div>
      <div class="legend-row">
        <span class="legend-circle" style="background:#ca8a04;"></span>
        <span>LOW Anomaly</span>
      </div>
      <div class="legend-row">
        <span class="legend-circle" style="background:#16a34a;"></span>
        <span>NORMAL (Routine)</span>
      </div>
      <div class="legend-row">
        <span class="legend-circle" style="background:#94a3b8;"></span>
        <span>Insufficient History</span>
      </div>
      <div class="legend-row" style="margin-top: 6px; padding-top: 4px; border-top: 1px solid #e2e8f0;">
        <span class="legend-square"></span>
        <span>OSM Industrial Facility</span>
      </div>
      <div class="legend-row">
        <span class="legend-dot"></span>
        <span>Isolated Hotspot</span>
      </div>
    `;
    return div;
  };
  legend.addTo(map);
}

// -----------------------------------------------------------------------------
// 2. Load Global Dashboard Counts
// -----------------------------------------------------------------------------
async function loadDashboardCounts() {
  try {
    const url = isSimulated ? "/api/dashboard?include_simulated=1" : "/api/dashboard";
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const counts = data.counts || {};
    document.getElementById("metric-detections").textContent = formatNumber(counts.detections);
    document.getElementById("metric-sites").textContent = formatNumber(counts.sites);
    document.getElementById("metric-isolated").textContent = formatNumber(counts.isolated_detections);
    document.getElementById("metric-facilities").textContent = formatNumber(counts.facilities);
    document.getElementById("metric-matched").textContent = formatNumber(counts.sites_matched);
    document.getElementById("metric-anomalous").textContent = formatNumber(counts.anomalous_sites);
    document.getElementById("metric-normal").textContent = formatNumber(counts.sites_normal);

    if (data.dataset_start && data.dataset_end) {
      document.getElementById("tag-period").textContent = `${data.dataset_start} – ${data.dataset_end}`;
    }
    if (data.status_as_of) {
      document.getElementById("tag-status").textContent = `Status as of ${data.status_as_of}`;
    }
  } catch (err) {
    console.error("Failed to load dashboard metrics:", err);
  }
}

// -----------------------------------------------------------------------------
// 3. Load Thermal Sites
// -----------------------------------------------------------------------------
async function loadSites() {
  try {
    sitesLayer.clearLayers();
    markersBySiteId = {};

    const res = await fetch("/api/sites");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const sites = await res.json();

    sites.forEach(site => {
      const isTargetSimSite = isSimulated && site.site_id === "TS-0001";
      const color = STATUS_COLORS[site.status] || STATUS_COLORS["INSUFFICIENT_HISTORY"];
      // Scale radius logarithmically between 5px and 13px based on detection count
      const radius = Math.min(13, Math.max(5, Math.round(4 + Math.log(site.n_detections || 1) * 1.3)));

      const markerOptions = {
        radius: radius,
        fillColor: color,
        color: isTargetSimSite ? "#dc2626" : "#ffffff",
        weight: isTargetSimSite ? 3 : 1.5,
        opacity: 0.95,
        fillOpacity: 0.85
      };

      if (isTargetSimSite) {
        markerOptions.dashArray = "4, 3";
      }

      const marker = L.circleMarker([site.lat, site.lon], markerOptions);

      const simBadgeText = isTargetSimSite
        ? `<br><span style="color:#dc2626; font-weight:800;">[SIMULATED DEMO EVENT]</span>`
        : "";

      const facilityText = site.facility_display_name
        ? `<br><small>🏭 ${escapeHtml(site.facility_display_name)}</small>`
        : `<br><small style="color:#64748b;">Unmapped</small>`;

      marker.bindTooltip(`
        <strong>${escapeHtml(site.site_id)}</strong> (${escapeHtml(site.status)})<br>
        ${formatNumber(site.n_detections)} detections
        ${facilityText}
        ${simBadgeText}
      `, { direction: "top", offset: [0, -radius] });

      marker.on("click", () => {
        openSiteDetail(site.site_id, marker);
        highlightPriorityItem(site.site_id);
      });

      marker.addTo(sitesLayer);
      markersBySiteId[site.site_id] = marker;
    });

    // Re-highlight active marker if one was selected
    if (activeSiteId && markersBySiteId[activeSiteId]) {
      activeSiteMarker = markersBySiteId[activeSiteId];
      activeSiteMarker.setStyle({ weight: 3.5, color: "#000000" });
    }
  } catch (err) {
    console.error("Failed to load sites:", err);
  }
}

// -----------------------------------------------------------------------------
// 4. Load OSM Industrial Facilities
// -----------------------------------------------------------------------------
async function loadFacilities() {
  try {
    const res = await fetch("/api/facilities");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const geojson = await res.json();

    L.geoJSON(geojson, {
      pointToLayer: function (feature, latlng) {
        return L.circleMarker(latlng, {
          radius: 4,
          fillColor: "#aec7e8",
          color: "#1f77b4",
          weight: 1.5,
          opacity: 0.8,
          fillOpacity: 0.6
        });
      },
      onEachFeature: function (feature, layer) {
        const props = feature.properties || {};
        let popup = `<strong>${escapeHtml(props.display_name || "Facility")}</strong><br>`;
        if (props.industrial) {
          popup += `<small>Industrial: ${escapeHtml(props.industrial)}</small><br>`;
        }
        if (props.landuse) {
          popup += `<small>Landuse: ${escapeHtml(props.landuse)}</small><br>`;
        }
        popup += `<small style="color:#64748b;">OSM: ${escapeHtml(props.facility_id)}</small>`;
        layer.bindPopup(popup);
      }
    }).addTo(facilitiesLayer);
  } catch (err) {
    console.error("Failed to load facilities:", err);
  }
}

// -----------------------------------------------------------------------------
// 5. Load Isolated Detections (On Demand)
// -----------------------------------------------------------------------------
async function loadIsolatedDetections() {
  try {
    isolatedDataLoaded = true;
    const res = await fetch("/api/detections/isolated");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const coords = await res.json();

    coords.forEach(pt => {
      L.circleMarker([pt[0], pt[1]], {
        radius: 2,
        stroke: false,
        fillColor: "#888888",
        fillOpacity: 0.45
      }).addTo(isolatedLayer);
    });
  } catch (err) {
    console.error("Failed to load isolated detections:", err);
    isolatedDataLoaded = false;
  }
}

// -----------------------------------------------------------------------------
// 6. Priority / Anomaly List (T12)
// -----------------------------------------------------------------------------
async function loadPriorityList() {
  try {
    const url = isSimulated ? "/api/risk?include_simulated=1" : "/api/risk";
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    riskData = await res.json();

    const countPill = document.getElementById("priority-count-pill");
    const simSuffix = isSimulated ? " [1 SIMULATED]" : "";
    countPill.textContent = `${riskData.length} sites${simSuffix}`;

    renderPriorityList(riskData);
  } catch (err) {
    console.error("Failed to load priority list:", err);
  }
}

function renderPriorityList(items) {
  const container = document.getElementById("priority-list");
  if (!items || items.length === 0) {
    container.innerHTML = '<div class="no-items-msg">No matching anomalous sites.</div>';
    return;
  }

  let html = "";
  items.forEach(item => {
    const isSim = Boolean(item.is_simulated);
    const prioClass = `prio-${item.priority}`;
    const simClass = isSim ? "simulated-item" : "";
    const activeClass = item.site_id === activeSiteId ? "active" : "";

    const facilityDisplay = item.facility_display_name
      ? escapeHtml(item.facility_display_name)
      : '<span class="unmapped">Unmapped facility</span>';

    const simPill = isSim ? '<span class="sim-tag">[SIMULATED]</span>' : "";

    html += `
      <div class="priority-item ${prioClass} ${simClass} ${activeClass}"
           data-site-id="${escapeHtml(item.site_id)}"
           data-lat="${item.lat}"
           data-lon="${item.lon}">
        <div class="priority-top-row">
          <div class="priority-rank-site">
            <span class="priority-rank">#${item.rank}</span>
            <span class="priority-site-id">${escapeHtml(item.site_id)}</span>
          </div>
          <div class="priority-pills">
            ${simPill}
            <span class="prio-tag status-${item.priority}">${escapeHtml(item.priority)}</span>
            <span class="score-tag">${item.score} pts</span>
          </div>
        </div>
        <div class="priority-facility">${facilityDisplay}</div>
        <div class="priority-reason">${escapeHtml(item.top_reason)}</div>
      </div>
    `;
  });

  container.innerHTML = html;

  // Bind click listeners to all items
  container.querySelectorAll(".priority-item").forEach(card => {
    card.addEventListener("click", () => {
      const sid = card.getAttribute("data-site-id");
      const lat = parseFloat(card.getAttribute("data-lat"));
      const lon = parseFloat(card.getAttribute("data-lon"));

      // Focus map to site coordinates
      map.flyTo([lat, lon], 12, { duration: 1.0 });

      // Open site panel
      const marker = markersBySiteId[sid];
      openSiteDetail(sid, marker);
      highlightPriorityItem(sid);
    });
  });
}

function highlightPriorityItem(siteId) {
  document.querySelectorAll(".priority-item").forEach(card => {
    if (card.getAttribute("data-site-id") === siteId) {
      card.classList.add("active");
      card.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } else {
      card.classList.remove("active");
    }
  });
}

function filterPriorityList() {
  const query = document.getElementById("priority-search-input").value.trim().toLowerCase();
  if (!query) {
    renderPriorityList(riskData);
    return;
  }

  const filtered = riskData.filter(item => {
    const sid = (item.site_id || "").toLowerCase();
    const fac = (item.facility_display_name || "").toLowerCase();
    const prio = (item.priority || "").toLowerCase();
    const reason = (item.top_reason || "").toLowerCase();
    return sid.includes(query) || fac.includes(query) || prio.includes(query) || reason.includes(query);
  });

  renderPriorityList(filtered);
}

// -----------------------------------------------------------------------------
// 7. Site Detail Panel & 52-Week Chart
// -----------------------------------------------------------------------------
async function openSiteDetail(siteId, marker) {
  activeSiteId = siteId;
  const panel = document.getElementById("site-panel");
  const placeholder = document.getElementById("panel-placeholder");
  const content = document.getElementById("panel-content");

  panel.classList.remove("closed");
  placeholder.style.display = "none";
  content.style.display = "flex";

  // Highlight active marker on map
  if (activeSiteMarker && activeSiteMarker !== marker) {
    const isOldSim = isSimulated && activeSiteMarker._siteId === "TS-0001";
    activeSiteMarker.setStyle({
      weight: isOldSim ? 3 : 1.5,
      color: isOldSim ? "#dc2626" : "#ffffff"
    });
  }
  activeSiteMarker = marker;
  if (marker) {
    marker._siteId = siteId;
    marker.setStyle({ weight: 3.5, color: "#000000" });
  }

  try {
    const url = isSimulated ? `/api/sites/${siteId}?include_simulated=1` : `/api/sites/${siteId}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    renderSiteDetail(data);
  } catch (err) {
    console.error(`Failed to load details for ${siteId}:`, err);
  }
}

function renderSiteDetail(data) {
  const site = data.site || {};
  const facility = data.facility;
  const baseline = data.baseline || {};
  const weekly = data.weekly || [];
  const anomalies = data.anomalies || [];

  // Header: ID and Status Badge
  document.getElementById("panel-site-id").textContent = site.site_id || "—";
  const statusEl = document.getElementById("panel-site-status");
  statusEl.textContent = site.status || "UNKNOWN";
  statusEl.className = `panel-site-status status-${site.status}`;

  // Rule-based class display label (PRD FR-16)
  const classTitle = SITE_CLASS_LABELS[site.site_class] || site.site_class || "Unclassified";
  document.getElementById("panel-class-title").textContent = classTitle;

  // Facility Context Card
  const facContent = document.getElementById("panel-facility-content");
  if (facility && site.match_type && site.match_type !== "none") {
    const distText = site.match_type === "inside"
      ? "Located inside facility boundary (0 m)"
      : `Located ${Math.round(facility.distance_m || site.match_distance_m || 0)} m from facility`;

    let tagsHtml = "";
    if (facility.industrial) {
      tagsHtml += `<span class="facility-tag">industrial=${escapeHtml(facility.industrial)}</span>`;
    }
    if (facility.landuse) {
      tagsHtml += `<span class="facility-tag">landuse=${escapeHtml(facility.landuse)}</span>`;
    }

    facContent.innerHTML = `
      <div class="facility-name">
        <a href="${escapeHtml(facility.osm_url)}" target="_blank" rel="noopener noreferrer">
          ${escapeHtml(facility.display_name)} ↗
        </a>
      </div>
      <div class="facility-meta">
        <span>${escapeHtml(distText)}</span>
        ${tagsHtml}
      </div>
    `;
  } else {
    facContent.innerHTML = `
      <div class="unmapped-notice">
        No mapped OSM industrial facility within 1 km — source needs manual verification.
      </div>
    `;
  }

  // Evidence & Summary Stats
  document.getElementById("stat-detections").textContent = formatNumber(site.n_detections);
  document.getElementById("stat-active-weeks").textContent = `${site.active_weeks_total || 0} / 52`;
  document.getElementById("stat-night-pct").textContent = site.night_fraction !== null
    ? `${(site.night_fraction * 100).toFixed(1)}%`
    : "—";
  document.getElementById("stat-static-pct").textContent = site.static_type_fraction !== null
    ? `${(site.static_type_fraction * 100).toFixed(1)}%`
    : "—";
  document.getElementById("stat-mean-frp").textContent = site.mean_frp !== null
    ? `${Number(site.mean_frp).toFixed(1)} MW`
    : "—";
  document.getElementById("stat-max-frp").textContent = site.max_frp !== null
    ? `${Number(site.max_frp).toFixed(1)} MW`
    : "—";
  document.getElementById("stat-first-seen").textContent = site.first_seen || "—";
  document.getElementById("stat-last-seen").textContent = site.last_seen || "—";

  // Baseline Behavior Body
  const baselineBody = document.getElementById("panel-baseline-body");
  if (baseline.established === 1) {
    baselineBody.innerHTML = `
      <div class="baseline-grid">
        <div class="baseline-row"><span>Established:</span> <strong>Yes (active ≥10 weeks)</strong></div>
        <div class="baseline-row"><span>Active weeks:</span> <strong>${baseline.active_weeks} / ${baseline.n_weeks}</strong></div>
        <div class="baseline-row"><span>Mean heat output:</span> <strong>${Number(baseline.frp_sum_mean).toFixed(1)} MW</strong></div>
        <div class="baseline-row"><span>Std deviation (σ):</span> <strong>${Number(baseline.frp_sum_std).toFixed(1)} MW</strong></div>
      </div>
      <div class="baseline-row" style="margin-top: 4px; padding-top: 4px; border-top: 1px solid #e2e8f0;">
        <span>Normal upper limit (mean + 3σ):</span>
        <span class="threshold-highlight">${Number(baseline.threshold).toFixed(1)} MW</span>
      </div>
    `;
  } else {
    baselineBody.innerHTML = `
      <div class="unmapped-notice">
        Insufficient baseline history (active in ${baseline.active_weeks || 0} of 39 baseline weeks; minimum 10 required to establish a statistical baseline).
      </div>
    `;
  }

  // 52-Week FRP Chart
  renderWeeklyChart(weekly, baseline, anomalies);

  // Anomalies List
  const anomaliesList = document.getElementById("panel-anomalies-list");
  if (anomalies.length > 0) {
    let anomHtml = '<div class="anomalies-list">';
    anomalies.forEach(anom => {
      const isSim = Boolean(anom.is_simulated);
      const prioClass = `prio-${anom.priority}`;
      const simClass = isSim ? "simulated-item" : "";
      const reasons = Array.isArray(anom.reasons) ? anom.reasons : [];
      let reasonsListHtml = "";
      reasons.forEach(r => {
        reasonsListHtml += `<li>${escapeHtml(r)}</li>`;
      });

      const simHeaderBadge = isSim ? '<span class="sim-tag" style="margin-right:4px;">[SIMULATED]</span>' : "";

      anomHtml += `
        <div class="anomaly-item ${prioClass} ${simClass}">
          <div class="anomaly-header">
            <span class="anomaly-period">Week ${anom.week_index} (${escapeHtml(anom.week_start)} – ${escapeHtml(anom.week_end)})</span>
            <div>
              ${simHeaderBadge}
              <span class="anomaly-badge status-${anom.priority}">${escapeHtml(anom.priority)} · ${anom.score} pts</span>
            </div>
          </div>
          <ul class="reasons-list">
            ${reasonsListHtml}
          </ul>
        </div>
      `;
    });
    anomHtml += '</div>';
    anomaliesList.innerHTML = anomHtml;
  } else {
    if (baseline.established === 1) {
      anomaliesList.innerHTML = `
        <div class="normal-notice">
          <strong>Within normal range:</strong> Weekly heat output remained within the site's baseline upper limit throughout all monitoring weeks.
        </div>
      `;
    } else {
      anomaliesList.innerHTML = `
        <div class="unmapped-notice">
          No anomalies evaluated (insufficient baseline history to judge exceedance).
        </div>
      `;
    }
  }
}

// -----------------------------------------------------------------------------
// 8. Render 52-Week FRP Chart with Chart.js
// -----------------------------------------------------------------------------
function renderWeeklyChart(weekly, baseline, anomalies) {
  const ctx = document.getElementById("weekly-chart").getContext("2d");

  if (currentChart) {
    currentChart.destroy();
    currentChart = null;
  }

  // Build anomaly map by week_index
  const anomalyByWeek = {};
  anomalies.forEach(a => {
    anomalyByWeek[a.week_index] = a;
  });

  const labels = weekly.map(w => {
    if (w.is_simulated || w.week_index === 52) {
      return "W52 [SIM]";
    }
    return `W${w.week_index}`;
  });

  const frpData = weekly.map(w => Number(w.frp_sum.toFixed(1)));

  // Color each bar based on baseline vs monitoring vs anomaly vs simulation
  const barColors = weekly.map(w => {
    if (w.is_simulated || w.week_index === 52) {
      return "#dc2626"; // Bright red for simulated week
    }
    if (anomalyByWeek[w.week_index]) {
      const p = anomalyByWeek[w.week_index].priority;
      if (p === "HIGH") return "#d62728";
      if (p === "MEDIUM") return "#ff7f0e";
      return "#ca8a04";
    }
    if (w.period === "baseline") {
      return "#3b82f6"; // Blue for baseline weeks
    }
    return "#22c55e"; // Green for normal monitoring weeks
  });

  const datasets = [
    {
      type: "bar",
      label: "Weekly Heat Output (MW)",
      data: frpData,
      backgroundColor: barColors,
      borderRadius: 2,
      borderSkipped: false
    }
  ];

  // Draw threshold line if baseline is established
  if (baseline && baseline.established === 1 && baseline.threshold > 0) {
    const threshVal = Number(baseline.threshold.toFixed(1));
    datasets.push({
      type: "line",
      label: `Upper Limit (${threshVal} MW)`,
      data: weekly.map(() => threshVal),
      borderColor: "#dc2626",
      borderWidth: 1.8,
      borderDash: [5, 4],
      pointRadius: 0,
      fill: false,
      tension: 0
    });
  }

  currentChart = new Chart(ctx, {
    data: {
      labels: labels,
      datasets: datasets
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: "index",
        intersect: false
      },
      plugins: {
        legend: {
          display: false
        },
        tooltip: {
          callbacks: {
            title: function (items) {
              const idx = items[0].dataIndex;
              const w = weekly[idx];
              const simTag = (w.is_simulated || w.week_index === 52) ? " [SIMULATED DEMO EVENT]" : "";
              return `Week ${w.week_index} (${w.week_start} – ${w.week_end})${simTag}`;
            },
            label: function (item) {
              if (item.dataset.type === "line") {
                return `Threshold: ${item.formattedValue} MW`;
              }
              const w = weekly[item.dataIndex];
              let text = `FRP Sum: ${item.formattedValue} MW (${w.detection_count} detections)`;
              if (w.is_simulated || w.week_index === 52) {
                text += " [SIMULATED HIGH ANOMALY]";
              } else if (anomalyByWeek[w.week_index]) {
                text += ` [${anomalyByWeek[w.week_index].priority} Anomaly]`;
              }
              return text;
            }
          }
        }
      },
      scales: {
        x: {
          grid: {
            display: false
          },
          ticks: {
            maxTicksLimit: 14,
            font: {
              size: 10
            }
          }
        },
        y: {
          beginAtZero: true,
          title: {
            display: true,
            text: "Total FRP (MW)",
            font: {
              size: 10
            }
          },
          ticks: {
            font: {
              size: 10
            }
          }
        }
      }
    }
  });
}

// -----------------------------------------------------------------------------
// 9. Simulation Toggle Controls (T12)
// -----------------------------------------------------------------------------
function setSimulationState(enabled) {
  isSimulated = enabled;

  const toggleBtn = document.getElementById("toggle-sim-btn");
  const toggleLabel = document.getElementById("sim-toggle-label");
  const banner = document.getElementById("sim-banner");
  const chartSimNote = document.getElementById("chart-sim-note");

  if (isSimulated) {
    toggleBtn.classList.add("active");
    toggleLabel.textContent = "Demo Simulation: ON";
    banner.style.display = "block";
    if (chartSimNote) chartSimNote.style.display = "inline";
  } else {
    toggleBtn.classList.remove("active");
    toggleLabel.textContent = "Demo Simulation: OFF";
    banner.style.display = "none";
    if (chartSimNote) chartSimNote.style.display = "none";
  }

  // Reload all dynamic components with the new include_simulated state
  loadDashboardCounts();
  loadSites();
  loadPriorityList();

  // If a site detail panel is currently open, refresh its data
  if (activeSiteId) {
    const marker = markersBySiteId[activeSiteId];
    openSiteDetail(activeSiteId, marker);
  }
}

// -----------------------------------------------------------------------------
// 10. About & Methodology Modal (T12)
// -----------------------------------------------------------------------------
function initAboutModal() {
  const modal = document.getElementById("about-modal");
  const openBtn = document.getElementById("about-btn");
  const closeBtn = document.getElementById("close-about-btn");
  const dismissBtn = document.getElementById("modal-dismiss-btn");

  const openModal = () => {
    modal.style.display = "flex";
  };
  const closeModal = () => {
    modal.style.display = "none";
  };

  openBtn.addEventListener("click", openModal);
  closeBtn.addEventListener("click", closeModal);
  dismissBtn.addEventListener("click", closeModal);

  // Close modal when clicking backdrop outside card
  modal.addEventListener("click", (e) => {
    if (e.target === modal) {
      closeModal();
    }
  });

  // Close on Escape key
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modal.style.display === "flex") {
      closeModal();
    }
  });
}

// -----------------------------------------------------------------------------
// 11. Event Listeners & Startup
// -----------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  initMap();
  loadDashboardCounts();
  loadSites();
  loadFacilities();
  loadPriorityList();
  initAboutModal();

  // Search input in priority list
  document.getElementById("priority-search-input").addEventListener("input", filterPriorityList);

  // Simulation toggle button in header
  document.getElementById("toggle-sim-btn").addEventListener("click", () => {
    setSimulationState(!isSimulated);
  });

  // Turn off button in persistent banner
  document.getElementById("sim-banner-off-btn").addEventListener("click", () => {
    setSimulationState(false);
  });

  // Close site detail panel button
  document.getElementById("close-panel-btn").addEventListener("click", () => {
    document.getElementById("site-panel").classList.add("closed");
    if (activeSiteMarker) {
      const isTargetSim = isSimulated && activeSiteId === "TS-0001";
      activeSiteMarker.setStyle({
        weight: isTargetSim ? 3 : 1.5,
        color: isTargetSim ? "#dc2626" : "#ffffff"
      });
      activeSiteMarker = null;
    }
    activeSiteId = null;
    document.querySelectorAll(".priority-item").forEach(card => card.classList.remove("active"));
  });
});
