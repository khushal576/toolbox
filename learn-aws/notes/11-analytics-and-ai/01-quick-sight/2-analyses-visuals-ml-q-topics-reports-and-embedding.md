# Amazon Quick Sight – 2. Analyses, visuals, ML, Q topics, reports and embedding

Short notes. Each point is a fact you can be asked about.

## A. Analyses, sheets and dashboards
- **Analysis** = the author's editable workspace; **only authors** (and co-owners) open analyses.
- An analysis holds **sheets** (tabs); each sheet holds **visuals**, text boxes, images, filters, parameters and controls.
- **Sheet limits**: about **20 sheets per analysis** and about **50 visuals per sheet** **(verify)**.
- **Sheet types**: **interactive sheet** (normal dashboard) and **pixel-perfect (paginated) sheet** for print-style reports.
- **Layouts**: **free-form** (pixel position), **tiled** (grid that snaps) and **classic** **(verify current layout names)**.
- **One analysis can use several datasets** (up to about 50 **(verify)**); each visual uses **one dataset**.
- **Catch**: two datasets in one analysis are **not joined**; filters across them need **cross-dataset filters / parameters** on matching field names.
- **Dashboard** = published, **read-only snapshot** of an analysis; readers can filter, drill and use controls but **cannot change the design**.
- **Publishing** creates a **new dashboard version**; you can **roll back** to an earlier version **(verify rollback in console)**.
- **Publish options**: allow **ad hoc filtering**, **export to CSV/Excel**, **expand-on-hover menu**, **reader-created alerts**, **data point drill**, **Q&A** **(verify full list)**.
- **Dashboard permissions**: **viewer** (read) or **co-owner** (edit, share, delete); share with **users, groups, or everyone in the account**.
- **Analysis sharing**: share an analysis with other authors as **co-owners** to collaborate.
- **Saving an analysis as a copy** (Save as) creates an independent analysis; changes don't flow back.
- **Readers see dashboards, never datasets**; but **anyone with dataset access can see all its columns** unless CLS/RLS restricts them.
- **Bookmarks**: readers save their own filter states on a dashboard **(verify)**.
- **Folders**: **personal** and **shared** folders; shared folders carry **permissions** to their assets and help organize by team **(verify restricted folders)**.
- **Themes**: color palettes, fonts, spacing, backgrounds; apply to an analysis and its dashboard for **branding**; can be shared.
- **Templates**: a reusable **definition** of an analysis/dashboard without data; create dashboards from a template by swapping in datasets with the **same schema** (`CreateTemplate`, `CreateDashboard`).

## B. Visual types (know when each fits)
- **AutoGraph**: Quick picks a visual type from the fields you drag in.
- **Bar charts** (horizontal/vertical, clustered, stacked, 100% stacked): compare categories.
- **Line and area charts**: trends over time; **combo chart** = bars + line (two measures, two scales).
- **Pie and donut**: part-to-whole with few categories (trap: many slices are unreadable).
- **KPI visual**: one value vs target or prior period, with trend and conditional color; supports **threshold alerts**.
- **Gauge**: value against a range/target; supports **threshold alerts**.
- **Table** (flat rows) and **pivot table** (rows × columns, subtotals, totals); pivot tables support **conditional formatting** and collapsing.
- **Scatter plot**: relationship between two measures (bubble size can show a third).
- **Heat map**: two dimensions colored by a measure; **tree map**: hierarchical part-to-whole by area.
- **Histogram**: distribution of one measure in bins; **box plot**: distribution with quartiles and outliers.
- **Waterfall**: running total of positive and negative changes (P&L bridge).
- **Funnel**: stage-by-stage drop-off (sales pipeline, conversion).
- **Sankey**: flows between categories (source → target with weight).
- **Radar chart**: compare several measures across categories.
- **Word cloud**: frequency of text values.
- **Geospatial**: **points on map**, **filled map** (choropleth by country/state), and **layer maps** **(verify layer map name)**; need geospatial roles or lat/long.
- **Insight visual**: auto-generated **narrative text** (ML insights, see section E).
- **Custom visual content**: embed a web page/URL in a visual; **Highcharts visual** for custom chart code **(verify)**.
- **Text box, image** for annotation and branding.
- **Field wells**: dimensions (group by/color), measures (values), and small multiples on supported visuals.
- **Small multiples**: split one chart into a grid by a dimension.
- **Conditional formatting**: color/icons on tables, pivot tables, KPIs by rules or gradients.
- **Reference lines** and **forecast** lines can be added to line/bar charts.
- **Sorting, top/bottom N filters, "other" grouping** control busy categories.

## C. Filters, interactivity and actions
- **Filter scopes**: apply to **one visual**, **selected visuals**, **all visuals on a sheet** that use the dataset, or **across sheets** **(verify cross-sheet filter name)**.
- **Filter types**: **category** (list/custom), **numeric** (range, top/bottom), **date** (relative, range, rolling), and **filter conditions on calculated fields**.
- **Dataset-level filters** (set in data prep) apply to **every analysis** and reduce SPICE size; **analysis filters** apply only there.
- **Filter on aggregated vs row level**: some filters can act after aggregation (e.g. "sum of sales > 1000") **(verify option name)**.
- **Controls** connect filters/parameters to UI widgets placed at the **top of the sheet** or **inside the sheet**.
- **Cascading controls**: one control limits the choices in another (country → city).
- **Filter action**: click a data point in one visual to **filter other visuals** (cross-visual filtering).
- **Navigation action**: click to **jump to another sheet**, optionally setting **parameters**.
- **URL action**: open an external link with field values in the URL (e.g. CRM record page).
- **Drill-down / drill-up**: add a **field hierarchy** (year → quarter → month, or country → state → city) to a field well; readers drill on click.
- **Date hierarchy** drill is built in for date fields.
- **Parameters in URLs**: dashboard URL can pass parameter values (`#p.ParamName=value`) to open a pre-filtered view **(verify syntax)**.
- **Highlighting**: selecting a point can highlight related points across visuals **(verify)**.
- **Ad hoc filtering** on dashboards lets readers add their own filters if the publisher allowed it.
- **Catch**: actions work only between visuals of the **same dataset** unless fields are mapped **(verify cross-dataset actions)**.

## D. Alerts
- **Threshold alerts**: readers set an alert on a **KPI or gauge** value (e.g. "sales below 1,000") and get an **email** when crossed.
- **Edition**: threshold alerts are **Enterprise** **(verify)**.
- **Evaluation timing**: checked when **SPICE data refreshes**; for **direct query** datasets, checked on a schedule set by the author **(verify schedule)**.
- **Anomaly alerts**: subscribe to anomaly detection insights to get emails when an **anomaly is found** in a metric.
- **Pricing**: alerts and anomaly detection bill **per 1,000 metrics evaluated**: **$0.50** (first 1 M), **$0.25** (1–10 M), **$0.10** (10–100 M), **$0.05** (over 100 M).
- **Catch**: anomaly detection across many dimensions explodes the number of metrics → cost; limit dimensions.
- **Catch**: alerts cannot fire faster than the data refreshes (SPICE).

## E. ML insights (built in, no ML skills needed)
- **ML insights** are an **Enterprise** feature using ML built into Quick Sight.
- **Anomaly detection**: uses **Random Cut Forest (RCF)** to find outliers in a time series across many dimension combinations; set **sensitivity** and the fields to analyze.
- **Anomaly detection needs** a **date field**, at least **one measure** and optional dimensions; a minimum number of data points is required **(verify count)**.
- **Anomaly detection is not supported on datasets that use RLS** (docs).
- **Anomaly detection runs** after each SPICE refresh or on a schedule **(verify)**.
- **Contribution analysis (key drivers)**: explains **which dimensions drove** an anomaly or change.
- **Forecasting**: ML forecast (RCF-based, handles **seasonality and trend**) on line charts with a date field; set **forecast length**, **prediction interval**, seasonality; **what-if** edits **(verify what-if)**.
- **Forecast catch**: needs enough history (at least a few seasonal cycles) and a **single date field** at regular granularity.
- **Autonarratives** (insight visual): text summaries like "Top 3 regions", "Month-over-month change", "Forecast"; editable with an expression-style editor.
- **Suggested insights**: Quick proposes insights when you build visuals.
- **SageMaker AI integration**: run inference with a **SageMaker model** during SPICE ingestion to add prediction columns **(verify current status)**.
- **Where heavier ML belongs**: SageMaker AI; Quick Sight ML insights are for **analysts, not data scientists**.

## F. Q topics and generative BI (Pro roles)
- **Topic** = a curated layer over one or more datasets for **natural-language questions**; authors set **friendly names, synonyms, semantic types** (currency, date, location), default aggregations and **named entities**.
- **Why topics**: Q maps words like "revenue" or "last quarter" to the right fields; better metadata = better answers.
- **Asking questions**: users type questions ("top 5 products by sales in 2025") in the **Q bar / Ask** box and get a visual plus answer **(verify bar name in Quick)**.
- **Topics need indexing/refresh** after dataset changes so new values (product names) are recognized **(verify)**.
- **Q&A billing**: enabling topics Q&A or **Dashboard Q&A** triggers the **$250/month account fee**; **question capacity** pricing exists (500 questions/month for $250, then $0.50) for anonymous/embedded Q **(verify scope)**.
- **Annual question capacity**: 60,000/yr for $18,000 ($0.30 extra), 600,000/yr for $120,000 ($0.20 extra).
- **Author Pro** generative BI: **build visuals by describing them**, **build calculated fields from a description**, refine visuals, create topics faster.
- **Reader Pro** generative BI: **executive summaries** of dashboards, **data stories**, **ask questions** of dashboards.
- **Plain Reader / Author** roles **do not get generative BI**; upgrade the specific people to **Pro**.
- **Data stories**: AI-drafted narrative documents mixing visuals and text, for sharing insights **(verify sharing rules)**.
- **Executive summary**: AI summary of key points on a dashboard sheet.
- **Dashboard Q&A**: ask questions from a dashboard without a hand-built topic (topic auto-created) **(verify)**.
- **Quick (umbrella) features**: chat agents, **Spaces**, **Flows/Automate** can use Quick Sight dashboards and topics as context **(verify specifics)**.
- **Catch**: generative answers follow **RLS/CLS** of the user asking **(verify)**.
- **Old exam wording**: "Amazon Q in QuickSight" or "QuickSight Q" = these natural-language features.

## G. Stories, pixel-perfect reports, email reports and exports
- **Stories / data stories**: guided narrative sequences of captured views (older "stories" in analyses) or AI-generated stories for Pro users.
- **Pixel-perfect (paginated) reports**: print-ready, **multi-page** reports (invoices, statements, regulatory reports) with exact layout, headers/footers, page breaks.
- **Pixel-perfect is an add-on** (Enterprise) billed by **report units** **(verify add-on requirement)**.
- **Report unit** = up to **100 pages or 100 MB** of generated report.
- **Pricing**: monthly plan **500 units for $500** ($1.00 per extra unit); annual plan **4,000 units/month for $24,000/yr** ($0.50 per extra unit).
- **Scheduled email reports**: send a dashboard sheet or paginated report by **email on a schedule** as **PDF**, with optional **CSV/Excel** attachments **(verify formats)**.
- **Email report options**: recipients (users/groups), schedule, which sheet, and **"send to users with their own RLS view"** behavior → each recipient gets **their own filtered data** **(verify)**.
- **Exports from visuals**: **CSV** and **Excel** (data), **PDF** (dashboard/sheet print) if the publisher allowed export.
- **Snapshot export API**: `StartDashboardSnapshotJob` generates **PDF/CSV/Excel** of a dashboard for a user (programmatic reports) **(verify formats)**.
- **Catch**: export can leak data → disable with **publish options** or **custom permissions** (file 3).
- **Interactive dashboard vs pixel-perfect**: interactive = explore on screen; pixel-perfect = fixed pages to print/archive.
- **Cost trap**: a big scheduled pixel-perfect report to many recipients burns **many report units** (each 100 pages / 100 MB = 1 unit).
- **Pick the delivery**: people need numbers in their inbox → **email report**; people need to explore → **dashboard link**; system needs a file → **snapshot API**.
- **Exam skill 3.2.1 (visualize data)**: know which visual fits the question (trend → line, compare → bar, distribution → histogram/box plot, flow → Sankey, geography → map, single number → KPI).
- **Exam trap**: "real-time operational metrics for engineers" → CloudWatch/Grafana, not Quick Sight dashboards.

## H. Embedding – types
- **Embedded analytics** = put Quick Sight dashboards, visuals, the authoring console or Q into **your own web app/portal**.
- **Embedding is Enterprise**.
- **Two user models**: **registered users** (they have a Quick user identity) and **anonymous users** (no Quick identity).
- **Registered-user API**: `GenerateEmbedUrlForRegisteredUser` (dashboards, single visuals, **full console/authoring**, Q search bar, generative Q&A).
- **Anonymous-user API**: `GenerateEmbedUrlForAnonymousUser` (dashboards, single visuals, Q search bar/generative Q&A) **(verify Q experiences)**; **no authoring console** for anonymous users.
- **Old APIs** `GetDashboardEmbedUrl` / `GetSessionEmbedUrl` still work but **lack the newer features** (docs).
- **Registered users** are billed as normal **Readers/Authors** (per user) or sessions **(verify)**; they keep their own permissions and **user-based RLS** applies.
- **Anonymous embedding needs session capacity pricing**; without it the call returns **`UnsupportedPricingPlanException`** (docs).
- **Anonymous embedding needs a namespace** in the request (`default` or another) (docs).
- **Experience configuration** names what to show: `Dashboard` (InitialDashboardId), `DashboardVisual` (dashboard, sheet, visual IDs), `QSearchBar` **(verify)**.
- **AuthorizedResourceArns**: list of dashboard ARNs the anonymous session may open (can switch between them).
- **Visual embedding**: embed one **single visual** instead of a whole dashboard.

## I. Embedding – security, sessions and SDK
- **Flow**: user hits your app → app backend (IAM role with `quicksight:GenerateEmbedUrlFor...`) calls the API → gets a signed URL → front end loads it in an **iframe** via the **Embedding SDK**.
- **Never call the embed API from the browser**: the backend holds AWS credentials.
- **Embed URL validity**: **5 minutes** to start the session; it carries a one-time **auth code** (docs).
- **Session lifetime**: `SessionLifetimeInMinutes` **15–600 minutes**, **default 600 (10 hours)** (docs).
- **Catch**: an embed URL can be used **once**; refreshing the page with the same URL fails → generate a new URL.
- **Domain allow-list**: the host domain must be on the account's **allowed domains** (Manage Quick) or passed at runtime.
- **Runtime `AllowedDomains`**: list **up to 3 domains/subdomains** in the API call to override static ones (docs).
- **Restrict runtime domains** with the IAM condition key **`quicksight:AllowedEmbeddingDomains`**; use operators that block URL variations (trailing slash, case) (docs).
- **Session tags** (anonymous): key/value pairs passed in `SessionTags` that drive **tag-based RLS** on datasets (e.g. `tenant_id = 42`).
- **Tag-based RLS**: configured on the dataset (`RowLevelPermissionTagConfiguration`) mapping tag keys to columns; up to **50 tags** per dataset **(verify)**.
- **Catch**: if the app forgets to pass a required tag, the user sees **no data** (not all data) **(verify)**.
- **Embedding SDK** (`amazon-quicksight-embedding-sdk`, JavaScript): `createEmbeddingContext`, `embedDashboard`; set **parameters**, react to events (`CONTENT_LOADED`, `ERROR_OCCURRED`, `PARAMETERS_CHANGED`), hide toolbar options (export, undo/redo, reset).
- **Fixed vs responsive size**: pixel width/height = fixed; percent width/height = responsive layout (docs).
- **Load-balanced app servers**: if a session reconnects to a different server with a new role session, a **new session** starts (docs) → more session usage.

## J. 1-click embedding, public sharing and multi-tenancy
- **1-click embedding (registered users)**: copy an **embed code** from the dashboard share menu and paste it into an internal site; viewers sign in with their Quick identity; no code **(verify)**.
- **1-click public embedding / public sharing**: embed for **anyone on the internet** without sign-in; requires **session capacity pricing** and an admin turning on **public access** for the account and the dashboard **(verify)**.
- **Catch**: public embedding exposes all data in that dashboard → **no RLS per viewer**; use only for public data.
- **Admins can disable public sharing** at account level (custom permissions / account settings).
- **Namespaces** = isolated partitions of users and groups in one account for **multi-tenant SaaS**; users in one namespace **cannot see** users/assets of another.
- **Namespace limit**: about **100 namespaces per account** **(verify)**; created with `CreateNamespace`; **Enterprise**.
- **Multi-tenant patterns**: (1) **one dashboard + anonymous embedding + tag-based RLS** (simplest, scales to many tenants); (2) **namespaces + registered users + user-based RLS** (tenant users get accounts); (3) **separate AWS accounts** per tenant (strongest isolation, more admin).
- **Per-tenant branding**: themes per namespace or set at embed time **(verify)**.

## Scenarios: "If X → Y, because Z"
- If customers of a SaaS app (no AWS identities) must see only their own data → **anonymous embedding + session tags + tag-based RLS**, because tags filter rows per session without user accounts.
- If internal staff already use SSO and need dashboards inside the company portal → **registered-user embedding** (`GenerateEmbedUrlForRegisteredUser`), because their own permissions and RLS apply.
- If `GenerateEmbedUrlForAnonymousUser` returns `UnsupportedPricingPlanException` → **buy session capacity**, because anonymous embedding requires capacity pricing.
- If the embedded dashboard is blank on the partner's site → **add their domain to allowed domains (or runtime AllowedDomains)**, because only allow-listed domains can host it.
- If an embedded dashboard fails after a page refresh → **generate a new URL each load**, because the URL is single-use and valid for 5 minutes.
- If finance needs monthly invoice PDFs with exact layout → **pixel-perfect reports on a schedule**, because dashboards aren't paginated.
- If a manager wants an email when daily sales fall below target → **threshold alert on a KPI visual**, because alerts email when a value crosses a threshold.
- If the business wants unusual spikes flagged with reasons → **ML anomaly detection + contribution analysis**, because RCF finds outliers and contribution shows drivers.
- If anomaly detection is greyed out on a dataset → **check for RLS**, because anomaly detection isn't supported on RLS datasets.
- If executives want to ask "sales by region last quarter" in plain English → **Q topic (or Dashboard Q&A) with Reader Pro**, because topics map words to fields and Pro roles unlock generative BI.
- If clicking a region bar should filter the rest of the sheet → **filter action**, because it cross-filters visuals on click.
- If clicking an order should open the CRM page → **URL action with the order ID**, because URL actions pass field values to links.
- If one design must be stamped out for 50 clients' datasets → **template + CreateDashboard with each dataset**, because templates hold the design without data.
- If readers keep exporting sensitive data to CSV → **turn off export in publish options/custom permissions**, because export is allowed by default when enabled.
- If public, non-sensitive stats must be on a public website → **public (1-click) embedding with session capacity**, because no sign-in is needed.

Verified from AWS docs on 2026-11-02 (pages used): Embedding dashboards for anonymous users (APIs, session lifetime, URL validity, AllowedDomains, namespace, UnsupportedPricingPlanException), RLS with user-based rules (anomaly detection not supported with RLS), Amazon Quick Sight pricing page (alerts, Q question capacity, pixel-perfect units).
Unconfirmed (verify): sheets/visuals/datasets per analysis limits; layout names; rollback in console; publish option list; bookmarks; restricted folders; layer map and Highcharts visual names; cross-sheet filter naming; aggregated filters; URL parameter syntax; cross-dataset actions; threshold alert edition and direct-query schedule; anomaly minimum data points and run timing; forecast what-if; SageMaker integration status; Q bar name, topic indexing, Dashboard Q&A auto-topic, question-capacity scope, generative answers honoring RLS/CLS, data story sharing; pixel-perfect add-on requirement; email report formats and per-recipient RLS; snapshot job formats; registered-user billing for embedding; anonymous Q experiences; tag limit and missing-tag behavior; 1-click and public embedding rules; namespace limit and per-namespace themes.
