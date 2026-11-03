# Running EVOLUTION X on macOS

These steps were written for macOS 13+ on Apple Silicon or Intel. **They have not been run on a Mac**: they were
written and checked in a Linux container. If a step fails, the error message is what matters.

## What works on macOS and what does not

| Component | macOS |
|---|---|
| Synthetic market simulator, dashboard, scenarios, experiments | Works (pure Python + Node) |
| Historical data download, QC, causal backtest of the frozen v0 (`make backtest`) | Works |
| Simulator calibration (`make calibrate`), evaluation (`make eval`) | Works |
| Research loop that **executes generated code** (`make research-smoke`, `make research-campaign`) | **Disabled.** It needs Linux user/mount/network namespaces. Without them the supervisor refuses to run untrusted code (`SandboxUnavailable`) rather than run it unprotected |
| Viewing existing research results in the dashboard | Works if you copy `artifacts/research/` from a Linux run |

To run the research loop from a Mac, use a Linux VM (e.g. UTM or Lima). The Dockerfile has not been executed
in any environment so far, and Docker Desktop for Mac runs Linux containers without the user namespaces
privileges this sandbox needs by default.

## 1. Install the prerequisites

```bash
xcode-select --install
```

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

```bash
brew install uv node@22 git
```

```bash
uv python install 3.13
```

## 2. Unpack and install

```bash
mkdir -p ~/code && tar -xzf ~/Downloads/evolution-x-src.tar.gz -C ~/code
```

```bash
cd ~/code/evolution-x && uv sync
```

```bash
cd ~/code/evolution-x/web && npm ci && npm run build
```

## 3. Get the data (internet access to data.binance.vision needed)

```bash
cd ~/code/evolution-x && uv run evox data --research
```

This downloads about 330 small monthly archives (≈ 4 min) and 9 daily 1-minute files. It then verifies the Binance
checksums and writes `data/research/manifest.json` and the vault split into `data/vault/`.

## 4. Check the installation

```bash
cd ~/code/evolution-x && uv run pytest -q
```

On macOS the research-loop tests are **skipped** (the sandbox is unavailable). Everything else should pass.

## 5. Use it

```bash
cd ~/code/evolution-x && make demo
```

```bash
cd ~/code/evolution-x && make backtest
```

```bash
cd ~/code/evolution-x && uv run evox serve --port 8000
```

Then open http://localhost:8000 in your browser. The **Research** page shows the research results stored in
`artifacts/research/`.
