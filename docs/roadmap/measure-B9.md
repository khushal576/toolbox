# Toolbox baseline (roadmap S0.2)

Measured 2026-10-25T10:05:03 on commit `20d2c55` — host 8 CPUs, 7.5 GB RAM. Regenerate with `python3 tools/bench/baseline.py --restart`.
Raw numbers: `baseline.json` next to this file. Later phases compare against these.

## Summary
| Metric | Value |
|---|---|
| Image size | 1.35 GB |
| Container memory at idle (docker stats) | 169.1MiB / 7.498GiB |
| Server process RSS at idle | 245.8 MB in 6 process(es) |
| CPU at idle / PIDs | 0.49% / 10 |
| Cold start (restart → home page 200) | 1.54 s |
| `import fastapi` floor | 39.7 MB |
| All tools imported (today's startup) | +153.6 MB, 3.11 s |

## Import cost per tool (fresh process each, on top of the fastapi floor)
Shared libraries are counted for every tool that imports them, so the rows add up to more than
the all-tools total. This is the RAM a tool would cost if it were the only one loaded (lazy loading, A3).

| Tool | Module | Extra RSS | Import time | Note |
|---|---|---|---|---|
| duck-lab | `duck_lab.server` | 97.4 MB | 0.99 s |  |
| df-studio | `df_studio.server` | 83.2 MB | 1.15 s |  |
| ssh-sftp | `ssh_sftp.server` | 50.4 MB | 1.11 s |  |
| sql-studio | `sql_studio.server` | 45.4 MB | 0.62 s |  |
| vault | `vault.server` | 30.3 MB | 0.44 s |  |
| data-syncer | `data_syncer.server` | 28.0 MB | 0.46 s |  |
| data-dumper | `data_dumper.server` | 27.5 MB | 0.49 s |  |
| schema-copy | `schema_copy.server` | 27.2 MB | 0.45 s |  |
| schema-map | `schema_map.server` | 26.6 MB | 0.39 s |  |
| curl-builder | `curl_builder.server` | 6.5 MB | 0.15 s |  |
| datadiff-pro | `api.app` | 3.0 MB | 0.09 s |  |
| latex-pdf | `latex_pdf.server` | 0.2 MB | 0.01 s |  |
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
| GET /  (home page) | 30 | 3.0 ms | 3.9 ms | 3.0 ms | 200 |
| GET /tools/encode-decode/  (static page) | 30 | 2.3 ms | 5.7 ms | 2.7 ms | 200 |
| POST datadiff /compare  (100 records) | 30 | 10.3 ms | 88.8 ms | 18.5 ms | 200 |
| POST datadiff /compare  (5,000 records) | 5 | 388.5 ms | 414.3 ms | 385.9 ms | 200 |
| POST latex-pdf /compile  (1 page) | 5 | 901.7 ms | 1127.1 ms | 945.3 ms | 200 |

Single-user, sequential requests on a laptop: use these numbers for before/after comparison,
not as capacity figures. Load testing comes in D3.
