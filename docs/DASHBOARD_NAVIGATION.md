# Dashboard 导航梳理与方案

## 一、现状

### 1.1 路由与页面

| 路径 | 页面说明 |
|------|----------|
| `/dashboard` | 主控制台：Summary 卡片、Provider Keys、Proxy Keys（应用列表）、Recent Requests |
| `/requests` | 全部请求列表（分页、按应用/模型/状态筛选） |
| `/requests/{request_id}` | 单条请求详情 |
| `/applications/{app_id}` | 应用概览（统计、最近请求、模型/状态分布） |
| `/applications/{app_id}/analytics` | 应用分析（时间范围、Prompt 分析、Tool 使用等） |
| `/applications/{app_id}/deep-analytics` | Deep Analytics（缓存、Token 分解、Tool 调用等） |

操作类（非页面）：`/add-provider`、`/add-proxy`、`/delete-provider/{id}`、`/delete-proxy/{id}`、`/toggle-proxy/{id}`、`/test-proxy/{id}`。

### 1.2 当前各页导航

- **Dashboard**
  - 顶部：标题 + 三个**本页锚点**（Provider Keys、Proxy Keys、Statistics），无「请求列表」「应用列表」等独立入口。
  - 表格内：应用名 → Analytics，应用名下小字 → Deep Analytics；Recent Requests 区有「View All」→ `/requests`。
- **Requests 列表**
  - 仅「Back to Dashboard」，无「应用」或「请求详情」的层级入口。
- **Request 详情**
  - 仅「Back to Dashboard」，无「返回请求列表」或「所属应用」。
- **Application 概览**（`/applications/{id}`）
  - Back to Dashboard；右侧：Analytics、Test Connectivity。**无 Deep Analytics 入口**。
- **Application Analytics**
  - Back to Dashboard；右侧：Overview、Test；内容区：Overview、All Requests。**无 Deep Analytics 入口**。
- **Deep Analytics**
  - Back to Dashboard；右侧：Overview、Analytics。无「All Requests」入口。

### 1.3 存在的问题

1. **层级不清晰**：子页大多只强调「回 Dashboard」，缺少「上一级 / 同级」的稳定入口（如请求详情应有「返回列表」「所属应用」）。
2. **入口不一致**：Deep Analytics 只在 Dashboard 表格和 Deep Analytics 自身 nav 出现；应用概览、Analytics 页都没有 Deep Analytics 入口。
3. **全局入口缺失**：Dashboard 没有「全部请求」「应用列表」的显式主导航；Requests 页没有「按应用」的入口说明，只能靠筛选。
4. **命名与心智**：「Back to Dashboard」在各处重复，容易让人以为所有路径都以 Dashboard 为唯一枢纽；应用维度的「Overview / Analytics / Deep Analytics」关系未在导航上统一呈现。
5. **锚点易误解**：Dashboard 顶部的 Provider Keys / Proxy Keys / Statistics 是锚点而非独立页面，易被当成主导航。

---

## 二、需求（目标）

- **层级清晰**：任意子页都能明确「当前在哪、上一级/同级有哪些」，且有一致的返回路径（如列表 → 详情 → 列表）。
- **入口统一**：同一功能（如某应用的 Analytics / Deep Analytics / 请求列表）在相关页面都有可预期的入口，不依赖「只在某页才有」的链接。
- **主导航简洁**：Dashboard 顶部或侧边有少量、稳定的主导航（如 Dashboard、Requests、Applications），子页在此基础上做「当前应用/请求」的局部导航。
- **可选的体验**：面包屑或 Tab 让「应用概览 / Analytics / Deep Analytics」的关系一目了然。

---

## 三、方案 A：顶部主导航 + 应用内 Tab

### 思路

- 所有页面使用**统一的顶部导航栏**，左侧 Logo/标题，右侧固定 3 个主导航：**Dashboard**、**Requests**、**Applications**（或「Keys & Apps」合并到 Dashboard，仅 **Dashboard**、**Requests**）。
- **Dashboard**：保持现有内容，顶部锚点可保留或收起到「本页内跳转」小菜单。
- **Requests**：列表页为默认；请求详情页在顶栏下增加「← Back to list」或面包屑 `Requests > {id}`。
- **Applications**：  
  - 若单独做「应用列表」页，则列表为 `/applications`，点击进入 `/applications/{id}`。  
  - 若不做单独列表，则「Applications」下拉或点击后仍跳 Dashboard 的 Proxy Keys 区块，或 Dashboard 保留「应用列表」表格，顶栏「Applications」仅高亮并锚点到 `#proxy-keys`。
- **应用维度**（进入某应用后）：在顶栏下方或页面内增加 **Tab**：**Overview** | **Analytics** | **Deep Analytics** | **Requests**（当前应用的请求），保证三个分析入口和请求列表在同一层级、任意子页都能切到。

### 主要改动

- 抽一个**公共 nav 片段**（如 `_nav.html` 或 Python 生成函数），各路由渲染时传入 `current_page`（dashboard / requests / applications）和可选的 `app_id`、`request_id`。
- Dashboard：顶栏增加「Requests」「Applications」链接；锚点可改为下拉或保留。
- Requests 列表 / 请求详情：使用公共顶栏；详情页增加「Back to list」「所属应用」链接。
- 应用概览 / Analytics / Deep Analytics：共用顶栏 + 应用名 + 同一套 Tab（Overview / Analytics / Deep Analytics / Requests），Tab 高亮当前页。
- 可选：新增 `/applications` 列表页，或继续用 Dashboard 的 Proxy Keys 表格作为「应用列表」入口。

### 优点

- 任意页面都能快速跳到「全部请求」或「应用维度」，心智一致。
- 应用内 Tab 明确「Overview / Analytics / Deep Analytics」关系，Deep Analytics 入口统一。

### 缺点

- 需抽公共 nav 并给各路由传参；若做独立 `/applications` 列表，多一层页面。

---

## 四、方案 B：侧边栏 + 面包屑

### 思路

- 使用**固定侧边栏**作为主导航（可折叠）：**Dashboard**、**Requests**、**Applications**（或 **Keys & Apps** 与 Dashboard 合并后为 **Dashboard**、**Requests**）。
- **Dashboard**：侧边栏高亮 Dashboard；本页仍可保留 Summary、Provider Keys、Proxy Keys、Recent Requests。
- **Requests**：侧边栏高亮 Requests；列表与详情页共用侧栏，详情页在内容区上方加面包屑 `Requests > Detail #{id}`，并带「返回列表」「所属应用」链接。
- **Applications**：  
  - 侧边栏可展示「应用列表」或仅「Applications」入口点进 Dashboard 的 Proxy Keys 区块 / 独立应用列表页。  
  - 进入某应用后，侧栏二级展开该应用，或内容区上方面包屑：`Applications > {AppName} > Overview | Analytics | Deep Analytics`，子页用 Tab 或链接切换。

### 主要改动

- 引入**布局模板**：左侧侧边栏（公共）+ 右侧主内容区；侧栏项与路由一一对应，支持「当前项」高亮和可选的二级展开（当前应用）。
- 各子页在内容区上方渲染**面包屑**（如 `Dashboard > Applications > MyApp > Analytics`），面包屑可点击。
- 应用维度的 Overview / Analytics / Deep Analytics：通过侧栏「当前应用」下的子项，或面包屑 + 子 Tab 切换，保证三处入口统一。
- 请求详情：面包屑 `Requests > {id}`，并增加「Back to list」「View in Application」链接。

### 优点

- 侧边栏适合功能较多的后台，扩展性好；面包屑明确层级，便于「从哪里来、回哪里去」。

### 缺点

- 布局改动大，需统一 wrap 所有 dashboard 相关页；侧栏在小屏需考虑折叠或抽屉。

---

## 五、业界常见做法（参考）

### 5.1 可观测性产品：Grafana / Datadog

- **Grafana（Saga 设计系统）**
  - **Megamenu** 作为主导航：覆盖 L1～L3 信息架构；L4 用**页内 Tab**，L5+ 用标题、步骤等。
  - **面包屑**：表示**层级位置**（hierarchy），不是浏览历史；每个面包屑对应真实页面，可点击。
  - **Return to previous**：从「远处」跳过来时（如配置 SLO 后跳到告警规则），用独立组件「返回上一工作上下文」，避免用户只靠浏览器后退或面包屑找路。
  - 规范：名词、句首大写、L1 配图标；为每个 overview/分类提供落地页，不靠重定向凑面包屑。

- **Datadog（导航改版）**
  - **侧边栏**分区：顶部 = 搜索 + **最近访问**；中间 = 按**产品域**分组（Infrastructure、APM、Logs、Security 等）；底部 = 核心能力（Logs、Metrics 等）+ 管理/帮助。
  - 按**使用场景/产品域**组织，而非按数据库表；列表可扫读，重要功能按使用频率和关系排序。
  - 侧栏对比度与可读性单独优化，支持收藏与较长标题。

### 5.2 管理后台 UX 共识

- **任务导向**：按操作者任务组织（如「处理退款」「审批验证」），而不是按实体表；减少点击和认知负担。
- **渐进披露**：首屏只展示关键信息，高级功能按需展开；KPI 在上、下钻在下（倒金字塔）。
- **导航要素**：可折叠侧栏、清晰标签、面包屑、粘性顶栏、全局搜索；移动端适配（侧栏收成抽屉/汉堡菜单）。
- **一致性**：统一配色、图标、布局与设计系统，便于扩展。

### 5.3 资源型后台（React-Admin / Filament / ActiveAdmin）

- **资源 = 列表 + 详情 + 子资源**：例如 Applications → Application 详情 → Overview / Analytics / Requests；每层都有明确「上一级」和「同级」入口。
- **嵌套资源**：子资源用 Tab 或二级侧栏（Overview | Analytics | Deep Analytics），避免深层级多级 Tab。
- **面包屑**：与路由/资源层级一致，如 `Applications > MyApp > Analytics`。

---

## 六、方案 C：业界对齐版（侧栏 + 面包屑 + 应用 Tab + Return to previous）

在方案 B 基础上，显式对齐 Grafana/Datadog 与资源型后台的常见做法，适合「希望一次做到业界水准」的场景。

### 思路

1. **固定侧边栏**（可折叠）
   - **顶部**：产品名 + 可选「最近访问」（如最近 3 个应用/请求），便于跨分支快速返回。
   - **L1**：**Dashboard** | **Requests** | **Applications**（每项配图标）；Applications 点击进入应用列表（或 Dashboard #proxy-keys）。
   - **底部**：设置/API Docs 等（若有）。

2. **面包屑**（仅表示层级，不表示历史）
   - 所有子页在内容区上方：`Dashboard`、`Requests`、`Requests > {id}`、`Applications`、`Applications > {AppName}`、`Applications > {AppName} > Analytics` 等；每段可点击跳转。

3. **应用维度**：同一套 **Tab**
   - 进入任意应用后，内容区上方：应用名 + Tab：**Overview** | **Analytics** | **Deep Analytics** | **Requests**（该应用的请求）；Tab 对应层级视为 L4，不再嵌套。

4. **Request 详情页**
   - 面包屑：`Requests > Detail #{id}`；增加「Back to list」「View in Application」链接。
   - 若用户是从「某应用 → 某请求」跳过来的，可增加 **Return to previous** 区块（如「从 MyApp 过来 → 返回 MyApp」），避免只能回 Requests 列表。

5. **Dashboard 本页**
   - 侧栏高亮 Dashboard；本页内「Provider Keys / Proxy Keys / Statistics」保留为**锚点或区块标题**，不在侧栏重复；侧栏不展示「本页锚点」为一级菜单，避免与真实页面混淆。

### 与业界的对应关系

| 做法 | 来源 | 在本方案中的体现 |
|------|------|------------------|
| 侧栏按域/任务分区 | Datadog | Dashboard / Requests / Applications 三域 |
| 面包屑 = 层级、可点击 | Grafana | 所有子页统一面包屑，不表示历史 |
| Return to previous | Grafana | 请求详情页「从某应用来」时提供返回应用 |
| 最近访问 | Datadog | 侧栏顶部可选「最近访问」 |
| 资源 + 子资源 Tab | React-Admin / Filament | 应用 → Overview / Analytics / Deep Analytics / Requests |
| L4 用 Tab、不深嵌套 | Grafana | 应用下仅一层 Tab |

### 主要改动

- 布局模板：侧栏 + 主内容区；侧栏组件接收 `current_section`、可选 `app_id`。
- 面包屑组件：接收 `crumbs` 列表（如 `[("Dashboard", "/dashboard"), ("Applications", "/dashboard#proxy-keys"), ("MyApp", "/applications/xxx"), ("Analytics", None)]`），最后一项为当前页不链接。
- 应用相关三页 + 应用列表（若有）：共用同一 Tab 组件与高亮逻辑。
- 请求详情：若 `referrer` 或 session 能识别「从某应用进入」，则渲染「Return to previous: 返回 {AppName}」。

### 优点

- 与 Grafana/Datadog/资源型后台的主流模式一致，后续扩展（如加「设置」「审计」）可直接挂到侧栏与面包屑。
- 层级清晰、入口统一；跨分支场景有 Return to previous，体验更完整。

### 缺点

- 实现量最大：统一布局、侧栏、面包屑、Tab、可选「最近访问」与 Return to previous；小屏需侧栏折叠/抽屉。

---

## 七、方案对比与建议

| 维度 | 方案 A（顶栏 + Tab） | 方案 B（侧栏 + 面包屑） | 方案 C（业界对齐版） |
|------|----------------------|-------------------------|---------------------------|
| 实现量 | 中 | 较大 | 最大 |
| 层级表达 | Tab + 文案 | 面包屑 | 面包屑 + Tab + 可选 Return to previous |
| 扩展性 | 顶栏不宜过多 | 侧栏易扩展 | 侧栏 + 最近访问，扩展性最好 |
| 与业界一致度 | 通用 | 常见 | 对齐 Grafana/Datadog/资源型后台 |
| 移动端 | 顶栏→汉堡菜单 | 侧栏→抽屉 | 同 B |

- **先快速止血**：做**方案 A**（统一顶栏 + 应用内 Tab + 请求详情「返回列表 / 所属应用」），改动适中。
- **中期成型**：做**方案 B**，侧栏 + 面包屑，结构清晰。
- **一次做到业界水准**：做**方案 C**，在 B 的基础上加上「面包屑仅表层级」「应用统一 Tab」「Request 详情 Return to previous」及可选的「最近访问」，与 Grafana/Datadog 等可观测产品、以及资源型管理后台的常见模式对齐。

以上为现状梳理、业界做法参考与三个方案，可按资源与产品预期择一或分阶段实施。
