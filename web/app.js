/**
 * Forge Console — Frontend Application
 * Vanilla JS, no external libraries, offline-ready.
 */

(function () {
  "use strict";

  /* ==================== STATE & CONFIG ==================== */

  const API = {
    FLOW: "/api/flow",
    HEALTH: "/api/health",
    INSIGHTS: "/api/proxy/insights",
    SCHEME: "/api/proxy/scheme",
    PROJECTS: "/api/projects",
  };

  const CATEGORY_COLORS = {
    ai_automation: "#A78BFA",
    digital_product: "#38BDF8",
    service: "#34D399",
    content_media: "#F472B6",
    e_commerce: "#FBBF24",
    trading_investing: "#4ADE80",
    real_world: "#FB923C",
    community: "#E879F9",
    other: "#94A3B8",
  };

  const CATEGORY_NAMES = {
    ai_automation: "AI & Automation",
    digital_product: "Digital Product",
    service: "Service",
    content_media: "Content & Media",
    e_commerce: "E-Commerce",
    trading_investing: "Trading & Investing",
    real_world: "Real World",
    community: "Community",
    other: "Other",
  };

  const STATUS_COLORS = {
    raw: "#94A3B8",
    developed: "#60A5FA",
    testing: "#FBBF24",
    being_built: "#FF8C42",
    proven: "#34D399",
    dead: "#F87171",
  };

  const CTYPE_COLORS = {
    parallel: "#FF8C42",
    complements: "#4CC9F0",
    same_market: "#B5E48C",
    competes: "#F25C54",
    extends: "#B185DB",
  };

  const SCORE_LABELS = {
    capital: "Capital Req.",
    effort: "Effort Req.",
    time_to_revenue: "Time to Rev.",
    ceiling: "Rev. Ceiling",
    difficulty: "Difficulty",
    moat: "Moat",
    risk: "Downside Risk",
  };

  const SOURCE_DEFS = [
    { src: "c6", label: "C6 (Hermes)" },
    { src: "opencode", label: "opencode" },
    { src: "claudecode", label: "claude code" },
    { src: "antigravity", label: "antigravity" },
    { src: "all", label: "all" },
  ];

  // Global App State
  const state = {
    activeTab: "flow",
    isTabInitialized: {
      insights: false,
      ideas: false,
      flow: false,
      projects: false,
    },
    // Projects Tab State
    projects: {
      items: [],
      filter: "",
      activeProjectId: null,
      pollInterval: null,
    },
    // Insights Tab State
    insights: {
      days: "30",
      source: "c6",
      includeCR: false,
      data: null,
      pricing: { models: {} },
      projections: {},
      isRefreshing: false,
    },
    // Ideas Tab State
    ideas: {
      view: "map",
      ideas: [],
      connections: [],
      themes: [],
      stats: null,
      analysisRuns: [],
      filters: {
        category: "",
        status: "",
        search: "",
        hideSeeded: false,
      },
      selectedIdea: null,
      graph: {
        nodes: [],
        edges: [],
        panX: 0,
        panY: 0,
        zoom: 1.0,
        hoveredNode: null,
        draggedNode: null,
        isPanning: false,
        lastMouseX: 0,
        lastMouseY: 0,
        simTicksRemaining: 0,
      },
    },
    // Flow Tab State
    flow: {
      rawDoc: null,
      nodes: [],
      edges: [],
      particles: [],
      selectedNode: null,
      hoveredNode: null,
      panX: 0,
      panY: 0,
      zoom: 1.0,
      isPanning: false,
      userAdjusted: false,
      lastMouseX: 0,
      lastMouseY: 0,
      motionEnabled: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
      isPaused: false,
      lastFrameTime: performance.now(),
      loopRunning: false,
    },
  };

  /* ==================== SHELL & NAVIGATION ==================== */

  function initShell() {
    // 1. Clock
    updateClock();
    setInterval(updateClock, 1000);

    // 2. Tab switcher buttons
    document.querySelectorAll(".nav-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.getAttribute("data-tab");
        switchTab(tab);
      });
    });

    // 3. Routing from URL hash
    window.addEventListener("hashchange", handleHashRoute);
    handleHashRoute();

    // 4. Keyboard shortcuts
    window.addEventListener("keydown", handleKeydown);

    // 5. Shortcut modal handlers
    const btnHelp = document.getElementById("btn-help");
    const modalShortcuts = document.getElementById("modal-shortcuts");
    const btnCloseShortcuts = document.getElementById("btn-close-shortcuts");
    if (btnHelp && modalShortcuts) {
      btnHelp.addEventListener("click", () => {
        modalShortcuts.style.display = "flex";
      });
    }
    if (btnCloseShortcuts && modalShortcuts) {
      btnCloseShortcuts.addEventListener("click", () => {
        modalShortcuts.style.display = "none";
      });
    }
    if (modalShortcuts) {
      modalShortcuts.addEventListener("click", (e) => {
        if (e.target === modalShortcuts) modalShortcuts.style.display = "none";
      });
    }

    // 6. Global alert close button
    const btnAlertClose = document.getElementById("btn-alert-close");
    if (btnAlertClose) {
      btnAlertClose.addEventListener("click", () => {
        document.getElementById("global-alert-banner").style.display = "none";
      });
    }

    // 7. Visibility change to pause animations when hidden
    document.addEventListener("visibilitychange", () => {
      state.flow.isPaused = document.hidden;
      if (!document.hidden && state.activeTab === "flow") {
        ensureFlowLoop();
      }
    });
  }

  function updateClock() {
    const el = document.getElementById("live-clock");
    if (!el) return;
    const now = new Date();
    el.textContent = now.toLocaleTimeString("en-GB", { hour12: false });
  }

  function handleHashRoute() {
    const hash = window.location.hash.toLowerCase();
    if (hash === "#/insights") switchTab("insights", false);
    else if (hash === "#/ideas") switchTab("ideas", false);
    else if (hash.startsWith("#/projects")) {
      switchTab("projects", false);
      const parts = hash.split("/");
      if (parts.length >= 3 && parts[2]) {
        showProjectDetail(parts[2], false);
      } else {
        showProjectsList();
      }
    }
    else switchTab("flow", false);
  }

  function switchTab(tabId, updateHash = true) {
    if (!["insights", "ideas", "flow", "projects"].includes(tabId)) tabId = "flow";
    state.activeTab = tabId;

    if (updateHash) {
      if (tabId === "projects" && state.projects.activeProjectId) {
        window.location.hash = `#/projects/${state.projects.activeProjectId}`;
      } else {
        window.location.hash = `#/${tabId}`;
      }
    }

    // Update Tab Buttons
    document.querySelectorAll(".nav-tab").forEach((btn) => {
      const match = btn.getAttribute("data-tab") === tabId;
      btn.classList.toggle("active", match);
      btn.setAttribute("aria-selected", match ? "true" : "false");
    });

    // Update Panes
    document.querySelectorAll(".tab-pane").forEach((pane) => {
      pane.style.display = "none";
      pane.classList.remove("active");
    });
    const targetPane = document.getElementById(`pane-${tabId}`);
    if (targetPane) {
      targetPane.style.display = "block";
      targetPane.classList.add("active");
    }

    // Flow tab active: initialize if needed and cleanly re-measure and re-fit canvas
    if (tabId === "flow") {
      if (!state.isTabInitialized.flow) {
        state.isTabInitialized.flow = true;
        initFlowTab();
      }
      refreshFlowLayout();
      requestAnimationFrame(() => refreshFlowLayout());
    }

    // Projects tab active
    if (tabId === "projects") {
      if (!state.isTabInitialized.projects) {
        state.isTabInitialized.projects = true;
        initProjectsTab();
      }
      fetchProjects();
      if (!state.projects.pollInterval) {
        state.projects.pollInterval = setInterval(() => {
          if (state.activeTab === "projects") {
            fetchProjects();
          }
        }, 20000);
      }
    }
  }

  function handleKeydown(e) {
    // Ignore keys if typing in an input or textarea
    const tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
      if (e.key === "Escape") e.target.blur();
      return;
    }

    if (e.key === "1") {
      switchTab("insights");
    } else if (e.key === "2") {
      switchTab("ideas");
    } else if (e.key === "3") {
      switchTab("flow");
    } else if (e.key === "4") {
      switchTab("projects");
    } else if (e.key === "?") {
      const m = document.getElementById("modal-shortcuts");
      if (m) m.style.display = m.style.display === "none" ? "flex" : "none";
    } else if (e.key === "Escape") {
      closeAllDrawersAndModals();
    } else if (e.key === " " && state.activeTab === "flow") {
      e.preventDefault();
      recenterFlowCanvas();
    }
  }

  function closeAllDrawersAndModals() {
    const modals = ["modal-shortcuts", "modal-add-project", "modal-edit-project"];
    modals.forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.style.display = "none";
    });
    deselectFlowNode();
  }

  function updateServiceStrip(services) {
    const dotsEl = document.getElementById("strip-dots");
    const summaryEl = document.getElementById("strip-summary");
    if (!dotsEl || !services || !services.length) return;

    dotsEl.innerHTML = "";
    let upCount = 0;

    services.forEach((s) => {
      const dot = document.createElement("span");
      dot.className = `sdot ${s.status}`;
      dot.title = `${s.name}: ${s.status} (${s.detail || ""})`;
      dotsEl.appendChild(dot);
      if (s.status === "green") upCount++;
    });

    if (summaryEl) {
      summaryEl.textContent = `${upCount}/${services.length} UP`;
    }
  }

  /* ==================== RETIRED REIMPLEMENTATIONS ==================== */
  // Insights and Ideas reimplementations retired in Merge Brief 15.
  // Replaced by iframes to /insights/ and /ideas/.

  /* ==================== FLOW TAB & DATA ==================== */

  function initFlowTab() {
    initFlowCanvas();
    fetchFlowData();
    setInterval(fetchFlowData, 5000);
  }

  async function fetchFlowData() {
    try {
      const doc = await fetchJson(API.FLOW);
      state.flow.rawDoc = doc;
      updateFlowHud(doc);
      buildFlowGraph(doc);
      updateServiceStrip(doc.services);
    } catch (err) {
      console.warn("Failed fetching flow doc:", err);
    }
  }

  function updateFlowHud(doc) {
    if (!doc) return;

    // Harnesses
    const harnesses = doc.harnesses || [];
    const activeHarnessCount = harnesses.filter((h) => {
      const isC6 = h.id === "harness-c6" || h.name === "c6";
      return isC6
        ? Boolean(h.running && (h.active_sessions > 0 || (h.last_active_s != null && h.last_active_s < 300)))
        : (h.active_sessions > 0 || h.running);
    }).length;
    setText("hud-val-harness", `${activeHarnessCount} Active (${harnesses.length} total)`);
    const dotHarness = document.getElementById("hud-dot-harness");
    if (dotHarness) dotHarness.className = `hud-dot ${activeHarnessCount > 0 ? "active" : ""}`;

    // Filesystem
    const recent = (doc.filesystem && doc.filesystem.recent) || [];
    setText("hud-val-fs", `${recent.length} recent writes`);

    // Services
    const srvs = doc.services || [];
    const healthySrvs = srvs.filter((s) => s.status === "green").length;
    setText("hud-val-srv", `${healthySrvs}/${srvs.length} Healthy`);

    // Data stores
    const dbs = doc.databases || [];
    setText("hud-val-db", `${dbs.length} tracked stores`);
  }

  /* ==================== FLOW RENDERER (CANVAS) ==================== */

  function deselectFlowNode() {
    state.flow.selectedNode = null;
    const drawer = document.getElementById("flow-detail-drawer");
    if (drawer) drawer.style.display = "none";
  }

  function refreshFlowLayout() {
    state.flow.userAdjusted = false;
    resizeFlowCanvas();
    fitFlowCanvas();
    // Restart dot phase so nothing looks off
    state.flow.particles = [];
    state.flow.lastFrameTime = performance.now();
    ensureFlowLoop();
    drawFlowScene(performance.now());
  }

  function initFlowCanvas() {
    const canvas = document.getElementById("flow-canvas");
    if (!canvas) return;

    window.addEventListener("resize", () => {
      resizeFlowCanvas();
      if (state.activeTab === "flow") {
        refreshFlowLayout();
      }
    });
    resizeFlowCanvas();

    // Controls
    const btnZoomIn = document.getElementById("btn-flow-zoom-in");
    const btnZoomOut = document.getElementById("btn-flow-zoom-out");
    const btnRecenter = document.getElementById("btn-flow-recenter");
    const btnMotion = document.getElementById("btn-flow-motion");
    const btnCloseDrawer = document.getElementById("btn-close-flow-drawer");

    if (btnZoomIn) btnZoomIn.addEventListener("click", () => zoomFlowCanvas(1.2));
    if (btnZoomOut) btnZoomOut.addEventListener("click", () => zoomFlowCanvas(0.8));
    if (btnRecenter) btnRecenter.addEventListener("click", recenterFlowCanvas);
    if (btnMotion) {
      btnMotion.addEventListener("click", () => {
        state.flow.motionEnabled = !state.flow.motionEnabled;
        btnMotion.style.color = state.flow.motionEnabled ? "var(--accent)" : "var(--text-dim)";
      });
    }
    if (btnCloseDrawer) {
      btnCloseDrawer.addEventListener("click", () => {
        deselectFlowNode();
      });
    }

    // Pan & Zoom events
    canvas.addEventListener("mousedown", (e) => {
      state.flow.isPanning = true;
      state.flow.lastMouseX = e.clientX;
      state.flow.lastMouseY = e.clientY;
      state.flow.panMoved = 0;
    });

    window.addEventListener("mousemove", (e) => {
      const f = state.flow;
      if (f.isPanning) {
        const dx = e.clientX - f.lastMouseX;
        const dy = e.clientY - f.lastMouseY;
        f.panMoved = (f.panMoved || 0) + Math.hypot(dx, dy);
        if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
          f.userAdjusted = true;
        }
        f.panX += dx;
        f.panY += dy;
        f.lastMouseX = e.clientX;
        f.lastMouseY = e.clientY;
      } else if (state.activeTab === "flow") {
        // Tooltip hover detection
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const hit = hitTestFlowNode(mx, my);
        f.hoveredNode = hit;

        const tip = document.getElementById("flow-tooltip");
        if (tip) {
          if (hit) {
            tip.style.display = "block";
            tip.style.left = `${e.clientX + 14}px`;
            tip.style.top = `${e.clientY + 14}px`;
            tip.innerHTML = formatFlowNodeTooltip(hit);
          } else {
            tip.style.display = "none";
          }
        }
        canvas.style.cursor = hit ? "pointer" : "default";
      }
    });

    window.addEventListener("mouseup", () => {
      state.flow.isPanning = false;
    });

    canvas.addEventListener("click", (e) => {
      if (state.flow.panMoved && state.flow.panMoved > 5) return;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const hit = hitTestFlowNode(mx, my);
      if (hit) {
        showFlowNodeDetail(hit);
      } else {
        deselectFlowNode();
      }
    });

    canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.12 : 0.88;
      zoomFlowCanvas(factor);
    });

    // Start persistent RAF loop (exactly once; see ensureFlowLoop)
    ensureFlowLoop();
  }

  function resizeFlowCanvas() {
    const canvas = document.getElementById("flow-canvas");
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || window.innerWidth;
    const h = canvas.clientHeight || (window.innerHeight - 52);
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    fitFlowCanvas();
  }

  function zoomFlowCanvas(factor) {
    const f = state.flow;
    f.zoom = Math.max(0.4, Math.min(2.5, f.zoom * factor));
    f.userAdjusted = true;
  }

  function fitFlowCanvas() {
    const canvas = document.getElementById("flow-canvas");
    if (!canvas) return;
    const cw = canvas.clientWidth;
    const ch = canvas.clientHeight;
    if (!cw || !ch) return;

    const nodes = state.flow.nodes;
    if (!nodes || nodes.length === 0) return;

    let minX = Infinity, maxX = -Infinity;
    let minY = Infinity, maxY = -Infinity;
    for (const n of nodes) {
      const hw = (n.w || 60) / 2;
      const hh = (n.h || 48) / 2;
      if (n.x - hw < minX) minX = n.x - hw;
      if (n.x + hw > maxX) maxX = n.x + hw;
      if (n.y - hh < minY) minY = n.y - hh;
      if (n.y + hh > maxY) maxY = n.y + hh;
    }

    const sceneW = maxX - minX;
    const sceneH = maxY - minY;
    const sceneCy = (minY + maxY) / 2;

    // Reserve room for top HUD pill strip (bottom ≈ 35-44px) with safe clearance
    const topOffset = 52;
    // Reserve room for bottom edge clearance
    const bottomOffset = 22;
    const sideOffset = 24;

    const usableW = Math.max(100, cw - sideOffset * 2);
    const usableH = Math.max(100, ch - topOffset - bottomOffset);

    const scaleX = usableW / sceneW;
    const scaleY = usableH / sceneH;
    const fitZoom = Math.max(0.4, Math.min(scaleX, scaleY, 1.0));

    const targetCenterY = topOffset + usableH / 2;

    const f = state.flow;
    f.zoom = fitZoom;
    f.panX = 0; // maintain center alignment on The Forge
    f.panY = targetCenterY - ch / 2 - (sceneCy - ch / 2) * f.zoom;
  }

  function recenterFlowCanvas() {
    state.flow.userAdjusted = false;
    fitFlowCanvas();
  }

  function screenToWorldFlow(sx, sy, cw, ch) {
    const f = state.flow;
    const x = (sx - (cw / 2 + f.panX)) / f.zoom + cw / 2;
    const y = (sy - (ch / 2 + f.panY)) / f.zoom + ch / 2;
    return { x, y };
  }

  function hitTestFlowNode(mx, my) {
    const canvas = document.getElementById("flow-canvas");
    if (!canvas) return null;
    const cw = canvas.clientWidth;
    const ch = canvas.clientHeight;
    const world = screenToWorldFlow(mx, my, cw, ch);

    for (let i = state.flow.nodes.length - 1; i >= 0; i--) {
      const n = state.flow.nodes[i];
      const hw = (n.w || 60) / 2 + 6;
      const hh = (n.h || 48) / 2 + 6;
      if (Math.abs(world.x - n.x) <= hw && Math.abs(world.y - n.y) <= hh) return n;
    }
    return null;
  }

  // A store counts as "hot" when it was written in the last ~5 minutes.
  function isStoreHot(store) {
    return store && store.last_write_age_s !== null && store.last_write_age_s !== undefined && store.last_write_age_s < 300;
  }

  // Short display label for an insights-node port (full name in tooltip).
  function storePortLabel(storeName) {
    const s = String(storeName || "");
    if (/opencode/i.test(s)) return "opencode";
    if (/scheme/i.test(s)) return "board";
    if (/cron/i.test(s)) return "cron";
    if (/log/i.test(s)) return "logs";
    if (/state/i.test(s)) return "state";
    return s.slice(0, 10);
  }

  // Measure a node title so box width can derive from content.
  let _flowMeasureCtx = null;
  function measureFlowTitle(title, font) {
    try {
      if (!_flowMeasureCtx) _flowMeasureCtx = document.createElement("canvas").getContext("2d");
      _flowMeasureCtx.font = font;
      return _flowMeasureCtx.measureText(String(title || "")).width;
    } catch (err) {
      return String(title || "").length * 7;
    }
  }

  /* ==================== FLOW GRAPH GEOMETRY CONSTANTS ==================== */
  const NODE_RADIUS = 8;

  // Hydrocarbon Forge Logo geometry (pre-computed from favicon.svg transforms)
  const FORGE_LOGO_HEX = [
    [0, 47.33],
    [-40.05, 23.66],
    [-40.05, -23.66],
    [0, -47.33],
    [40.05, -23.66],
    [40.05, 23.66],
  ];
  const FORGE_LOGO_TOP = [
    [-27.69, -16.36],
    [0.02, -0.67],
    [27.72, -16.35],
    [0, -32.73],
  ];
  const FORGE_LOGO_LEFT = [
    [0.02, -0.67],
    [0.02, 32.66],
    [-27.66, 16.30],
    [-27.67, -16.36],
  ];
  const FORGE_LOGO_RIGHT = [
    [0.02, -0.67],
    [0.02, 32.72],
    [27.70, 16.36],
    [27.71, -16.35],
  ];
  const FORGE_LOGO_STROKE_WIDTH = 25.0;

  function sizeFlowNode(title, minW, maxW, h) {
    const tw = measureFlowTitle(title, "600 12px Inter, sans-serif");
    const w = Math.max(minW, Math.min(maxW, Math.ceil(tw) + 36));
    return { w: w, h: h };
  }

  function buildFlowGraph(doc) {
    const canvas = document.getElementById("flow-canvas");
    const width = (canvas && canvas.clientWidth) || 1200;
    const height = (canvas && canvas.clientHeight) || 800;
    const cx = width / 2;
    const cy = height / 2;

    const existingPos = new Map();
    state.flow.nodes.forEach((n) => existingPos.set(n.id, { x: n.x, y: n.y }));

    const nodes = [];
    const edges = [];

    // 1. Forge Central Hub Node (large accent square with logo)
    const hubSize = sizeFlowNode("THE FORGE", 120, 160, 96);
    const hubNode = {
      id: "hub-forge",
      name: "THE FORGE",
      label: "The Forge",
      type: "hub",
      x: cx,
      y: cy,
      w: hubSize.w,
      h: hubSize.h,
      accent: "#FF8C42",
      active: true,
      ports: [],
      data: {
        description: "Central Hydrocarbon Forge Controller & Router",
        status: "Online",
      },
    };
    nodes.push(hubNode);

    // 2. Harness Nodes (Positioned above Hub)
    const harnesses = doc.harnesses || [];
    const numHarnesses = harnesses.length;
    const hSpacing = 165;
    const hStartY = cy - 230;
    harnesses.forEach((h, idx) => {
      const x = cx + (idx - (numHarnesses - 1) / 2) * hSpacing;
      const y = hStartY;
      const isC6 = h.id === "harness-c6" || h.name === "c6";
      const active = isC6
        ? Boolean(h.running && (h.active_sessions > 0 || (h.last_active_s != null && h.last_active_s < 300)))
        : (h.active_sessions > 0 || h.running);
      const sz = sizeFlowNode(h.label || h.name, 150, 190, 52);
      const node = {
        id: h.id,
        name: h.label || h.name,
        type: "harness",
        x: x,
        y: y,
        w: sz.w,
        h: sz.h,
        accent: h.accent || "#38BDF8",
        active: active,
        data: h,
      };
      nodes.push(node);

      // Edge to Hub (idle harnesses carry no flow at all)
      edges.push({
        source: node,
        target: hubNode,
        accent: node.accent,
        active: node.active,
        speed: node.active ? 1.6 : 0.4,
        density: node.active ? 4 : 0,
      });
    });

    // 3. Filesystem Node (Positioned in Left Column, level with Harnesses)
    const fsActive = (doc.filesystem && doc.filesystem.recent && doc.filesystem.recent.length > 0);
    const fsSize = sizeFlowNode("FILESYSTEM", 170, 210, 52);
    const leftColX = cx - 420;
    const fsY = cy - 230;
    const fsNode = {
      id: "fs-node",
      name: "FILESYSTEM",
      label: "Projects Workspace",
      type: "filesystem",
      x: leftColX,
      y: fsY,
      w: fsSize.w,
      h: fsSize.h,
      accent: "#FFB454",
      active: fsActive,
      ports: [
        { id: "bottom", dx: 0, dy: fsSize.h / 2 },
        { id: "right", dx: fsSize.w / 2, dy: 0 },
      ],
      data: doc.filesystem || { recent: [] },
    };
    nodes.push(fsNode);

    // 4. Projects Node (tall node showing ALL projects as rows)
    const projects = doc.projects || [];
    const numProjects = projects.length;
    const activeCount = projects.filter((p) => p.active).length;
    const projectsActive = activeCount > 0;

    // Prioritize active projects first, then sort alphabetically by name
    const sortedProjects = [...projects].sort(
      (a, b) => (b.active ? 1 : 0) - (a.active ? 1 : 0) || a.name.localeCompare(b.name)
    );

    // Measure text width among title and ALL project names
    let maxTw = measureFlowTitle("PROJECTS", "600 13px Inter, sans-serif");
    sortedProjects.forEach((p) => {
      const font = p.active ? "600 12px JetBrains Mono, monospace" : "12px JetBrains Mono, monospace";
      const tw = measureFlowTitle(p.name, font);
      if (tw > maxTw) maxTw = tw;
    });

    const projW = Math.max(260, Math.min(360, Math.ceil(maxTw) + 48));
    const projPitch = 30;
    const headerH = 36;
    const projH = numProjects === 0 ? 56 : headerH + numProjects * projPitch + 10;

    // Position directly below Filesystem with a clean gap to ensure disjoint boxes
    const fsGap = 16;
    const projTop = fsY + fsSize.h / 2 + fsGap;
    const projY = projTop + projH / 2;

    const projectsNode = {
      id: "projects",
      name: "PROJECTS",
      label: "Projects",
      type: "projects",
      x: leftColX,
      y: projY,
      w: projW,
      h: projH,
      accent: "#5AA9E6",
      active: projectsActive,
      ports: [],
      data: {
        projects: sortedProjects,
        total: numProjects,
        active_count: activeCount,
        headerH: headerH,
        pitch: projPitch,
      },
    };

    // Assign per-row ports on right edge of PROJECTS node
    sortedProjects.forEach((p, idx) => {
      const rowDy = -projH / 2 + headerH + idx * projPitch + projPitch / 2;
      projectsNode.ports.push({
        id: `proj-port-${idx}`,
        project: p,
        dx: projW / 2, // right edge
        dy: rowDy,
        active: !!p.active,
      });
    });

    // Top port for incoming edge from Filesystem
    const projTopPortIdx = projectsNode.ports.length;
    projectsNode.ports.push({
      id: "fs-in",
      dx: 0,
      dy: -projH / 2,
    });

    nodes.push(projectsNode);

    // Setup left-side anchor ports on THE FORGE:
    // Port 0: Filesystem anchor (upper-left)
    // Ports 1..: Active project row anchors (distributed along left edge)
    hubNode.ports.push({ id: "hub-fs", dx: -hubNode.w / 2, dy: -24 });
    const numActiveProjects = sortedProjects.filter((p) => p.active).length;
    for (let k = 0; k < numActiveProjects; k++) {
      const hubRowDy = numActiveProjects === 1 ? 8 : -4 + (k / (numActiveProjects - 1)) * 32;
      hubNode.ports.push({
        id: `hub-proj-row-${k}`,
        dx: -hubNode.w / 2,
        dy: hubRowDy,
      });
    }

    // Edge: Filesystem -> Projects
    edges.push({
      source: fsNode,
      sourcePort: 0, // fs bottom port
      target: projectsNode,
      targetPort: projTopPortIdx, // projects top port
      accent: projectsActive ? "#FFB454" : "rgba(255,255,255,0.15)",
      active: projectsActive,
      speed: projectsActive ? 1.4 : 0.3,
      density: projectsActive ? 3 : 0,
    });

    // Edge: Filesystem -> Hub (Item 3: active when recent writes exist)
    edges.push({
      source: fsNode,
      sourcePort: 1, // fs right port
      target: hubNode,
      targetPort: 0, // hub fs anchor
      accent: "#FFB454",
      active: fsActive,
      speed: fsActive ? 1.4 : 0.4,
      density: fsActive ? 2 : 0,
    });

    // Edges: Hub -> Active Project Rows (flow OUTWARD from hub toward project)
    let activeRowK = 0;
    sortedProjects.forEach((p, idx) => {
      if (p.active) {
        const hubPortIdx = 1 + activeRowK;
        activeRowK++;
        edges.push({
          source: hubNode,
          sourcePort: hubPortIdx, // corresponding hub anchor
          target: projectsNode,
          targetPort: idx, // row connector dot on projectsNode
          accent: p.accent || "#5AA9E6",
          active: true,
          speed: 1.4,
          density: 3,
        });
      }
    });

    // 5. Service Nodes (Positioned to the Right)
    const services = doc.services || [];
    const srvSpacing = 75;
    const srvStartY = cy - ((services.length - 1) * srvSpacing) / 2;
    services.forEach((s, idx) => {
      const x = cx + 340;
      const y = srvStartY + idx * srvSpacing;
      const active = s.status === "green";
      const sz = sizeFlowNode(s.label || s.name, 150, 190, 50);
      const sNode = {
        id: s.id,
        name: s.label || s.name,
        type: "service",
        x: x,
        y: y,
        w: sz.w,
        h: sz.h,
        accent: s.status === "green" ? "#5AD6A0" : s.status === "amber" ? "#FFB454" : "#F25C54",
        active: active,
        data: s,
      };
      nodes.push(sNode);
    });

    // 6. Data Stores Node (single horizontal bar below the hub, with labeled port dots on top edge)
    const databases = doc.databases || [];
    const numStores = databases.length;
    const storesW = Math.max(280, numStores * 60 + 20);
    const storesH = 64;
    const storesNode = {
      id: "data-stores",
      name: "DATA STORES",
      label: "Insights / Data Stores",
      type: "datastores",
      x: cx,
      y: cy + 230,
      w: storesW,
      h: storesH,
      accent: "#B5E48C",
      active: false,
      stores: databases,
      ports: [],
      data: { count: numStores, hot: 0 },
    };

    let hotCount = 0;
    const portPitch = numStores > 1 ? (storesW - 60) / (numStores - 1) : 0;
    databases.forEach((db, idx) => {
      const hot = isStoreHot(db);
      if (hot) hotCount++;
      const dx = numStores > 1 ? -((numStores - 1) * portPitch) / 2 + idx * portPitch : 0;
      storesNode.ports.push({
        store: db,
        label: storePortLabel(db.name),
        hot: hot,
        dx: dx,
        dy: -storesH / 2, // on the top edge
      });
    });
    storesNode.active = hotCount > 0;
    storesNode.data.hot = hotCount;
    nodes.push(storesNode);

    // Hub -> stores edge (connects to group center)
    edges.push({
      source: hubNode,
      target: storesNode,
      accent: "#B5E48C",
      active: storesNode.active,
      speed: 0.6,
      density: storesNode.active ? 2 : 0,
    });

    // 7. Connect Service Nodes to matching PORTS on the data-stores node (Item 4).
    // Derived from the data's reader field (with hermes gateway matching
    // all hermes data stores: state, cron, logs). Every hot store has an incoming edge.
    nodes.filter((n) => n.type === "service").forEach((sNode) => {
      const sName = (sNode.data && sNode.data.name) || sNode.id.replace(/^srv-/, "");

      storesNode.ports.forEach((port, portIdx) => {
        const db = port.store;
        if (!db) return;

        const isDirectReader = db.reader && (db.reader === sName || db.reader === sNode.id.replace(/^srv-/, ""));
        const isHermesMatch = (sNode.id === "srv-hermes-gateway" || sName === "hermes gateway") &&
                              (db.id.startsWith("data-hermes") || db.name.toLowerCase().includes("hermes"));

        if (isDirectReader || isHermesMatch) {
          const portHot = !!port.hot;
          edges.push({
            source: sNode,
            target: storesNode,
            targetPort: portIdx,
            accent: sNode.accent,
            active: sNode.active,
            speed: 0.8,
            // Reader relationship carries flow while service is up AND store is hot
            density: sNode.active && portHot ? 1 : 0,
          });
        }
      });
    });

    state.flow.nodes = nodes;
    state.flow.edges = edges;
    if (!state.flow.userAdjusted) {
      fitFlowCanvas();
    }
  }

  // Persistent RAF loop: ALWAYS reschedules itself so leaving the tab (or
  // hiding the window) can never kill the chain. Expensive work is skipped
  // while hidden, and lastFrameTime tracks the skipped frames so there is no
  // delta jump on return.
  function ensureFlowLoop() {
    if (state.flow.loopRunning) return;
    state.flow.loopRunning = true;
    state.flow.lastFrameTime = performance.now();
    requestAnimationFrame(renderFlowLoop);
  }

  function renderFlowLoop(currentTime) {
    requestAnimationFrame(renderFlowLoop);

    if (state.flow.isPaused || state.activeTab !== "flow") {
      state.flow.lastFrameTime = currentTime;
      return;
    }

    const delta = Math.min(0.1, (currentTime - state.flow.lastFrameTime) / 1000);
    state.flow.lastFrameTime = currentTime;

    updateFlowParticles(delta);
    drawFlowScene(currentTime);
  }

  function updateFlowParticles(delta) {
    if (!state.flow.motionEnabled) {
      state.flow.particles = [];
      return;
    }

    const particles = state.flow.particles;
    const edges = state.flow.edges;

    // Spawn new particles only along edges with REAL activity: the edge
    // must be active AND carry flow (density > 0). Idle edges never spawn.
    edges.forEach((edge) => {
      if (!edge.active || !(edge.density > 0)) return;
      const spawnChance = (edge.density || 1) * delta * 1.5;
      if (Math.random() < spawnChance) {
        particles.push({
          edge: edge,
          progress: 0,
          speed: (edge.speed || 1.0) * (0.2 + Math.random() * 0.1),
          accent: edge.accent || "#fff",
        });
      }
    });

    // Update progress
    for (let i = particles.length - 1; i >= 0; i--) {
      const p = particles[i];
      p.progress += p.speed * delta;
      if (p.progress >= 1.0) {
        particles.splice(i, 1);
      }
    }
  }

  // Resolve an edge endpoint to world coords: a port offset when the edge
  // targets a specific port (service -> insights-node port), else the node.
  function flowEdgePoint(node, portIdx) {
    if (node && portIdx !== undefined && portIdx !== null && node.ports && node.ports[portIdx]) {
      const p = node.ports[portIdx];
      return { x: node.x + p.dx, y: node.y + p.dy };
    }
    return { x: node.x, y: node.y };
  }

  // Node-editor grid drawn in world space so it pans/zooms with the scene.
  function drawFlowGrid(ctx, w, h) {
    const tl = screenToWorldFlow(0, 0, w, h);
    const br = screenToWorldFlow(w, h, w, h);
    const minor = 40;
    const majorEvery = 5;

    ctx.save();
    ctx.lineWidth = 1 / state.flow.zoom;

    // Minor lines
    ctx.strokeStyle = "rgba(255,255,255,0.04)";
    ctx.beginPath();
    for (let x = Math.floor(tl.x / minor) * minor; x <= br.x; x += minor) {
      ctx.moveTo(x, tl.y);
      ctx.lineTo(x, br.y);
    }
    for (let y = Math.floor(tl.y / minor) * minor; y <= br.y; y += minor) {
      ctx.moveTo(tl.x, y);
      ctx.lineTo(br.x, y);
    }
    ctx.stroke();

    // Major lines
    ctx.strokeStyle = "rgba(255,255,255,0.07)";
    ctx.beginPath();
    for (let x = Math.floor(tl.x / (minor * majorEvery)) * (minor * majorEvery); x <= br.x; x += minor * majorEvery) {
      ctx.moveTo(x, tl.y);
      ctx.lineTo(x, br.y);
    }
    for (let y = Math.floor(tl.y / (minor * majorEvery)) * (minor * majorEvery); y <= br.y; y += minor * majorEvery) {
      ctx.moveTo(tl.x, y);
      ctx.lineTo(br.x, y);
    }
    ctx.stroke();
    ctx.restore();
  }

  // Tall node for PROJECTS displaying ALL projects as rows (~30px pitch).
  // Every project row has a small connector dot on its right edge.
  // Active rows get an accent dot + glow; inactive rows get a dim dot.
  // The count sub-line ('14 · 2 active') is rendered below the box.
  function drawProjectsNode(ctx, node, isHovered, isSelected, time) {
    const w = node.w || 260;
    const h = node.h || 466;
    const x = node.x - w / 2;
    const y = node.y - h / 2;
    const r = NODE_RADIUS;
    const pulse = state.flow.motionEnabled ? 0.5 + 0.5 * Math.sin(time / 250) : 1;

    // 1. Box background & border
    ctx.save();
    if (node.active && state.flow.motionEnabled) {
      ctx.shadowColor = node.accent;
      ctx.shadowBlur = 14;
    }

    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x, y, w, h, NODE_RADIUS);
    else ctx.rect(x, y, w, h);
    ctx.fillStyle = node.active ? "#17171a" : "#141416";
    ctx.fill();
    ctx.shadowBlur = 0;

    ctx.lineWidth = isSelected ? 2.5 : isHovered ? 2 : 1.5;
    ctx.strokeStyle = isSelected ? "#fff" : !node.active ? "rgba(255,255,255,0.18)" : isHovered ? "#fff" : node.accent;
    ctx.stroke();

    // Accent left-edge stripe for active nodes
    if (node.active) {
      ctx.fillStyle = node.accent;
      const sw = 4;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(x + 1, y + 4, sw, h - 8, 2);
      else ctx.rect(x + 1, y + 4, sw, h - 8);
      ctx.fill();
    }
    ctx.restore();

    // 2. Header: Title 'PROJECTS' and node-level right connector dot
    const headerH = (node.data && node.data.headerH) || 36;
    ctx.save();
    ctx.fillStyle = isSelected ? "#fff" : node.active ? "#f2f2f4" : "#9a9ba1";
    ctx.font = "600 13px Inter, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(node.name || "PROJECTS", node.x, y + headerH / 2);

    // Subtle divider below header
    ctx.strokeStyle = "rgba(255,255,255,0.07)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x + 10, y + headerH);
    ctx.lineTo(x + w - 10, y + headerH);
    ctx.stroke();
    ctx.restore();

    // Top connector dot (FILESYSTEM input)
    ctx.save();
    ctx.beginPath();
    ctx.arc(node.x, y, 3, 0, Math.PI * 2);
    ctx.fillStyle = node.active ? "#FFB454" : "#28292e";
    ctx.fill();
    ctx.strokeStyle = node.active ? "#fff" : "rgba(255,255,255,0.25)";
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.restore();

    // 3. Project Rows (ALL projects shown on the face)
    const projs = (node.data && node.data.projects) || [];
    const pitch = (node.data && node.data.pitch) || 30;

    projs.forEach((p, idx) => {
      const rowY = y + headerH + idx * pitch + pitch / 2;
      const isActive = !!p.active;
      const rowAccent = p.accent || node.accent;

      // Subtle row highlight for active projects
      if (isActive) {
        ctx.fillStyle = "rgba(90, 169, 230, 0.07)";
        ctx.fillRect(x + 6, rowY - pitch / 2 + 2, w - 12, pitch - 4);
      }

      // Small active indicator dot on the left
      if (isActive) {
        ctx.beginPath();
        ctx.arc(x + 14, rowY, 2.5, 0, Math.PI * 2);
        ctx.fillStyle = rowAccent;
        ctx.fill();
      }

      // Project Name (left-aligned)
      ctx.save();
      ctx.font = isActive ? "600 12px JetBrains Mono, monospace" : "12px JetBrains Mono, monospace";
      ctx.fillStyle = isActive ? rowAccent : "#a8a9b3";
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";

      const textX = isActive ? x + 22 : x + 14;
      const maxTextW = w - (isActive ? 40 : 32);
      let str = p.name;
      while (str.length > 3 && ctx.measureText(str).width > maxTextW) {
        str = str.slice(0, -1);
      }
      if (str !== p.name) str = str.slice(0, -1) + "…";
      ctx.fillText(str, textX, rowY);
      ctx.restore();

      // Connector dot / port on right edge (Item 2)
      // Active rows: accent dot + glow + white stroke; Inactive rows: dim dot, no glow
      const dotX = x + w;
      const dotY = rowY;
      ctx.save();
      ctx.beginPath();
      if (isActive) {
        if (state.flow.motionEnabled) {
          ctx.shadowColor = rowAccent;
          ctx.shadowBlur = 6 + 4 * pulse;
        }
        ctx.arc(dotX, dotY, 4, 0, Math.PI * 2);
        ctx.fillStyle = rowAccent;
        ctx.fill();
        ctx.shadowBlur = 0;
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 1;
        ctx.stroke();
      } else {
        ctx.arc(dotX, dotY, 3, 0, Math.PI * 2);
        ctx.fillStyle = "#28292e";
        ctx.fill();
        ctx.strokeStyle = "rgba(255,255,255,0.25)";
        ctx.lineWidth = 1;
        ctx.stroke();
      }
      ctx.restore();
    });

    // 4. Sub-label below the box: '14 · 2 active'
    const subText = flowNodeSubLabel(node);
    if (subText) {
      ctx.fillStyle = node.active ? "#8a8b92" : "#62636a";
      ctx.font = "10px JetBrains Mono, monospace";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(subText, node.x, y + h + 14);
    }
  }

  // Rounded-square node (Blender/Nuke/Unreal style): title inside the face,
  // sub-label inside below it; active nodes get accent border + glow +
  // left-edge stripe; inactive nodes are dim with no glow.
  function drawSquareNode(ctx, node, isHovered, isSelected, time) {
    const w = node.w || 140;
    const h = node.h || 50;
    const x = node.x - w / 2;
    const y = node.y - h / 2;
    const r = NODE_RADIUS;

    ctx.save();
    if (node.active && state.flow.motionEnabled) {
      ctx.shadowColor = node.accent;
      ctx.shadowBlur = 14;
    }

    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x, y, w, h, NODE_RADIUS);
    else ctx.rect(x, y, w, h);
    ctx.fillStyle = node.active ? "#17171a" : "#141416";
    ctx.fill();
    ctx.shadowBlur = 0;

    ctx.lineWidth = isSelected ? 2.5 : isHovered ? 2 : 1.5;
    ctx.strokeStyle = isSelected ? "#fff" : !node.active ? "rgba(255,255,255,0.18)" : isHovered ? "#fff" : node.accent;
    ctx.stroke();

    // Accent left-edge stripe for active nodes
    if (node.active) {
      ctx.fillStyle = node.accent;
      const sw = 4;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(x + 1, y + 4, sw, h - 8, 2);
      else ctx.rect(x + 1, y + 4, sw, h - 8);
      ctx.fill();
    }
    ctx.restore();

    // Title inside (top area)
    ctx.fillStyle = isSelected ? "#fff" : node.active ? "#f2f2f4" : "#9a9ba1";
    ctx.font = "600 12px Inter, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const title = String(node.name || "").slice(0, 24);
    ctx.fillText(title, node.x + 2, node.y - 8);

    // Sub-label inside below the title
    const subText = flowNodeSubLabel(node);
    if (subText) {
      ctx.fillStyle = node.active ? "#8a8b92" : "#62636a";
      ctx.font = "10px JetBrains Mono, monospace";
      ctx.fillText(subText.slice(0, 30), node.x + 2, node.y + 10);
    }
    ctx.textBaseline = "alphabetic";
  }

  function flowNodeSubLabel(node) {
    if (node.type === "harness") {
      const isC6 = node.data && (node.data.id === "harness-c6" || node.data.name === "c6");
      if (isC6) {
        return node.data.active_sessions > 0
          ? `${node.data.active_sessions} active`
          : "idle";
      }
      return node.data.active_sessions > 0
        ? `${node.data.active_sessions} active`
        : node.data.running
        ? "0 active"
        : "idle";
    } else if (node.type === "projects") {
      const d = node.data || {};
      return `${d.total || 0} · ${d.active_count || 0} active`;
    } else if (node.type === "project") {
      return node.data.changes_60m > 0 ? `${node.data.changes_60m} changes` : `${node.data.file_count || 0} files`;
    } else if (node.type === "service") {
      return node.data.port ? `:${node.data.port}` : node.data.detail || "";
    } else if (node.type === "datastores") {
      const hot = (node.data && node.data.hot) || 0;
      const count = (node.stores && node.stores.length) || 0;
      return hot > 0 ? `${hot}/${count} hot` : `${count} stores`;
    } else if (node.type === "filesystem") {
      const n = (node.data && node.data.recent && node.data.recent.length) || 0;
      return n > 0 ? `${n} recent writes` : "no recent writes";
    }
    return "";
  }

  // Horizontal bar for DATA STORES with labeled port dots along the top edge.
  // Hot stores get an accent dot + pulse glow; idle stores get a dim dot.
  function drawStoresBar(ctx, node, isHovered, isSelected, time) {
    const w = node.w || 320;
    const h = node.h || 64;
    const x = node.x - w / 2;
    const y = node.y - h / 2;
    const r = NODE_RADIUS;
    const pulse = state.flow.motionEnabled ? 0.5 + 0.5 * Math.sin(time / 250) : 1;

    // 1. Box background & border
    ctx.save();
    if (node.active && state.flow.motionEnabled) {
      ctx.shadowColor = node.accent;
      ctx.shadowBlur = 14;
    }
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x, y, w, h, NODE_RADIUS);
    else ctx.rect(x, y, w, h);
    ctx.fillStyle = node.active ? "#17171a" : "#141416";
    ctx.fill();
    ctx.shadowBlur = 0;

    ctx.lineWidth = isSelected ? 2.5 : isHovered ? 2 : 1.5;
    ctx.strokeStyle = isSelected ? "#fff" : !node.active ? "rgba(255,255,255,0.18)" : isHovered ? "#fff" : node.accent;
    ctx.stroke();

    // Accent left-edge stripe when active
    if (node.active) {
      ctx.fillStyle = node.accent;
      const sw = 4;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(x + 1, y + 4, sw, h - 8, 2);
      else ctx.rect(x + 1, y + 4, sw, h - 8);
      ctx.fill();
    }
    ctx.restore();

    // 2. Node Title & Sub-label (lower portion of the box)
    ctx.fillStyle = isSelected ? "#fff" : node.active ? "#f2f2f4" : "#9a9ba1";
    ctx.font = "600 12px Inter, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(node.name || "DATA STORES", node.x, node.y + 6);

    const subText = flowNodeSubLabel(node);
    if (subText) {
      ctx.fillStyle = node.active ? "#8a8b92" : "#62636a";
      ctx.font = "10px JetBrains Mono, monospace";
      ctx.fillText(subText, node.x, node.y + 20);
    }

    // 3. Port dots and labels along top edge
    (node.ports || []).forEach((p) => {
      const px = node.x + p.dx;
      const py = node.y + p.dy; // top edge of box

      ctx.save();
      ctx.beginPath();
      if (p.hot) {
        if (state.flow.motionEnabled) {
          ctx.shadowColor = node.accent;
          ctx.shadowBlur = 8 + 6 * pulse;
        }
        ctx.arc(px, py, 4.5, 0, Math.PI * 2);
        ctx.fillStyle = node.accent;
        ctx.fill();
        ctx.shadowBlur = 0;
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 1;
        ctx.stroke();
      } else {
        ctx.arc(px, py, 3.5, 0, Math.PI * 2);
        ctx.fillStyle = "#2d2e35";
        ctx.fill();
        ctx.strokeStyle = "rgba(255,255,255,0.35)";
        ctx.lineWidth = 1;
        ctx.stroke();
      }
      ctx.restore();

      // Port label below dot inside box
      ctx.fillStyle = p.hot ? node.accent : "#7a7b84";
      ctx.font = "9px JetBrains Mono, monospace";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(p.label, px, py + 14);
    });

    ctx.textBaseline = "alphabetic";
  }

  function drawFlowScene(time) {
    const canvas = document.getElementById("flow-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (!w || !h) return;

    ctx.save();
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);

    const f = state.flow;
    ctx.translate(w / 2 + f.panX, h / 2 + f.panY);
    ctx.scale(f.zoom, f.zoom);
    ctx.translate(-w / 2, -h / 2);

    // 0. Node-editor grid (world space: pans/zooms with the scene)
    drawFlowGrid(ctx, w, h);

    // 1. Draw Edges (port-aware endpoints)
    f.edges.forEach((edge) => {
      const a = flowEdgePoint(edge.source, edge.sourcePort);
      const b = flowEdgePoint(edge.target, edge.targetPort);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = edge.accent || "rgba(255,255,255,0.12)";
      ctx.lineWidth = edge.active ? 1.5 : 1.0;
      ctx.globalAlpha = edge.active ? 0.35 : 0.15;
      ctx.stroke();
      ctx.globalAlpha = 1.0;
    });

    // 2. Draw Moving Glowing Particles (real activity only; see spawn rule)
    if (f.motionEnabled) {
      f.particles.forEach((p) => {
        if (!p.edge.source || !p.edge.target) return;
        const a = flowEdgePoint(p.edge.source, p.edge.sourcePort);
        const b = flowEdgePoint(p.edge.target, p.edge.targetPort);
        const x = a.x + (b.x - a.x) * p.progress;
        const y = a.y + (b.y - a.y) * p.progress;

        ctx.beginPath();
        ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fillStyle = p.accent;
        ctx.shadowColor = p.accent;
        ctx.shadowBlur = 8;
        ctx.fill();
        ctx.shadowBlur = 0;
      });
    }

    // 3. Draw Nodes (squares; hub is a larger accent square with glyph)
    f.nodes.forEach((node) => {
      const isHovered = node === f.hoveredNode;
      const isSelected = f.selectedNode && f.selectedNode.id === node.id;

      if (node.type === "hub") {
        drawHubSquare(ctx, node, isHovered, isSelected);
      } else if (node.type === "datastores") {
        drawStoresBar(ctx, node, isHovered, isSelected, time);
      } else if (node.type === "projects") {
        drawProjectsNode(ctx, node, isHovered, isSelected, time);
      } else {
        drawSquareNode(ctx, node, isHovered, isSelected, time);
      }
    });

    ctx.restore();
  }

  function drawHubSquare(ctx, node, isHovered, isSelected) {
    const w = (node.w || 130) + (isHovered ? 6 : 0);
    const h = (node.h || 96) + (isHovered ? 6 : 0);
    const x = node.x - w / 2;
    const y = node.y - h / 2;

    ctx.save();
    if (state.flow.motionEnabled) {
      ctx.shadowColor = node.accent;
      ctx.shadowBlur = 18;
    }
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x, y, w, h, NODE_RADIUS);
    else ctx.rect(x, y, w, h);
    ctx.fillStyle = "#18181b";
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.strokeStyle = isSelected ? "#fff" : node.accent;
    ctx.lineWidth = isSelected ? 3.5 : 2.5;
    ctx.stroke();

    // Hydrocarbon Forge logo (cube with glowing hexagon outline and shaded faces)
    const logoX = node.x;
    const logoY = node.y - 19;
    const s = 0.35; // scales logo height to ~42px (~50-60% of inner area above label)

    // Render faces in tones lighter than #18181b background (#2e2e34 / #25252a / #1f1f23)
    function drawFace(pts, fillStyle) {
      ctx.beginPath();
      ctx.moveTo(logoX + pts[0][0] * s, logoY + pts[0][1] * s);
      for (let i = 1; i < pts.length; i++) {
        ctx.lineTo(logoX + pts[i][0] * s, logoY + pts[i][1] * s);
      }
      ctx.closePath();
      ctx.fillStyle = fillStyle;
      ctx.fill();
    }

    drawFace(FORGE_LOGO_TOP, "#2f2f35");
    drawFace(FORGE_LOGO_LEFT, "#26262b");
    drawFace(FORGE_LOGO_RIGHT, "#1f1f23");

    // Hexagon cube outline with node glow
    ctx.save();
    if (state.flow.motionEnabled) {
      ctx.shadowColor = node.accent;
      ctx.shadowBlur = 12;
    }
    ctx.beginPath();
    ctx.moveTo(logoX + FORGE_LOGO_HEX[0][0] * s, logoY + FORGE_LOGO_HEX[0][1] * s);
    for (let i = 1; i < FORGE_LOGO_HEX.length; i++) {
      ctx.lineTo(logoX + FORGE_LOGO_HEX[i][0] * s, logoY + FORGE_LOGO_HEX[i][1] * s);
    }
    ctx.closePath();
    ctx.strokeStyle = isSelected ? "#ffffff" : "#ffffff";
    ctx.lineWidth = FORGE_LOGO_STROKE_WIDTH * s;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.stroke();
    ctx.restore();

    ctx.restore();

    ctx.fillStyle = isSelected ? "#fff" : "#f2f2f4";
    ctx.font = "600 12px Inter, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(node.name, node.x, node.y + 14);
    ctx.fillStyle = "#8a8b92";
    ctx.font = "10px JetBrains Mono, monospace";
    ctx.fillText("online", node.x, node.y + 30);
    ctx.textBaseline = "alphabetic";
  }

  function formatFlowNodeTooltip(node) {
    let html = `<div style="font-weight:700; color:#fff; font-size:12px;">${escapeHtml(node.name)}</div>`;
    html += `<div style="color:${node.accent}; font-size:10px; text-transform:uppercase;">${node.type}</div>`;

    if (node.type === "harness") {
      const h = node.data || {};
      let lastActiveHtml = "";
      if (h.last_active_s !== null && h.last_active_s !== undefined) {
        const s = Math.round(h.last_active_s);
        const ageText = s < 60 ? `${s}s ago` : s < 3600 ? `${Math.floor(s / 60)}m ago` : `${Math.floor(s / 3600)}h ago`;
        lastActiveHtml = `<br>Last Active: <strong style="color:#fff;">${ageText}</strong>`;
      }
      html += `
        <div style="margin-top:6px; font-size:11px; color:var(--text-muted); word-break:break-word;">
          Active Sessions: <strong style="color:#fff;">${h.active_sessions || 0}</strong><br>
          Today's Tokens: <strong style="color:var(--accent);">${compactNum(h.tokens_today || 0)}</strong><br>
          Subtasks: ${h.subtasks || 0}${lastActiveHtml}
        </div>
      `;
    } else if (node.type === "projects") {
      const projs = (node.data && node.data.projects) || [];
      const rows = projs
        .map((p) => {
          const active = !!p.active;
          return `<div style="display:flex; justify-content:space-between; gap:8px; align-items:baseline; line-height:1.25; padding:1px 0;">
            <span style="color:${active ? node.accent : "#fff"}; word-break:break-word; min-width:0; overflow-wrap:break-word;">${escapeHtml(p.name)}${active ? " ●" : ""}</span>
            <span style="color:var(--text-dim); white-space:nowrap; flex-shrink:0;">${p.file_count || 0} files &middot; <strong style="color:${active ? "var(--accent)" : "inherit"};">${p.changes_60m || 0} chg</strong></span>
          </div>`;
        })
        .join("");
      html += `<div class="flow-tooltip-scrollable" style="margin-top:6px; font-size:10.5px; color:var(--text-muted); display:flex; flex-direction:column; gap:1px; max-height:320px; overflow-y:auto; overflow-x:hidden; word-break:break-word; scrollbar-width:none; -ms-overflow-style:none;">${rows || "No projects tracked."}</div>`;
    } else if (node.type === "project") {
      html += `
        <div style="margin-top:6px; font-size:11px; color:var(--text-muted);">
          Files: <strong>${node.data.file_count || 0}</strong><br>
          Changes (60m): <strong style="color:var(--accent);">${node.data.changes_60m || 0}</strong>
        </div>
      `;
    } else if (node.type === "service") {
      html += `
        <div style="margin-top:6px; font-size:11px; color:var(--text-muted);">
          Status: <strong style="color:${node.accent};">${node.data.status}</strong><br>
          Latency: ${node.data.latency_ms || 0} ms<br>
          Detail: ${escapeHtml(node.data.detail || "")}
        </div>
      `;
    } else if (node.type === "datastores") {
      const stores = node.stores || [];
      const rows = stores
        .map((db) => {
          const hot = isStoreHot(db);
          return `<div style="display:flex; justify-content:space-between; gap:8px;">
            <span style="color:${hot ? node.accent : "#fff"};">${escapeHtml(db.name)}${hot ? " ●" : ""}</span>
            <span style="color:var(--text-dim);">${escapeHtml(db.size_str || "—")} &middot; ${escapeHtml(db.last_write_age_str || "—")}</span>
          </div>`;
        })
        .join("");
      html += `<div style="margin-top:6px; font-size:11px; color:var(--text-muted); display:flex; flex-direction:column; gap:2px;">${rows || "No stores tracked."}</div>`;
    } else if (node.type === "filesystem") {
      const recent = (node.data && node.data.recent) || [];
      html += `<div style="margin-top:6px; font-size:11px; color:var(--text-muted);">${recent.length} recently changed files</div>`;
    }

    return html;
  }

  function showFlowNodeDetail(node) {
    state.flow.selectedNode = node;
    const drawer = document.getElementById("flow-detail-drawer");
    const titleEl = document.getElementById("flow-panel-title");
    const typeEl = document.getElementById("flow-panel-type");
    const bodyEl = document.getElementById("flow-panel-body");
    if (!drawer || !bodyEl) return;

    if (titleEl) titleEl.textContent = node.name;
    if (typeEl) {
      typeEl.textContent = node.type.toUpperCase();
      typeEl.style.color = node.accent;
    }

    let bodyHtml = "";

    if (node.type === "harness") {
      const h = node.data || {};
      const isC6 = h.id === "harness-c6" || h.name === "c6";
      const isC6Active = isC6 && h.running && (h.active_sessions > 0 || (h.last_active_s != null && h.last_active_s < 300));
      const isHarnessActive = isC6 ? isC6Active : (h.active_sessions > 0 || h.running);
      const statusText = h.active_sessions > 0
        ? `ACTIVE (${h.active_sessions} Sessions)`
        : isC6
        ? "IDLE"
        : h.running
        ? "RUNNING (0 Sessions)"
        : "IDLE";
      bodyHtml = `
        <div class="detail-section">
          <span class="detail-title">HARNESS STATUS</span>
          <div style="font-size:14px; font-weight:700; color:${isHarnessActive ? "var(--accent-green)" : "var(--text-dim)"}">
            ${statusText}
          </div>
        </div>
        <div class="kpi-grid">
          <div class="kpi-card"><div class="kpi-label">ACTIVE SESSIONS</div><div class="kpi-val">${h.active_sessions || 0}</div></div>
          <div class="kpi-card"><div class="kpi-label">TODAY'S TOKENS</div><div class="kpi-val accent">${compactNum(h.tokens_today || 0)}</div></div>
          <div class="kpi-card"><div class="kpi-label">SUBTASKS</div><div class="kpi-val">${h.subtasks || 0}</div></div>
          <div class="kpi-card"><div class="kpi-label">PROCESS PIDS</div><div class="kpi-val" style="font-size:16px;">${(h.pids || []).join(", ") || "none"}</div></div>
        </div>
      `;
    } else if (node.type === "projects") {
      const d = node.data || {};
      const projs = d.projects || [];
      const total = d.total !== undefined ? d.total : projs.length;
      const activeCount = d.active_count !== undefined ? d.active_count : projs.filter((p) => p.active).length;
      bodyHtml = `
        <div class="detail-section">
          <span class="detail-title">PROJECTS &middot; ${total} TOTAL (${activeCount} ACTIVE)</span>
          <div class="table-scroll" style="margin-top:8px;">
            <table class="data-table">
              <thead><tr><th>Project</th><th>Files</th><th>Changes (60m)</th><th>Status</th></tr></thead>
              <tbody>
                ${projs
                  .map((p) => {
                    const active = !!p.active;
                    return `
                  <tr>
                    <td style="color:${active ? "var(--accent)" : "#fff"}; font-size:11px; font-weight:600;">${escapeHtml(p.name)}${active ? " ●" : ""}</td>
                    <td style="color:var(--text-muted); font-size:10px;">${p.file_count || 0}</td>
                    <td style="color:${p.changes_60m > 0 ? "var(--accent)" : "var(--text-dim)"}; font-size:10px;">${p.changes_60m || 0}</td>
                    <td style="color:${active ? "var(--accent-green)" : "var(--text-dim)"}; font-size:10px;">${active ? "active" : "idle"}</td>
                  </tr>
                `;
                  })
                  .join("") || '<tr><td colspan="4" class="empty-cell">No projects tracked.</td></tr>'}
              </tbody>
            </table>
          </div>
        </div>
      `;
    } else if (node.type === "project") {
      const p = node.data;
      bodyHtml = `
        <div class="detail-section">
          <span class="detail-title">PROJECT DIRECTORY</span>
          <div class="detail-text" style="font-family:var(--font-mono); font-weight:600; color:#fff;">~/HydrocarbonForge/Projects/${escapeHtml(p.name)}</div>
        </div>
        <div class="kpi-grid">
          <div class="kpi-card"><div class="kpi-label">TOTAL FILES</div><div class="kpi-val">${p.file_count || 0}</div></div>
          <div class="kpi-card"><div class="kpi-label">CHANGES IN 60M</div><div class="kpi-val accent">${p.changes_60m || 0}</div></div>
        </div>
      `;
    } else if (node.type === "service") {
      const s = node.data;
      bodyHtml = `
        <div class="detail-section">
          <span class="detail-title">SERVICE HEALTH</span>
          <div style="font-size:15px; font-weight:700; color:${node.accent};">${s.status.toUpperCase()} (${s.detail || ""})</div>
        </div>
        <div class="kpi-grid">
          <div class="kpi-card"><div class="kpi-label">PORT</div><div class="kpi-val">${s.port ? ":" + s.port : "socket/proc"}</div></div>
          <div class="kpi-card"><div class="kpi-label">LATENCY</div><div class="kpi-val accent">${s.latency_ms || 0}ms</div></div>
        </div>
        ${s.url ? `<div class="detail-section"><span class="detail-title">ENDPOINT URL</span><div class="detail-text"><a href="${s.url}" target="_blank" style="color:var(--accent); text-decoration:underline;">${s.url} &rarr;</a></div></div>` : ""}
      `;
    } else if (node.type === "datastores") {
      const stores = node.stores || [];
      bodyHtml = `
        <div class="detail-section">
          <span class="detail-title">INSIGHTS DATA STORES &middot; ${stores.length} TRACKED</span>
          <div class="table-scroll" style="margin-top:8px;">
            <table class="data-table">
              <thead><tr><th>Store</th><th>Size</th><th>Last Write</th><th>Reader</th></tr></thead>
              <tbody>
                ${stores
                  .map((db) => {
                    const hot = isStoreHot(db);
                    return `
                  <tr>
                    <td style="color:${hot ? "var(--accent)" : "#fff"}; font-size:11px; font-weight:600;">${escapeHtml(db.name)}${hot ? " ●" : ""}</td>
                    <td style="color:var(--text-muted); font-size:10px;">${escapeHtml(db.size_str || "—")}</td>
                    <td style="color:${hot ? "var(--accent)" : "var(--text-dim)"}; font-size:10px;">${escapeHtml(db.last_write_age_str || "—")}</td>
                    <td style="color:var(--text-dim); font-size:10px;">${escapeHtml(db.reader || "—")}</td>
                  </tr>
                `;
                  })
                  .join("") || '<tr><td colspan="4" class="empty-cell">No data stores tracked.</td></tr>'}
              </tbody>
            </table>
          </div>
        </div>
      `;
    } else if (node.type === "filesystem") {
      const fs = node.data;
      const recent = fs.recent || [];
      bodyHtml = `
        <div class="detail-section">
          <span class="detail-title">RECENT WRITES &middot; PROJECTS</span>
          <div class="table-scroll" style="margin-top:8px;">
            <table class="data-table">
              <thead><tr><th>File</th><th>Age</th><th>Size</th></tr></thead>
              <tbody>
                ${recent
                  .map(
                    (f) => `
                  <tr>
                    <td style="color:#fff; font-size:11px;">${escapeHtml(f.path)}</td>
                    <td style="color:var(--accent); font-size:10px;">${f.age_m}m ago</td>
                    <td style="color:var(--text-dim); font-size:10px;">${formatByteSize(f.size)}</td>
                  </tr>
                `
                  )
                  .join("") || '<tr><td colspan="3" class="empty-cell">No recent file modifications.</td></tr>'}
              </tbody>
            </table>
          </div>
        </div>
      `;
    } else if (node.type === "hub") {
      bodyHtml = `
        <div class="detail-section">
          <span class="detail-title">CENTRAL ARCHITECTURE</span>
          <div class="detail-text">
            The Forge aggregates event telemetry and token metrics across all autonomous harnesses (OpenCode, Claude Code, Antigravity, C6) and connects them to data stores and projects.
          </div>
        </div>
      `;
    }

    bodyEl.innerHTML = bodyHtml;
    drawer.style.display = "flex";
  }

  /* ==================== UTILS & HELPERS ==================== */

  async function fetchJson(url) {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      const err = new Error(`Request to ${url} failed with status ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return res.json();
  }

  function computeOppScore(scores) {
    if (!scores) return null;
    const { ceiling, moat, capital, effort, risk } = scores;
    if ([ceiling, moat, capital, effort, risk].some((v) => v === undefined || v === null)) {
      return null;
    }
    return ceiling + moat - capital - effort - risk;
  }

  function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function formatNum(n) {
    return Number(n || 0).toLocaleString("en-US");
  }

  function compactNum(n) {
    n = Number(n || 0);
    if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
    return String(Math.round(n));
  }

  function formatMoney(amount) {
    return "$" + Number(amount || 0).toFixed(2);
  }

  function formatByteSize(bytes) {
    if (bytes === null || bytes === undefined) return "—";
    if (bytes >= 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + " MB";
    if (bytes >= 1024) return (bytes / 1024).toFixed(1) + " KB";
    return bytes + " B";
  }

  function formatAgeStr(dateVal) {
    if (!dateVal) return "—";
    let ts = 0;
    if (typeof dateVal === "number") {
      ts = dateVal > 1e11 ? dateVal / 1000 : dateVal;
    } else {
      ts = new Date(dateVal).getTime() / 1000;
    }
    const diff = Math.max(0, Math.floor(Date.now() / 1000 - ts));
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  }

  function escapeHtml(str) {
    return String(str ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        }[c])
    );
  }

  /* ==================== PROJECTS TAB ==================== */

  function initProjectsTab() {
    // 1. Search input listener
    const searchInput = document.getElementById("projects-search-input");
    if (searchInput) {
      searchInput.addEventListener("input", (e) => {
        state.projects.filter = e.target.value.trim().toLowerCase();
        renderProjectsTable();
      });
    }

    // 2. Open Add Modal
    const btnOpenAdd = document.getElementById("btn-open-add-project");
    const modalAdd = document.getElementById("modal-add-project");
    const btnCloseAdd = document.getElementById("btn-close-add-project");
    const btnCancelAdd = document.getElementById("btn-cancel-add-project");
    const formAdd = document.getElementById("form-add-project");

    if (btnOpenAdd && modalAdd) {
      btnOpenAdd.addEventListener("click", () => {
        formAdd.reset();
        const urlGroup = document.getElementById("add-proj-url-group");
        if (urlGroup) urlGroup.style.display = "none";
        modalAdd.style.display = "flex";
      });
    }
    if (btnCloseAdd && modalAdd) {
      btnCloseAdd.addEventListener("click", () => { modalAdd.style.display = "none"; });
    }
    if (btnCancelAdd && modalAdd) {
      btnCancelAdd.addEventListener("click", () => { modalAdd.style.display = "none"; });
    }
    if (modalAdd) {
      modalAdd.addEventListener("click", (e) => {
        if (e.target === modalAdd) modalAdd.style.display = "none";
      });
    }

    // Auto-slug on name input
    const addNameInput = document.getElementById("add-proj-name");
    const addIdInput = document.getElementById("add-proj-id");
    const addPathInput = document.getElementById("add-proj-path");
    if (addNameInput && addIdInput) {
      addNameInput.addEventListener("input", () => {
        const slug = addNameInput.value.toLowerCase().trim().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
        addIdInput.value = slug;
        if (addPathInput) {
          addPathInput.value = slug ? `~/HydrocarbonForge/Projects/${slug}` : "";
        }
      });
    }

    // Toggle URL group on deployed checkbox
    const addDepCheck = document.getElementById("add-proj-deployed");
    const addUrlGroup = document.getElementById("add-proj-url-group");
    if (addDepCheck && addUrlGroup) {
      addDepCheck.addEventListener("change", () => {
        addUrlGroup.style.display = addDepCheck.checked ? "flex" : "none";
      });
    }

    // Submit Add Form
    if (formAdd) {
      formAdd.addEventListener("submit", async (e) => {
        e.preventDefault();
        const name = document.getElementById("add-proj-name").value.trim();
        const id = document.getElementById("add-proj-id").value.trim();
        const path = document.getElementById("add-proj-path").value.trim();
        const description = document.getElementById("add-proj-desc").value.trim();
        const service = document.getElementById("add-proj-service").value.trim();
        const tagsRaw = document.getElementById("add-proj-tags").value.trim();
        const deployed = document.getElementById("add-proj-deployed").checked;
        const depUrl = document.getElementById("add-proj-url").value.trim();

        const tags = tagsRaw ? tagsRaw.split(",").map((t) => t.trim()).filter(Boolean) : [];
        const payload = { id, name, path, description, deployed, tags };
        if (service) payload.service = service;
        if (deployed && depUrl) payload.deployment_url = depUrl;

        try {
          const res = await fetch("/api/projects", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          if (!res.ok) {
            const err = await res.json();
            alert("Error creating project: " + (err.error || res.statusText));
            return;
          }
          modalAdd.style.display = "none";
          await fetchProjects();
          window.location.hash = `#/projects/${id}`;
        } catch (err) {
          alert("Network error: " + err.message);
        }
      });
    }

    // Edit Modal Handlers
    const modalEdit = document.getElementById("modal-edit-project");
    const btnCloseEdit = document.getElementById("btn-close-edit-project");
    const btnCancelEdit = document.getElementById("btn-cancel-edit-project");
    const formEdit = document.getElementById("form-edit-project");
    const btnEdit = document.getElementById("btn-edit-project");

    if (btnEdit && modalEdit) {
      btnEdit.addEventListener("click", () => {
        openEditModal();
      });
    }
    if (btnCloseEdit && modalEdit) {
      btnCloseEdit.addEventListener("click", () => { modalEdit.style.display = "none"; });
    }
    if (btnCancelEdit && modalEdit) {
      btnCancelEdit.addEventListener("click", () => { modalEdit.style.display = "none"; });
    }
    if (modalEdit) {
      modalEdit.addEventListener("click", (e) => {
        if (e.target === modalEdit) modalEdit.style.display = "none";
      });
    }

    const editDepCheck = document.getElementById("edit-proj-deployed");
    const editUrlGroup = document.getElementById("edit-proj-url-group");
    if (editDepCheck && editUrlGroup) {
      editDepCheck.addEventListener("change", () => {
        editUrlGroup.style.display = editDepCheck.checked ? "flex" : "none";
      });
    }

    if (formEdit) {
      formEdit.addEventListener("submit", async (e) => {
        e.preventDefault();
        const id = document.getElementById("edit-proj-id").value;
        const name = document.getElementById("edit-proj-name").value.trim();
        const path = document.getElementById("edit-proj-path").value.trim();
        const description = document.getElementById("edit-proj-desc").value.trim();
        const service = document.getElementById("edit-proj-service").value.trim();
        const tagsRaw = document.getElementById("edit-proj-tags").value.trim();
        const deployed = document.getElementById("edit-proj-deployed").checked;
        const depUrl = document.getElementById("edit-proj-url").value.trim();

        const tags = tagsRaw ? tagsRaw.split(",").map((t) => t.trim()).filter(Boolean) : [];
        const payload = { name, path, description, deployed, tags };
        payload.service = service || "";
        if (deployed) {
          payload.deployment_url = depUrl || "";
        } else {
          payload.deployment_url = "";
        }

        try {
          const res = await fetch(`/api/projects/${id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          if (!res.ok) {
            const err = await res.json();
            alert("Error updating project: " + (err.error || res.statusText));
            return;
          }
          modalEdit.style.display = "none";
          await fetchProjects();
          showProjectDetail(id);
        } catch (err) {
          alert("Network error: " + err.message);
        }
      });
    }

    // Back to Projects button
    const btnBack = document.getElementById("btn-back-to-projects");
    if (btnBack) {
      btnBack.addEventListener("click", () => {
        window.location.hash = "#/projects";
      });
    }

    // Delete Project Button
    const btnDelete = document.getElementById("btn-delete-project");
    if (btnDelete) {
      btnDelete.addEventListener("click", async () => {
        const id = state.projects.activeProjectId;
        if (!id) return;
        const proj = state.projects.items.find((p) => p.id === id);
        const name = proj ? proj.name : id;
        if (!confirm(`Are you sure you want to delete project "${name}"?`)) return;

        try {
          const res = await fetch(`/api/projects/${id}`, { method: "DELETE" });
          if (!res.ok) {
            const err = await res.json();
            alert("Error deleting project: " + (err.error || res.statusText));
            return;
          }
          await fetchProjects();
          window.location.hash = "#/projects";
        } catch (err) {
          alert("Network error: " + err.message);
        }
      });
    }
  }

  function openEditModal() {
    const id = state.projects.activeProjectId;
    if (!id) return;
    const proj = state.projects.items.find((p) => p.id === id);
    if (!proj) return;

    document.getElementById("edit-proj-id").value = proj.id;
    document.getElementById("edit-proj-name").value = proj.name || "";
    document.getElementById("edit-proj-path").value = proj.path || "";
    document.getElementById("edit-proj-desc").value = proj.description || "";
    document.getElementById("edit-proj-service").value = proj.service || "";
    document.getElementById("edit-proj-tags").value = (proj.tags || []).join(", ");
    const isDeployed = Boolean(proj.deployed);
    document.getElementById("edit-proj-deployed").checked = isDeployed;
    const urlGroup = document.getElementById("edit-proj-url-group");
    if (urlGroup) urlGroup.style.display = isDeployed ? "flex" : "none";
    document.getElementById("edit-proj-url").value = proj.deployment_url || "";

    const modalEdit = document.getElementById("modal-edit-project");
    if (modalEdit) modalEdit.style.display = "flex";
  }

  async function fetchProjects() {
    try {
      const res = await fetch("/api/projects");
      if (res.ok) {
        const data = await res.json();
        state.projects.items = Array.isArray(data) ? data : (data.projects || []);
        updateProjectsCount();
        renderProjectsTable();
        if (state.projects.activeProjectId) {
          showProjectDetail(state.projects.activeProjectId, false);
        }
      }
    } catch (e) {
      console.warn("Failed to fetch projects", e);
    }
  }

  function updateProjectsCount() {
    const el = document.getElementById("projects-count-badge");
    if (el) el.textContent = `${state.projects.items.length} PROJECTS`;
  }

  function renderProjectsTable() {
    const tbody = document.getElementById("projects-table-body");
    if (!tbody) return;

    const filter = (state.projects.filter || "").toLowerCase();
    const filtered = state.projects.items.filter((p) => {
      if (!filter) return true;
      const haystack = `${p.name} ${p.id} ${p.description || ""} ${p.service || ""} ${(p.tags || []).join(" ")}`.toLowerCase();
      return haystack.includes(filter);
    });

    if (filtered.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" class="empty-cell">No projects match "${escapeHtml(filter)}"</td></tr>`;
      return;
    }

    tbody.innerHTML = filtered.map((p) => {
      const statusBadge = p.deployed
        ? `<span class="chip badge-deployed">DEPLOYED</span>`
        : `<span class="chip badge-not-deployed">NOT DEPLOYED</span>`;

      const tagsHtml = (p.tags || []).map((t) => `<span class="project-tag-pill">${escapeHtml(t)}</span>`).join("");
      const serviceHtml = p.service
        ? `<span class="chip" style="color:var(--accent-steel);">${escapeHtml(p.service)}</span>`
        : `<span style="color:var(--text-dim);">-</span>`;

      return `
        <tr data-project-id="${escapeHtml(p.id)}">
          <td>
            <div style="font-weight:600; color:#fff; font-size:13px;">${escapeHtml(p.name)}</div>
            <div style="color:var(--text-dim); font-size:11px;">${escapeHtml(p.id)}</div>
          </td>
          <td>
            <div style="color:var(--text-muted); font-size:12px; margin-bottom:4px;">${escapeHtml(p.description || "—")}</div>
            <div>${tagsHtml}</div>
          </td>
          <td>${serviceHtml}</td>
          <td>${statusBadge}</td>
          <td style="color:var(--text-dim); font-size:11px;">${escapeHtml(p.updated || "—")}</td>
        </tr>
      `;
    }).join("");

    // Click handler for rows
    tbody.querySelectorAll("tr[data-project-id]").forEach((tr) => {
      tr.addEventListener("click", () => {
        const id = tr.getAttribute("data-project-id");
        window.location.hash = `#/projects/${id}`;
      });
    });
  }

  function showProjectsList() {
    state.projects.activeProjectId = null;
    const listView = document.getElementById("projects-list-view");
    const detailView = document.getElementById("project-detail-view");
    if (listView) listView.style.display = "block";
    if (detailView) detailView.style.display = "none";
  }

  function showProjectDetail(id, updateHash = true) {
    state.projects.activeProjectId = id;
    if (updateHash) {
      window.location.hash = `#/projects/${id}`;
    }

    const listView = document.getElementById("projects-list-view");
    const detailView = document.getElementById("project-detail-view");
    if (listView) listView.style.display = "none";
    if (detailView) detailView.style.display = "block";

    const proj = state.projects.items.find((p) => p.id === id);
    const container = document.getElementById("project-detail-content");
    if (!container) return;

    if (!proj) {
      container.innerHTML = `
        <div class="project-main-card">
          <div style="color:var(--accent-red); font-weight:600; margin-bottom:8px;">Project '${escapeHtml(id)}' not found</div>
          <div style="color:var(--text-muted);">This project does not exist in the central database.</div>
        </div>
      `;
      return;
    }

    const statusBadge = proj.deployed
      ? `<span class="chip badge-deployed">DEPLOYED</span>`
      : `<span class="chip badge-not-deployed">NOT DEPLOYED</span>`;

    const tagsHtml = (proj.tags && proj.tags.length > 0)
      ? proj.tags.map((t) => `<span class="project-tag-pill">${escapeHtml(t)}</span>`).join(" ")
      : `<span style="color:var(--text-dim);">none</span>`;

    let deploymentBannerHtml = "";
    if (proj.deployed && proj.deployment_url) {
      deploymentBannerHtml = `
        <div class="deploy-banner-active">
          <div class="deploy-banner-left">
            <div class="deploy-banner-title">⚡ ACTIVE DEPLOYMENT</div>
            <a href="${escapeHtml(proj.deployment_url)}" target="_blank" rel="noopener noreferrer" class="deploy-banner-url">
              ${escapeHtml(proj.deployment_url)} ↗
            </a>
          </div>
          <a href="${escapeHtml(proj.deployment_url)}" target="_blank" rel="noopener noreferrer" class="deploy-open-btn">
            OPEN DEPLOYMENT →
          </a>
        </div>
      `;
    } else {
      deploymentBannerHtml = `
        <div class="deploy-banner-inactive">
          <span class="deploy-inactive-text">No active deployment recorded for this project.</span>
          <button class="btn primary" id="btn-quick-record-deploy">RECORD DEPLOYMENT</button>
        </div>
      `;
    }

    container.innerHTML = `
      <div class="project-main-card">
        <div class="project-title-row">
          <h1 class="project-detail-name">${escapeHtml(proj.name)}</h1>
          ${statusBadge}
        </div>
        <div class="project-detail-desc">${escapeHtml(proj.description || "No description provided.")}</div>

        <div class="project-meta-grid">
          <div class="project-meta-item">
            <span class="project-meta-label">ID Slug</span>
            <span class="project-meta-val">${escapeHtml(proj.id)}</span>
          </div>
          <div class="project-meta-item">
            <span class="project-meta-label">Path</span>
            <span class="project-meta-val">${escapeHtml(proj.path || "—")}</span>
          </div>
          <div class="project-meta-item">
            <span class="project-meta-label">Service</span>
            <span class="project-meta-val">${escapeHtml(proj.service || "—")}</span>
          </div>
          <div class="project-meta-item">
            <span class="project-meta-label">Tags</span>
            <div class="project-meta-val">${tagsHtml}</div>
          </div>
          <div class="project-meta-item">
            <span class="project-meta-label">Last Updated</span>
            <span class="project-meta-val">${escapeHtml(proj.updated || "—")}</span>
          </div>
        </div>

        ${deploymentBannerHtml}
      </div>
    `;

    const quickRecordBtn = container.querySelector("#btn-quick-record-deploy");
    if (quickRecordBtn) {
      quickRecordBtn.addEventListener("click", () => {
        openEditModal();
      });
    }
  }

  // Expose state for inspection
  window.state = state;

  // Self-initialize on DOM load
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initShell);
  } else {
    initShell();
  }
})();
