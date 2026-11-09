# Extra CA certificates (optional)

Put the root CA of a TLS-inspecting proxy (Zscaler, Netskope, …) here as `*.crt` / `*.pem` if your network re-signs
HTTPS traffic. Without it a container fails with `CERTIFICATE_VERIFY_FAILED` ("Could not reach Microsoft sign-in
(ConnectError)"). Currently used only by the SharePoint tool (`sharepoint-lab/tls.py`); mounted read-only at `/certs`
in `rt-data`. The files themselves are git-ignored. Restart `rt-data` after changing them.

Linux host: the corporate root is usually already in `/usr/local/share/ca-certificates/` — copy it from there.
