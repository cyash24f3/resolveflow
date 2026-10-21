# Free services and inference

The hosted application uses the existing Render Free service and Neon Free PostgreSQL project. No hosting plan was upgraded. Idle free hosting can suspend; queued work resumes after the instance wakes. CI uses standard GitHub-hosted Linux runners for the public repository.

The preferred inference model is Gemini 3.8 Flash, with configured free Gemini 3.6 Flash and Gemini 3.5 Flash-Lite fallbacks. Google publishes free input/output pricing and a roughly one-million-token model input window. Actual quotas depend on the API project and model. The integration key reported 20 daily requests for Gemini 3.8 Flash, so the application detects daily exhaustion and selects another explicitly configured free model. It records the actual model and does not silently substitute scripted results.

Use a Google AI Studio project on the free tier. An API key does not itself prove billing status; the application does not change billing settings or enroll a paid plan. The app’s own context and active-time budgets are smaller than the model maximum. Free inference has no availability SLA.

References: [pricing](https://ai.google.dev/gemini-api/docs/pricing), [model capabilities](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash), [account quotas](https://ai.google.dev/gemini-api/docs/rate-limits).

For credential-free development, use the deterministic baseline or fixture. For local model inference, use a tool-capable Ollama model and its OpenAI-compatible endpoint. When running the worker in Docker, set `DOCKER_PROVIDER_BASE_URL` to an address reachable from the container. Use the same HTTPS endpoint as `PROVIDER_BASE_URL` for hosted inference, or `http://host.docker.internal:11434/v1` for a model on the Mac host. No model weights are downloaded by this repository.

The default Compose memory limits are PostgreSQL 768 MiB, API 512 MiB and worker 768 MiB, plus Docker overhead. Benchmark local inference before increasing concurrency. Paid external business integrations are outside the fictional sandbox’s scope.
