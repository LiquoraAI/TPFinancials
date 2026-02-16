(function () {
  /* 图表配色：5 条线/柱区分明显（凯淳=橙，靛蓝改黄） */
  const COLORS = ["#2563eb", "#059669", "#7c3aed", "#ca8a04", "#ea580c"];
  let chartInstances = {};

  var DATA_MAINT_API_BASE = "";  /* 与主面板同源，由 server.py 统一服务 */

  /* 看板公司 id（与 mockData 一致）与股票代码对应，用于 /api/data 的 records */
  var COMPANY_ID_TO_CODE = { A: "003010", B: "605136", C: "300792", D: "301110", E: "301001" };
  var CODE_TO_ID = {};
  Object.keys(COMPANY_ID_TO_CODE).forEach(function (k) { CODE_TO_ID[COMPANY_ID_TO_CODE[k]] = k; });

  /** 从 financials.json 的 records 构建与 getMockData 相同结构，供图表使用 */
  function buildDataFromRecords(records, options) {
    var yearFrom = options.yearFrom;
    var yearTo = options.yearTo;
    var companyIds = options.companyIds || [];
    var years = [];
    for (var y = yearFrom; y <= yearTo; y++) years.push(y);
    var selectedCodes = companyIds.map(function (id) { return COMPANY_ID_TO_CODE[id]; }).filter(Boolean);
    if (selectedCodes.length === 0) return null;

    var codeToName = {};
    records.forEach(function (r) {
      if (!codeToName[r.stock_code]) codeToName[r.stock_code] = r.stock_name;
    });
    var companies = companyIds.map(function (id) {
      var code = COMPANY_ID_TO_CODE[id];
      return { id: id, name: codeToName[code] || id };
    }).filter(function (c) { return selectedCodes.indexOf(COMPANY_ID_TO_CODE[c.id]) >= 0; });

    function getRecord(code, period) {
      return records.find(function (r) { return r.stock_code === code && r.period === String(period); });
    }

    var data = {
      years: years,
      companies: companies,
      overview: { revenue: [], netProfit: [] },
      finance: {},
      valuation: {},
      efficiency: {},
      conclusions: {},
    };

    companies.forEach(function (c) {
      var code = COMPANY_ID_TO_CODE[c.id];
      var revSeries = years.map(function (y) {
        var r = getRecord(code, y);
        var v = r && r.revenue != null ? Math.round(r.revenue / 1e6) : null;
        return { year: y, value: v };
      });
      var profitSeries = years.map(function (y) {
        var r = getRecord(code, y);
        var v = r && r.net_profit != null ? Math.round(r.net_profit / 1e6) : null;
        return { year: y, value: v };
      });
      var totalAssetsSeries = years.map(function (y) {
        var r = getRecord(code, y);
        var v = r && r.total_assets != null ? Math.round(r.total_assets / 1e6) : null;
        return { year: y, value: v };
      });
      data.overview.revenue.push({ company: c.name, series: revSeries });
      data.overview.netProfit.push({ company: c.name, series: profitSeries });
      data.finance[c.id] = {
        revenue: revSeries,
        netProfit: profitSeries,
        totalAssets: totalAssetsSeries,
        grossMargin: years.map(function (y) {
          var r = getRecord(code, y);
          return { year: y, value: r && r.gross_margin_pct != null ? r.gross_margin_pct : null };
        }),
        netMargin: years.map(function (y) {
          var r = getRecord(code, y);
          return { year: y, value: r && r.net_margin_pct != null ? r.net_margin_pct : null };
        }),
        roe: years.map(function (y) {
          var r = getRecord(code, y);
          return { year: y, value: r && r.roe_pct != null ? r.roe_pct : null };
        }),
        roa: years.map(function (y) { return { year: y, value: null }; }),
      };
      var debtSeries = years.map(function (y) {
        var r = getRecord(code, y);
        return { value: r && r.debt_ratio_pct != null ? r.debt_ratio_pct : null };
      });
      data.efficiency[c.id] = {
        inventoryTurnover: years.map(function () { return { value: null }; }),
        receivablesTurnover: years.map(function () { return { value: null }; }),
        debtRatio: debtSeries.length ? debtSeries : years.map(function () { return { value: null }; }),
      };
      data.valuation[c.id] = {
        pe: years.map(function () { return { value: null }; }),
        pb: years.map(function () { return { value: null }; }),
        ps: years.map(function () { return { value: null }; }),
      };
    });

    var mock = getMockData(options);
    if (mock) {
      data.conclusions = mock.conclusions || {};
      data.valuation = mock.valuation || data.valuation;
    }
    return data;
  }

  /** 优先从 /api/data 拉取 financials.json，无数据或失败时用 mock */
  function loadDashboardData(options) {
    return fetch(DATA_MAINT_API_BASE + "/api/data")
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (!res.records || res.records.length === 0) return getMockData(options);
        return buildDataFromRecords(res.records, options);
      })
      .catch(function () { return getMockData(options); });
  }

  function loadDataMaintLog() {
    fetch(DATA_MAINT_API_BASE + "/api/log")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.entries && data.entries.length) renderDataMaintLog(data.entries, data.run_at);
        else renderDataMaintLog([], data.run_at);
      })
      .catch(function () { renderDataMaintLog([], null); });
  }

  function renderDataMaintLog(entries, runAt) {
    var tbody = document.getElementById("dataMaintLogBody");
    var hint = document.getElementById("dataMaintHint");
    if (!tbody) return;
    if (hint) hint.style.display = entries.length ? "none" : "block";
    tbody.innerHTML = entries.length
      ? entries.map(function (e) {
          var statusClass = e.status === "成功" ? "log-success" : e.status === "失败" ? "log-fail" : "log-partial";
          return "<tr><td>" + (e.stock_name || "") + " (" + (e.stock_code || "") + ")</td><td><span class=\"log-status " + statusClass + "\">" + (e.status || "") + "</span></td><td>" + (e.message || "") + "</td><td>" + (e.timestamp || runAt || "") + "</td></tr>";
        }).join("")
      : "<tr><td colspan=\"4\">暂无记录，请点击「Update最新数据」执行一次更新。</td></tr>";
  }

  function getSelectedCompanies() {
    const checked = document.querySelectorAll("#companyCheckboxes input:checked");
    return Array.from(checked).map(function (el) { return el.value; });
  }

  function getOptions() {
    return {
      yearFrom: parseInt(document.getElementById("yearFrom").value, 10),
      yearTo: parseInt(document.getElementById("yearTo").value, 10),
      companyIds: getSelectedCompanies(),
      granularity: document.getElementById("granularity").value,
    };
  }

  function getSeries(data, parentKey, childKey, c) {
    var arr = data[parentKey][c.id][childKey];
    return arr.map(function (p) { return p && p.value != null ? p.value : null; });
  }

  function disposeChart(key) {
    if (chartInstances[key]) {
      chartInstances[key].dispose();
      chartInstances[key] = null;
    }
  }

  function baseOption(yAxisName) {
    return {
      textStyle: { color: "#5c5a57", fontFamily: "Plus Jakarta Sans, PingFang SC, Microsoft YaHei, sans-serif" },
      tooltip: { trigger: "axis", confine: true },
      legend: { top: 8, left: "center", textStyle: { color: "#3d3b38" } },
      grid: { left: "3%", right: "4%", bottom: "3%", top: "15%", containLabel: true },
      xAxis: { type: "category", boundaryGap: true, axisLine: { lineStyle: { color: "#d4d0c8" } }, axisLabel: { color: "#5c5a57" } },
      yAxis: { type: "value", name: yAxisName || "", nameTextStyle: { color: "#5c5a57" }, axisLine: { show: false }, splitLine: { lineStyle: { color: "rgba(0,0,0,0.08)" } }, axisLabel: { color: "#5c5a57" } },
    };
  }

  function renderOverview(data) {
    var el = document.getElementById("chartOverview");
    if (!el) return;
    disposeChart("overview");

    var years = data.years.map(String);
    var series = [];
    data.overview.revenue.forEach(function (s, i) {
      series.push({
        name: s.company + " 收入",
        type: "line",
        smooth: true,
        data: s.series.map(function (p) { return p.value; }),
        itemStyle: { color: COLORS[i] },
        yAxisIndex: 0,
      });
    });
    data.overview.netProfit.forEach(function (s, i) {
      series.push({
        name: s.company + " 净利润",
        type: "bar",
        data: s.series.map(function (p) { return p.value; }),
        itemStyle: { color: COLORS[i] },
        yAxisIndex: 1,
      });
    });

    var option = {
      textStyle: { color: "#5c5a57", fontFamily: "Plus Jakarta Sans, PingFang SC, Microsoft YaHei, sans-serif" },
      tooltip: { trigger: "axis", confine: true },
      legend: { top: 8, left: "center", textStyle: { color: "#3d3b38" } },
      grid: { left: "3%", right: "4%", bottom: "3%", top: "18%", containLabel: true },
      xAxis: { type: "category", boundaryGap: true, data: years, axisLine: { lineStyle: { color: "#d4d0c8" } }, axisLabel: { color: "#5c5a57" } },
      yAxis: [
        { type: "value", name: "收入(百万)", position: "left", nameTextStyle: { color: "#5c5a57" }, axisLine: { show: false }, splitLine: { lineStyle: { color: "rgba(0,0,0,0.08)" } }, axisLabel: { color: "#5c5a57" } },
        { type: "value", name: "净利润(百万)", position: "right", nameTextStyle: { color: "#5c5a57" }, axisLine: { show: false }, splitLine: { show: false }, axisLabel: { color: "#5c5a57" } },
      ],
      series: series,
    };
    chartInstances.overview = echarts.init(el);
    chartInstances.overview.setOption(option);
  }

  function renderBarChart(canvasId, key, data, parentKey, childKey, title) {
    var el = document.getElementById(canvasId);
    if (!el) return;
    disposeChart(key);

    var years = data.years.map(String);
    var series = data.companies.map(function (c, i) {
      return {
        name: c.name,
        type: "bar",
        data: getSeries(data, parentKey, childKey, c),
        itemStyle: { color: COLORS[i] },
      };
    });

    var option = baseOption(title);
    option.xAxis.data = years;
    option.series = series;
    chartInstances[key] = echarts.init(el);
    chartInstances[key].setOption(option);
  }

  function renderLineChart(canvasId, key, data, parentKey, childKey, title) {
    var el = document.getElementById(canvasId);
    if (!el) return;
    disposeChart(key);

    var years = data.years.map(String);
    var series = data.companies.map(function (c, i) {
      return {
        name: c.name,
        type: "line",
        smooth: true,
        data: getSeries(data, parentKey, childKey, c),
        itemStyle: { color: COLORS[i] },
        lineStyle: { color: COLORS[i] },
      };
    });

    var option = baseOption(title);
    option.xAxis.data = years;
    option.xAxis.boundaryGap = false;
    option.series = series;
    chartInstances[key] = echarts.init(el);
    chartInstances[key].setOption(option);
  }

  function renderCompanyCheckboxes() {
    var container = document.getElementById("companyCheckboxes");
    if (!container) return;
    container.innerHTML = MOCK_COMPANIES.map(function (c) {
      return '<label><input type="checkbox" value="' + c.id + '" checked /> ' + c.name + "</label>";
    }).join("");
  }

  function fillTable(tableId, headers, rows) {
    var table = document.getElementById(tableId);
    if (!table) return;
    table.innerHTML =
      "<thead><tr>" +
      headers.map(function (h) { return "<th>" + h + "</th>"; }).join("") +
      "</tr></thead><tbody>" +
      rows.map(function (r) { return "<tr>" + r.map(function (c) { return "<td>" + c + "</td>"; }).join("") + "</tr>"; }).join("") +
      "</tbody>";
  }

  function fmtVal(v) { return v != null && v !== "" ? v : "-"; }

  function renderFinanceTable(data) {
    var headers = ["公司", "指标"].concat(data.years.map(String));
    var rows = [];
    data.companies.forEach(function (c) {
      var rev = data.finance[c.id].revenue;
      var profit = data.finance[c.id].netProfit;
      var totalAssets = data.finance[c.id].totalAssets || [];
      var gm = data.finance[c.id].grossMargin;
      var roe = data.finance[c.id].roe;
      rows.push([c.name, "总资产(百万)"].concat((totalAssets.length ? totalAssets : rev.map(function () { return "-"; })).map(function (p) { return fmtVal(p && p.value); })));
      rows.push([c.name, "收入(百万)"].concat(rev.map(function (p) { return fmtVal(p.value); })));
      rows.push([c.name, "净利润(百万)"].concat(profit.map(function (p) { return fmtVal(p.value); })));
      rows.push([c.name, "毛利率(%)"].concat(gm.map(function (p) { return fmtVal(p.value); })));
      rows.push([c.name, "ROE(%)"].concat(roe.map(function (p) { return fmtVal(p.value); })));
    });
    fillTable("tableFinance", headers, rows);
  }

  function renderValuationTable(data) {
    var headers = ["公司", "PE", "PB", "PS"];
    var rows = data.companies.map(function (c) {
      var v = data.valuation[c.id];
      var peArr = v.pe.filter(function (x) { return x.value != null; });
      var pbArr = v.pb.filter(function (x) { return x.value != null; });
      var psArr = v.ps.filter(function (x) { return x.value != null; });
      var pe = peArr.length ? (peArr.reduce(function (a, x) { return a + x.value; }, 0) / peArr.length).toFixed(1) : "-";
      var pb = pbArr.length ? (pbArr.reduce(function (a, x) { return a + x.value; }, 0) / pbArr.length).toFixed(2) : "-";
      var ps = psArr.length ? (psArr.reduce(function (a, x) { return a + x.value; }, 0) / psArr.length).toFixed(2) : "-";
      return [c.name, pe, pb, ps];
    });
    fillTable("tableValuation", headers, rows);
  }

  function renderEfficiencyTable(data) {
    var headers = ["公司", "存货周转率", "应收周转率", "资产负债率(%)"];
    var rows = data.companies.map(function (c) {
      var e = data.efficiency[c.id];
      var invArr = (e.inventoryTurnover || []).filter(function (x) { return x.value != null; });
      var recArr = (e.receivablesTurnover || []).filter(function (x) { return x.value != null; });
      var drArr = (e.debtRatio || []).filter(function (x) { return x.value != null; });
      var inv = invArr.length ? (invArr.reduce(function (a, x) { return a + x.value; }, 0) / invArr.length).toFixed(2) : "-";
      var rec = recArr.length ? (recArr.reduce(function (a, x) { return a + x.value; }, 0) / recArr.length).toFixed(2) : "-";
      var dr = drArr.length ? (drArr.reduce(function (a, x) { return a + x.value; }, 0) / drArr.length).toFixed(1) : "-";
      return [c.name, inv, rec, dr];
    });
    fillTable("tableEfficiency", headers, rows);
  }

  function renderConclusions(data) {
    var list = function (arr) { return "<ul>" + arr.map(function (t) { return "<li>" + t + "</li>"; }).join("") + "</ul>"; };
    var overviewEl = document.getElementById("overviewConclusions");
    if (overviewEl) overviewEl.innerHTML = list(data.conclusions.overview);
    var valuationEl = document.getElementById("valuationConclusion");
    if (valuationEl) valuationEl.textContent = data.conclusions.valuation;
    var riskEl = document.getElementById("riskConclusions");
    if (riskEl) riskEl.innerHTML = list(data.conclusions.risk);
    var recEl = document.getElementById("summaryRecommend");
    if (recEl) recEl.innerHTML = data.conclusions.recommend.map(function (t) { return "<li>" + t + "</li>"; }).join("");
    var sumRiskEl = document.getElementById("summaryRisks");
    if (sumRiskEl) sumRiskEl.innerHTML = data.conclusions.summaryRisks.map(function (t) { return "<li>" + t + "</li>"; }).join("");
  }

  function runAnalysis() {
    var options = getOptions();
    if (options.companyIds.length === 0) {
      alert("请至少选择一家公司");
      return;
    }
    if (options.yearFrom > options.yearTo) {
      alert("时间范围无效");
      return;
    }
    loadDashboardData(options).then(function (data) {
      if (!data) return;
      renderOverview(data);
      renderBarChart("chartTotalAssets", "totalAssets", data, "finance", "totalAssets", "总资产(百万)");
      renderBarChart("chartRevenue", "revenue", data, "finance", "revenue", "收入(百万)");
      renderBarChart("chartNetProfit", "netProfit", data, "finance", "netProfit", "净利润(百万)");
      renderLineChart("chartMargin", "margin", data, "finance", "grossMargin", "毛利率(%)");
      renderLineChart("chartROE", "roe", data, "finance", "roe", "ROE(%)");
      renderFinanceTable(data);

      renderLineChart("chartPE", "pe", data, "valuation", "pe", "PE");
      renderLineChart("chartPB", "pb", data, "valuation", "pb", "PB");
      renderLineChart("chartPS", "ps", data, "valuation", "ps", "PS");
      renderValuationTable(data);

      renderBarChart("chartInventoryTurnover", "inv", data, "efficiency", "inventoryTurnover", "存货周转率");
      renderBarChart("chartReceivablesTurnover", "rec", data, "efficiency", "receivablesTurnover", "应收周转率");
      renderBarChart("chartLeverage", "lev", data, "efficiency", "debtRatio", "资产负债率(%)");
      renderEfficiencyTable(data);

      renderConclusions(data);
    });
  }

  function switchTab(tabId) {
    document.querySelectorAll(".tab-btn").forEach(function (btn) {
      var isActive = btn.getAttribute("data-tab") === tabId;
      btn.classList.toggle("active", isActive);
      btn.setAttribute("aria-selected", isActive ? "true" : "false");
    });
    document.querySelectorAll(".tab-pane").forEach(function (pane) {
      pane.classList.toggle("active", pane.id === "pane-" + tabId);
    });
    setTimeout(function () {
      Object.keys(chartInstances).forEach(function (key) {
        if (chartInstances[key]) chartInstances[key].resize();
      });
    }, 50);
  }

  function init() {
    renderCompanyCheckboxes();
    function onFilterChange() { runAnalysis(); }
    document.getElementById("yearFrom").addEventListener("change", onFilterChange);
    document.getElementById("yearTo").addEventListener("change", onFilterChange);
    document.getElementById("granularity").addEventListener("change", onFilterChange);
    document.getElementById("companyCheckboxes").addEventListener("change", onFilterChange);
    document.querySelectorAll(".tab-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        switchTab(btn.getAttribute("data-tab"));
        if (btn.getAttribute("data-tab") === "data-maint") loadDataMaintLog();
      });
    });
    runAnalysis();

    var btnUpdate = document.getElementById("btnUpdateData");
    if (btnUpdate) {
      btnUpdate.addEventListener("click", function () {
        var statusEl = document.getElementById("dataMaintStatus");
        var hintEl = document.getElementById("dataMaintHint");
        if (statusEl) statusEl.textContent = "正在更新…";
        if (hintEl) hintEl.style.display = "none";
        var parseEl = document.getElementById("dataMaintParse");
        if (parseEl) parseEl.textContent = "";
        var granularity = document.getElementById("granularity") ? document.getElementById("granularity").value : "annual";
        var body = { granularity: granularity };
        if (granularity === "annual") body.categories = ["年报"];
        fetch(DATA_MAINT_API_BASE + "/api/update-reports", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (statusEl) statusEl.textContent = data.ok ? "更新完成" : (data.error || "更新失败");
            var parseEl = document.getElementById("dataMaintParse");
            if (parseEl) parseEl.textContent = data.parse_msg ? " · 第二步: " + data.parse_msg : "";
            if (data.entries && data.entries.length) renderDataMaintLog(data.entries, data.run_at);
            else loadDataMaintLog();
          })
          .catch(function (e) {
            if (statusEl) statusEl.textContent = "请求失败";
            if (hintEl) hintEl.style.display = "block";
            console.error(e);
          });
      });
    }

    var btnParseForce = document.getElementById("btnParseForce");
    if (btnParseForce) {
      btnParseForce.addEventListener("click", function () {
        var parseEl = document.getElementById("dataMaintParse");
        var logEl = document.getElementById("dataMaintParseLog");
        if (logEl) logEl.textContent = "";
        if (parseEl) parseEl.textContent = "正在连接…";
        btnParseForce.disabled = true;

        function finish(summary) {
          btnParseForce.disabled = false;
          if (parseEl) parseEl.textContent = summary || "解析结束";
          if (summary && summary.indexOf("DONE:") === 0) runAnalysis();
        }

        fetch(DATA_MAINT_API_BASE + "/api/parse-reports-stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ force: true, annual_only: true }),
        })
          .then(function (response) {
            if (!response.ok) throw new Error(response.statusText);
            if (parseEl) parseEl.textContent = "解析中，请查看下方实时日志…";
            if (!response.body) {
              return response.text().then(function (text) {
                if (logEl) logEl.textContent = text;
                var last = text.trim().split("\n").pop() || "";
                finish(last);
              });
            }
            var reader = response.body.getReader();
            var decoder = new TextDecoder();
            var buf = "";
            function read() {
              return reader.read().then(function (result) {
                if (result.done) {
                  if (buf && logEl) logEl.textContent += buf;
                  var full = logEl ? logEl.textContent.trim() : "";
                  var last = full ? full.split("\n").pop() : "";
                  finish(last);
                  return;
                }
                buf += decoder.decode(result.value, { stream: true });
                var lines = buf.split("\n");
                buf = lines.pop() || "";
                if (logEl) {
                  for (var i = 0; i < lines.length; i++) logEl.textContent += lines[i] + "\n";
                  logEl.scrollTop = logEl.scrollHeight;
                }
                return read();
              });
            }
            return read();
          })
          .catch(function (e) {
            if (logEl) logEl.textContent += "\n请求失败: " + e.message;
            finish("请求失败");
            console.error(e);
          });
      });
    }

    window.addEventListener("resize", function () {
      Object.keys(chartInstances).forEach(function (key) {
        if (chartInstances[key]) chartInstances[key].resize();
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
