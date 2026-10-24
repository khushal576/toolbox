# Toolbox baseline (roadmap S0.2)

Measured 2026-10-24T20:39:00 on commit `9811175` — host 8 CPUs, 7.5 GB RAM. Regenerate with `python3 tools/bench/baseline.py --restart`.
Raw numbers: `baseline.json` next to this file. Later phases compare against these.

## Summary
| Metric | Value |
|---|---|
| Image size | 1.31 GB |
| Container memory at idle (docker stats) | 174.3MiB / 7.498GiB |
| Server process RSS at idle | 186.4 MB in 1 process(es) |
| CPU at idle / PIDs | 0.25% / 14 |
| Cold start (restart → home page 200) | 2.6 s |
| `import fastapi` floor | 40.0 MB |
| All tools imported (today's startup) | +130.0 MB, 1.21 s |

## Import cost per tool (fresh process each, on top of the fastapi floor)
Shared libraries are counted for every tool that imports them, so the rows add up to more than
the all-tools total. This is the RAM a tool would cost if it were the only one loaded (lazy loading, A3).

| Tool | Module | Extra RSS | Import time | Note |
|---|---|---|---|---|
| duck-lab | `duck_lab.server` | 101.6 MB | 0.54 s |  |
| df-studio | `df_studio.server` | 86.8 MB | 0.5 s |  |
| sql-studio | `sql_studio.server` | 43.6 MB | 0.29 s |  |
| vault | `vault.server` | 30.0 MB | 0.26 s |  |
| data-syncer | `data_syncer.server` | 24.3 MB | 0.23 s |  |
| data-dumper | `data_dumper.server` | 23.6 MB | 0.25 s |  |
| ssh-sftp | `ssh_sftp.server` | 23.0 MB | 0.24 s |  |
| schema-map | `schema_map.server` | 22.9 MB | 0.23 s |  |
| schema-copy | `schema_copy.server` | 22.8 MB | 0.22 s |  |
| curl-builder | `curl_builder.server` | 6.5 MB | 0.08 s |  |
| datadiff-pro | `api.app` | 3.0 MB | 0.06 s |  |
| latex-pdf | `latex_pdf.server` | 0.2 MB | 0.0 s |  |
| encode-decode | `encode_decode.server` | 0.0 MB | 0.0 s |  |
| subnet-calc | `subnet_calc.server` | 0.0 MB | 0.0 s |  |
| dns-lookup | `dns_lookup.server` | 0.0 MB | 0.0 s |  |
| vlan-designer | `vlan_designer.server` | 0.0 MB | 0.0 s |  |
| packet-journey | `packet_journey.server` | 0.0 MB | 0.0 s |  |
| header-reference | `header_reference.server` | 0.0 MB | 0.0 s |  |
| http-methods-status | `http_methods_status.server` | 0.0 MB | 0.0 s |  |
| cookie-lab | `cookie_lab.server` | 0.0 MB | 0.0 s |  |

## Latency
| Request | Runs | p50 | p95 | Mean | HTTP |
|---|---|---|---|---|---|
| GET /  (home page) | 30 | 15.1 ms | 20.4 ms | 17.2 ms | 200 |
| GET /tools/encode-decode/  (static page) | 30 | 1.3 ms | 1.5 ms | 1.3 ms | 200 |
| POST datadiff /compare  (100 records) | 30 | 8.3 ms | 9.5 ms | 8.0 ms | 200 |
| POST datadiff /compare  (5,000 records) | 5 | 270.9 ms | 284.1 ms | 256.7 ms | 200 |
| POST latex-pdf /compile  (1 page) | 5 | 967.0 ms | 1134.2 ms | 977.0 ms | 200 |

Single-user, sequential requests on a laptop: use these numbers for before/after comparison,
not as capacity figures. Load testing comes in D3.
