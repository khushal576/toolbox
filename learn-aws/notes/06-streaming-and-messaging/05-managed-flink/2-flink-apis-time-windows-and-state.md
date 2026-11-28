# Managed Service for Apache Flink – 2. Flink APIs, time, watermarks, windows, joins and state

Short notes. Each point is a fact you can be asked about.

## A. The API layers
- Flink has layered APIs. Higher layers are easier; lower layers give more control.
- Top: Flink SQL. Declarative SQL over dynamic tables (streams seen as tables that change).
- Table API: the same relational model as SQL, written as method calls in Java, Scala or Python.
- DataStream API: records, operators, keyed state, timers, custom windows. Java (and Python).
- Lowest: `ProcessFunction` / `KeyedProcessFunction`. Full access to state, timers and side outputs.
- SQL and Table API share one planner and optimizer. Same performance for the same query.
- You can mix them: convert a `DataStream` to a `Table` and back in one job.
- DataSet API (old batch API) is deprecated in 1.x and removed in Flink 2.x. Batch now uses DataStream in batch mode or Table/SQL.
- Pick SQL for filters, projections, windows, aggregations, joins written by SQL-skilled teams.
- Pick DataStream/ProcessFunction for custom state machines, complex event logic, custom timers, side outputs.

## B. DataStream API basics
- Program shape: get `StreamExecutionEnvironment` → add source (`fromSource`) → transformations → sink (`sinkTo`) → `execute()`.
- Stateless operators: `map` (1→1), `flatMap` (1→0..n), `filter`.
- `keyBy(key)` → `KeyedStream`. Records with the same key go to the same subtask. Required for keyed state and keyed windows.
- Aggregations on keyed streams: `reduce`, `aggregate`, `sum/min/max` (rolling, emits on every record).
- `union` merges streams of the same type. `connect` joins two streams of different types into a `ConnectedStreams` (shared state possible).
- `rebalance()` = round robin to all subtasks; fixes skew from few shards. `rescale()` = round robin to a local subset. `broadcast()` = send every record to all subtasks.
- Side outputs (`OutputTag`) send some records (for example late or bad records) to a second stream. Good for a dead-letter path.
- Async I/O (`AsyncDataStream.unorderedWait/orderedWait`) calls external services without blocking the operator thread. Use it for enrichment lookups.
- Async I/O settings: timeout, capacity (max in-flight requests). Unordered mode gives lower latency; ordered keeps input order.
- Broadcast state pattern: a low-volume rules/config stream is broadcast to all subtasks and stored as broadcast state. Use for dynamic rules or reference data.
- Set a unique ID with `.uid("...")` on every stateful operator. State in snapshots is matched by operator ID.
- Without UIDs, Flink generates IDs from the job graph. A small code change can then break snapshot restore ("operator ID mismatch").
- Give operators `.name()` too, so they are readable in the dashboard and logs.
- Flink CEP library: pattern matching over event sequences (for example "3 failed logins then 1 success within 5 minutes"). SQL equivalent is `MATCH_RECOGNIZE`.

## C. Table API and Flink SQL
- Dynamic table: a stream is a table that keeps changing. A continuous query runs forever and updates its result.
- Append-only result: only inserts (for example simple filters, window aggregates that emit once).
- Updating (changelog) result: inserts, updates and deletes (for example a plain `GROUP BY user_id` without a window).
- Trap: an updating result can only go to a sink that supports upserts/retractions (Kafka `upsert-kafka`, JDBC with a primary key, DynamoDB, Iceberg v2 upsert). An append-only sink like Kinesis or a plain file sink rejects it.
- Tables are defined with `CREATE TABLE ... WITH ('connector' = 'kinesis' | 'kafka' | 'filesystem' | ...)`.
- Event time column and watermark are declared in DDL: `WATERMARK FOR ts AS ts - INTERVAL '5' SECOND`.
- Processing time column: `proc AS PROCTIME()`.
- Catalogs hold table definitions. Default is an in-memory catalog (lost on restart; tables are recreated by your code).
- Glue Data Catalog can be used as a Flink catalog (Studio always uses it; apps can too, for example for Iceberg tables).
- Hive-compatible catalog and Iceberg catalog (Glue or S3 Tables) let SQL tables be shared with Athena, Glue and EMR.
- Flink SQL functions: built-ins plus UDFs (scalar, table, aggregate) in Java or Python.
- Mini-batch and two-phase aggregation are optimizer options that cut state access for heavy `GROUP BY` **(verify which options MSF allows)**.
- `EXPLAIN` shows the plan. Useful to spot unwanted updating results or missing watermarks.

## D. PyFlink
- PyFlink = Python API for Flink. Table API/SQL and DataStream API.
- At a high level the Python Table API is a wrapper over the Java Table API. SQL runs in the JVM; only Python UDFs run in Python workers.
- Python UDFs run in a separate Python process and pay serialization costs. Prefer built-in SQL functions for speed.
- Package: Python files + Python dependencies + Java connector JARs in one ZIP in S3.
- Connector JARs (Kinesis, Kafka, etc.) are still Java. PyFlink apps must ship them.
- Python versions follow Flink: Python 3.12 default on Flink 2.2+, Python 3.8 removed.
- Native Python packages must match the MSF runtime architecture (Linux x86_64) **(verify)**.
- Studio `%flink.pyflink` paragraphs use the same PyFlink API.
- Flink 2.2 adds async I/O in the Python DataStream API.

## E. Time: event time, processing time, ingestion time
- Event time = when the event happened, a timestamp inside the record (for example `order_ts`).
- Processing time = the wall-clock time of the machine when the operator sees the record.
- Ingestion time = time the record entered the stream. With Kinesis the default record timestamp is the approximate arrival time.
- Event time gives correct, repeatable results even with delays, replays and out-of-order data.
- Processing time gives lowest latency and no watermark logic, but results change with delays and replays.
- Exam rule: "results must be correct when data arrives late or is reprocessed" → event time.
- Exam rule: "only care about when the system saw it" or "simplest, lowest latency" → processing time.
- Replaying a stream from the start with processing time puts all old events in the current window. Wrong results. Event time fixes this.

## F. Watermarks
- Watermark = a marker that says "event time has reached T; no more events older than T are expected".
- Event-time windows close and fire when the watermark passes the window end.
- `WatermarkStrategy.forBoundedOutOfOrderness(Duration.ofSeconds(N))`: watermark = max seen event time − N. Allows N seconds of disorder.
- `WatermarkStrategy.forMonotonousTimestamps()`: watermark = max seen event time. Use only when data is in order.
- Larger out-of-orderness bound → fewer late records but higher latency (windows fire later).
- Smaller bound → lower latency but more records counted as late.
- Each source subtask makes its own watermark. An operator with many inputs uses the minimum of its input watermarks.
- Idle source trap: a shard or partition with no data sends no watermark. The minimum stays stuck. Event-time windows downstream never fire.
- Fix: `.withIdleness(Duration)`. Idle inputs are excluded from the minimum after that time.
- Trap: idleness does not move time forward if all inputs are idle. The last window stays open until new data arrives.
- Kinesis `uniformShardAssigner` spreads shards evenly so no source subtask is left without shards (which would act idle).
- Early watermark trap: at startup or with `TRIM_HORIZON`, some shards are read faster than others. Watermarks can jump ahead and make records late. Add an out-of-orderness buffer or allowed lateness.
- Watermark alignment (FLIP-182) pauses fast sources so they do not run far ahead of slow ones. Limits state growth during catch-up.
- Metrics: `currentInputWatermark` and `currentOutputWatermark` per operator. A growing gap means old events or a stuck upstream watermark.
- SQL: declare the watermark in DDL; `CURRENT_WATERMARK(ts)` shows it in a query.

## G. Late data
- Late record = event time older than the current watermark for its window.
- Default for windows: late records are dropped silently. Metric `numLateRecordsDropped` counts them.
- `allowedLateness(Duration)`: keep window state longer. A late record re-fires the window with an updated result.
- Catch: allowed lateness keeps more state and emits updates, so the sink must handle more than one result per window (upsert).
- `sideOutputLateData(tag)`: send late records to a side output for separate handling (for example to S3 for a batch fix).
- In SQL, late rows are dropped by window TVFs; there is no allowed lateness in standard window TVFs **(verify)**.
- Choose: drop (simplest), allowed lateness (correct but updates), side output (no loss, handled elsewhere).

## H. Window types
| Window | Shape | Typical use |
|---|---|---|
| Tumbling | Fixed size, no overlap | Count per minute, hourly totals |
| Sliding (hop) | Fixed size, slides by a step, overlaps | Last 10 minutes updated every minute |
| Session | Closes after a gap of inactivity, size varies per key | User sessions, sessionization |
| Global | One window per key forever; needs a custom trigger | Count-based windows (every 100 events) |
| Cumulate (SQL) | Grows in steps inside a max size | Running daily total updated every hour |
- Tumbling: each event belongs to exactly one window. Size and optional offset (for time zones).
- Sliding: each event belongs to size ÷ slide windows. 1-hour window sliding every 1 minute = 60 copies of each event. Watch state and CPU.
- Session: defined by a gap (for example 30 minutes). Windows for a key merge when events fall within the gap.
- Session with dynamic gap: gap computed per event (for example per customer tier).
- Global window: never closes by itself. Needs a trigger (count or custom) and often an evictor.
- Count windows (`countWindow(n)`) are built on global windows.
- Windows can be event time or processing time (for example `TumblingEventTimeWindows` vs `TumblingProcessingTimeWindows`).
- Keyed windows (`keyBy(...).window(...)`) run in parallel. Non-keyed windows (`windowAll`) run with parallelism 1. Bottleneck trap.
- Window functions: `ReduceFunction` / `AggregateFunction` aggregate incrementally (small state).
- `ProcessWindowFunction` sees all records of the window at once (keeps every record in state). Gives window metadata.
- Best practice: `aggregate(AggregateFunction, ProcessWindowFunction)` for incremental state plus window start/end info.
- Trap: a long window (days or weeks) with `ProcessWindowFunction` holds all events in state. Use incremental aggregation.
- Triggers decide when a window fires (event time, processing time, count, custom, early firing). Evictors remove records before/after the function.
- SQL window TVFs: `TUMBLE(TABLE t, DESCRIPTOR(ts), INTERVAL '1' MINUTE)`, `HOP(...)`, `CUMULATE(...)`, `SESSION(...)` (SESSION TVF in newer versions **(verify 1.19+)**).
- SQL group window syntax (`GROUP BY TUMBLE(ts, INTERVAL ...)`) is the older form; TVFs are recommended.
- SQL `OVER` windows: running aggregates per row, for example `AVG(price) OVER (PARTITION BY id ORDER BY ts RANGE BETWEEN INTERVAL '1' HOUR PRECEDING AND CURRENT ROW)`. Good for rolling averages.
- Window Top-N: `ROW_NUMBER() OVER (PARTITION BY window_start ORDER BY cnt DESC)` with a filter `<= N` on a window TVF result.
- Deduplication in SQL: `ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY proc_time) = 1` keeps the first copy (needs state per key; set state TTL).

## I. Joins
- Regular (unbounded) join in SQL: `a JOIN b ON a.id = b.id` with no time bounds. Both sides are kept in state forever.
- Regular join trap: state grows without limit. Set state TTL or use a time-bounded join.
- Interval join: join records whose times are within a range, for example `b.ts BETWEEN a.ts - INTERVAL '5' MINUTE AND a.ts + INTERVAL '10' MINUTE`.
- Interval join keeps only records inside the interval. State is cleaned as the watermark moves. Output is append-only.
- Use interval join for: order + payment within 1 hour, impression + click within 30 minutes.
- DataStream interval join: `keyedA.intervalJoin(keyedB).between(lower, upper)`. Event time only.
- Window join: join two streams on the same key inside the same tumbling/sliding/session window.
- Temporal join (versioned table): join each event with the version of a reference table valid at the event's time. `FOR SYSTEM_TIME AS OF o.order_time`.
- Temporal join use: currency rate at the time of the order, product price when the order was placed.
- Temporal join needs a versioned table: a changelog with a primary key and event time (for example upsert-kafka or CDC).
- Lookup join: enrich each event by querying an external table at processing time, `FOR SYSTEM_TIME AS OF o.proc_time` on a JDBC/lookup table.
- Lookup join catch: uses the current value, not the historic one. Each lookup is a network call; enable the lookup cache (TTL, max rows) to cut load.
- Lookup join is the SQL version of Async I/O enrichment in DataStream.
- Delta join (Flink 2.1+): keeps less state by reading the latest version from an external store; needs extra infrastructure (for example Apache Fluss).
- Broadcast state join: small reference data broadcast to all subtasks, joined in memory. Fast; reference data must fit in state.
- Choosing a join: time-related streams → interval; "value as of event time" → temporal; external DB enrichment → lookup or Async I/O; small rules table → broadcast state.

## J. Keyed state
- State = data an operator remembers between records (counts, last value, open sessions, seen IDs).
- Keyed state is scoped to the current key. Each key has its own copy. Only on keyed streams.
- `ValueState<T>`: one value per key (last reading, running total).
- `ListState<T>`: a list per key (buffered events).
- `MapState<K,V>`: a map per key (counts per sub-key). Efficient with RocksDB because entries are stored separately.
- `ReducingState` and `AggregatingState`: values are combined on add.
- Operator state (non-keyed): per parallel subtask, for example source offsets. Redistributed on rescale.
- Broadcast state: same copy on every subtask, from a broadcast stream.
- Timers (event time or processing time) in `KeyedProcessFunction` fire `onTimer()` per key. Used for timeouts, session end, cleanup.
- Keyed state is split into key groups (number = maxParallelism). Rescaling moves whole key groups between subtasks.
- State skew: a hot key puts most state and CPU on one subtask. Spread keys (salting, pre-aggregation) or pick a better key.
- Use Flink native state structures, not big Java collections inside `ValueState`. A whole collection is serialized on every access and checkpoint.
- State serialization: POJOs and Avro support schema evolution. Kryo (generic fallback) does not evolve well.
- Flink 2.x Kryo upgrade (2.24 → 5.6) can make old Kryo state unreadable. Avro and Protobuf state are not affected.

## K. State backends
- State backend = where working state lives. MSF uses RocksDB (EmbeddedRocksDBStateBackend).
- RocksDB keeps state on local disk (running application storage), with a memory cache. State can be far larger than heap memory.
- RocksDB state access needs serialization on every read/write. Slower than heap, but scales to large state.
- The HashMap (heap) backend keeps state as Java objects in memory. Faster, but limited by heap and causes GC pressure. MSF does not let you switch to it by default **(verify)**.
- RocksDB uses Flink managed memory (off-heap). Metrics: `managedMemoryUsed`, `managedMemoryTotal`, `managedMemoryUtilization`.
- `containerMemoryUtilization` includes RocksDB native memory. `heapMemoryUtilization` does not. Watch both.
- Checkpoints copy RocksDB files to durable storage. MSF uses incremental checkpoints, so only new SST files upload.
- Flink 2.x RocksDB is upgraded (8.10) for better I/O. The ForSt disaggregated backend is not supported on MSF.

## L. State TTL
- State TTL = automatic expiry of keyed state entries after a time since last write (or read).
- Configure with `StateTtlConfig.newBuilder(Duration)` on a state descriptor.
- Update type: `OnCreateAndWrite` (default) or `OnReadAndWrite` (reads also reset the timer).
- Visibility: `NeverReturnExpired` (default) or `ReturnExpiredIfNotCleanedUp`.
- TTL is based on processing time only. Not event time.
- In SQL, set `table.exec.state.ttl` (for example `1 d`) to expire state of regular joins, `GROUP BY` and dedup.
- SQL trap: TTL that is too short drops state still needed. A join row or aggregate resets and gives wrong results.
- With RocksDB, expired entries are removed during compaction. State size (and checkpoint size) drops only after compaction.
- AWS note: below about 200 MB checkpoint size you will rarely see a drop from TTL. A snapshot (savepoint) is a clean copy and removes expired data.
- No TTL on unbounded keys (user IDs, order IDs) → state grows forever → slower checkpoints, then failures. Classic exam root cause.
- Windows clean their own state when they close. TTL matters for `ProcessFunction` state, regular joins, dedup and non-windowed aggregates.

## M. Typical patterns mapped to Flink features
- Real-time anomaly detection: keyed state per device with running mean/stddev, flag values far from normal; or call a SageMaker endpoint with Async I/O; or `ML_PREDICT` in Flink 2.2 SQL.
- Threshold alerting: sliding window average per key > limit → emit alert to SNS via Lambda, to KDS, or to EventBridge **(verify direct EventBridge connector)**.
- Sessionization: event-time session window with a 30-minute gap per user; emit session length, page count.
- Enrichment: Async I/O or lookup join against DynamoDB/RDS; broadcast state for small reference data; temporal join for history-correct values.
- Deduplication: keyed `ValueState<Boolean>` "seen" per event ID with TTL equal to the max duplicate delay.
- Top-N per minute: tumbling window aggregate + window Top-N.
- Fraud pattern: Flink CEP or `MATCH_RECOGNIZE` (sequence within a time limit).
- Rolling averages: SQL `OVER` window or sliding window.
- Streaming ETL: filter, clean, flatten JSON, convert types, write Parquet or Iceberg to S3.
- CDC processing: read Debezium/DMS changes from Kafka or KDS as a changelog, keep the latest row per key, upsert into a sink.

## Scenarios: "If X → Y, because Z"
- **If** results must stay correct when mobile devices send events **hours late**, **then** use **event time** (the timestamp inside the record) with a **watermark**, and send late records to a **side output** for separate handling (for example to Amazon S3 for a batch fix). **This works because** event time gives correct, repeatable results even with delays and replays, while processing time (the machine's clock) puts late events in the wrong window. By default, late records are dropped silently, so the side output keeps them from being lost.
- **If** event-time windows **never fire** on a stream where some shards are quiet, **then** add `.withIdleness(Duration)` to the watermark strategy. **This works because** each source subtask makes its own watermark and an operator uses the **minimum** of its inputs; an idle shard sends no watermark, so the minimum gets stuck. With idleness, inputs quiet for that time are left out of the minimum. The Kinesis `uniformShardAssigner` also helps by spreading shards evenly, so no source subtask is left without shards.
- **If** the very last window in a test never closes, **then** send one more event (or a heartbeat event). **This works because** idleness does not move time forward when **all** inputs are idle, so the watermark passes the window end only when new data arrives.
- **If** too many records are dropped as late (metric `numLateRecordsDropped` rising), **then** raise the **out-of-orderness bound** in `forBoundedOutOfOrderness`, or use **allowed lateness**. **This works because** the watermark (max seen event time − bound) is running ahead of the real disorder in the data. A larger bound means fewer late records but windows fire later. Allowed lateness keeps window state longer and re-fires the window with an updated result, so the sink must handle more than one result per window (upsert).
- **If** dashboards need **low latency** more than perfect accuracy, **then** use a **small out-of-orderness bound** or switch to **processing time**. **This works because** windows fire only when the watermark passes their end, and a large bound delays that. The catch: a small bound counts more records as late, and processing-time results change with delays and replays.
- **If** you need "**last 10 minutes, refreshed every minute**", **then** use a **sliding (hop) window** of size **10 minutes** that slides by **1 minute**. **This works because** sliding windows overlap, while tumbling windows are fixed and never overlap. The catch: each event belongs to size ÷ slide windows (here **10**), so watch state and CPU.
- **If** you need web sessions that end after **30 minutes of inactivity**, **then** use a **session window** with a **30-minute gap** per user. **This works because** a session window closes after a gap with no events, so its length varies per user; windows for a key merge when events fall within the gap.
- **If** you need a **running daily total updated every hour**, **then** use the Flink SQL **CUMULATE** window table-valued function (TVF). **This works because** a cumulate window grows in steps (here 1 hour) inside a maximum size (here 1 day), emitting the running total at each step.
- **If** a window job runs at **parallelism 1** no matter what you set, **then** it is using `windowAll`; key the stream with `keyBy(...)` before the window. **This works because** non-keyed windows (`windowAll`) always run with parallelism 1 and become a bottleneck, while keyed windows run in parallel.
- **If** a **week-long** window causes huge state, **then** use incremental aggregation with an `AggregateFunction` (optionally combined with a `ProcessWindowFunction` for window start/end info). **This works because** a `ProcessWindowFunction` alone keeps **every** event of the window in state until it fires, while an `AggregateFunction` keeps only a small running result.
- **If** orders and payments must be matched within **1 hour**, **then** use an **interval join**, which joins records whose times fall within a set range. **This works because** an interval join keeps only records inside the interval and cleans state as the watermark moves, so state is bounded by time and output is append-only. A regular join with no time bounds keeps both sides forever.
- **If** each order needs the **exchange rate that was valid at order time**, **then** use a **temporal join** (`FOR SYSTEM_TIME AS OF o.order_time`) on a **versioned rate table**: a changelog with a primary key and event time, for example from `upsert-kafka` or change data capture (CDC). **This works because** a temporal join picks the version valid at the event's time, while a **lookup join** queries the external table at processing time and so returns **today's** rate, not the historic one.
- **If** each event needs the **current** customer tier from **Amazon Relational Database Service (RDS)**, **then** use a **lookup join** (or **Async I/O** in the DataStream API) with the lookup **cache** turned on. **This works because** a lookup join queries the database at processing time and returns the current value. Each lookup is a network call, so the cache (with a time-to-live and max rows) cuts load on the database.
- **If** a regular SQL join's state **grows forever**, **then** set `table.exec.state.ttl` (for example `1 d`) or switch to an **interval join**. **This works because** a regular (unbounded) join keeps both sides in state forever; state time-to-live (TTL) expires old entries, and an interval join bounds state by time. The catch: a TTL that is too short drops rows still needed and gives wrong results.
- **If** enrichment calls to **Amazon DynamoDB** make an operator slow, **then** use **Async I/O** (`AsyncDataStream.unorderedWait` or `orderedWait`), which calls external services without blocking the operator thread. **This works because** synchronous calls block the thread while waiting, which slows the operator and causes **backpressure** upstream. Async I/O keeps many requests in flight (set by capacity and timeout); unordered mode gives lower latency, ordered mode keeps input order.
- **If** rules must change at runtime **without redeploying**, **then** use the **broadcast state** pattern: send a low-volume rules stream to all subtasks and store it as broadcast state. **This works because** every subtask gets the same copy of the new rules and applies them to the main stream straight away.
- **If** duplicate events must be removed within **24 hours**, **then** keep keyed "**seen**" state per event ID (for example `ValueState<Boolean>`) with a **24-hour state time-to-live (TTL)**. **This works because** the TTL equals the maximum duplicate delay, so each ID is remembered just long enough. Without TTL, state for unbounded keys like event IDs grows forever, making checkpoints slower until they fail.
- **If** checkpoint size keeps climbing week after week, **then** look for state with **no time-to-live (TTL)** or very **long windows**. **This works because** unbounded keys (user IDs, order IDs) keep adding state that never expires, which slows checkpoints and then causes failures. Windows clean their own state when they close, so the usual culprits are `ProcessFunction` state, regular joins, dedup and non-windowed aggregates.
- **If** state time-to-live (TTL) is set but checkpoint size does not shrink, **then** wait for **RocksDB compaction** or take a **snapshot** (savepoint). **This works because** with RocksDB, expired entries are removed only during compaction, so size drops only after it; a snapshot is a clean copy without expired data. AWS notes that below about **200 MB** checkpoint size you will rarely see a drop.
- **If** a `GROUP BY user_id` query fails to write to a **Kinesis** sink, **then** window the aggregate or write to an **upsert sink** (for example `upsert-kafka`, JDBC with a primary key, DynamoDB or Iceberg v2). **This works because** a plain `GROUP BY` without a window gives an **updating changelog** (inserts, updates, deletes), and an append-only sink like Kinesis rejects it. A window aggregate emits once per window, so its result is append-only.
- **If** snapshot restore fails after you added a `map` step, **then** set a unique `.uid("...")` on every stateful operator. **This works because** state in snapshots is matched by **operator ID**; without UIDs, Flink generates IDs from the job graph, so a small code change changes them ("operator ID mismatch"). Add `.name()` too, for readable dashboards and logs.
- **If** state is serialized with **Kryo** and you plan to move to **Flink 2.2**, **then** migrate state to **Avro** or **POJO** serializers first, or test carefully. **This works because** Flink 2.x upgrades Kryo from **2.24 to 5.6**, which can make old Kryo state unreadable. Avro and Protobuf state are not affected.
- **If** you need fraud detection like "**3 failed logins then 1 success within 5 minutes**", **then** use the **Flink Complex Event Processing (CEP)** library or SQL `MATCH_RECOGNIZE`. **This works because** both match **ordered patterns** of events within a time limit.
- **If** older questions suggest `RANDOM_CUT_FOREST` for anomaly detection, **then** build it in **Managed Service for Apache Flink (MSF)** with custom logic (for example a running mean/stddev in keyed state), or call an **Amazon SageMaker** endpoint from MSF with Async I/O. **This works because** that SQL function belonged to **Kinesis Data Analytics (KDA) for SQL**, which has been shut down. Flink 2.2 SQL also adds `ML_PREDICT`.
- **If** a **Python user-defined function (UDF)** is slow, **then** use built-in SQL functions or a **Java UDF**. **This works because** Python UDFs run in a separate Python process and pay **cross-process serialization** costs, while SQL and Java run inside the JVM.

Verified from AWS docs on 2026-11-02 (MSF best practices: watermarks, idle shards, uniformShardAssigner, operator UIDs; troubleshooting unbounded state growth and TTL/compaction; Flink 2.2 page: Kryo, SQL features, RocksDB; Python page; checkpoints page stating RocksDB backend). Flink API behavior (windows, joins, state types, TTL options) follows Apache Flink documentation.
Unconfirmed (verify): which SQL optimizer options MSF allows; heap state backend availability on MSF; SESSION window TVF version; allowed lateness in SQL TVFs; native Python package architecture; direct EventBridge sink connector.
