# Free-only services and the requested Mac

Decision date: 30 September 2026. The project is usable with no provider account. No subscription, paid API, upgrade, or cloud provisioning was performed.

| Component | Selected path | Cost boundary |
|---|---|---|
| API, interface, worker | Local Python + FastAPI + Jinja/vanilla JS | Open-source dependencies |
| Business DB, jobs, checkpoints | Local PostgreSQL 17 in Docker | No managed DB account |
| Deterministic demos/evaluation | Baseline + clearly labeled fixture | No model calls |
| Live model (optional) | Ollama locally; one configurable OpenAI-compatible adapter | No API bill; model download, memory and electricity are local resources |
| Hosted live model (optional) | Groq Free Plan, manually supplied key | Remain on Free Plan; rate limits are not a billing cap for a paid account |
| Source and CI | Public [GitHub repository](https://github.com/cyash24f3/resolveflow), standard GitHub-hosted Linux runner | Public-repository standard runners are free; no larger runner selected |
| Remote database (optional) | Neon Free Plan | Not required or provisioned; check current account limits |
| Deployment | Local Docker Compose | No claim of a free always-on cloud worker |

The workflow uses `ubuntu-latest`, a standard hosted runner. GitHub documents free Actions usage for public repositories using standard runners: [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions). No paid runner, hosting plan or billing setting was enabled.

Groq publishes free-plan rate limits and an OpenAI-compatible endpoint. Exact allowances depend on account/model, and identifiers can change: [rate limits](https://console.groq.com/docs/rate-limits), [compatibility](https://console.groq.com/docs/openai). No free allowance is treated as permission to use a paid account. ResolveFlow cannot infer the billing plan from an API key.

Ollama supports local tool calling and an OpenAI-compatible chat endpoint: [compatibility](https://docs.ollama.com/api/openai-compatibility), [tool calling](https://docs.ollama.com/capabilities/tool-calling). The following local configuration is implemented but not live-verified:

```sh
# Install Ollama separately from its official download, then:
ollama pull qwen3:8b
ollama serve
```

Set `.env` values (never in browser code):

```dotenv
PROVIDER_ENABLED=true
PROVIDER_BASE_URL=http://localhost:11434/v1
PROVIDER_MODEL=qwen3:8b
PROVIDER_API_KEY=
# For Compose's worker, the endpoint needs to reach the macOS host:
DOCKER_PROVIDER_BASE_URL=http://host.docker.internal:11434/v1
```

For a manually configured **Groq Free Plan**, use:

```dotenv
PROVIDER_ENABLED=true
PROVIDER_BASE_URL=https://api.groq.com/openai/v1
DOCKER_PROVIDER_BASE_URL=https://api.groq.com/openai/v1
PROVIDER_MODEL=openai/gpt-oss-20b
PROVIDER_API_KEY=YOUR_FREE_PLAN_KEY
```

These are example configurable model aliases, not immutable revisions or verified model recommendations. Check your provider's available models. Restart the API and worker after configuration changes. Use `--allow-live --systems provider --limit 1` for the first isolated verification; this runner refuses unbounded live evaluations. The maximum request budget is the per-turn retry cap multiplied by the configured logical model-call cap, and the response token limit is 1,000 per request. Unknown usage from timeouts remains unknown. There is no paid pricing estimate in the evidence.

For 24 GB unified memory, begin with one model at a time and one worker. An 8B quantized model is a conservative starting experiment, not a measured throughput promise. Avoid 70B models and simultaneous large downloads. Compose limits PostgreSQL to 768 MiB, API to 512 MiB and worker to 768 MiB; Docker's VM overhead is additional. A Docker Desktop allocation around 4 GB is a starting configuration, not something this build changed globally. Leave memory for macOS and other applications. Keep inference native on macOS so the local inference runtime can use Apple silicon acceleration.

An Air is fanless: sustained inference may slow as it warms. Measure your selected model before increasing concurrency. The 1 TB SSD has ample nominal room for this source project; actual available space and model sizes must be checked before downloads. No model weights were automatically downloaded.

Docker Desktop licensing is subject to its terms, including personal/student use: [official Mac installation guidance](https://docs.docker.com/desktop/setup/install/mac-install/). Neon is optional: [official pricing](https://neon.com/pricing). Remote hosting remains unverified; a free web process that sleeps does not establish reliable background-worker availability.
