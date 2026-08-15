# autodroid

Android automation worker com fila persistente, `CLI`, `API` e adapters por aplicativo.

## Sprint 1

A Sprint 1 entrega:
- `1` Android Worker
- fila persistente com `SQLite + SQLAlchemy + Alembic`
- dispatcher serial com prioridade, `run_after`, `cron_expression` e janela de execução
- `CLI` para jobs e worker
- `API` com `FastAPI`
- adapter inicial do LinkedIn com job `linkedin.extract_profile_basic`
- OCR com `PaddleOCR` apenas como fallback

## Arquitetura

```text
lib/
├── core/
├── dal/
│   ├── local/
│   └── remote/
├── domain/
│   ├── adapters/
│   ├── models/
│   └── services/
└── presentation/
    ├── api/
    └── cli/
```

## Requisitos

- Python `3.11+`
- `adb` disponível no `PATH`
- Android Worker acessível em `ANDROID_SERIAL`
- app do LinkedIn instalado no Android virtual

## Setup local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
python -m alembic upgrade head
```

## Variáveis principais

- `AUTODROID_DATABASE_URL` — padrão `sqlite:///./var/autodroid.db`
- `AUTODROID_WORKER_NAME` — padrão `main`
- `AUTODROID_TIMEZONE` — padrão `UTC`
- `ANDROID_SERIAL` — padrão `127.0.0.1:5555`
- `LINKEDIN_PACKAGE_NAME` — padrão `com.linkedin.android`
- `AUTODROID_OUTPUT_DIR` — padrão `output`

## CLI

Criar job do LinkedIn:

```bash
autodroid jobs create linkedin.extract_profile_basic linkedin --payload '{"scrolls": 2}'
```

Listar jobs:

```bash
autodroid jobs list
```

Executar uma iteração do dispatcher:

```bash
autodroid worker run --iterations 1
```

Consultar worker:

```bash
autodroid worker status --as-json
```

## API

Subir API local:

```bash
autodroid worker serve-api --host 127.0.0.1 --port 8000
```

Rotas iniciais:
- `GET /health`
- `POST /jobs`
- `GET /jobs`
- `GET /jobs/{job_id}`
- `POST /jobs/{job_id}/cancel`
- `POST /jobs/{job_id}/reprioritize`
- `GET /workers/main`

## Migrações

Aplicar:

```bash
autodroid db upgrade
```

## LinkedIn

Job inicial:
- `linkedin.extract_profile_basic`

Fluxo:
- vai para `HOME`
- faz `force-stop` do app alvo
- abre o LinkedIn
- tenta abrir a área de perfil
- coleta textos visíveis pela árvore de UI
- cai para screenshot + OCR só se necessário
- persiste o resultado no job

## Política da Sprint 1

- toda execução começa de `HOME`
- o app alvo é sempre encerrado completamente antes de abrir
- não existe retomada de progresso no meio da task
- placeholders de resume/contexto ficam preparados apenas para evolução futura

## Changelog

Configuração de `git-cliff` disponível em `cliff.toml`.
