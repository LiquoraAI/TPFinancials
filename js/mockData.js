/**
 * 模拟数据：5 家同行业公司 2021–2025 年度（来自 PPT：A股上市公司同行业对比）
 */
const MOCK_COMPANIES = [
  { id: "A", name: "若羽臣" },
  { id: "B", name: "丽人丽妆" },
  { id: "C", name: "壹网壹创" },
  { id: "D", name: "青木科技" },
  { id: "E", name: "凯淳股份" },
];

const MOCK_YEARS = [2021, 2022, 2023, 2024, 2025];

function randomIn(min, max) {
  return Math.round(min + Math.random() * (max - min));
}

function buildMockSeries(years, base, growthPct) {
  const out = [];
  let v = base;
  for (const y of years) {
    out.push({ year: y, value: Math.round(v) });
    v *= 1 + growthPct / 100;
  }
  return out;
}

/** 按筛选条件生成当前看板用的模拟数据 */
function getMockData(options) {
  const { yearFrom, yearTo, companyIds, granularity } = options;
  const years = [];
  for (let y = yearFrom; y <= yearTo; y++) years.push(y);
  const companies = MOCK_COMPANIES.filter((c) => companyIds.includes(c.id));
  if (companies.length === 0) return null;

  const revenueBase = [3200, 2800, 2100, 1800, 1500];
  const profitBase = [420, 350, 180, 120, 90];
  const data = {
    years,
    companies,
    overview: { revenue: [], netProfit: [] },
    finance: {},
    valuation: {},
    efficiency: {},
    conclusions: {},
  };

  companies.forEach((c, i) => {
    const rev = buildMockSeries(years, revenueBase[i], 8 + (i % 5));
    const profit = buildMockSeries(years, profitBase[i], 5 + (i % 4));
    data.overview.revenue.push({ company: c.name, series: rev });
    data.overview.netProfit.push({ company: c.name, series: profit });
    data.finance[c.id] = {
      revenue: rev,
      netProfit: profit,
      grossMargin: years.map((y, j) => ({ year: y, value: 58 + (i + j) % 12 })),
      netMargin: years.map((y, j) => ({ year: y, value: 10 + (i + j) % 8 })),
      roe: years.map((y, j) => ({ year: y, value: 12 + (i + j) % 10 })),
      roa: years.map((y, j) => ({ year: y, value: 6 + (i + j) % 5 })),
    };
    data.valuation[c.id] = {
      pe: years.map(() => ({ value: 18 + randomIn(0, 25) })),
      pb: years.map(() => ({ value: 2.5 + Math.random() * 3 })),
      ps: years.map(() => ({ value: 1.2 + Math.random() * 2 })),
    };
    data.efficiency[c.id] = {
      inventoryTurnover: years.map(() => ({ value: 4 + Math.random() * 4 })),
      receivablesTurnover: years.map(() => ({ value: 6 + Math.random() * 6 })),
      debtRatio: years.map(() => ({ value: 35 + Math.random() * 25 })),
    };
  });

  data.conclusions = {
    overview: [
      "行业整体 2021–2025 收入复合增速约 8%–12%，头部公司集中度提升。",
      "净利润增速分化明显，公司A、公司B 盈利能力强于同业。",
      "毛利率普遍在 55%–70% 区间，高端化与成本控制是主要驱动。",
    ],
    valuation: "当前估值处于近五年中位数附近，PE 分化较大，建议结合增速与ROE筛选。",
    risk: [
      "部分公司存货周转率下行，需关注渠道库存与终端动销。",
      "应收账款周转放缓的公司现金流压力可能加大。",
      "资产负债率超过 60% 的公司需关注偿债与再融资能力。",
    ],
    recommend: companies.slice(0, 2).map((c) => `建议重点关注：${c.name}（收入与盈利增速领先）`),
    summaryRisks: [
      "行业竞争加剧可能导致毛利率承压。",
      "宏观消费波动将影响终端需求。",
    ],
  };

  return data;
}
